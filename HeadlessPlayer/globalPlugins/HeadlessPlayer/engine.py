# -*- coding: utf-8 -*-
"""
HeadlessPlayer Core Audio & Video Media Engine.
Coordinates detached mpv subprocess lifecycle, pure ctypes Win32 Named Pipe IPC,
thread-safe property caching, granular seek, pitch-preserved variable speed,
A-B segment repeat, chapter navigation, and audio stream switching.
"""

import logging
import os
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .ipc_client import WinNamedPipeClient
from .mpv_process import DEFAULT_PIPE_NAME, MpvProcess, find_mpv_binary

logger = logging.getLogger("HeadlessPlayer.Engine")

# Supported Media Extensions
SUPPORTED_AUDIO_EXTENSIONS: Set[str] = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus",
    ".wma", ".aiff", ".aif", ".ape", ".ac3", ".dts", ".mka", ".mid",
    ".midi", ".alac", ".wv", ".spx", ".mpc", ".amr", ".caf", ".au", ".snd"
}

SUPPORTED_VIDEO_EXTENSIONS: Set[str] = {
    ".mp4", ".mkv", ".avi", ".webm", ".mov", ".wmv", ".flv", ".ts",
    ".m2ts", ".mts", ".vob", ".ogv", ".3gp", ".3g2", ".m4v", ".mpg",
    ".mpeg", ".f4v", ".rm", ".rmvb", ".divx"
}

SUPPORTED_PLAYLIST_EXTENSIONS: Set[str] = {
    ".m3u", ".m3u8", ".pls", ".cue"
}

ALL_SUPPORTED_EXTENSIONS: Set[str] = (
    SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_PLAYLIST_EXTENSIONS
)

# Standard speed presets for Shift+Up / Shift+Down cycling
SPEED_PRESETS: List[float] = [
    1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0, 3.5, 4.0
]


def is_supported_media_file(path: str) -> bool:
    """Check if the given file path has a supported audio or video extension."""
    if not path or not isinstance(path, str):
        return False
    _, ext = os.path.splitext(path.lower())
    return ext in ALL_SUPPORTED_EXTENSIONS


