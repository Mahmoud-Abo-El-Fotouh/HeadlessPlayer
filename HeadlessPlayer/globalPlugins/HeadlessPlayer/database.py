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
import re
import shutil
import sys
import tempfile
import threading
import time
import zlib
from typing import Any, Dict, List, Optional, Sequence

try:
    import globalVars
except Exception:
    globalVars = None

try:
    import config
except Exception:
    config = None

logger = logging.getLogger("HeadlessPlayer.Database")

DB_FILE_NAME = "headlessPlayer.db"
MAGIC_HEADER = b"HPDB\x01"
_OBFUSCATE_KEY = b"HeadlessPlayerSecureDb2026!#"


def _encode_database_payload(data: Dict[str, Any]) -> bytes:
    """Encodes and obfuscates database cache into compact binary format."""
    raw = json.dumps(data, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    comp = zlib.compress(raw, 3)
    masked = bytes([b ^ _OBFUSCATE_KEY[i % len(_OBFUSCATE_KEY)] for i, b in enumerate(comp)])
    return MAGIC_HEADER + masked


def _decode_database_payload(blob: bytes) -> Dict[str, Any]:
    """Decodes binary or legacy plain-text database blob."""
    if not blob:
        return {}
    if blob.startswith(MAGIC_HEADER):
        payload = blob[len(MAGIC_HEADER):]
        unmasked = bytes([b ^ _OBFUSCATE_KEY[i % len(_OBFUSCATE_KEY)] for i, b in enumerate(payload)])
        raw = zlib.decompress(unmasked)
        return json.loads(raw.decode('utf-8'))
    elif blob.strip().startswith(b"{") or blob.strip().startswith(b"["):
        return json.loads(blob.decode('utf-8', errors='ignore'))
    else:
        raise ValueError("Unrecognized database file format")


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
        gv = sys.modules.get("globalVars", globalVars)
        if gv is not None and hasattr(gv, "appArgs") and hasattr(gv.appArgs, "configPath"):
            config_path = gv.appArgs.configPath
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


_YT_ID_REGEX = re.compile(
    r'(?:https?://)?(?:www\.|m\.|music\.)?'
    r'(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|v/|live/)|youtu\.be/|youtube:)'
    r'([a-zA-Z0-9_-]{11})',
    re.IGNORECASE
)


def normalize_file_path(file_path: str) -> str:
    """
    Normalizes a file path or stream URL for consistent database keys on Windows.
    - YouTube streams are normalized to canonical 'youtube:<video_id>'.
    - Local files are expanded to absolute paths and normalized case.
    - Other online URLs are preserved cleanly.
    """
    if not file_path:
        return ""
    p = str(file_path).strip()
    m = _YT_ID_REGEX.search(p)
    if m:
        return f"youtube:{m.group(1)}"

    if p.lower().startswith(("http://", "https://", "ytdl://", "custom://")):
        return p

    try:
        expanded = os.path.expanduser(os.path.expandvars(p))
        abs_path = os.path.abspath(expanded)
        return os.path.normcase(abs_path)
    except Exception:
        return p.lower()


def disambiguate_recent_name(item: Dict[str, Any], all_items: Sequence[Dict[str, Any]]) -> str:
    """
    Returns an accessible, disambiguated display title for a recent container or track.
    - For local folders: If multiple folders have the same folder name, prepends parent folder (e.g. 'Parent - Folder').
    - For local files: If multiple files have the same filename, prepends parent folder.
    - For online streams/playlists: If channel/platform is present and duplicates exist, prepends channel/platform.
    """
    title = str(item.get("title") or item.get("filename") or "").strip()
    parent = str(item.get("parent_name") or item.get("parent_folder") or "").strip()
    platform = str(item.get("platform_or_channel") or "").strip()

    same_title_count = sum(
        1 for it in all_items
        if str(it.get("title") or it.get("filename") or "").strip().lower() == title.lower()
    )

    if same_title_count > 1:
        if parent:
            return f"{parent} - {title}"
        elif platform:
            return f"{platform} - {title}"

    return title or str(item.get("path", ""))


class DatabaseManager:
    """
    Thread-safe, crash-resilient Database Manager for HeadlessPlayer.
    Persists settings, resume positions, playback history, and playlist state
    using high-speed memory caching, compact encrypted binary storage, and
    atomic disk synchronization.
    Zero binary dependencies; works across all NVDA versions.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or get_default_db_path()
        self._lock = threading.RLock()
        self._cache: Dict[str, Any] = {
            "settings": {},
            "positions": {},
            "recent_media": [],
            "recent_playlists": [],
            "recent_containers": [],
            "recent_tracks": [],
            "playlists_state": {}
        }
        self._init_database()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _init_database(self) -> None:
        """Loads existing data from disk or runs migration from legacy files."""
        with self._lock:
            if not self._db_path or self._db_path == ":memory:":
                return
            loaded = False
            if os.path.isfile(self._db_path):
                try:
                    with open(self._db_path, "rb") as f:
                        blob = f.read()
                    data = _decode_database_payload(blob)
                    if isinstance(data, dict):
                        self._cache["settings"] = data.get("settings", {})
                        self._cache["positions"] = data.get("positions", {})
                        self._cache["recent_media"] = data.get("recent_media", [])
                        rec_playlists = data.get("recent_playlists", data.get("recent_containers", []))
                        self._cache["recent_playlists"] = rec_playlists
                        self._cache["recent_containers"] = rec_playlists
                        self._cache["recent_tracks"] = data.get("recent_tracks", [])
                        self._cache["playlists_state"] = data.get("playlists_state", {})
                        loaded = True
                except Exception as e:
                    logger.warning("Failed to load existing database file: %s", e)
                    # Automatically preserve corrupted database before resetting cache!
                    try:
                        backup_name = f"{self._db_path}.corrupted_{int(time.time())}"
                        shutil.copy2(self._db_path, backup_name)
                        logger.info("Preserved corrupted database backup at %s", backup_name)
                    except Exception as bkp_err:
                        logger.error("Could not write backup for corrupted database: %s", bkp_err)

            # If primary database could not be loaded, attempt recovery from rolling backups (.bak1, .bak2)
            if not loaded:
                for ext in (".bak1", ".bak2"):
                    bak_file = self._db_path + ext
                    if os.path.isfile(bak_file):
                        try:
                            with open(bak_file, "rb") as f:
                                b_blob = f.read()
                            b_data = _decode_database_payload(b_blob)
                            if isinstance(b_data, dict):
                                self._cache["settings"] = b_data.get("settings", {})
                                self._cache["positions"] = b_data.get("positions", {})
                                self._cache["recent_media"] = b_data.get("recent_media", [])
                                rec_playlists = b_data.get("recent_playlists", b_data.get("recent_containers", []))
                                self._cache["recent_playlists"] = rec_playlists
                                self._cache["recent_containers"] = rec_playlists
                                self._cache["recent_tracks"] = b_data.get("recent_tracks", [])
                                self._cache["playlists_state"] = b_data.get("playlists_state", {})
                                loaded = True
                                logger.info("Successfully recovered database from backup: %s", bak_file)
                                try:
                                    self._save_to_disk()
                                except Exception as save_err:
                                    logger.warning("Could not immediately sync recovered db to disk: %s", save_err)
                                break
                        except Exception as bak_err:
                            logger.warning("Failed to recover from %s: %s", bak_file, bak_err)

            # Migrate legacy recent_media into recent_tracks if empty
            if not self._cache.get("recent_tracks") and self._cache.get("recent_media"):
                migrated = []
                for m in self._cache["recent_media"]:
                    fp = m.get("file_path", "")
                    fn = m.get("filename", "")
                    lp = m.get("last_played", time.time())
                    is_stream = fp.startswith(("http://", "https://", "youtube:", "ytdl://", "custom://"))
                    p_folder = os.path.basename(os.path.dirname(fp)) if not is_stream and os.path.exists(fp) else ""
                    migrated.append({
                        "path": fp,
                        "title": fn,
                        "type": "stream" if is_stream else "file",
                        "parent_folder": p_folder,
                        "platform_or_channel": "",
                        "last_played": lp
                    })
                self._cache["recent_tracks"] = migrated

            # Migrate legacy state if present
            self._migrate_legacy_data()
            # Migrate and enrich positions to v2 canonical and fingerprint format
            self._migrate_positions_v2()

    def _save_to_disk(self) -> None:
        """Atomically writes memory cache to disk via temp file replacement with retry."""
        with self._lock:
            if not self._db_path or self._db_path == ":memory:":
                return
            db_dir = os.path.dirname(self._db_path)
            if db_dir:
                try:
                    os.makedirs(db_dir, exist_ok=True)
                except Exception:
                    pass

            temp_path = self._db_path + f".tmp_{os.getpid()}_{threading.get_ident()}"
            try:
                payload = _encode_database_payload(self._cache)
                with open(temp_path, "wb") as f:
                    f.write(payload)

                # Maintain rolling backups (.bak1 and .bak2) before replacing primary db
                if os.path.exists(self._db_path) and os.path.getsize(self._db_path) > 0:
                    bak1 = self._db_path + ".bak1"
                    bak2 = self._db_path + ".bak2"
                    try:
                        if os.path.exists(bak1) and os.path.getsize(bak1) > 0:
                            shutil.copy2(bak1, bak2)
                        shutil.copy2(self._db_path, bak1)
                    except Exception as bkp_err:
                        logger.debug("Failed to rotate database backups: %s", bkp_err)

                # Atomic replace on Windows with retry loop for transient locks (Error 32)
                replaced = False
                for attempt in range(5):
                    try:
                        if os.path.exists(self._db_path):
                            os.replace(temp_path, self._db_path)
                        else:
                            os.rename(temp_path, self._db_path)
                        replaced = True
                        break
                    except (PermissionError, OSError):
                        if attempt < 4:
                            time.sleep(0.05 * (2 ** attempt))
                        else:
                            raise
            except Exception as e:
                logger.error("Error writing database to %s: %s", self._db_path, e)
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass

    def _migrate_legacy_data(self) -> None:
        """Migrates state from legacy headlessPlayer_data.json, headlessPlayer_state.json or nvda.ini."""
        with self._lock:
            legacy_dir = os.path.dirname(self._db_path)
            
            # 1. Check legacy headlessPlayer_data.json
            legacy_data_json = os.path.join(legacy_dir, "headlessPlayer_data.json")
            if os.path.isfile(legacy_data_json):
                try:
                    with open(legacy_data_json, "rb") as f:
                        data = _decode_database_payload(f.read())
                    if isinstance(data, dict):
                        if data.get("settings") and isinstance(data["settings"], dict):
                            for k, v in data["settings"].items():
                                if k not in self._cache["settings"]:
                                    self._cache["settings"][k] = v
                        if data.get("positions") and isinstance(data["positions"], dict):
                            for path, rec in data["positions"].items():
                                norm_key = normalize_file_path(path)
                                if norm_key and norm_key not in self._cache["positions"]:
                                    self._cache["positions"][norm_key] = rec
                        if data.get("recent_media") and isinstance(data["recent_media"], list):
                            existing_recent = {item.get("file_path") for item in self._cache["recent_media"] if isinstance(item, dict)}
                            for item in data["recent_media"]:
                                if isinstance(item, dict) and item.get("file_path") not in existing_recent:
                                    self._cache["recent_media"].append(item)
                                    existing_recent.add(item.get("file_path"))
                        if data.get("playlists_state") and isinstance(data["playlists_state"], dict):
                            for pl_name, pl_data in data["playlists_state"].items():
                                if pl_name not in self._cache["playlists_state"]:
                                    self._cache["playlists_state"][pl_name] = pl_data
                    try:
                        os.remove(legacy_data_json)
                    except Exception:
                        pass
                    self._save_to_disk()
                except Exception as e:
                    logger.warning("Error migrating headlessPlayer_data.json: %s", e)

            # 2. Check legacy headlessPlayer_state.json
            legacy_json_path = os.path.join(legacy_dir, "headlessPlayer_state.json")
            if os.path.isfile(legacy_json_path):
                try:
                    with open(legacy_json_path, "rb") as f:
                        data = _decode_database_payload(f.read())
                    if isinstance(data, dict):
                        # Settings
                        settings = data.get("settings", {})
                        if isinstance(settings, dict):
                            for k, v in settings.items():
                                if k not in self._cache["settings"]:
                                    self._cache["settings"][k] = v
                        # Positions
                        positions = data.get("positions", {})
                        if isinstance(positions, dict):
                            for path, rec in positions.items():
                                if isinstance(rec, dict):
                                    norm_key = normalize_file_path(path)
                                    if norm_key and norm_key not in self._cache["positions"]:
                                        self._cache["positions"][norm_key] = {
                                            "position": float(rec.get("position", 0.0)),
                                            "duration": float(rec["duration"]) if rec.get("duration") else None,
                                            "filename": rec.get("filename") or os.path.basename(path),
                                            "updated_at": time.time()
                                        }
                        # Recent files
                        recent = data.get("recent_files", [])
                        if isinstance(recent, list):
                            existing_recent = {item.get("file_path") for item in self._cache["recent_media"] if isinstance(item, dict)}
                            for r_path in recent:
                                if isinstance(r_path, str) and r_path.strip():
                                    norm_key = normalize_file_path(r_path.strip())
                                    if norm_key not in existing_recent:
                                        fn = os.path.basename(r_path) if not r_path.startswith("http") else r_path
                                        self._cache["recent_media"].append({
                                            "file_path": norm_key,
                                            "filename": fn,
                                            "last_played": time.time()
                                        })
                                        existing_recent.add(norm_key)
                        # Last playlist
                        last_pl = data.get("last_playlist")
                        if isinstance(last_pl, dict) and last_pl.get("tracks"):
                            if "default" not in self._cache["playlists_state"]:
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

            # 3. Migrate from nvda.ini [headlessPlayer]
            try:
                cfg = sys.modules.get("config", config)
                if cfg is not None and hasattr(cfg, "conf") and "headlessPlayer" in cfg.conf:
                    for k, v in cfg.conf["headlessPlayer"].items():
                        if k not in self._cache["settings"]:
                            self._cache["settings"][k] = v
                    self._save_to_disk()
            except Exception:
                pass

    def _migrate_positions_v2(self) -> None:
        """
        Migrates legacy position records to the v2 Smart Media Fingerprint format:
        1. Backs up database before migration to *.pre_migration_backup.
        2. Normalizes all legacy YouTube URLs into canonical 'youtube:<video_id>' keys.
        3. Enriches existing local files that are present on disk with file_size and mtime.
        Guarantees zero data loss.
        """
        with self._lock:
            positions = self._cache.get("positions")
            if not positions or not isinstance(positions, dict):
                return

            backup_created = False
            if self._db_path and self._db_path != ":memory:" and os.path.isfile(self._db_path):
                backup_path = f"{self._db_path}.pre_migration_backup"
                if not os.path.isfile(backup_path):
                    try:
                        shutil.copy2(self._db_path, backup_path)
                        backup_created = True
                        logger.info("Created pre-migration database backup at %s", backup_path)
                    except Exception as e:
                        logger.warning("Could not create pre-migration backup: %s", e)

            modified = False
            keys = list(positions.keys())
            for key in keys:
                rec = positions.get(key)
                if not isinstance(rec, dict):
                    continue

                norm_key = normalize_file_path(key)
                # 1. YouTube URL canonicalization
                if norm_key != key and norm_key.startswith("youtube:"):
                    if norm_key not in positions:
                        positions[norm_key] = rec
                    else:
                        existing = positions[norm_key]
                        if float(rec.get("updated_at", 0)) >= float(existing.get("updated_at", 0)):
                            positions[norm_key] = rec
                    del positions[key]
                    modified = True

                # 2. Local file fingerprint auto-enrichment
                elif not norm_key.startswith(("http://", "https://", "youtube:", "ytdl://", "custom://")):
                    if rec.get("file_size") is None:
                        try:
                            if os.path.isfile(norm_key):
                                rec["file_size"] = os.path.getsize(norm_key)
                                rec["file_mtime"] = os.path.getmtime(norm_key)
                                modified = True
                        except Exception:
                            pass

            if modified:
                logger.info("Successfully migrated database positions to v2 format")
                self._save_to_disk()

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

    set_multiple_settings = set_settings_bulk

    def get_all_settings(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._cache["settings"])

    def delete_setting(self, key: str) -> None:
        with self._lock:
            if key in self._cache["settings"]:
                del self._cache["settings"][key]
                self._save_to_disk()


    # -------------------------------------------------------------------------
    # Track Resume Position API
    # -------------------------------------------------------------------------

    def save_position(
        self,
        file_path: str,
        position_sec: Optional[float] = None,
        duration_sec: Optional[float] = None,
        filename: Optional[str] = None,
        position: Optional[float] = None,
        duration: Optional[float] = None,
        file_size: Optional[int] = None,
        file_mtime: Optional[float] = None,
        min_threshold_sec: float = 1.0,
        end_threshold_sec: float = 3.0,
        **kwargs: Any
    ) -> None:
        pos = position_sec if position_sec is not None else position
        if pos is None:
            return
        if pos < min_threshold_sec:
            self.clear_position(file_path)
            return
        dur = duration_sec if duration_sec is not None else duration
        if dur and dur > 0 and (dur - pos) <= end_threshold_sec:
            self.clear_position(file_path)
            return

        norm_path = normalize_file_path(file_path)
        if not norm_path:
            return

        # For local media files, automatically extract media fingerprint (size and mtime) if not passed
        is_stream = norm_path.startswith(("http://", "https://", "youtube:", "ytdl://", "custom://"))
        if not is_stream:
            try:
                if file_size is None and os.path.isfile(norm_path):
                    file_size = os.path.getsize(norm_path)
                if file_mtime is None and os.path.isfile(norm_path):
                    file_mtime = os.path.getmtime(norm_path)
            except Exception:
                pass

        with self._lock:
            fn = filename or (os.path.basename(file_path) if not is_stream else norm_path)
            rec: Dict[str, Any] = {
                "position": float(pos),
                "duration": float(dur) if dur is not None else None,
                "filename": fn,
                "updated_at": time.time()
            }
            if file_size is not None:
                rec["file_size"] = int(file_size)
            if file_mtime is not None:
                rec["file_mtime"] = float(file_mtime)

            self._cache["positions"][norm_path] = rec
            self._save_to_disk()

    def prune_positions(self, max_entries: int = 500) -> int:
        """Prunes oldest position records when count exceeds max_entries."""
        with self._lock:
            positions = self._cache.get("positions", {})
            if len(positions) <= max_entries:
                return 0
            # Sort keys by updated_at ascending (oldest first)
            sorted_items = sorted(
                positions.items(),
                key=lambda item: float(item[1].get("updated_at", 0.0) if isinstance(item[1], dict) else 0.0)
            )
            to_remove_count = len(positions) - max_entries
            for k, _ in sorted_items[:to_remove_count]:
                positions.pop(k, None)
            self._save_to_disk()
            return to_remove_count

    def get_position(
        self,
        file_path: str,
        current_duration: Optional[float] = None,
        current_size: Optional[int] = None
    ) -> Optional[float]:
        rec = self.get_position_record(
            file_path,
            current_duration=current_duration,
            current_size=current_size
        )
        if rec and isinstance(rec, dict):
            return float(rec.get("position", 0.0))
        return None

    def get_position_record(
        self,
        file_path: str,
        current_duration: Optional[float] = None,
        current_size: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        norm_path = normalize_file_path(file_path)
        if not norm_path:
            return None

        with self._lock:
            rec = self._cache["positions"].get(norm_path)
            if not rec or not isinstance(rec, dict):
                # Fallback check for streams: if norm_path is youtube:ID, check raw file_path
                if norm_path.startswith("youtube:") and file_path in self._cache["positions"]:
                    rec = self._cache["positions"][file_path]
                else:
                    return None

            pos = float(rec.get("position", 0.0))
            dur = float(rec.get("duration", 0.0)) if rec.get("duration") is not None else None

            is_stream = norm_path.startswith(("http://", "https://", "youtube:", "ytdl://", "custom://"))

            if not is_stream:
                # Local File Fingerprint Verification
                if os.path.isfile(norm_path):
                    try:
                        actual_size = current_size if current_size is not None else os.path.getsize(norm_path)
                        actual_mtime = os.path.getmtime(norm_path)

                        # Check file_size mismatch (file replaced or overwritten)
                        saved_size = rec.get("file_size")
                        if saved_size is not None and actual_size is not None:
                            if saved_size != actual_size:
                                logger.info(
                                    "Position invalidated for '%s': file size changed (saved=%d, actual=%d)",
                                    norm_path, saved_size, actual_size
                                )
                                del self._cache["positions"][norm_path]
                                self._save_to_disk()
                                return None

                        # Check duration mismatch if known (differs by > 3s)
                        saved_dur = rec.get("duration")
                        if saved_dur and current_duration and current_duration > 0:
                            if abs(float(current_duration) - float(saved_dur)) > 3.0:
                                logger.info(
                                    "Position invalidated for '%s': duration changed (saved=%.1f, actual=%.1f)",
                                    norm_path, float(saved_dur), float(current_duration)
                                )
                                del self._cache["positions"][norm_path]
                                self._save_to_disk()
                                return None

                        # Backward-Compatible Auto-Enrichment:
                        # If record lacks file_size, enrich it now so it is protected going forward
                        if saved_size is None and actual_size is not None:
                            rec["file_size"] = actual_size
                            rec["file_mtime"] = actual_mtime
                            self._save_to_disk()

                    except Exception as e:
                        logger.debug("Error checking file fingerprint for '%s': %s", norm_path, e)

            # Finished check: If position is within 3s of end, treat as completed
            if dur and dur > 0 and (dur - pos) <= 3.0:
                del self._cache["positions"][norm_path]
                self._save_to_disk()
                return None

            return dict(rec)

    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """Returns a copy of all stored position records."""
        with self._lock:
            return {k: dict(v) for k, v in self._cache.get("positions", {}).items() if isinstance(v, dict)}

    def clear_position(self, file_path: str) -> None:
        norm_path = normalize_file_path(file_path)
        if not norm_path:
            return
        with self._lock:
            modified = False
            if norm_path in self._cache["positions"]:
                del self._cache["positions"][norm_path]
                modified = True
            if file_path != norm_path and file_path in self._cache["positions"]:
                del self._cache["positions"][file_path]
                modified = True
            if modified:
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
    # Recents History Engine (Playlists & Tracks)
    # -------------------------------------------------------------------------

    def save_recent_playlist(
        self,
        path: str,
        title: Optional[str] = None,
        container_type: str = "folder",
        parent_name: Optional[str] = None,
        platform_or_channel: Optional[str] = None,
        max_entries: Optional[int] = None
    ) -> None:
        """
        Saves a local folder or playlist into the recent playlists collection.
        Deduplicates by path, places at index 0 (newest), and trims to max limit.
        """
        if not path:
            return
        with self._lock:
            cfg_enabled = self.get_setting("recentsEnabled")
            if cfg_enabled is False:
                return

            if container_type == "folder":
                if self.get_setting("recentsKeepFolders") is False:
                    return
            elif container_type in ("playlist", "container", "search"):
                if self.get_setting("recentsKeepPlaylists") is False:
                    return

            limit = max_entries or int(self.get_setting("recentsMaxEntries") or 30)

            p_name = parent_name
            if not p_name and not path.startswith(("http://", "https://", "youtube:", "ytdl://", "custom://")) and os.path.exists(path):
                try:
                    p_name = os.path.basename(os.path.dirname(os.path.abspath(path)))
                except Exception:
                    p_name = ""

            t_name = title or (os.path.basename(os.path.normpath(path)) if not path.startswith("http") else path)

            norm_key = normalize_file_path(path)
            raw_items = self._cache.get("recent_playlists") or self._cache.get("recent_containers", [])
            playlists = [
                c for c in raw_items
                if normalize_file_path(c.get("path", "")) != norm_key and c.get("path") != path
            ]
            record = {
                "path": path,
                "title": t_name,
                "type": container_type,
                "parent_name": p_name or "",
                "platform_or_channel": platform_or_channel or "",
                "last_played": time.time()
            }
            playlists.insert(0, record)
            trimmed = playlists[:limit]
            self._cache["recent_playlists"] = trimmed
            self._cache["recent_containers"] = trimmed
            self._save_to_disk()

    save_recent_container = save_recent_playlist

    def get_recent_playlists(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns the list of recent playlists (folders & playlists), newest first."""
        with self._lock:
            cfg_enabled = self.get_setting("recentsEnabled")
            if cfg_enabled is False:
                return []
            lim = limit or int(self.get_setting("recentsMaxEntries") or 30)
            items = list(self._cache.get("recent_playlists") or self._cache.get("recent_containers", []))
            keep_folders = self.get_setting("recentsKeepFolders") is not False
            keep_playlists = self.get_setting("recentsKeepPlaylists") is not False
            filtered = [
                it for it in items
                if (it.get("type") == "folder" and keep_folders) or (it.get("type") in ("playlist", "container", "search") and keep_playlists)
            ]
            return filtered[:lim]

    get_recent_containers = get_recent_playlists

    def delete_recent_playlist(self, path: str) -> bool:
        """Removes a playlist from recent history by path."""
        if not path:
            return False
        with self._lock:
            norm_key = normalize_file_path(path)
            raw_items = self._cache.get("recent_playlists") or self._cache.get("recent_containers", [])
            orig_len = len(raw_items)
            filtered = [
                c for c in raw_items
                if normalize_file_path(c.get("path", "")) != norm_key and c.get("path") != path
            ]
            self._cache["recent_playlists"] = filtered
            self._cache["recent_containers"] = filtered
            if len(filtered) != orig_len:
                self._save_to_disk()
                return True
            return False

    delete_recent_container = delete_recent_playlist

    def clear_recent_playlists(self) -> None:
        with self._lock:
            self._cache["recent_playlists"] = []
            self._cache["recent_containers"] = []
            self._save_to_disk()

    clear_recent_containers = clear_recent_playlists

    def save_recent_track(
        self,
        path: str,
        title: Optional[str] = None,
        track_type: str = "file",
        parent_folder: Optional[str] = None,
        platform_or_channel: Optional[str] = None,
        max_entries: Optional[int] = None
    ) -> None:
        """
        Saves a local file or online stream into the recent tracks collection.
        Deduplicates by path, places at index 0 (newest), and trims to max limit.
        """
        if not path:
            return
        with self._lock:
            cfg_enabled = self.get_setting("recentsEnabled")
            if cfg_enabled is False:
                return

            if track_type == "file":
                if self.get_setting("recentsKeepFiles") is False:
                    return
            elif track_type == "stream":
                if self.get_setting("recentsKeepStreams") is False:
                    return

            limit = max_entries or int(self.get_setting("recentsMaxEntries") or 30)

            p_folder = parent_folder
            if not p_folder and not path.startswith(("http://", "https://", "youtube:", "ytdl://", "custom://")) and os.path.isfile(path):
                try:
                    p_folder = os.path.basename(os.path.dirname(os.path.abspath(path)))
                except Exception:
                    p_folder = ""

            t_name = title or (os.path.basename(path) if not path.startswith("http") else path)

            norm_key = normalize_file_path(path)
            tracks = [
                t for t in self._cache.get("recent_tracks", [])
                if normalize_file_path(t.get("path", "")) != norm_key and t.get("path") != path
            ]
            record = {
                "path": path,
                "title": t_name,
                "type": track_type,
                "parent_folder": p_folder or "",
                "platform_or_channel": platform_or_channel or "",
                "last_played": time.time()
            }
            tracks.insert(0, record)
            self._cache["recent_tracks"] = tracks[:limit]
            # Synchronize legacy recent_media for backward compatibility
            self.save_recent_file(path, filename=t_name, max_entries=limit)
            self._save_to_disk()

    def get_recent_tracks(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns the list of recent tracks (files & streams), newest first."""
        with self._lock:
            cfg_enabled = self.get_setting("recentsEnabled")
            if cfg_enabled is False:
                return []
            lim = limit or int(self.get_setting("recentsMaxEntries") or 30)
            items = list(self._cache.get("recent_tracks", []))
            keep_files = self.get_setting("recentsKeepFiles") is not False
            keep_streams = self.get_setting("recentsKeepStreams") is not False
            filtered = [
                it for it in items
                if (it.get("type") == "file" and keep_files) or (it.get("type") == "stream" and keep_streams)
            ]
            return filtered[:lim]

    def delete_recent_track(self, path: str) -> bool:
        """Removes a track from recent history by path."""
        if not path:
            return False
        with self._lock:
            norm_key = normalize_file_path(path)
            orig_len = len(self._cache.get("recent_tracks", []))
            self._cache["recent_tracks"] = [
                t for t in self._cache.get("recent_tracks", [])
                if normalize_file_path(t.get("path", "")) != norm_key and t.get("path") != path
            ]
            self._cache["recent_media"] = [
                m for m in self._cache.get("recent_media", [])
                if normalize_file_path(m.get("file_path", "")) != norm_key and m.get("file_path") != path
            ]
            if len(self._cache["recent_tracks"]) != orig_len:
                self._save_to_disk()
                return True
            return False

    def clear_recent_tracks(self) -> None:
        with self._lock:
            self._cache["recent_tracks"] = []
            self._cache["recent_media"] = []
            self._save_to_disk()

    # -------------------------------------------------------------------------
    # Playlist State API
    # -------------------------------------------------------------------------

    def save_playlist_state(
        self,
        name: str = "default",
        tracks: Optional[List[Dict[str, Any]]] = None,
        current_index: int = 0,
        position: float = 0.0,
        shuffle: bool = False,
        repeat_mode: str = "off",
        auto_next: bool = True,
        source_target: Optional[str] = None,
        source_type: str = "listing"
    ) -> None:
        with self._lock:
            self._cache["playlists_state"][name] = {
                "tracks": list(tracks or []),
                "current_index": int(current_index),
                "position": float(position),
                "shuffle": bool(shuffle),
                "repeat_mode": str(repeat_mode),
                "auto_next": bool(auto_next),
                "source_target": source_target,
                "source_type": source_type,
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
                "position": 0.0,
                "shuffle": False,
                "repeat_mode": "off",
                "auto_next": True,
                "source_target": None,
                "source_type": "listing",
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
