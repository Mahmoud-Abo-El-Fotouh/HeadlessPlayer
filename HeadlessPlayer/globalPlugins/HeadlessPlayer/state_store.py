# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Persistent State Store.
Provides atomic JSON-backed storage for playback resume positions,
recent playlists, last played files, and session state.
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("HeadlessPlayer.StateStore")

# Default state file name
STATE_FILE_NAME = "headlessPlayer_state.json"
CURRENT_SCHEMA_VERSION = 1


def get_default_state_file_path() -> str:
    """
    Determines the appropriate location for the state store file.
    Prefers NVDA user configuration directory when running within NVDA,
    falling back to %APPDATA%/nvda or user home directory.
    """
    # 1. Environment variable override
    env_path = os.environ.get("HEADLESSPLAYER_STATE_FILE")
    if env_path:
        return os.path.abspath(env_path)

    # 2. NVDA globalVars configPath
    try:
        import globalVars
        if hasattr(globalVars, "appArgs") and hasattr(globalVars.appArgs, "configPath"):
            config_path = globalVars.appArgs.configPath
            if config_path and os.path.isdir(config_path):
                return os.path.join(config_path, STATE_FILE_NAME)
    except Exception:
        pass

    # 3. Standard Windows %APPDATA%/nvda
    app_data = os.environ.get("APPDATA")
    if app_data:
        nvda_dir = os.path.join(app_data, "nvda")
        if os.path.isdir(nvda_dir):
            return os.path.join(nvda_dir, STATE_FILE_NAME)
        # Create headlessPlayer subfolder in AppData if NVDA folder is not found
        hp_dir = os.path.join(app_data, "HeadlessPlayer")
        try:
            os.makedirs(hp_dir, exist_ok=True)
            return os.path.join(hp_dir, STATE_FILE_NAME)
        except OSError:
            pass

    # 4. Fallback to user home directory
    home_dir = os.path.expanduser("~")
    hp_dir = os.path.join(home_dir, ".headlessPlayer")
    try:
        os.makedirs(hp_dir, exist_ok=True)
        return os.path.join(hp_dir, STATE_FILE_NAME)
    except OSError:
        pass

    return os.path.join(tempfile.gettempdir(), STATE_FILE_NAME)


def normalize_file_path(file_path: str) -> str:
    """
    Normalizes a file path to ensure consistent keys across different
    casing and path representations on Windows.
    """
    if not file_path:
        return ""
    # Online stream URLs are used verbatim as keys (never path-normalized)
    if file_path.strip().lower().startswith(("http://", "https://")):
        return file_path.strip()
    try:
        expanded = os.path.expanduser(os.path.expandvars(file_path))
        abs_path = os.path.abspath(expanded)
        return os.path.normcase(abs_path)
    except Exception:
        return file_path.strip().lower()


def compute_file_hash_key(file_path: str) -> str:
    """
    Computes a deterministic hash key for a normalized file path.
    """
    norm = normalize_file_path(file_path)
    return hashlib.sha256(norm.encode("utf-8", errors="ignore")).hexdigest()[:16]