class HeadlessEngine:
    """
    High-level headless media player engine.
    Wraps MpvProcess and WinNamedPipeClient with synchronized state tracking and callbacks.
    """

    def __init__(
        self,
        pipe_name: str = DEFAULT_PIPE_NAME,
        custom_mpv_path: Optional[str] = None,
        addon_root: Optional[str] = None
    ):
        self.pipe_name: str = pipe_name
        self.custom_mpv_path: Optional[str] = custom_mpv_path
        self.addon_root: Optional[str] = addon_root

        self._process: Optional[MpvProcess] = None
        self._ipc: Optional[WinNamedPipeClient] = None
        self._lock = threading.RLock()

        # Cached playback state
        self.time_pos: float = 0.0
        self.duration: float = 0.0
        self.volume: float = 100.0
        self.speed: float = 1.0
        self.paused: bool = False
        self.muted: bool = False
        self.ab_loop_a: Optional[float] = None
        self.ab_loop_b: Optional[float] = None
        self.ab_loop_active: bool = False
        self.track_repeat: bool = False
        self.chapters: int = 0
        self.chapter: int = 0
        self.chapter_list: List[Dict[str, Any]] = []
        self.track_list: List[Dict[str, Any]] = []
        self.audio_tracks: List[Dict[str, Any]] = []
        self.aid: Any = "auto"
        self.media_title: str = ""
        self.filename: str = ""
        self.path: str = ""
        self.core_idle: bool = True
        self.eof_reached: bool = False
        self.is_loaded: bool = False
        self.bass_gain: float = 0.0

        # Upstream event callbacks
        self.on_file_loaded: Optional[Callable[[], None]] = None
        self.on_track_end: Optional[Callable[[str], None]] = None
        self.on_property_change: Optional[Callable[[str, Any], None]] = None
        self.on_playback_restart: Optional[Callable[[], None]] = None
        self.on_seek: Optional[Callable[[], None]] = None

    @property
    def is_running(self) -> bool:
        """True if mpv process is active and IPC client is connected."""
        with self._lock:
            return bool(
                self._process and self._process.is_running() and
                self._ipc and self._ipc.is_connected()
            )

    def start(self) -> bool:
        """
        Start mpv background process and connect Named Pipe IPC.
        Sets up automatic property change subscriptions.
        """
        with self._lock:
            if self.is_running:
                return True

            # 1. Launch mpv process
            self._process = MpvProcess(
                mpv_executable=self.custom_mpv_path,
                pipe_name=self.pipe_name,
                addon_root=self.addon_root
            )

            if not self._process.start():
                logger.error("Failed to start mpv process.")
                return False

            # 2. Connect WinNamedPipeClient
            self._ipc = WinNamedPipeClient(
                pipe_path=self.pipe_name,
                event_callback=self._handle_ipc_event
            )

            if not self._ipc.connect(timeout_sec=5.0):
                logger.error("Failed to connect WinNamedPipeClient to %s", self.pipe_name)
                self.shutdown()
                return False

            # 3. Setup Property Observers
            self._setup_property_observers()

            # 4. Re-apply persistent audio settings (volume, speed, bass) after launch
            self._ipc.send_command_async(["set_property", "volume", float(self.volume)])
            self._ipc.send_command_async(["set_property", "speed", float(self.speed)])
            if self.bass_gain:
                self._apply_bass_filter()

            logger.info("HeadlessEngine initialized and connected successfully (vol=%.1f, speed=%.2fx).", self.volume, self.speed)
            return True

    def shutdown(self) -> None:
        """Clean shutdown of IPC client and mpv daemon."""
        with self._lock:
            if self._ipc:
                try:
                    self._ipc.send_command_async(["quit"])
                    self._ipc.close()
                except Exception as e:
                    logger.debug("Error closing IPC client: %s", e)
                self._ipc = None

            if self._process:
                try:
                    self._process.stop(timeout_sec=1.5)
                except Exception as e:
                    logger.debug("Error stopping mpv process: %s", e)
                self._process = None

            self.is_loaded = False
            self.core_idle = True
            logger.info("HeadlessEngine shut down.")

    def _setup_property_observers(self) -> None:
        """Register observers for all playback properties."""
        if not self._ipc or not self._ipc.is_connected():
            return

        observers = [
            (1, "pause"),
            (2, "time-pos"),
            (3, "duration"),
            (4, "volume"),
            (5, "mute"),
            (6, "speed"),
            (7, "media-title"),
            (8, "filename"),
            (9, "path"),
            (10, "ab-loop-a"),
            (11, "ab-loop-b"),
            (12, "loop-file"),
            (13, "chapter"),
            (14, "chapters"),
            (15, "chapter-list"),
            (16, "track-list"),
            (17, "aid"),
            (18, "core-idle"),
            (19, "eof-reached"),
        ]

        for sub_id, prop_name in observers:
            self._ipc.observe_property(sub_id, prop_name)

    def _handle_ipc_event(self, msg: Dict[str, Any]) -> None:
        """Handle raw mpv event and dispatch to listeners."""
        evt = msg.get("event")
        if not evt:
            return

        if evt == "property-change":
            name = msg.get("name", "")
            data = msg.get("data")
            self._update_property_cache(name, data)
            if self.on_property_change:
                try:
                    self.on_property_change(name, data)
                except Exception as e:
                    logger.error("Error in on_property_change callback: %s", e, exc_info=True)

        elif evt == "file-loaded":
            with self._lock:
                self.is_loaded = True
                self.core_idle = False
                self.eof_reached = False
            if self.on_file_loaded:
                try:
                    self.on_file_loaded()
                except Exception as e:
                    logger.error("Error in on_file_loaded callback: %s", e, exc_info=True)

        elif evt == "end-file":
            reason = msg.get("reason", "eof")
            with self._lock:
                if reason == "eof":
                    self.eof_reached = True
                elif reason in ("stop", "quit", "error"):
                    self.is_loaded = False
                    self.core_idle = True
            if self.on_track_end:
                import time
                now = time.time()
                if now - getattr(self, "_last_eof_time", 0.0) > 0.5:
                    self._last_eof_time = now
                    try:
                        self.on_track_end(reason)
                    except Exception as e:
                        logger.error("Error in on_track_end callback: %s", e, exc_info=True)

        elif evt == "playback-restart":
            if self.on_playback_restart:
                try:
                    self.on_playback_restart()
                except Exception as e:
                    logger.error("Error in on_playback_restart callback: %s", e, exc_info=True)

        elif evt == "seek":
            if self.on_seek:
                try:
                    self.on_seek()
                except Exception as e:
                    logger.error("Error in on_seek callback: %s", e, exc_info=True)

    def _update_property_cache(self, name: str, data: Any) -> None:
        """Update internal state cache on property change event."""
        with self._lock:
            if name == "pause":
                self.paused = bool(data)
            elif name == "time-pos" and data is not None:
                try:
                    self.time_pos = float(data)
                except (ValueError, TypeError):
                    pass
            elif name == "duration" and data is not None:
                try:
                    self.duration = float(data)
                except (ValueError, TypeError):
                    pass
            elif name == "volume" and data is not None:
                try:
                    self.volume = float(data)
                except (ValueError, TypeError):
                    pass
            elif name == "speed" and data is not None:
                try:
                    self.speed = float(data)
                except (ValueError, TypeError):
                    pass
            elif name == "mute":
                self.muted = bool(data)
            elif name == "media-title":
                self.media_title = str(data) if data is not None else ""
            elif name == "filename":
                self.filename = str(data) if data is not None else ""
            elif name == "path":
                self.path = str(data) if data is not None else ""
            elif name == "ab-loop-a":
                self.ab_loop_a = float(data) if (data is not None and data != "no") else None
                self._update_ab_active_state()
            elif name == "ab-loop-b":
                self.ab_loop_b = float(data) if (data is not None and data != "no") else None
                self._update_ab_active_state()
            elif name == "loop-file":
                self.track_repeat = bool(data and data != "no")
            elif name == "chapter" and data is not None:
                try:
                    self.chapter = int(data)
                except (ValueError, TypeError):
                    pass
            elif name == "chapters" and data is not None:
                try:
                    self.chapters = int(data)
                except (ValueError, TypeError):
                    pass
            elif name == "chapter-list" and isinstance(data, list):
                self.chapter_list = data
            elif name == "track-list" and isinstance(data, list):
                self.track_list = data
                self.audio_tracks = [t for t in data if isinstance(t, dict) and t.get("type") == "audio"]
            elif name == "aid":
                self.aid = data
            elif name == "core-idle":
                self.core_idle = bool(data)
            elif name == "eof-reached":
                self.eof_reached = bool(data)
                if data and self.is_loaded and self.on_track_end:
                    import time
                    now = time.time()
                    if now - getattr(self, "_last_eof_time", 0.0) > 0.5:
                        self._last_eof_time = now
                        try:
                            self.on_track_end("eof")
                        except Exception as e:
                            logger.error("Error in on_track_end callback: %s", e)

    def _update_ab_active_state(self) -> None:
        """Calculate whether A-B looping is currently active."""
        self.ab_loop_active = (self.ab_loop_a is not None and self.ab_loop_b is not None)

    # -------------------------------------------------------------------------
    # Core Playback Methods
    # -------------------------------------------------------------------------

    def load_file(self, file_path: str, append: bool = False) -> bool:
        """
        Load a media file or URL for playback.
        If append is True, appends to mpv's playlist; otherwise replaces current playback.
        """
        if not self.is_running:
            if not self.start():
                return False

        mode = "append" if append else "replace"
        if not append:
            with self._lock:
                self.time_pos = 0.0
                self.duration = 0.0
                self.ab_loop_a = None
                self.ab_loop_b = None
                self.ab_loop_active = False
                self.is_loaded = False
                self.path = file_path
                self.filename = os.path.basename(file_path) if os.path.exists(file_path) else file_path

        logger.info("Loading media: %s (mode: %s)", file_path, mode)
        ok = self._ipc.send_command_async(["loadfile", file_path, mode])
        if ok and not append:
            # Always start fresh loads unpaused
            self._ipc.send_command_async(["set_property", "pause", False])
            with self._lock:
                self.paused = False
        return ok

    def set_http_headers(self, headers: Optional[Dict[str, str]]) -> None:
        """
        Applies (or clears) custom HTTP request headers for network streams.
        Must be called before load_file for URLs that require Referer/User-Agent.
        """
        if not self.is_running:
            return
        field_list = []
        if headers:
            for k, v in headers.items():
                if k and v is not None:
                    field_list.append(f"{k}: {v}")
        self._ipc.send_command_async(["set_property", "http-header-fields", field_list])

    def load_stream(self, stream_url: str, headers: Optional[Dict[str, str]] = None) -> bool:
        """Loads a resolved network stream URL, applying its HTTP headers first."""
        if not self.is_running:
            if not self.start():
                return False
        self.set_http_headers(headers)
        return self.load_file(stream_url, append=False)

    def toggle_pause(self) -> bool:
        """Toggle playback pause state and return the predicted/new pause state."""
        if not self.is_running:
            return False
        with self._lock:
            self.paused = not self.paused
            new_state = self.paused
        self._ipc.send_command_async(["cycle", "pause"])
        return new_state

    def pause(self) -> bool:
        """Explicitly pause playback."""
        if not self.is_running:
            return False
        with self._lock:
            self.paused = True
        return self._ipc.send_command_async(["set_property", "pause", True])

    def resume(self) -> bool:
        """Explicitly resume playback."""
        if not self.is_running:
            return False
        with self._lock:
            self.paused = False
        return self._ipc.send_command_async(["set_property", "pause", False])

    def stop(self) -> bool:
        """Stop playback and clear active file."""
        if not self.is_running:
            return False
        with self._lock:
            self.time_pos = 0.0
            self.duration = 0.0
            self.paused = False
            self.is_loaded = False
            self.core_idle = True
            self.ab_loop_a = None
            self.ab_loop_b = None
            self.ab_loop_active = False
        return self._ipc.send_command_async(["stop"])

    def toggle_mute(self) -> bool:
        """Toggle audio mute state and return new mute state."""
        if not self.is_running:
            return False
        with self._lock:
            self.muted = not self.muted
            new_muted = self.muted
        self._ipc.send_command_async(["cycle", "mute"])
        return new_muted

    def adjust_volume(self, delta: float) -> float:
        """
        Adjust volume by delta percentage (+5 or -5).
        Clamped between 0.0% and 150.0%. Returns new volume.
        """
        if not self.is_running:
            return self.volume
        with self._lock:
            new_vol = max(0.0, min(150.0, self.volume + delta))
            self.volume = round(new_vol, 1)
        self._ipc.send_command_async(["set_property", "volume", self.volume])
        return self.volume

    def set_volume(self, volume: float) -> float:
        """Set volume directly (clamped between 0.0 and 150.0)."""
        if not self.is_running:
            return self.volume
        with self._lock:
            self.volume = max(0.0, min(150.0, float(volume)))
        self._ipc.send_command_async(["set_property", "volume", self.volume])
        return self.volume

    # -------------------------------------------------------------------------
    # Bass Control (ffmpeg 'bass' shelf filter via mpv's af chain)
    # -------------------------------------------------------------------------

    def _apply_bass_filter(self) -> bool:
        """Applies the cached bass gain to mpv's audio filter chain."""
        if not self.is_running:
            return False
        if self.bass_gain:
            return self._ipc.send_command_async(["af", "set", f"bass=g={self.bass_gain:g}"])
        return self._ipc.send_command_async(["af", "set", ""])

    def adjust_bass(self, delta: float) -> float:
        """
        Adjusts the bass gain by delta decibels, clamped to [-15, +15] dB.
        The filter persists across track changes. Returns the new gain.
        """
        if not self.is_running:
            return self.bass_gain
        with self._lock:
            self.bass_gain = max(-15.0, min(15.0, round(self.bass_gain + delta, 1)))
        self._apply_bass_filter()
        return self.bass_gain

    def set_bass_gain(self, gain: float) -> float:
        """Sets an exact bass gain in decibels, clamped to [-15, +15]."""
        if not self.is_running:
            return self.bass_gain
        with self._lock:
            self.bass_gain = max(-15.0, min(15.0, round(float(gain), 1)))
        self._apply_bass_filter()
        return self.bass_gain

    # -------------------------------------------------------------------------
    # Granular Seek Controls
    # -------------------------------------------------------------------------

    def seek(self, delta_sec: float, absolute: bool = False) -> bool:
        """
        High-resolution seek.
        If absolute is True, seeks to exact timestamp in seconds.
        Otherwise performs relative seek by delta_sec.
        """
        if absolute:
            return self.seek_absolute(delta_sec)
        with self._lock:
            # Optimistically adjust cached time_pos clamped to [0, duration]
            if self.duration > 0:
                self.time_pos = max(0.0, min(self.duration, self.time_pos + delta_sec))
            else:
                self.time_pos = max(0.0, self.time_pos + delta_sec)
        if not self._ipc or not self._ipc.is_connected():
            return False
        return self._ipc.send_command_async(["seek", delta_sec, "relative"])

    def seek_absolute(self, pos_sec: float) -> bool:
        """Seek to an exact timestamp in seconds."""
        with self._lock:
            target = max(0.0, float(pos_sec))
            if self.duration > 0:
                target = min(self.duration, target)
            self.time_pos = target
        if not self._ipc or not self._ipc.is_connected():
            return False
        return self._ipc.send_command_async(["seek", self.time_pos, "absolute"])

    def seek_percent(self, percent: float) -> bool:
        """
        Jump to percentage of file duration (e.g. 10.0 to 90.0 for keys 1-9).
        Clamped between 0.0% and 100.0%.
        """
        target_pct = max(0.0, min(100.0, float(percent)))
        with self._lock:
            if self.duration > 0:
                self.time_pos = (target_pct / 100.0) * self.duration
        if not self._ipc or not self._ipc.is_connected():
            return False
        return self._ipc.send_command_async(["seek", target_pct, "absolute-percent"])

    # -------------------------------------------------------------------------
    # Pitch-Preserved Speed Engine
    # -------------------------------------------------------------------------

    def adjust_speed(self, delta: float) -> float:
        """
        Fine-tune speed adjustment (e.g. +0.1x / -0.1x).
        Clamped between 0.1x and 4.0x, rounded to 2 decimal places.
        Returns the updated speed multiplier.
        """
        if not self.is_running:
            return self.speed
        with self._lock:
            new_speed = max(0.1, min(4.0, round(self.speed + delta, 2)))
            self.speed = new_speed
        self._ipc.send_command_async(["set_property", "speed", self.speed])
        return self.speed

    def set_speed(self, speed: float) -> float:
        """Set exact speed multiplier clamped between 0.1x and 4.0x."""
        if not self.is_running:
            return self.speed
        with self._lock:
            self.speed = max(0.1, min(4.0, round(float(speed), 2)))
        self._ipc.send_command_async(["set_property", "speed", self.speed])
        return self.speed

    def set_speed_preset(self, idx: int) -> float:
        """Set speed directly to a preset index from SPEED_PRESETS."""
        if not SPEED_PRESETS:
            return self.speed
        idx = max(0, min(len(SPEED_PRESETS) - 1, idx))
        return self.set_speed(SPEED_PRESETS[idx])

    def cycle_speed_preset(self, forward: bool = True) -> float:
        """
        Cycle through standard preset speeds (1.0x, 1.25x, 1.5x, 1.75x, 2.0x, 2.25x, 2.5x, 3.0x, 3.5x, 4.0x).
        Finds the closest preset and moves to next or previous.
        """
        if not self.is_running:
            return self.speed

        with self._lock:
            current = self.speed

            # Find closest preset index
            closest_idx = 0
            min_diff = float("inf")
            for i, p in enumerate(SPEED_PRESETS):
                diff = abs(p - current)
                if diff < min_diff:
                    min_diff = diff
                    closest_idx = i

            if forward:
                # If current is slightly less than closest, jump to closest; otherwise next
                if current < SPEED_PRESETS[closest_idx] - 0.01:
                    target_idx = closest_idx
                else:
                    target_idx = min(len(SPEED_PRESETS) - 1, closest_idx + 1)
            else:
                if current > SPEED_PRESETS[closest_idx] + 0.01:
                    target_idx = closest_idx
                else:
                    target_idx = max(0, closest_idx - 1)

            target_speed = SPEED_PRESETS[target_idx]

        return self.set_speed(target_speed)

    # -------------------------------------------------------------------------
    # A-B Segment Repeat & Track Looping
    # -------------------------------------------------------------------------

    def set_ab_point_a(self, time_pos: Optional[float] = None) -> float:
        """
        Mark Point A (start of segment loop). Defaults to current playback time_pos.
        Returns Point A timestamp in seconds.
        """
        if not self.is_running:
            return 0.0

        pos = time_pos if time_pos is not None else self.time_pos
        pos = max(0.0, round(float(pos), 2))

        with self._lock:
            self.ab_loop_a = pos
            # If point B was previously set and is now <= point A, clear point B
            if self.ab_loop_b is not None and self.ab_loop_b <= pos:
                self.ab_loop_b = None
                self._ipc.send_command_async(["set_property", "ab-loop-b", "no"])
            self._update_ab_active_state()

        self._ipc.send_command_async(["set_property", "ab-loop-a", pos])
        logger.info("Marked A-B Point A: %.2fs", pos)
        return pos

    def set_ab_point_b(self, time_pos: Optional[float] = None) -> Tuple[float, bool]:
        """
        Mark Point B (end of segment loop). Defaults to current playback time_pos.
        Validates that Point B > Point A.
        Returns tuple of (point_b_seconds, is_valid).
        """
        if not self.is_running:
            return 0.0, False

        pos = time_pos if time_pos is not None else self.time_pos
        pos = max(0.0, round(float(pos), 2))

        with self._lock:
            if self.ab_loop_a is None or pos <= self.ab_loop_a:
                logger.warning("Point B (%.2fs) must be greater than Point A (%s)", pos, self.ab_loop_a)
                return pos, False

            self.ab_loop_b = pos
            self.ab_loop_active = True

        self._ipc.send_command_async(["set_property", "ab-loop-b", pos])
        logger.info("Marked A-B Point B: %.2fs (Segment: %.2fs - %.2fs)", pos, self.ab_loop_a, pos)
        return pos, True

    def toggle_repeat(self) -> str:
        """
        Toggle repeat mode:
        1. If Point A & Point B are set: toggles A-B segment repeat.
           Returns 'ab_loop_on' or 'ab_loop_off'.
        2. If no A-B points are set: toggles single-track repeat.
           Returns 'track_repeat_on' or 'track_repeat_off'.
        """
        if not self.is_running:
            return "track_repeat_off"

        with self._lock:
            # Case 1: A-B points exist
            if self.ab_loop_a is not None and self.ab_loop_b is not None:
                if self.ab_loop_active:
                    # Deactivate A-B loop in mpv but keep cached points
                    self.ab_loop_active = False
                    self._ipc.send_command_async(["set_property", "ab-loop-a", "no"])
                    self._ipc.send_command_async(["set_property", "ab-loop-b", "no"])
                    return "ab_loop_off"
                else:
                    # Reactivate A-B loop with saved points
                    self.ab_loop_active = True
                    self._ipc.send_command_async(["set_property", "ab-loop-a", self.ab_loop_a])
                    self._ipc.send_command_async(["set_property", "ab-loop-b", self.ab_loop_b])
                    return "ab_loop_on"

            # Case 2: Track Repeat fallback
            self.track_repeat = not self.track_repeat
            loop_val = "inf" if self.track_repeat else "no"
            self._ipc.send_command_async(["set_property", "loop-file", loop_val])
            return "track_repeat_on" if self.track_repeat else "track_repeat_off"

    def set_track_repeat(self, enabled: bool) -> None:
        """Explicitly set single-track repeat state."""
        with self._lock:
            self.track_repeat = bool(enabled)
            loop_val = "inf" if self.track_repeat else "no"
            if self.is_running:
                self._ipc.send_command_async(["set_property", "loop-file", loop_val])

    def clear_ab_points(self) -> None:
        """Clear all marked A-B loop points and deactivate segment looping."""
        if not self.is_running:
            return

        with self._lock:
            self.ab_loop_a = None
            self.ab_loop_b = None
            self.ab_loop_active = False

        self._ipc.send_command_async(["set_property", "ab-loop-a", "no"])
        self._ipc.send_command_async(["set_property", "ab-loop-b", "no"])
        logger.info("Cleared A-B loop points.")

    @property
    def chapter_count(self) -> int:
        """Returns the total number of chapters in the active file."""
        return self.chapters or len(self.chapter_list or [])

    def next_chapter(self) -> bool:
        """Jump to next chapter."""
        if not self.is_running:
            return False
        return self._ipc.send_command_async(["add", "chapter", 1])

    def prev_chapter(self) -> bool:
        """Jump to previous chapter."""
        if not self.is_running:
            return False
        return self._ipc.send_command_async(["add", "chapter", -1])

    def get_current_chapter_title(self) -> Optional[str]:
        """Get the title of the current chapter if chapter metadata exists."""
        with self._lock:
            if not self.chapter_list or self.chapter < 0 or self.chapter >= len(self.chapter_list):
                return None
            item = self.chapter_list[self.chapter]
            return item.get("title") if isinstance(item, dict) else None

    # -------------------------------------------------------------------------
    # Audio Stream Tracks
    # -------------------------------------------------------------------------

    def cycle_audio_track(self) -> bool:
        """Cycle to next audio track / language stream."""
        if not self.is_running:
            return False
        return self._ipc.send_command_async(["cycle", "aid"])

    def get_current_audio_track_info(self) -> Optional[Dict[str, Any]]:
        """Get details about the currently selected audio track."""
        with self._lock:
            for track in self.audio_tracks:
                if track.get("selected") or track.get("id") == self.aid:
                    return track
            return self.audio_tracks[0] if self.audio_tracks else None

    # -------------------------------------------------------------------------
    # Time & State Queries
    # -------------------------------------------------------------------------

    def get_remaining_time(self) -> float:
        """Return remaining time in seconds."""
        with self._lock:
            if self.duration > 0:
                return max(0.0, self.duration - self.time_pos)
            return 0.0

    def get_elapsed_time(self) -> float:
        """Return elapsed playback time in seconds."""
        with self._lock:
            return max(0.0, self.time_pos)

    def get_duration(self) -> float:
        """Return total duration in seconds."""
        with self._lock:
            return max(0.0, self.duration)

    def get_media_info(self) -> Dict[str, Any]:
        """
        Return a comprehensive snapshot of player and media state.
        Useful for UI queries, speech announcements, and debugging.
        """
        with self._lock:
            title = self.media_title or self.filename or (os.path.basename(self.path) if self.path else "")
            rem = max(0.0, self.duration - self.time_pos) if self.duration > 0 else 0.0
            pct = (self.time_pos / self.duration * 100.0) if self.duration > 0 else 0.0

            return {
                "title": title,
                "filename": self.filename,
                "path": self.path,
                "duration": self.duration,
                "time_pos": self.time_pos,
                "time_remaining": rem,
                "percent_pos": round(pct, 1),
                "volume": self.volume,
                "speed": self.speed,
                "paused": self.paused,
                "muted": self.muted,
                "ab_loop_a": self.ab_loop_a,
                "ab_loop_b": self.ab_loop_b,
                "ab_loop_active": self.ab_loop_active,
                "track_repeat": self.track_repeat,
                "chapter": self.chapter,
                "chapters": self.chapters,
                "chapter_title": self.get_current_chapter_title(),
                "audio_tracks_count": len(self.audio_tracks),
                "current_aid": self.aid,
                "is_loaded": self.is_loaded,
                "core_idle": self.core_idle,
            }
