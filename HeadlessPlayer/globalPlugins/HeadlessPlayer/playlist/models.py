# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Playlist Models.
Provides RepeatMode enum and Track data structure.
"""

from __future__ import annotations
from enum import Enum
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Union

try:
    from ..utils.common import is_audio_file, is_video_file, is_supported_media_file
except ImportError:
    try:
        from ..utils import is_audio_file, is_video_file, is_supported_media_file
    except ImportError:
        from utils import is_audio_file, is_video_file, is_supported_media_file

try:
    from ..utils.explorer import extract_local_media_durations
except ImportError:
    try:
        from ..explorer_utils import extract_local_media_durations
    except ImportError:
        try:
            from explorer_utils import extract_local_media_durations
        except ImportError:
            extract_local_media_durations = None

logger = logging.getLogger("HeadlessPlayer.Playlist.Models")


class RepeatMode(str, Enum):
    """
    Playback repeat modes.
    """
    OFF = "off"
    TRACK = "track"
    PLAYLIST = "playlist"

    @classmethod
    def from_string(cls, val: Union[str, RepeatMode]) -> RepeatMode:
        if isinstance(val, cls):
            return val
        s = str(val).strip().lower()
        if s in ("track", "single", "one", "repeat_track", "repeat_one"):
            return cls.TRACK
        if s in ("playlist", "all", "loop", "repeat_playlist", "repeat_all"):
            return cls.PLAYLIST
        return cls.OFF

    def cycle(self) -> RepeatMode:
        """
        Cycles: OFF -> TRACK -> PLAYLIST -> OFF
        """
        if self == RepeatMode.OFF:
            return RepeatMode.TRACK
        elif self == RepeatMode.TRACK:
            return RepeatMode.PLAYLIST
        else:
            return RepeatMode.OFF


class Track:
    """
    Represents a single media item in the playlist queue.
    """

    def __init__(
        self,
        path: str,
        title: Optional[str] = None,
        duration: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_stream: Optional[bool] = None
    ) -> None:
        if is_stream is not None:
            self.is_stream = bool(is_stream)
        else:
            self.is_stream = bool(path) and str(path).strip().lower().startswith(("http://", "https://", "ytdl://", "custom://", "youtube:"))
        self.metadata: Dict[str, Any] = dict(metadata) if metadata else {}
        if self.is_stream:
            self.path = str(path).strip()
            self.filename = self.path
            self.title = title or self.path
            kind = (self.metadata.get("kind") or "").lower()
            if kind in ("audio", "radio", "soundcloud") or self.path.lower().endswith((".mp3", ".m4a", ".aac", ".ogg", ".opus")):
                self.is_audio = True
                self.is_video = False
            else:
                self.is_audio = bool(self.metadata.get("is_audio", True))
                self.is_video = bool(self.metadata.get("is_video", False))
        else:
            self.path = os.path.abspath(path) if path else ""
            self.filename = os.path.basename(self.path)
            base_name, _ = os.path.splitext(self.filename)
            self.title = title or base_name
            self.is_audio = is_audio_file(self.path)
            self.is_video = is_video_file(self.path)
        self.duration: Optional[float] = float(duration) if duration is not None else None
        self.chapters: List[Dict[str, Any]] = list(self.metadata.get("chapters", [])) if isinstance(self.metadata.get("chapters"), list) else []

    @classmethod
    def from_path(cls, path: str) -> Track:
        return cls(path=path)

    @property
    def display_name(self) -> str:
        return self.title or self.filename

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "filename": self.filename,
            "title": self.title,
            "duration": self.duration,
            "is_audio": self.is_audio,
            "is_video": self.is_video,
            "is_stream": self.is_stream,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Track:
        if isinstance(data, Track):
            return data
        if not isinstance(data, dict):
            return cls(path=str(data or ""))
        return cls(
            path=str(data.get("path") or ""),
            title=data.get("title"),
            duration=data.get("duration"),
            metadata=data.get("metadata"),
        )

    @staticmethod
    def _normalize_track_key(p: Optional[str]) -> str:
        if not p:
            return ""
        if p.startswith(("http://", "https://", "ytdl://", "custom://")):
            return p.strip()
        try:
            return os.path.normcase(p)
        except Exception:
            return p

    def __repr__(self) -> str:
        return f"<Track '{self.display_name}' path='{self.path}'>"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Track):
            return False
        return self._normalize_track_key(self.path) == self._normalize_track_key(other.path)

    def __hash__(self) -> int:
        return hash(self._normalize_track_key(self.path))


def _extract_durations_safe(paths: Sequence[str]) -> Dict[str, float]:
    """Safely extracts durations for local media files using explorer_utils without crashing."""
    if callable(extract_local_media_durations):
        try:
            return extract_local_media_durations(paths)
        except Exception:
            return {}
    return {}
