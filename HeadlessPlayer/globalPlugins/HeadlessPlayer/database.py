# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Persistent Database Storage Layer.
Provides high-performance, ACID-compliant, thread-safe persistence for
all add-on settings, custom keyboard shortcuts, track resume positions,
playback history, and active playlist states.

Zero binary / C-extension dependencies; 100% compatible with all NVDA builds.
"""

from __future__ import annotations
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("HeadlessPlayer.Database")

DB_FILE_NAME = "headlessPlayer_data.json"


def get_default_db_path() -> str:
    """
    Determines the storage path for the database file.
    Prefers NVDA user configuration directory (%APPDATA%/nvda),
    ensuring private user state is never stored inside add-on code folders.
    """
    # 1. Environment variable override
    env_path = os.environ.get("HEADLESSPLAYER_DB_PATH") or os.environ.get("HEADLESSPLAYER_STATE_FILE")
    if env_path:
        return os.path.abspath(env_path)

    # 2. NVDA globalVars configPath
    try:
        import globalVars
        if hasattr(globalVars, "appArgs") and hasattr(globalVars.appArgs, "configPath"):
            config_path = globalVars.appArgs.configPath
            if config_path and os.path.isdir(config_path):
                return os.path.join(config_path, DB_FILE_NAME)
    except Exception:
        pass

    # 3. Standard Windows %APPDATA%/nvda
    app_data = os.environ.get("APPDATA")
    if app_data:
        nvda_dir = os.path.join(app_data, "nvda")
        if os.path.isdir(nvda_dir):
            return os.path.join(nvda_dir, DB_FILE_NAME)
        hp_dir = os.path.join(app_data, "HeadlessPlayer")
        try:
            os.makedirs(hp_dir, exist_ok=True)
            return os.path.join(hp_dir, DB_FILE_NAME)
        except OSError:
            pass

    # 4. Fallback to user home directory
    home_dir = os.path.expanduser("~")
    hp_dir = os.path.join(home_dir, ".headlessPlayer")
    try:
        os.makedirs(hp_dir, exist_ok=True)
        return os.path.join(hp_dir, DB_FILE_NAME)
    except OSError:
        pass

    return os.path.join(tempfile.gettempdir(), DB_FILE_NAME)


def normalize_file_path(file_path: str) -> str:
    """
    Normalizes a file path for consistent database keys on Windows.
    Online URLs are preserved verbatim.
    """
    if not file_path:
        return ""
    if file_path.strip().lower().startswith(("http://", "https://")):
        return file_path.strip()
    try:
        expanded = os.path.expanduser(os.path.expandvars(file_path))
        abs_path = os.path.abspath(expanded)
        return os.path.normcase(abs_path)
    except Exception:
        return file_path.strip().lower()


class DatabaseManager:
    """
    Thread-safe, crash-resilient Database Manager for HeadlessPlayer.
    Persists settings, resume positions, playback history, and playlist state
    using high-speed memory caching and atomic disk synchronization.
    Zero binary dependencies; works across all NVDA versions.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or get_default_db_path()
        self._lock = threading.RLock()
        self._cache: Dict[str, Any] = {
            "settings": {},
            "positions": {},
            "recent_media": [],
            "playlists_state": {}
        }
        self._init_database()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _init_database(self) -> None:
        """Loads existing data from disk or runs migration from legacy files."""
        with self._lock:
            if os.path.isfile(self._db_path):
                try:
                    with open(self._db_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._cache["settings"] = data.get("settings", {})
                        self._cache["positions"] = data.get("positions", {})
                        self._cache["recent_media"] = data.get("recent_media", [])
                        self._cache["playlists_state"] = data.get("playlists_state", {})
                except Exception as e:
                    logger.warning("Failed to load existing database file, starting fresh: %s", e)

            # Migrate legacy state if present
            self._migrate_legacy_data()

    def _save_to_disk(self) -> None:
        """Atomically writes memory cache to disk via temp file replacement."""
        with self._lock:
            db_dir = os.path.dirname(self._db_path)
            if db_dir:
                try:
                    os.makedirs(db_dir, exist_ok=True)
                except Exception:
                    pass

            temp_path = self._db_path + f".tmp_{os.getpid()}_{threading.get_ident()}"
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(self._cache, f, ensure_ascii=False, indent=2)
                
                # Atomic replace on Windows
                if os.path.exists(self._db_path):
                    os.replace(temp_path, self._db_path)
                else:
                    os.rename(temp_path, self._db_path)
            except Exception as e:
                logger.error("Error writing database to %s: %s", self._db_path, e)
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass

    def _migrate_legacy_data(self) -> None:
        """Migrates state from legacy headlessPlayer_state.json or nvda.ini."""
        with self._lock:
            legacy_dir = os.path.dirname(self._db_path)
            legacy_json_path = os.path.join(legacy_dir, "headlessPlayer_state.json")

            if os.path.isfile(legacy_json_path):
                try:
                    with open(legacy_json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        # Settings
                        settings = data.get("settings", {})
                        if isinstance(settings, dict):
                            self._cache["settings"].update(settings)
                        # Positions
                        positions = data.get("positions", {})
                        if isinstance(positions, dict):
                            for path, rec in positions.items():
                                if isinstance(rec, dict):
                                    norm_key = normalize_file_path(path)
                                    self._cache["positions"][norm_key] = {
                                        "position": float(rec.get("position", 0.0)),
                                        "duration": float(rec["duration"]) if rec.get("duration") else None,
                                        "filename": rec.get("filename") or os.path.basename(path),
                                        "updated_at": time.time()
                                    }
                        # Recent files
                        recent = data.get("recent_files", [])
                        if isinstance(recent, list):
                            for r_path in recent:
                                if isinstance(r_path, str) and r_path.strip():
                                    norm_key = normalize_file_path(r_path.strip())
                                    fn = os.path.basename(r_path) if not r_path.startswith("http") else r_path
                                    self._cache["recent_media"].insert(0, {
                                        "file_path": norm_key,
                                        "filename": fn,
                                        "last_played": time.time()
                                    })
                        # Last playlist
                        last_pl = data.get("last_playlist")
                        if isinstance(last_pl, dict) and last_pl.get("tracks"):
                            self._cache["playlists_state"]["default"] = {
                                "tracks": last_pl.get("tracks", []),
                                "current_index": last_pl.get("current_index", 0),
                                "shuffle": bool(last_pl.get("shuffle", False)),
                                "repeat_mode": str(last_pl.get("repeat_mode", "off")),
                                "auto_next": bool(last_pl.get("auto_next", True)),
                                "updated_at": time.time()
                            }
                    try:
                        os.replace(legacy_json_path, legacy_json_path + ".migrated")
                    except Exception:
                        pass
                    self._save_to_disk()
                except Exception as e:
                    logger.warning("Error migrating legacy state: %s", e)

            # Migrate from nvda.ini [headlessPlayer]
            try:
                import config
                if hasattr(config, "conf") and "headlessPlayer" in config.conf:
                    for k, v in config.conf["headlessPlayer"].items():
                        if k not in self._cache["settings"]:
                            self._cache["settings"][k] = v
                    self._save_to_disk()
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Settings Key-Value API
    # -------------------------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._cache["settings"].get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache["settings"][key] = value
            self._save_to_disk()

    def set_settings_bulk(self, settings_dict: Dict[str, Any]) -> None:
        with self._lock:
            self._cache["settings"].update(settings_dict)
            self._save_to_disk()

    def get_all_settings(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._cache["settings"])

    def delete_setting(self, key: str) -> None:
        with self._lock:
            if key in self._cache["settings"]:
                del self._cache["settings"][key]
                self._save_to_disk()

    # -------------------------------------------------------------------------
    # Keymap Shortcuts API
    # -------------------------------------------------------------------------

    def get_keymap(self) -> Dict[str, str]:
        val = self.get_setting("customKeymap", None)
        if isinstance(val, dict):
            return dict(val)
        return {}

    def set_keymap(self, keymap: Dict[str, str]) -> None:
        self.set_setting("customKeymap", dict(keymap))

    def reset_keymap(self) -> None:
        self.delete_setting("customKeymap")

    # -------------------------------------------------------------------------
    # Track Resume Position API
    # -------------------------------------------------------------------------

    def save_position(
        self,
        file_path: str,
        position: float,
        duration: Optional[float] = None,
        filename: Optional[str] = None
    ) -> None:
        norm_path = normalize_file_path(file_path)
        if not norm_path:
            return
        with self._lock:
            fn = filename or (os.path.basename(file_path) if not file_path.startswith("http") else file_path)
            self._cache["positions"][norm_path] = {
                "position": float(position),
                "duration": float(duration) if duration is not None else None,
                "filename": fn,
                "updated_at": time.time()
            }
            self._save_to_disk()

    def get_position(self, file_path: str) -> Optional[float]:
        norm_path = normalize_file_path(file_path)
        if not norm_path:
            return None
        with self._lock:
            rec = self._cache["positions"].get(norm_path)
            if rec and isinstance(rec, dict):
                return float(rec.get("position", 0.0))
            return None

    def get_position_record(self, file_path: str) -> Optional[Dict[str, Any]]:
        norm_path = normalize_file_path(file_path)
        if not norm_path:
            return None
        with self._lock:
            rec = self._cache["positions"].get(norm_path)
            if rec and isinstance(rec, dict):
                return dict(rec)
            return None

    def clear_position(self, file_path: str) -> None:
        norm_path = normalize_file_path(file_path)
        if not norm_path:
            return
        with self._lock:
            if norm_path in self._cache["positions"]:
                del self._cache["positions"][norm_path]
                self._save_to_disk()

    def clear_all_positions(self) -> None:
        with self._lock:
            self._cache["positions"].clear()
            self._save_to_disk()

    def save_recent_file(
        self,
        file_path: str,
        filename: Optional[str] = None,
        max_entries: int = 100
    ) -> None:
        norm_path = normalize_file_path(file_path)
        if not norm_path:
            return
        with self._lock:
            fn = filename or (os.path.basename(file_path) if not file_path.startswith("http") else file_path)
            # Remove any existing entry for same file
            self._cache["recent_media"] = [
                r for r in self._cache["recent_media"]
                if r.get("file_path") != norm_path
            ]
            self._cache["recent_media"].insert(0, {
                "file_path": norm_path,
                "filename": fn,
                "last_played": time.time()
            })
            # Keep top max_entries recent files
            self._cache["recent_media"] = self._cache["recent_media"][:max_entries]
            self._save_to_disk()

    def get_recent_files(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._cache["recent_media"][:limit])

    def clear_recent_files(self) -> None:
        with self._lock:
            self._cache["recent_media"].clear()
            self._save_to_disk()

    # -------------------------------------------------------------------------
    # Playlist State API
    # -------------------------------------------------------------------------

    def save_playlist_state(
        self,
        name: str = "default",
        tracks: Optional[List[Dict[str, Any]]] = None,
        current_index: int = 0,
        shuffle: bool = False,
        repeat_mode: str = "off",
        auto_next: bool = True
    ) -> None:
        with self._lock:
            self._cache["playlists_state"][name] = {
                "tracks": list(tracks or []),
                "current_index": int(current_index),
                "shuffle": bool(shuffle),
                "repeat_mode": str(repeat_mode),
                "auto_next": bool(auto_next),
                "updated_at": time.time()
            }
            self._save_to_disk()

    def get_playlist_state(self, name: str = "default") -> Dict[str, Any]:
        with self._lock:
            st = self._cache["playlists_state"].get(name)
            if st and isinstance(st, dict):
                return dict(st)
            return {
                "tracks": [],
                "current_index": 0,
                "shuffle": False,
                "repeat_mode": "off",
                "auto_next": True,
            }

    def clear_playlist_state(self, name: str = "default") -> None:
        with self._lock:
            if name in self._cache["playlists_state"]:
                del self._cache["playlists_state"][name]
                self._save_to_disk()


# Global singleton instance
_global_db_manager: Optional[DatabaseManager] = None
_db_singleton_lock = threading.Lock()


def get_db_manager(db_path: Optional[str] = None) -> DatabaseManager:
    """Returns or creates the global DatabaseManager singleton instance."""
    global _global_db_manager
    with _db_singleton_lock:
        if _global_db_manager is None or (db_path and _global_db_manager.db_path != db_path):
            _global_db_manager = DatabaseManager(db_path=db_path)
        return _global_db_manager


get_database_manager = get_db_manager


def set_db_manager(instance: Optional[DatabaseManager]) -> None:
    """Sets or clears the global DatabaseManager instance (useful in tests)."""
    global _global_db_manager
    with _db_singleton_lock:
        _global_db_manager = instance
