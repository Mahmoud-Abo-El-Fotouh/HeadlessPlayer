# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Playlist & Queue Management Engine.
Handles ordered track queues, natural alphanumeric sorting for folders,
non-destructive shuffle/unshuffle index mapping, repeat modes, and auto-next coordination.
"""

from __future__ import annotations
from enum import Enum
import logging
import os
import random
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

try:
    from .utils import (
        ALL_SUPPORTED_EXTENSIONS,
        filter_and_sort_media_files,
        find_media_files_in_dir,
        is_audio_file,
        is_supported_media_file,
        is_video_file,
        natural_sort,
        log_debug,
        log_exception,
    )
except ImportError:
    # Direct import fallback for standalone testing
    from utils import (
        ALL_SUPPORTED_EXTENSIONS,
        filter_and_sort_media_files,
        find_media_files_in_dir,
        is_audio_file,
        is_supported_media_file,
        is_video_file,
        natural_sort,
        log_debug,
        log_exception,
    )

logger = logging.getLogger("HeadlessPlayer.Playlist")


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
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        self.is_stream: bool = bool(path) and str(path).strip().lower().startswith(("http://", "https://", "ytdl://", "custom://"))
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
        # Online stream URLs (YouTube, HTTP, HLS) are case-sensitive and must NOT be mangled by normcase
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


class Playlist:
    """
    Thread-safe playlist manager supporting natural sorting, non-destructive
    shuffle/unshuffle, repeat modes, and auto-next coordination.
    """

    def __init__(
        self,
        repeat_mode: Union[str, RepeatMode] = RepeatMode.OFF,
        auto_next: bool = True,
        shuffle: bool = False
    ) -> None:
        self._lock = threading.RLock()
        self._tracks: List[Track] = []
        self._current_index: int = -1  # Index in active sequence (shuffled or original)
        self._shuffle: bool = bool(shuffle)
        self._shuffled_indices: List[int] = []  # Maps active index -> index in _tracks
        self._repeat_mode: RepeatMode = RepeatMode.from_string(repeat_mode)
        self._auto_next: bool = bool(auto_next)
        self._listeners: List[Callable[[str, Any], None]] = []

    # -------------------------------------------------------------------------
    # Properties & Basic Queries
    # -------------------------------------------------------------------------

    @property
    def tracks(self) -> List[Track]:
        """Returns a shallow copy of the original ordered track list."""
        with self._lock:
            return list(self._tracks)

    @property
    def count(self) -> int:
        """Returns total number of tracks in the playlist."""
        with self._lock:
            return len(self._tracks)

    def __len__(self) -> int:
        return self.count

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._tracks) == 0

    @property
    def current_index(self) -> int:
        """
        0-based index in the currently active playback sequence.
        Returns -1 if playlist is empty or no track selected.
        """
        with self._lock:
            return self._current_index

    @property
    def original_index(self) -> int:
        """
        0-based index in the underlying original track list.
        Returns -1 if playlist is empty or no track selected.
        """
        with self._lock:
            if self._current_index < 0 or not self._tracks:
                return -1
            if self._shuffle and self._shuffled_indices:
                if 0 <= self._current_index < len(self._shuffled_indices):
                    return self._shuffled_indices[self._current_index]
                return -1
            return self._current_index

    @property
    def shuffle(self) -> bool:
        with self._lock:
            return self._shuffle

    @property
    def repeat_mode(self) -> RepeatMode:
        with self._lock:
            return self._repeat_mode

    @property
    def auto_next(self) -> bool:
        with self._lock:
            return self._auto_next

    # -------------------------------------------------------------------------
    # Current Track & Info Queries
    # -------------------------------------------------------------------------

    def get_current_track(self) -> Optional[Track]:
        """
        Returns the currently active Track, or None if playlist is empty.
        """
        with self._lock:
            if not self._tracks or self._current_index < 0:
                return None
            orig_idx = self.original_index
            if 0 <= orig_idx < len(self._tracks):
                return self._tracks[orig_idx]
            return None

    def get_track_at(self, index: int) -> Optional[Track]:
        """
        Returns the Track at a specific index in the active playback sequence.
        """
        with self._lock:
            if index < 0 or index >= len(self._tracks):
                return None
            if self._shuffle and self._shuffled_indices:
                if 0 <= index < len(self._shuffled_indices):
                    orig_idx = self._shuffled_indices[index]
                    return self._tracks[orig_idx]
                return None
            return self._tracks[index]

    def get_track_info(self, lang: str = "en") -> str:
        """
        Returns formatted track position information (e.g. 'Track 3 of 15').
        """
        with self._lock:
            total = len(self._tracks)
            if total == 0 or self._current_index < 0:
                return "No tracks in playlist" if lang == "en" else "لا توجد مقاطع في قائمة التشغيل"

            # In shuffle mode, announce the position in the current playlist queue
            current_num = self._current_index + 1
            cur_track = self.get_current_track()
            track_name = cur_track.display_name if cur_track else ""

            if lang == "ar":
                info = f"المقطع {current_num} من {total}"
                if track_name:
                    info += f": {track_name}"
                return info
            else:
                info = f"Track {current_num} of {total}"
                if track_name:
                    info += f": {track_name}"
                return info

    # -------------------------------------------------------------------------
    # Navigation API
    # -------------------------------------------------------------------------

    def next_track(self, manual: bool = True) -> Optional[Track]:
        """
        Advances to the next track.
        
        Args:
            manual: If True, user explicitly pressed Next Track (PageDown).
                    If False, called automatically on track completion (EOF).
                    
        Returns:
            The new active Track, or None if end of playlist is reached (in RepeatMode.OFF).
        """
        with self._lock:
            if not self._tracks:
                return None

            total = len(self._tracks)

            # Auto-next with RepeatMode.TRACK loops the current track
            if not manual and self._repeat_mode == RepeatMode.TRACK:
                cur = self.get_current_track()
                self._notify_listeners("track_changed", cur)
                return cur

            next_idx = self._current_index + 1

            if next_idx < total:
                self._current_index = next_idx
            else:
                # Reached end of playlist
                if self._repeat_mode == RepeatMode.PLAYLIST:
                    # Wrap around to start
                    if self._shuffle:
                        # Reshuffle for a fresh round while keeping first track randomized
                        self._generate_shuffle_order(keep_current=False)
                    self._current_index = 0
                else:
                    # End reached in OFF / TRACK manual mode
                    if not manual:
                        # Stop auto-next at end of playlist
                        self._current_index = total - 1
                        return None
                    # If manual, stay at last track or wrap?
                    # Keep at last track and return None to signal boundary hit
                    self._current_index = total - 1
                    return None

            track = self.get_current_track()
            self._notify_listeners("track_changed", track)
            return track

    def prev_track(self) -> Optional[Track]:
        """
        Navigates to the previous track.
        
        Returns:
            The new active Track, or None if playlist is empty.
        """
        with self._lock:
            if not self._tracks:
                return None

            total = len(self._tracks)
            prev_idx = self._current_index - 1

            if prev_idx >= 0:
                self._current_index = prev_idx
            else:
                # At start of playlist
                if self._repeat_mode == RepeatMode.PLAYLIST:
                    # Wrap around to end
                    self._current_index = total - 1
                else:
                    # At start boundary with no wrap — return None so the
                    # controller can announce the boundary and play the tone
                    return None

            track = self.get_current_track()
            self._notify_listeners("track_changed", track)
            return track

    def jump_to_index(self, index: int) -> Optional[Track]:
        """
        Jumps directly to a specific track index in the active sequence.
        """
        with self._lock:
            if not self._tracks:
                return None
            if 0 <= index < len(self._tracks):
                self._current_index = index
                track = self.get_current_track()
                self._notify_listeners("track_changed", track)
                return track
            return None

    def jump_to_original_index(self, orig_index: int) -> Optional[Track]:
        """
        Jumps to a specific track by its original unshuffled index.
        """
        with self._lock:
            if not self._tracks or orig_index < 0 or orig_index >= len(self._tracks):
                return None

            if self._shuffle and self._shuffled_indices:
                try:
                    active_idx = self._shuffled_indices.index(orig_index)
                    return self.jump_to_index(active_idx)
                except ValueError:
                    return None
            else:
                return self.jump_to_index(orig_index)

    def jump_to_path(self, file_path: str) -> Optional[Track]:
        """
        Jumps to a track matching the given file path.
        """
        with self._lock:
            if not file_path:
                return None
            is_url = file_path.startswith(("http://", "https://", "ytdl://", "custom://"))
            norm_target = file_path.strip() if is_url else os.path.normcase(os.path.abspath(file_path))
            for orig_idx, track in enumerate(self._tracks):
                track_is_url = track.path.startswith(("http://", "https://", "ytdl://", "custom://"))
                track_norm = track.path.strip() if track_is_url else os.path.normcase(track.path)
                if track_norm == norm_target:
                    return self.jump_to_original_index(orig_idx)
            return None

    def first_track(self) -> Optional[Track]:
        """
        Jumps directly to the first track in the active playlist sequence (Control + Home).
        """
        with self._lock:
            if not self._tracks:
                return None
            return self.jump_to_index(0)

    def last_track(self) -> Optional[Track]:
        """
        Jumps directly to the last track in the active playlist sequence (Control + End).
        """
        with self._lock:
            if not self._tracks:
                return None
            return self.jump_to_index(len(self._tracks) - 1)

    # -------------------------------------------------------------------------
    # Auto-Next Coordination API
    # -------------------------------------------------------------------------

    def on_track_ended(self) -> Optional[Track]:
        """
        Called when mpv fires an EOF event (track finished playing).
        Decides whether to advance or repeat.
        """
        with self._lock:
            if not self._tracks:
                return None

            if self._repeat_mode == RepeatMode.TRACK:
                return self.get_current_track()

            if self._auto_next:
                return self.next_track(manual=False)

            return None

    def toggle_auto_next(self) -> bool:
        """
        Toggles auto-next playback and returns the new state.
        """
        with self._lock:
            self._auto_next = not self._auto_next
            self._notify_listeners("auto_next_changed", self._auto_next)
            return self._auto_next

    def set_auto_next(self, enabled: bool) -> None:
        with self._lock:
            self._auto_next = bool(enabled)
            self._notify_listeners("auto_next_changed", self._auto_next)

    # -------------------------------------------------------------------------
    # Repeat Modes API
    # -------------------------------------------------------------------------

    def cycle_repeat_mode(self) -> RepeatMode:
        """
        Cycles repeat mode: OFF -> TRACK -> PLAYLIST -> OFF
        """
        with self._lock:
            self._repeat_mode = self._repeat_mode.cycle()
            self._notify_listeners("repeat_mode_changed", self._repeat_mode)
            return self._repeat_mode

    def set_repeat_mode(self, mode: Union[str, RepeatMode]) -> None:
        with self._lock:
            self._repeat_mode = RepeatMode.from_string(mode)
            self._notify_listeners("repeat_mode_changed", self._repeat_mode)

    # -------------------------------------------------------------------------
    # Shuffle Mode API (Non-Destructive)
    # -------------------------------------------------------------------------

    def toggle_shuffle(self) -> bool:
        """
        Toggles shuffle mode non-destructively and returns the new state.
        """
        with self._lock:
            return self.set_shuffle(not self._shuffle)

    def set_shuffle(self, enabled: bool) -> bool:
        """
        Sets shuffle mode non-destructively.
        When enabling: randomizes order while preserving current track as active.
        When disabling: restores original order, keeping current track selected.
        """
        with self._lock:
            new_val = bool(enabled)
            if self._shuffle == new_val:
                return self._shuffle

            if new_val:
                # Enabling shuffle
                self._shuffle = True
                self._generate_shuffle_order(keep_current=True)
            else:
                # Disabling shuffle: restore linear index of current track
                if self._shuffled_indices and 0 <= self._current_index < len(self._shuffled_indices):
                    orig_idx = self._shuffled_indices[self._current_index]
                    self._current_index = orig_idx
                self._shuffle = False
                self._shuffled_indices = []

            self._notify_listeners("shuffle_changed", self._shuffle)
            return self._shuffle

    def _generate_shuffle_order(self, keep_current: bool = True) -> None:
        """
        Generates a randomized index map of _tracks.
        If keep_current is True and a track is currently active, that track
        is positioned at index 0 so playback continues seamlessly.
        """
        total = len(self._tracks)
        if total == 0:
            self._shuffled_indices = []
            return

        current_orig = self.original_index if (keep_current and self._current_index >= 0) else None

        remaining = [i for i in range(total) if i != current_orig]
        random.shuffle(remaining)

        if current_orig is not None and 0 <= current_orig < total:
            self._shuffled_indices = [current_orig] + remaining
            self._current_index = 0
        else:
            self._shuffled_indices = remaining
            self._current_index = 0

    # -------------------------------------------------------------------------
    # Loading Media API
    # -------------------------------------------------------------------------

    def load_file(self, file_path: str, append: bool = False) -> Optional[Track]:
        """
        Loads a single media file into the playlist.
        
        Args:
            file_path: Path to the media file.
            append: If True, appends to existing tracks. If False, replaces playlist.
            
        Returns:
            The loaded Track, or None if file is not supported.
        """
        if not file_path or not is_supported_media_file(file_path):
            return None

        track = Track.from_path(file_path)
        with self._lock:
            if not append:
                self.clear()

            self._tracks.append(track)
            if self._shuffle:
                # Re-index shuffle
                self._generate_shuffle_order(keep_current=True)
            else:
                if not append or self._current_index < 0:
                    self._current_index = len(self._tracks) - 1

            self._notify_listeners("playlist_updated", self)
            return track

    def load_file_with_folder(self, file_path: str, append: bool = False) -> Optional[Track]:
        """
        Loads the specified media file along with all other supported media files
        in the same directory into the playlist, positioning the specified file as the active starting track.
        This allows Auto-Next to seamlessly play subsequent tracks in the folder.
        """
        if not file_path or not is_supported_media_file(file_path):
            return None

        abs_target = os.path.abspath(file_path)
        parent_dir = os.path.dirname(abs_target)
        sibling_files = find_media_files_in_dir(parent_dir, recursive=False)
        if not sibling_files:
            return self.load_file(abs_target, append=append)

        tracks = [Track.from_path(p) for p in sibling_files]
        norm_target = os.path.normcase(abs_target)

        with self._lock:
            if not append:
                self.clear()

            start_len = len(self._tracks)
            self._tracks.extend(tracks)

            target_idx = start_len
            for idx, p in enumerate(sibling_files):
                if os.path.normcase(os.path.abspath(p)) == norm_target:
                    target_idx = start_len + idx
                    break

            if self._shuffle:
                self._generate_shuffle_order(keep_current=True)
            else:
                self._current_index = target_idx

            self._notify_listeners("playlist_updated", self)
            return self.get_current_track()

    def load_folder(
        self,
        folder_path: str,
        recursive: bool = False,
        append: bool = False
    ) -> int:
        """
        Scans and loads all supported media files in a directory using natural sorting.
        
        Args:
            folder_path: Path to the directory.
            recursive: If True, scans subdirectories recursively.
            append: If True, appends to existing tracks. If False, replaces playlist.
            
        Returns:
            Number of tracks loaded.
        """
        if not folder_path or not os.path.isdir(folder_path):
            return 0

        found_paths = find_media_files_in_dir(folder_path, recursive=recursive)
        if not found_paths:
            return 0

        tracks = [Track.from_path(p) for p in found_paths]
        with self._lock:
            if not append:
                self.clear()

            start_len = len(self._tracks)
            self._tracks.extend(tracks)

            if self._shuffle:
                self._generate_shuffle_order(keep_current=append)
            else:
                if not append or self._current_index < 0:
                    self._current_index = start_len

            self._notify_listeners("playlist_updated", self)
            return len(tracks)

    def load_paths(
        self,
        paths: Sequence[str],
        append: bool = False
    ) -> int:
        """
        Loads a sequence of file and/or folder paths.
        Folders are automatically expanded with natural sorting.
        
        Args:
            paths: Sequence of file or folder paths.
            append: If True, appends to playlist. If False, replaces playlist.
            
        Returns:
            Number of tracks loaded.
        """
        if not paths:
            return 0

        collected_files: List[str] = []
        for p in paths:
            if not p:
                continue
            if os.path.isdir(p):
                folder_files = find_media_files_in_dir(p, recursive=False)
                collected_files.extend(folder_files)
            elif os.path.isfile(p) and is_supported_media_file(p):
                collected_files.append(os.path.abspath(p))

        # Filter duplicates while maintaining natural/input order
        seen = set()
        unique_files: List[str] = []
        for f in collected_files:
            norm = os.path.normcase(f)
            if norm not in seen:
                seen.add(norm)
                unique_files.append(f)

        if not unique_files:
            return 0

        tracks = [Track.from_path(p) for p in unique_files]
        with self._lock:
            if not append:
                self.clear()

            start_len = len(self._tracks)
            self._tracks.extend(tracks)

            if self._shuffle:
                self._generate_shuffle_order(keep_current=append)
            else:
                if not append or self._current_index < 0:
                    self._current_index = start_len

            self._notify_listeners("playlist_updated", self)
            return len(tracks)

    def load_stream_tracks(
        self,
        tracks: Sequence[Track],
        start_index: int = 0,
        append: bool = False
    ) -> Optional[Track]:
        """
        Loads a sequence of online stream tracks (URL-based) as the playlist queue,
        positioning start_index as the active track. Online playlists behave
        exactly like local folder playlists for navigation/shuffle/repeat.

        Returns:
            The active starting Track, or None if the sequence was empty.
        """
        track_list = [t for t in tracks if isinstance(t, Track) and t.path]
        if not track_list:
            return None

        log_debug("PLAYLIST", "load_stream_tracks: received %d tracks, start_index=%d, append=%s", len(track_list), start_index, append)

        with self._lock:
            if not append:
                self.clear()

            start_len = len(self._tracks)
            self._tracks.extend(track_list)
            target_idx = start_len + max(0, min(start_index, len(track_list) - 1))

            if not append or self._current_index < 0:
                if self._shuffle:
                    self._current_index = target_idx
                    self._generate_shuffle_order(keep_current=True)
                else:
                    self._current_index = target_idx
            else:
                if self._shuffle:
                    new_indices = list(range(start_len, len(self._tracks)))
                    random.shuffle(new_indices)
                    self._shuffled_indices.extend(new_indices)

            log_debug("PLAYLIST", "load_stream_tracks updated: total_tracks=%d, current_index=%d", len(self._tracks), self._current_index)
            self._notify_listeners("playlist_updated", self)
            return self.get_current_track()

    def add_track(self, track_or_path: Union[Track, str]) -> Optional[Track]:
        """
        Adds a single track to the end of the playlist.
        """
        if isinstance(track_or_path, str):
            if not is_supported_media_file(track_or_path):
                return None
            track = Track.from_path(track_or_path)
        elif isinstance(track_or_path, Track):
            track = track_or_path
        else:
            return None

        with self._lock:
            self._tracks.append(track)
            if self._current_index < 0:
                self._current_index = 0
            if self._shuffle:
                self._generate_shuffle_order(keep_current=True)
            self._notify_listeners("playlist_updated", self)
            return track

    def remove_track(self, index: int) -> Optional[Track]:
        """
        Removes a track at the given index in the active sequence.
        """
        with self._lock:
            if not self._tracks or index < 0 or index >= len(self._tracks):
                return None

            if self._shuffle and self._shuffled_indices:
                # Map the active-sequence index → original track index
                if 0 <= index < len(self._shuffled_indices):
                    orig_idx = self._shuffled_indices[index]
                else:
                    return None
            else:
                orig_idx = index
            removed = self._tracks.pop(orig_idx)

            if self._shuffle:
                if self._shuffled_indices:
                    new_shuffled = []
                    for idx in self._shuffled_indices:
                        if idx == orig_idx:
                            continue
                        elif idx > orig_idx:
                            new_shuffled.append(idx - 1)
                        else:
                            new_shuffled.append(idx)
                    self._shuffled_indices = new_shuffled
                if not self._tracks:
                    self._current_index = -1
                elif self._current_index >= len(self._tracks):
                    self._current_index = len(self._tracks) - 1
            else:
                if self._current_index >= len(self._tracks):
                    self._current_index = max(0, len(self._tracks) - 1)
                if not self._tracks:
                    self._current_index = -1

            self._notify_listeners("playlist_updated", self)
            return removed

    @property
    def total_duration(self) -> float:
        """Returns total duration of all tracks in seconds."""
        with self._lock:
            total = 0.0
            for t in self._tracks:
                if t.duration and t.duration > 0:
                    total += t.duration
            return total

    def clear(self) -> None:
        """
        Clears all tracks from the playlist.
        """
        with self._lock:
            self._tracks.clear()
            self._shuffled_indices.clear()
            self._current_index = -1
            self._notify_listeners("playlist_updated", self)

    # -------------------------------------------------------------------------
    # Listeners API
    # -------------------------------------------------------------------------

    def add_listener(self, listener: Callable[[str, Any], None]) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[str, Any], None]) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _notify_listeners(self, event_type: str, data: Any) -> None:
        listeners_copy = list(self._listeners)
        for listener in listeners_copy:
            try:
                listener(event_type, data)
            except Exception as e:
                logger.warning(f"Error in playlist listener for '{event_type}': {e}")

    # -------------------------------------------------------------------------
    # State Store Serialization
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "tracks": [t.path for t in self._tracks],
                "current_index": self.original_index,
                "shuffle": self._shuffle,
                "repeat_mode": self._repeat_mode.value,
                "auto_next": self._auto_next,
            }

    def from_dict(self, data: Dict[str, Any]) -> None:
        with self._lock:
            paths = data.get("tracks", [])
            self.clear()
            if paths:
                self._tracks = [
                    Track.from_path(p) for p in paths
                    if p and (
                        str(p).strip().lower().startswith(("http://", "https://"))
                        or (os.path.exists(p) and is_supported_media_file(p))
                    )
                ]
            self._repeat_mode = RepeatMode.from_string(data.get("repeat_mode", "off"))
            self._auto_next = bool(data.get("auto_next", True))
            saved_idx = int(data.get("current_index", 0))
            if self._tracks:
                self._current_index = min(max(0, saved_idx), len(self._tracks) - 1)
            else:
                self._current_index = -1

            should_shuffle = bool(data.get("shuffle", False))
            if should_shuffle:
                self.set_shuffle(True)
