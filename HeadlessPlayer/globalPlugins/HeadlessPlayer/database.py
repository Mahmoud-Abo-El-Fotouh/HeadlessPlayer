# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - SQLite Database Storage Layer.
Provides high-performance, ACID-compliant, thread-safe persistence for
all add-on settings, custom keyboard shortcuts, track resume positions,
playback history, and active playlist states.
"""

from __future__ import annotations
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("HeadlessPlayer.Database")

DB_FILE_NAME = "headlessPlayer.db"
CURRENT_SCHEMA_VERSION = 1


def get_default_db_path() -> str:
    """
    Determines the storage path for the SQLite database file.
    Prefers NVDA user configuration directory (%APPDATA%/nvda),
    ensuring private user state is never stored inside add-on code folders.
    """
    # 1. Environment variable override (used for testing or custom portable setups)
    env_path = os.environ.get("HEADLESSPLAYER_DB_PATH") or os.environ.get("HEADLESSPLAYER_STATE_FILE")
    if env_path:
        if env_path.endswith(".json"):
            env_path = env_path[:-5] + ".db"
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
    Normalizes a file path for consistent database primary keys on Windows.
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
    Thread-safe SQLite Database Manager for HeadlessPlayer.
    Manages settings, track resume positions, and playlist state.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or get_default_db_path()
        self._lock = threading.RLock()
        self._local = threading.local()
        self._init_database()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _get_connection(self) -> sqlite3.Connection:
        """Returns a thread-local SQLite connection with WAL mode enabled."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            db_dir = os.path.dirname(self._db_path)
            if db_dir:
                try:
                    os.makedirs(db_dir, exist_ok=True)
                except Exception:
                    pass
            conn = sqlite3.connect(
                self._db_path,
                timeout=10.0,
                check_same_thread=False,
                isolation_level=None  # autocommit mode for high-concurrency safety
            )
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            self._local.conn = conn
        return conn

    def _init_database(self) -> None:
        """Creates tables and indexes if they do not exist, and performs legacy migration."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS positions (
                        file_path TEXT PRIMARY KEY,
                        position REAL NOT NULL,
                        duration REAL,
                        filename TEXT,
                        updated_at REAL NOT NULL
                    );
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_positions_updated ON positions(updated_at);
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS recent_media (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_path TEXT UNIQUE,
                        filename TEXT,
                        last_played REAL NOT NULL
                    );
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_recent_last_played ON recent_media(last_played DESC);
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS playlists_state (
                        name TEXT PRIMARY KEY,
                        tracks_json TEXT NOT NULL,
                        current_index INTEGER NOT NULL DEFAULT 0,
                        shuffle INTEGER NOT NULL DEFAULT 0,
                        repeat_mode TEXT NOT NULL DEFAULT 'off',
                        auto_next INTEGER NOT NULL DEFAULT 1,
                        updated_at REAL NOT NULL
                    );
                """)

            # Check and run automatic migration from legacy JSON or nvda.ini
            self._migrate_legacy_data()

    def _migrate_legacy_data(self) -> None:
        """Migrates state from legacy headlessPlayer_state.json and nvda.ini if present."""
        legacy_dir = os.path.dirname(self._db_path)
        legacy_json_path = os.path.join(legacy_dir, "headlessPlayer_state.json")

        if os.path.isfile(legacy_json_path):
            try:
                logger.info("Migrating legacy state from %s to SQLite...", legacy_json_path)
                with open(legacy_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, dict):
                    # 1. Migrate settings
                    settings = data.get("settings", {})
                    if isinstance(settings, dict):
                        for k, v in settings.items():
                            self.set_setting(k, v)

                    # 2. Migrate positions
                    positions = data.get("positions", {})
                    if isinstance(positions, dict):
                        for path, rec in positions.items():
                            if isinstance(rec, dict):
                                pos = float(rec.get("position", 0.0))
                                dur = float(rec["duration"]) if rec.get("duration") else None
                                fn = rec.get("filename") or os.path.basename(path)
                                self.save_position(path, pos, dur, filename=fn)

                    # 3. Migrate recent files
                    recent = data.get("recent_files", [])
                    if isinstance(recent, list):
                        for r_path in recent:
                            if isinstance(r_path, str) and r_path.strip():
                                self.save_recent_file(r_path.strip())

                    # 4. Migrate last playlist
                    last_pl = data.get("last_playlist")
                    if isinstance(last_pl, dict) and last_pl.get("tracks"):
                        self.save_playlist_state(
                            name="default",
                            tracks=last_pl.get("tracks", []),
                            current_index=last_pl.get("current_index", 0),
                            shuffle=last_pl.get("shuffle", False),
                            repeat_mode=last_pl.get("repeat_mode", "off"),
                            auto_next=last_pl.get("auto_next", True)
                        )

                # Rename migrated JSON file to .migrated so we do not re-run migration
                try:
                    os.replace(legacy_json_path, legacy_json_path + ".migrated")
                except Exception:
                    pass
                logger.info("Legacy state migration completed successfully.")
            except Exception as e:
                logger.warning("Error migrating legacy state file: %s", e)

        # Migrate from nvda.ini [headlessPlayer] if settings table is mostly empty
        try:
            import config
            if hasattr(config, "conf") and "headlessPlayer" in config.conf:
                legacy_nvda_cfg = config.conf["headlessPlayer"]
                for k, v in legacy_nvda_cfg.items():
                    if self.get_setting(k) is None:
                        self.set_setting(k, v)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Settings Key-Value API
    # -------------------------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Retrieves a single setting value decoded from JSON."""
        try:
            conn = self._get_connection()
            cursor = conn.execute("SELECT value_json FROM settings WHERE key = ?;", (key,))
            row = cursor.fetchone()
            if row and row[0] is not None:
                return json.loads(row[0])
        except Exception as e:
            logger.debug("Error getting setting %s: %e", key, e)
        return default

    def set_setting(self, key: str, value: Any) -> None:
        """Stores a single setting value encoded as JSON."""
        try:
            conn = self._get_connection()
            val_json = json.dumps(value, ensure_ascii=False)
            now = time.time()
            with self._lock:
                conn.execute("""
                    INSERT INTO settings (key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at;
                """, (key, val_json, now))
        except Exception as e:
            logger.error("Error setting setting %s: %s", key, e)

    def get_all_settings(self) -> Dict[str, Any]:
        """Returns a dictionary copy of all settings in the database."""
        res: Dict[str, Any] = {}
        try:
            conn = self._get_connection()
            cursor = conn.execute("SELECT key, value_json FROM settings;")
            for k, val_json in cursor.fetchall():
                try:
                    res[k] = json.loads(val_json)
                except Exception:
                    res[k] = val_json
        except Exception as e:
            logger.debug("Error fetching all settings: %s", e)
        return res

    def set_multiple_settings(self, mapping: Dict[str, Any]) -> None:
        """Stores multiple setting values atomically."""
        if not mapping:
            return
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            rows = [(k, json.dumps(v, ensure_ascii=False), now) for k, v in mapping.items()]
            conn.executemany("""
                INSERT INTO settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at;
            """, rows)

    # -------------------------------------------------------------------------
    # Resume Positions API
    # -------------------------------------------------------------------------

    def save_position(
        self,
        file_path: str,
        position_sec: float,
        duration_sec: Optional[float] = None,
        filename: Optional[str] = None,
        min_threshold_sec: float = 1.0,
        end_threshold_sec: float = 1.0
    ) -> bool:
        """
        Saves the playback position for a media file.
        Positions under min_threshold or within end_threshold of completion are cleared.
        """
        if not file_path or position_sec is None:
            return False

        norm_path = normalize_file_path(file_path)
        if not norm_path:
            return False

        # If at start, clear saved position
        if position_sec < min_threshold_sec:
            self.clear_position(norm_path)
            return False

        # If completed (near end of duration), clear saved position
        if duration_sec is not None and duration_sec > 0:
            if (duration_sec - position_sec) <= end_threshold_sec:
                self.clear_position(norm_path)
                return False

        now = time.time()
        fn = filename or os.path.basename(file_path)

        with self._lock:
            conn = self._get_connection()
            conn.execute("""
                INSERT INTO positions (file_path, position, duration, filename, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    position = excluded.position,
                    duration = excluded.duration,
                    filename = excluded.filename,
                    updated_at = excluded.updated_at;
            """, (norm_path, round(float(position_sec), 2), round(float(duration_sec), 2) if duration_sec else None, fn, now))

            # Prune old positions if exceeding 1,000 entries
            conn.execute("""
                DELETE FROM positions WHERE file_path NOT IN (
                    SELECT file_path FROM positions ORDER BY updated_at DESC LIMIT 1000
                );
            """)
            return True

    def get_position(self, file_path: str) -> float:
        """Retrieves saved resume position for a file in seconds, or 0.0 if not found."""
        if not file_path:
            return 0.0
        norm_path = normalize_file_path(file_path)
        try:
            conn = self._get_connection()
            cursor = conn.execute("SELECT position FROM positions WHERE file_path = ?;", (norm_path,))
            row = cursor.fetchone()
            if row and row[0] is not None:
                return float(row[0])
        except Exception as e:
            logger.debug("Error getting position for %s: %s", file_path, e)
        return 0.0

    def clear_position(self, file_path: str) -> None:
        """Clears saved position for a specific file."""
        if not file_path:
            return
        norm_path = normalize_file_path(file_path)
        with self._lock:
            conn = self._get_connection()
            conn.execute("DELETE FROM positions WHERE file_path = ?;", (norm_path,))

    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """Returns all saved position records as a dictionary."""
        res: Dict[str, Dict[str, Any]] = {}
        try:
            conn = self._get_connection()
            cursor = conn.execute("SELECT file_path, position, duration, filename, updated_at FROM positions;")
            for path, pos, dur, fn, upd in cursor.fetchall():
                res[path] = {
                    "position": pos,
                    "duration": dur,
                    "filename": fn,
                    "updated_at": upd
                }
        except Exception as e:
            logger.debug("Error fetching all positions: %s", e)
        return res

    # -------------------------------------------------------------------------
    # Recent Media History API
    # -------------------------------------------------------------------------

    def save_recent_file(self, file_path: str, filename: Optional[str] = None, max_entries: int = 50) -> None:
        """Records a file path in the recent media history."""
        if not file_path:
            return
        norm_path = normalize_file_path(file_path)
        fn = filename or os.path.basename(file_path)
        now = time.time()

        with self._lock:
            conn = self._get_connection()
            conn.execute("""
                INSERT INTO recent_media (file_path, filename, last_played)
                VALUES (?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    last_played = excluded.last_played,
                    filename = excluded.filename;
            """, (norm_path, fn, now))

            conn.execute("""
                DELETE FROM recent_media WHERE id NOT IN (
                    SELECT id FROM recent_media ORDER BY last_played DESC LIMIT ?
                );
            """, (max_entries,))

    def get_recent_files(self) -> List[str]:
        """Returns ordered list of recently played file paths."""
        try:
            conn = self._get_connection()
            cursor = conn.execute("SELECT file_path FROM recent_media ORDER BY last_played DESC;")
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.debug("Error getting recent files: %s", e)
            return []

    def clear_recent_files(self) -> None:
        """Clears all recent media history."""
        with self._lock:
            conn = self._get_connection()
            conn.execute("DELETE FROM recent_media;")

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
        """Saves active playlist state across sessions."""
        now = time.time()
        tracks_json = json.dumps(tracks or [], ensure_ascii=False)
        with self._lock:
            conn = self._get_connection()
            conn.execute("""
                INSERT INTO playlists_state (name, tracks_json, current_index, shuffle, repeat_mode, auto_next, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    tracks_json = excluded.tracks_json,
                    current_index = excluded.current_index,
                    shuffle = excluded.shuffle,
                    repeat_mode = excluded.repeat_mode,
                    auto_next = excluded.auto_next,
                    updated_at = excluded.updated_at;
            """, (name, tracks_json, max(0, int(current_index)), 1 if shuffle else 0, str(repeat_mode), 1 if auto_next else 0, now))

    def get_playlist_state(self, name: str = "default") -> Dict[str, Any]:
        """Retrieves saved playlist state."""
        try:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT tracks_json, current_index, shuffle, repeat_mode, auto_next FROM playlists_state WHERE name = ?;",
                (name,)
            )
            row = cursor.fetchone()
            if row:
                tracks = json.loads(row[0]) if row[0] else []
                return {
                    "tracks": tracks,
                    "current_index": int(row[1]),
                    "shuffle": bool(row[2]),
                    "repeat_mode": str(row[3]),
                    "auto_next": bool(row[4]),
                }
        except Exception as e:
            logger.debug("Error getting playlist state for %s: %s", name, e)

        return {
            "tracks": [],
            "current_index": 0,
            "shuffle": False,
            "repeat_mode": "off",
            "auto_next": True,
        }

    def clear_playlist_state(self, name: str = "default") -> None:
        """Clears playlist state for given name."""
        with self._lock:
            conn = self._get_connection()
            conn.execute("DELETE FROM playlists_state WHERE name = ?;", (name,))


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


def set_db_manager(instance: Optional[DatabaseManager]) -> None:
    """Sets or clears the global DatabaseManager instance (useful in tests)."""
    global _global_db_manager
    with _db_singleton_lock:
        _global_db_manager = instance