class StateStore:
    """
    Thread-safe, atomic JSON-based state manager for HeadlessPlayer.
    """

    def __init__(
        self,
        state_file_path: Optional[str] = None,
        auto_save: bool = True
    ) -> None:
        self._state_file_path = state_file_path or get_default_state_file_path()
        self._auto_save = auto_save
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = self._create_empty_state()
        self.load()

    def _create_empty_state(self) -> Dict[str, Any]:
        return {
            "version": CURRENT_SCHEMA_VERSION,
            "positions": {},
            "recent_files": [],
            "last_playlist": {
                "tracks": [],
                "current_index": 0,
                "shuffle": False,
                "repeat_mode": "off",
                "auto_next": True,
            },
            "settings": {},
        }

    @property
    def state_file_path(self) -> str:
        return self._state_file_path

    def load(self) -> None:
        """
        Loads the state store from disk. Handles missing or corrupt files safely.
        """
        with self._lock:
            if not os.path.exists(self._state_file_path):
                self._data = self._create_empty_state()
                return

            try:
                with open(self._state_file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        self._data = self._create_empty_state()
                        return
                    data = json.loads(content)

                if isinstance(data, dict):
                    # Schema migration / validation
                    if "positions" not in data:
                        data["positions"] = {}
                    if "recent_files" not in data:
                        data["recent_files"] = []
                    if "last_playlist" not in data:
                        data["last_playlist"] = {
                            "tracks": [],
                            "current_index": 0,
                            "shuffle": False,
                            "repeat_mode": "off",
                            "auto_next": True,
                        }
                    if "settings" not in data:
                        data["settings"] = {}
                    self._data = data
                else:
                    self._data = self._create_empty_state()
            except Exception as e:
                logger.warning(f"Failed to parse state file {self._state_file_path}: {e}. Creating fresh state.")
                # Create backup of corrupt file for diagnosis
                try:
                    corrupt_backup = f"{self._state_file_path}.corrupt.{int(time.time())}"
                    shutil.copyfile(self._state_file_path, corrupt_backup)
                except Exception:
                    pass
                self._data = self._create_empty_state()

    def save(self) -> bool:
        """
        Atomically saves the state to disk using a temporary file and replace.
        """
        with self._lock:
            temp_file = None
            try:
                target_dir = os.path.dirname(self._state_file_path)
                if target_dir:
                    os.makedirs(target_dir, exist_ok=True)

                # Write to temp file in the same directory for atomic replace
                temp_file = f"{self._state_file_path}.tmp.{os.getpid()}.{threading.get_ident()}"
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(temp_file, self._state_file_path)
                return True
            except Exception as e:
                logger.error(f"Failed to save state to {self._state_file_path}: {e}")
                if temp_file and os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except Exception:
                        pass
                return False

    # -------------------------------------------------------------------------
    # Resume Positions API
    # -------------------------------------------------------------------------

    def save_position(
        self,
        file_path: str,
        position_sec: float,
        duration_sec: Optional[float] = None,
        min_threshold_sec: float = 1.0,
        end_threshold_sec: float = 1.0
    ) -> bool:
        """
        Saves the playback resume position for a media file.
        
        Args:
            file_path: Absolute or relative file path.
            position_sec: Current playback position in seconds.
            duration_sec: Total duration in seconds if known.
            min_threshold_sec: Positions below this threshold are ignored (considered at start).
            end_threshold_sec: Positions within this threshold of duration are cleared (considered completed).
            
        Returns:
            True if position was recorded, False if cleared or ignored.
        """
        if not file_path or position_sec is None:
            return False

        norm_path = normalize_file_path(file_path)
        if not norm_path:
            return False

        with self._lock:
            # Check threshold at the start of track
            if position_sec < min_threshold_sec:
                self.clear_position(file_path)
                return False

            # Check threshold at the end of track (completion)
            if duration_sec is not None and duration_sec > 0:
                if (duration_sec - position_sec) <= end_threshold_sec:
                    self.clear_position(file_path)
                    return False

            positions = self._data.setdefault("positions", {})
            positions[norm_path] = {
                "position": round(float(position_sec), 2),
                "duration": round(float(duration_sec), 2) if duration_sec else None,
                "updated_at": time.time(),
                "filename": os.path.basename(file_path),
            }

            self._prune_positions_locked(max_entries=500)

            if self._auto_save:
                self.save()
            return True

    def get_position(self, file_path: str) -> float:
        """
        Retrieves the saved resume position for a file in seconds.
        Returns 0.0 if no position is saved.
        """
        if not file_path:
            return 0.0

        norm_path = normalize_file_path(file_path)
        with self._lock:
            positions = self._data.get("positions", {})
            record = positions.get(norm_path)
            if record and isinstance(record, dict):
                return float(record.get("position", 0.0))
            return 0.0

    def clear_position(self, file_path: str) -> None:
        """
        Clears any saved resume position for a specific file.
        """
        if not file_path:
            return

        norm_path = normalize_file_path(file_path)
        with self._lock:
            positions = self._data.get("positions", {})
            if norm_path in positions:
                del positions[norm_path]
                if self._auto_save:
                    self.save()

    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns a copy of all saved resume position records.
        """
        with self._lock:
            return dict(self._data.get("positions", {}))

    def clear_all_positions(self) -> None:
        """
        Clears all stored resume positions.
        """
        with self._lock:
            self._data["positions"] = {}
            if self._auto_save:
                self.save()

    def _prune_positions_locked(self, max_entries: int = 500) -> None:
        """
        Prunes oldest position entries if total count exceeds max_entries.
        Must be called while holding self._lock.
        """
        positions = self._data.get("positions", {})
        if len(positions) > max_entries:
            sorted_items = sorted(
                positions.items(),
                key=lambda item: item[1].get("updated_at", 0) if isinstance(item[1], dict) else 0
            )
            excess = len(positions) - max_entries
            for key, _ in sorted_items[:excess]:
                del positions[key]

    # -------------------------------------------------------------------------
    # Recent Files API
    # -------------------------------------------------------------------------

    def save_recent_file(self, file_path: str, max_recent: int = 20) -> None:
        """
        Adds a file path to the top of the recent files list.
        """
        if not file_path:
            return

        norm_path = normalize_file_path(file_path)
        with self._lock:
            recent: List[str] = self._data.setdefault("recent_files", [])
            # Remove any existing occurrences
            recent = [p for p in recent if normalize_file_path(p) != norm_path]
            # Insert at beginning
            recent.insert(0, os.path.abspath(file_path))
            # Cap at max_recent
            self._data["recent_files"] = recent[:max_recent]

            if self._auto_save:
                self.save()

    def get_recent_files(self) -> List[str]:
        """
        Returns the list of recently played file paths.
        """
        with self._lock:
            return list(self._data.get("recent_files", []))

    def clear_recent_files(self) -> None:
        """
        Clears the recent files history.
        """
        with self._lock:
            self._data["recent_files"] = []
            if self._auto_save:
                self.save()

    # -------------------------------------------------------------------------
    # Last Playlist Session API
    # -------------------------------------------------------------------------

    def save_last_playlist(
        self,
        tracks: List[str],
        current_index: int = 0,
        shuffle: bool = False,
        repeat_mode: str = "off",
        auto_next: bool = True
    ) -> None:
        """
        Saves the last active playlist state across sessions.
        """
        with self._lock:
            self._data["last_playlist"] = {
                "tracks": list(tracks),
                "current_index": max(0, int(current_index)),
                "shuffle": bool(shuffle),
                "repeat_mode": str(repeat_mode),
                "auto_next": bool(auto_next),
                "updated_at": time.time(),
            }
            if self._auto_save:
                self.save()

    def get_last_playlist(self) -> Dict[str, Any]:
        """
        Retrieves the last active playlist state.
        """
        with self._lock:
            return dict(self._data.get("last_playlist", {
                "tracks": [],
                "current_index": 0,
                "shuffle": False,
                "repeat_mode": "off",
                "auto_next": True,
            }))

    def clear_last_playlist(self) -> None:
        """
        Clears saved playlist state.
        """
        with self._lock:
            self._data["last_playlist"] = {
                "tracks": [],
                "current_index": 0,
                "shuffle": False,
                "repeat_mode": "off",
                "auto_next": True,
            }
            if self._auto_save:
                self.save()

    # -------------------------------------------------------------------------
    # Player Settings API
    # -------------------------------------------------------------------------

    def save_setting(self, key: str, value: Any) -> None:
        """
        Saves an arbitrary setting key-value pair.
        """
        with self._lock:
            settings = self._data.setdefault("settings", {})
            settings[key] = value
            if self._auto_save:
                self.save()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Retrieves a setting value.
        """
        with self._lock:
            settings = self._data.get("settings", {})
            return settings.get(key, default)

    def save_volume(self, volume: int) -> None:
        self.save_setting("volume", int(volume))

    def get_volume(self) -> Optional[int]:
        val = self.get_setting("volume")
        return int(val) if val is not None else None

    def save_speed(self, speed: float) -> None:
        self.save_setting("speed", round(float(speed), 2))

    def get_speed(self) -> Optional[float]:
        val = self.get_setting("speed")
        return float(val) if val is not None else None

    def save_auto_next(self, enabled: bool) -> None:
        self.save_setting("auto_next", bool(enabled))

    def get_auto_next(self) -> Optional[bool]:
        val = self.get_setting("auto_next")
        return bool(val) if val is not None else None

    def save_repeat_mode(self, mode: str) -> None:
        self.save_setting("repeat_mode", str(mode))

    def get_repeat_mode(self) -> Optional[str]:
        val = self.get_setting("repeat_mode")
        return str(val) if val is not None else None

    def save_shuffle(self, enabled: bool) -> None:
        self.save_setting("shuffle", bool(enabled))

    def get_shuffle(self) -> Optional[bool]:
        val = self.get_setting("shuffle")
        return bool(val) if val is not None else None

    def reset(self) -> None:
        """
        Resets all stored state to empty defaults and deletes state file if it exists.
        """
        with self._lock:
            self._data = self._create_empty_state()
            try:
                if os.path.exists(self._state_file_path):
                    os.remove(self._state_file_path)
            except Exception as e:
                logger.warning(f"Could not delete state file {self._state_file_path}: {e}")


# Global singleton instance
_global_state_store: Optional[StateStore] = None
_global_lock = threading.Lock()


def get_state_store(state_file_path: Optional[str] = None) -> StateStore:
    """
    Returns the global StateStore singleton instance.
    """
    global _global_state_store
    with _global_lock:
        if _global_state_store is None:
            _global_state_store = StateStore(state_file_path=state_file_path)
        elif state_file_path and _global_state_store.state_file_path != state_file_path:
            _global_state_store = StateStore(state_file_path=state_file_path)
        return _global_state_store
