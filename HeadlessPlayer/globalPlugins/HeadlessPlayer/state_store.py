# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Persistent State Store (SQLite-backed).
Provides high-performance, ACID-compliant persistence for playback
resume positions, recent playlists, and session states.
"""

from __future__ import annotations
import hashlib
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .database import get_db_manager, normalize_file_path, DatabaseManager, get_default_db_path

logger = logging.getLogger("HeadlessPlayer.StateStore")
CURRENT_SCHEMA_VERSION = 1


def compute_file_hash_key(file_path: str) -> str:
    """
    Computes a deterministic hash key for a normalized file path.
    """
    norm = normalize_file_path(file_path)
    return hashlib.sha256(norm.encode("utf-8", errors="ignore")).hexdigest()[:16]


class StateStore:
    """
    Thread-safe, SQLite-backed state manager for HeadlessPlayer.
    Maintains 100% backward compatibility for all API methods.
    """

    def __init__(
        self,
        state_file_path: Optional[str] = None,
        auto_save: bool = True
    ) -> None:
        self._db: DatabaseManager = get_db_manager(db_path=state_file_path)
        self._auto_save = auto_save
        self._lock = threading.RLock()

    @property
    def state_file_path(self) -> str:
        return self._db.db_path

    def load(self) -> None:
        """No-op: SQLite connections read dynamically from disk with WAL cache."""
        pass

    def save(self) -> bool:
        """No-op: SQLite operations are committed synchronously/WAL."""
        return True

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
        self._db.save_position(
            file_path=file_path,
            position_sec=position_sec,
            duration_sec=duration_sec,
            min_threshold_sec=min_threshold_sec,
            end_threshold_sec=end_threshold_sec
        )
        return True

    def get_position(self, file_path: str) -> float:
        return self._db.get_position(file_path) or 0.0

    def clear_position(self, file_path: str) -> None:
        self._db.clear_position(file_path)

    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        return self._db.get_all_positions()

    def get_position_record(self, file_path: str) -> Optional[Dict[str, Any]]:
        positions = self._db.get_all_positions()
        norm = normalize_file_path(file_path)
        return positions.get(norm)

    def prune_positions(self, max_entries: int = 500) -> int:
        return self._db.prune_positions(max_entries=max_entries)

    # -------------------------------------------------------------------------
    # Recent Files History API
    # -------------------------------------------------------------------------

    def save_recent_file(self, file_path: str, max_entries: int = 20) -> None:
        self._db.save_recent_file(file_path=file_path, max_entries=max_entries)

    def get_recent_files(self) -> List[str]:
        raw = self._db.get_recent_files()
        res: List[str] = []
        for r in raw:
            if isinstance(r, dict):
                p = r.get("file_path")
                if p and isinstance(p, str):
                    res.append(p)
            elif isinstance(r, str):
                res.append(r)
        return res

    def clear_recent_files(self) -> None:
        self._db.clear_recent_files()

    # -------------------------------------------------------------------------
    # Playlist State API
    # -------------------------------------------------------------------------

    def save_last_playlist(
        self,
        tracks: Sequence[str],
        current_index: int = 0,
        shuffle: bool = False,
        repeat_mode: str = "off",
        auto_next: bool = True
    ) -> None:
        track_list = [{"path": t} if isinstance(t, str) else t for t in tracks]
        self._db.save_playlist_state(
            name="default",
            tracks=track_list,
            current_index=current_index,
            shuffle=shuffle,
            repeat_mode=str(repeat_mode),
            auto_next=auto_next
        )

    def get_last_playlist(self) -> Dict[str, Any]:
        return self._db.get_playlist_state("default")

    def clear_last_playlist(self) -> None:
        self._db.clear_playlist_state("default")

    # -------------------------------------------------------------------------
    # Player Settings API
    # -------------------------------------------------------------------------

    def save_setting(self, key: str, value: Any) -> None:
        self._db.set_setting(key, value)

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._db.get_setting(key, default)

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

    def export_state_to_dict(self) -> Dict[str, Any]:
        return {
            "version": CURRENT_SCHEMA_VERSION,
            "positions": self.get_all_positions(),
            "recent_files": self.get_recent_files(),
            "last_playlist": self.get_last_playlist(),
            "settings": self._db.get_all_settings(),
        }


# Global singleton instance
_global_state_store: Optional[StateStore] = None
_store_singleton_lock = threading.Lock()


def get_state_store(state_file_path: Optional[str] = None) -> StateStore:
    """Returns or creates the global StateStore singleton instance."""
    global _global_state_store
    with _store_singleton_lock:
        if _global_state_store is None:
            _global_state_store = StateStore(state_file_path=state_file_path)
        return _global_state_store


def set_state_store(instance: Optional[StateStore]) -> None:
    """Sets or clears the global StateStore singleton (useful in tests)."""
    global _global_state_store
    with _store_singleton_lock:
        _global_state_store = instance
