# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Speech & Braille Feedback Subsystem.
Provides accessible, non-blocking screen reader and braille announcements via ui.message(),
honors user verbosity configuration from config_spec, implements media query handlers
(media info, remaining time, elapsed time), and features high-resolution rapid seek debouncing.
"""

from __future__ import annotations
import logging
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, Union

# Attempt importing NVDA modules with robust fallback
try:
    import ui  # type: ignore
    _NVDA_UI_AVAILABLE = True
except ImportError:
    ui = None  # type: ignore
    _NVDA_UI_AVAILABLE = False

try:
    import speech  # type: ignore
    _NVDA_SPEECH_AVAILABLE = True
except ImportError:
    speech = None  # type: ignore
    _NVDA_SPEECH_AVAILABLE = False

try:
    from . import _  # type: ignore
except (ImportError, ValueError):
    try:
        _ = _  # type: ignore
    except NameError:
        _ = lambda text: text

try:
    from .config_spec import getConfig
except ImportError:
    try:
        from config_spec import getConfig
    except ImportError:
        def getConfig() -> Dict[str, Any]:
            return {}

try:
    from .utils import format_time, format_spoken_time
except ImportError:
    from utils import format_time, format_spoken_time

try:
    from .tones_helper import play_seek_click, tone_manager
except ImportError:
    try:
        from tones_helper import play_seek_click, tone_manager
    except ImportError:
        def play_seek_click() -> None:
            pass
        tone_manager = None

logger = logging.getLogger("HeadlessPlayer.SpeechFeedback")

# Default rapid seek debounce interval in seconds
SEEK_DEBOUNCE_INTERVAL: float = 0.250  # 250 milliseconds


class SpeechFeedback:
    """
    Coordinates spoken and braille feedback for HeadlessPlayer actions and queries.
    Manages rapid seek event coalescing (debouncing) with immediate auditory tactile clicks.
    """

    def __init__(
        self,
        debounce_interval: float = SEEK_DEBOUNCE_INTERVAL,
        ui_module: Any = None,
        speech_module: Any = None
    ) -> None:
        self.debounce_interval: float = float(debounce_interval)
        self._ui = ui_module or ui
        self._speech = speech_module or speech
        self._lock = threading.RLock()

        # Rapid seek debouncing state
        self._seek_timer: Optional[threading.Timer] = None
        self._seek_accum_delta: float = 0.0
        self._seek_last_target_pos: float = 0.0
        self._seek_last_duration: float = 0.0
        self._seek_last_time: float = 0.0

        # Message history for inspection and unit testing
        self.message_history: list[str] = []

    # -------------------------------------------------------------------------
    # Core Speech & Braille Output
    # -------------------------------------------------------------------------

    def speak(self, text: str, cancel_previous: bool = True) -> None:
        """
        Outputs a message to the screen reader and braille display via ui.message().
        By default cancels any previously queued speech so rapid actions speak only the latest value.
        """
        if not text:
            return

        with self._lock:
            self.message_history.append(str(text))

        if cancel_previous:
            self.cancel_speech()

        ui_mod = self._ui or sys.modules.get("ui")
        if ui_mod and hasattr(ui_mod, "message"):
            try:
                ui_mod.message(str(text))
            except Exception as e:
                logger.debug("Failed to deliver speech message via ui.message: %s", e)
        else:
            logger.info("[Speech Output] %s", text)

    def cancel_speech(self) -> None:
        """
        Cancels active speech synthesis if supported by NVDA runtime.
        """
        speech_mod = self._speech or sys.modules.get("speech")
        if speech_mod and hasattr(speech_mod, "cancelSpeech"):
            try:
                speech_mod.cancelSpeech()
            except Exception as e:
                logger.debug("Failed to cancel speech: %s", e)
        else:
            try:
                import speech
                if hasattr(speech, "cancelSpeech"):
                    speech.cancelSpeech()
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Configuration Verbosity Check
    # -------------------------------------------------------------------------

    def is_announcement_enabled(self, category: str) -> bool:
        """
        Checks if speech feedback is enabled for a specific category in config_spec.
        Categories: 'volume', 'seek', 'speed', 'track', 'loop', 'chapter'.
        """
        cfg = getConfig()
        key_map = {
            "volume": "announceVolume",
            "seek": "announceSeek",
            "speed": "announceSpeed",
            "track": "announceTrack",
            "loop": "announceLoop",
            "chapter": "announceChapter",
        }
        config_key = key_map.get(category.lower())
        if config_key and config_key in cfg:
            return bool(cfg[config_key])
        return True

    # -------------------------------------------------------------------------
    # Media Information Queries (i, Ctrl+i, Shift+i)
    # -------------------------------------------------------------------------

    def speak_media_info(
        self,
        title: Optional[str] = None,
        duration: Optional[float] = None,
        current_index: int = 0,
        total_tracks: int = 0,
        is_loaded: bool = True
    ) -> None:
        """
        Query 'i': Speaks complete media metadata.
        Format: 'Title: X, Duration: HH:MM:SS, Track Y of Z'
        """
        if not is_loaded or (not title and (duration is None or duration <= 0)):
            self.speak(_("Playlist empty"))
            return

        dur_str = format_time(duration) if duration and duration > 0 else "00:00"
        media_title = title or _("Default Test Media")

        if total_tracks > 0 and current_index > 0:
            msg = _("Title: %s, Duration: %s, Track %d of %d") % (
                media_title,
                dur_str,
                current_index,
                total_tracks,
            )
        elif total_tracks > 1:
            msg = _("Title: %s, Duration: %s, Track %d of %d") % (
                media_title,
                dur_str,
                1,
                total_tracks,
            )
        else:
            # Single file info or fallback
            msg = _("Title: %s, Duration: %s, Track %d of %d") % (
                media_title,
                dur_str,
                1,
                1,
            )

        self.speak(msg)

    def speak_remaining_time(
        self,
        remaining_sec: Optional[float] = None,
        duration: Optional[float] = None,
        is_loaded: bool = True
    ) -> None:
        """
        Query 'Ctrl+i': Speaks remaining playback duration.
        Format: 'Remaining time: HH:MM:SS'
        """
        if not is_loaded:
            self.speak(_("Playlist empty"))
            return

        rem_val = max(0.0, float(remaining_sec)) if remaining_sec is not None else 0.0
        rem_str = format_time(rem_val)
        msg = _("Remaining time: %s") % rem_str
        self.speak(msg)

    def speak_elapsed_time(
        self,
        elapsed_sec: Optional[float] = None,
        is_loaded: bool = True
    ) -> None:
        """
        Query 'Shift+i': Speaks elapsed playback timestamp.
        Format: 'Elapsed time: HH:MM:SS'
        """
        if not is_loaded:
            self.speak(_("Playlist empty"))
            return

        el_val = max(0.0, float(elapsed_sec)) if elapsed_sec is not None else 0.0
        el_str = format_time(el_val)
        msg = _("Elapsed time: %s") % el_str
        self.speak(msg)

    # -------------------------------------------------------------------------
    # Rapid Seek Debouncing & Feedback
    # -------------------------------------------------------------------------

    def on_seek_performed(
        self,
        delta_sec: float,
        current_pos: float,
        duration: float,
        play_click: bool = True
    ) -> None:
        """
        Handles seek navigation events with instantaneous acoustic feedback (click)
        and coalesces rapid seeks into a single spoken announcement after 250ms of inactivity.
        """
        # 1. Instantaneous auditory feedback
        if play_click:
            try:
                play_seek_click()
            except Exception:
                pass

        # 2. Check verbosity setting
        if not self.is_announcement_enabled("seek"):
            return

        with self._lock:
            # Cancel active debounce timer
            if self._seek_timer is not None:
                try:
                    self._seek_timer.cancel()
                except Exception:
                    pass
                self._seek_timer = None

            # Accumulate seek delta
            self._seek_accum_delta += delta_sec
            self._seek_last_target_pos = max(0.0, float(current_pos))
            self._seek_last_duration = max(0.0, float(duration))
            self._seek_last_time = time.time()

            # Schedule delayed speech announcement
            self._seek_timer = threading.Timer(
                self.debounce_interval,
                self._flush_debounced_seek
            )
            self._seek_timer.daemon = True
            self._seek_timer.start()

    def _flush_debounced_seek(self) -> None:
        """
        Dispatches the accumulated seek announcement once debouncing timer expires.
        """
        with self._lock:
            self._seek_timer = None
            delta = self._seek_accum_delta
            target_pos = self._seek_last_target_pos
            duration = self._seek_last_duration
            self._seek_accum_delta = 0.0

        if delta == 0.0 and target_pos == 0.0 and duration == 0.0:
            return

        # Format relative delta: e.g. "5s", "30s", "05:00"
        abs_delta = abs(delta)
        if abs_delta < 60.0 and abs_delta == int(abs_delta):
            delta_str = f"{int(abs_delta)}s"
        else:
            delta_str = format_time(abs_delta)

        pos_str = format_time(target_pos)
        dur_str = format_time(duration) if duration > 0 else "00:00"

        if delta >= 0:
            msg = _("Forward %s, position %s of %s") % (delta_str, pos_str, dur_str)
        else:
            msg = _("Backward %s, position %s of %s") % (delta_str, pos_str, dur_str)

        self.speak(msg)

    def cancel_debounced_seek(self) -> None:
        """
        Cancels any pending seek debouncing timer and resets accumulated seek delta.
        """
        with self._lock:
            if self._seek_timer is not None:
                try:
                    self._seek_timer.cancel()
                except Exception:
                    pass
                self._seek_timer = None
            self._seek_accum_delta = 0.0

    def cleanup(self) -> None:
        """
        Cleans up active resources and cancels pending timers.
        """
        self.cancel_debounced_seek()

    def announce_percent_jump(self, percent: int, target_pos: float) -> None:
        """
        Announces direct percentage jump (keys 1-9 / 0).
        """
        if not self.is_announcement_enabled("seek"):
            return
        pos_str = format_time(target_pos)
        msg = _("Jump to %d percent, position %s") % (int(percent), pos_str)
        self.speak(msg)

    def announce_boundary(self, is_start: bool) -> None:
        """
        Announces hitting beginning or end of media file.
        """
        msg = _("Start of media") if is_start else _("End of media")
        self.speak(msg)

    # -------------------------------------------------------------------------
    # Core Action Announcements (Honoring Verbosity Flags)
    # -------------------------------------------------------------------------

    def announce_volume(self, volume: float) -> None:
        """
        Announces volume change: 'Volume X percent'.
        """
        if not self.is_announcement_enabled("volume"):
            return
        msg = _("Volume %d percent") % int(round(volume))
        self.speak(msg)

    def announce_speed(self, speed: float, is_preset: bool = False) -> None:
        """
        Announces playback speed adjustment.
        """
        if not self.is_announcement_enabled("speed"):
            return
        if abs(speed - 1.0) < 0.001:
            msg = _("Speed reset to 1.0x")
        elif is_preset:
            msg = _("Speed %.2fx (Preset)") % speed
        else:
            msg = _("Speed %.2fx") % speed
        self.speak(msg)

    def announce_playback_state(self, state: str) -> None:
        """
        Announces playback state transitions: Playing, Paused, Stopped, Muted, Unmuted.
        """
        state_lower = str(state).lower()
        if state_lower in ("play", "playing", "resume", "resumed"):
            self.speak(_("Playing"))
        elif state_lower in ("pause", "paused"):
            self.speak(_("Paused"))
        elif state_lower in ("stop", "stopped"):
            self.speak(_("Stopped"))
        elif state_lower in ("mute", "muted"):
            self.speak(_("Muted"))
        elif state_lower in ("unmute", "unmuted"):
            self.speak(_("Unmuted"))

    def announce_track(
        self,
        current_index: int,
        total_tracks: int,
        title: str
    ) -> None:
        """
        Announces active track navigation in playlist.
        """
        if not self.is_announcement_enabled("track"):
            return
        msg = _("Track %d of %d: %s") % (current_index, total_tracks, title)
        self.speak(msg)

    def announce_point_a(self, time_pos: float) -> None:
        """
        Announces Point A marker set.
        """
        if not self.is_announcement_enabled("loop"):
            return
        pos_str = format_time(time_pos)
        msg = _("A-B Repeat: Start point set at %s") % pos_str
        self.speak(msg)

    def announce_point_b(self, time_pos: float) -> None:
        """
        Announces Point B marker set.
        """
        if not self.is_announcement_enabled("loop"):
            return
        pos_str = format_time(time_pos)
        msg = _("A-B Repeat: End point set at %s") % pos_str
        self.speak(msg)

    def announce_ab_loop_active(self, point_a: float, point_b: float) -> None:
        """
        Announces A-B loop segment engaged.
        """
        if not self.is_announcement_enabled("loop"):
            return
        a_str = format_time(point_a)
        b_str = format_time(point_b)
        msg = _("A-B Looping active from %s to %s") % (a_str, b_str)
        self.speak(msg)

    def announce_ab_loop_cleared(self) -> None:
        """
        Announces A-B repeat markers cleared.
        """
        if not self.is_announcement_enabled("loop"):
            return
        self.speak(_("A-B Repeat cleared"))

    def announce_repeat_mode(self, mode: str) -> None:
        """
        Announces repeat mode cycle: Track, Playlist, Disabled.
        """
        if not self.is_announcement_enabled("loop"):
            return
        m = str(mode).lower()
        if m in ("track", "single", "one"):
            self.speak(_("Repeat Track enabled"))
        elif m in ("playlist", "all"):
            self.speak(_("Repeat Playlist enabled"))
        else:
            self.speak(_("Repeat disabled"))

    def announce_chapter(self, chapter_num: int, title: Optional[str] = None) -> None:
        """
        Announces chapter navigation.
        """
        if not self.is_announcement_enabled("chapter"):
            return
        if title:
            msg = _("Chapter %d: %s") % (chapter_num, title)
        else:
            msg = _("Chapter %d") % chapter_num
        self.speak(msg)

    def announce_no_chapters(self) -> None:
        """
        Announces media lacks chapter markers.
        """
        if not self.is_announcement_enabled("chapter"):
            return
        self.speak(_("No chapters available in media"))

    def announce_audio_track(
        self,
        track_id: int,
        title: Optional[str] = None,
        lang: Optional[str] = None
    ) -> None:
        """
        Announces audio stream track cycling.
        """
        if title and lang:
            msg = _("Audio track %d: %s (%s)") % (track_id, title, lang)
        elif title:
            msg = _("Audio track %d: %s") % (track_id, title)
        else:
            msg = _("Audio track %d") % track_id
        self.speak(msg)

    def announce_no_other_audio_tracks(self) -> None:
        """
        Announces that no additional audio tracks or languages are available in this media.
        """
        self.speak(_("No other audio tracks available in this media"))

    def announce_auto_next(self, enabled: bool) -> None:
        """
        Announces auto-next toggle state.
        """
        msg = _("Auto-next enabled") if enabled else _("Auto-next disabled")
        self.speak(msg)

    def announce_shuffle(self, enabled: bool) -> None:
        """
        Announces shuffle toggle state.
        """
        msg = _("Shuffle enabled") if enabled else _("Shuffle disabled")
        self.speak(msg)

    def announce_loaded_files(self, count: int) -> None:
        """
        Announces count of files loaded into playlist.
        """
        msg = _("Loaded %d files into playlist") % count
        self.speak(msg)

    def announce_resume_position(self, pos_sec: float) -> None:
        """
        Announces playback position restored from saved state.
        """
        pos_str = format_time(pos_sec)
        msg = _("Playback resumed from %s") % pos_str
        self.speak(msg)

    def announce_no_explorer_selection(self) -> None:
        """
        Announces no media files found in active Windows Explorer selection.
        """
        self.speak(_("No media files currently selected in Windows Explorer"))

    def announce_no_media_in_folder(self) -> None:
        """
        Announces no media files found in selected directory.
        """
        self.speak(_("No media files found in selected folder"))

    def announce_player_closed(self) -> None:
        """
        Announces that the media player has been completely closed and stopped.
        """
        self.speak(_("Player closed"))

    def announce_sponsor_skipped(self, category: str) -> None:
        """
        Announces that a sponsor or promotional segment was automatically skipped.
        """
        if not self._should_announce("announceSponsorSkip"):
            return
        from .sponsorblock import get_category_display_name
        cat_name = get_category_display_name(category)
        msg = _("Skipped %s") % cat_name
        self.speak(msg)


# Module singleton instance
_global_speech_feedback: Optional[SpeechFeedback] = None
_speech_lock = threading.Lock()


def get_speech_feedback() -> SpeechFeedback:
    """
    Returns global SpeechFeedback singleton.
    """
    global _global_speech_feedback
    with _speech_lock:
        if _global_speech_feedback is None:
            _global_speech_feedback = SpeechFeedback()
        return _global_speech_feedback


def set_speech_feedback(instance: Optional[SpeechFeedback]) -> None:
    """
    Sets or overrides global SpeechFeedback instance.
    """
    global _global_speech_feedback
    with _speech_lock:
        _global_speech_feedback = instance
