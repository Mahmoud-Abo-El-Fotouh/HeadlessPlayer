# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Central Player Controller.
Coordinates the headless mpv audio engine, playlist and queue manager, persistent state store,
acoustic tone cues, spoken feedback, and modal keyboard capture layer.
"""

from __future__ import annotations
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from . import _  # type: ignore
except (ImportError, ValueError):
    try:
        _ = _  # type: ignore
    except NameError:
        _ = lambda text: text

import sys

try:
    import wx
except Exception:
    wx = None

try:
    import gui
except Exception:
    gui = None

try:
    import globalPluginHandler
except Exception:
    globalPluginHandler = None

from .engine import HeadlessEngine
from .playlist import Playlist, Track, RepeatMode
from .state_store import StateStore, get_state_store
from .speech_feedback import SpeechFeedback, get_speech_feedback
from .input_layer import ModalInputLayer
from .config_spec import getConfig, getConfigValue, setConfigValue, saveConfig
from .dialog_utils import prompt_open_file_dialog, prompt_open_folder_dialog, prompt_help_dialog
from .explorer_utils import get_active_explorer_or_focus_paths
from .utils import format_time, copy_to_clipboard, log_debug, log_exception, log_info
from .database import get_db_manager, disambiguate_recent_name
from .sponsorblock import extract_youtube_id, fetch_sponsor_segments
from . import stream_engine
from .url_dialogs import prompt_url_input, show_results_dialog
from .settings_panel import HeadlessPlayerSettingsPanel
from .recents_manager import RecentsManager
from .export_coordinator import ExportCoordinator

logger = logging.getLogger("HeadlessPlayer.Controller")


class PlayerController:
    """
    Central coordinator for HeadlessPlayer.
    Links the headless media engine, playlist state, state persistence,
    speech feedback, tone cues, and modal keyboard interception.
    """

    def __init__(
        self,
        engine: Optional[HeadlessEngine] = None,
        playlist: Optional[Playlist] = None,
        state_store: Optional[StateStore] = None,
        tone_mgr: Optional[Any] = None,
        speech_feedback: Optional[SpeechFeedback] = None,
        input_layer: Optional[ModalInputLayer] = None,
        pipe_name: Optional[str] = None
    ) -> None:
        self._lock = threading.RLock()

        # Component instances
        self.state_store: StateStore = state_store if state_store is not None else get_state_store()
        self.speech: SpeechFeedback = speech_feedback if speech_feedback is not None else get_speech_feedback()
        self.playlist: Playlist = playlist if playlist is not None else Playlist()
        
        cfg = getConfig()
        pipe = pipe_name or cfg.get("namedPipeName", r"\\.\pipe\nvda_headless_player")
        custom_mpv = cfg.get("mpvExecutablePath") or None
        self.engine: HeadlessEngine = engine if engine is not None else HeadlessEngine(pipe_name=pipe, custom_mpv_path=custom_mpv)

        self.input_layer: Optional[ModalInputLayer] = input_layer

        # Pending resume position to restore once file is loaded in mpv
        self._pending_resume_pos: Optional[float] = None
        self._last_loaded_path: Optional[str] = None
        self._is_terminating: bool = False

        # Generation counter guarding async online stream resolution races
        self._stream_play_generation: int = 0
        self._current_stream_chapters: List[Dict[str, Any]] = []
        self._stream_audio_tracks: List[Dict[str, Any]] = []
        self._stream_audio_track_idx: int = 0

        # Stream resolution guard and debounce tracking
        self._is_resolving_stream: bool = False
        self._resolving_track_path: Optional[str] = None
        self._stream_auto_retries: int = 0

        # Dynamic streaming queue auto-extension tracking
        self._active_stream_source_url: Optional[str] = None
        self._active_stream_source_target: Optional[str] = None
        self._active_stream_source_type: str = "listing"
        self._active_stream_next_idx: int = 1
        self._active_stream_batch_size: int = 50
        self._active_stream_has_more: bool = False
        self._active_stream_fetching: bool = False

        # Suppress resume announcement when cycling audio tracks
        self._silence_resume_announcement: bool = False

        # Double-press tracking for remaining time queries
        self._last_remaining_time_press: float = 0.0

        # Periodic session heartbeat auto-save tracking
        self._last_heartbeat_save_time: float = time.time()

        # Modular Sub-Controllers
        self.recents_manager = RecentsManager(self)
        self.export_coordinator = ExportCoordinator(self)

        # Chapter transition tracking for automatic announcements and duplicate suppression
        self._active_native_chapter_idx: Optional[int] = None
        self._active_stream_chapter_idx: Optional[int] = None
        self._suppress_next_auto_chapter: bool = False

        # Clip export and direct stream info state
        self._export_busy: bool = False
        self._current_stream_info: Optional[Dict[str, Any]] = None

        # Recents navigation and focus state
        self._recents_container_idx: int = 0
        self._recents_track_idx: int = 0
        self._recents_focus_active: bool = False
        self._recents_focus_category: Optional[str] = None
        self._recents_last_interaction: float = 0.0

        # Bind engine event callbacks

        self._bind_engine_callbacks()

        # Connect controller to input_layer if provided
        if self.input_layer is not None:
            self.input_layer.controller = self
            self._apply_config_to_input_layer(cfg)

        # Apply initial settings from config
        self._apply_initial_config(cfg)

    def _bind_engine_callbacks(self) -> None:
        """Register listeners for engine property changes and lifecycle events."""
        self.engine.on_file_loaded = self._on_engine_file_loaded
        self.engine.on_track_end = self._on_engine_track_end
        self.engine.on_property_change = self._on_engine_property_change
        self.engine.on_playback_restart = self._on_engine_playback_restart
        self.engine.on_seek = self._on_engine_seek
        self.engine.on_sponsor_skipped = self._on_sponsor_skipped

    def _apply_initial_config(self, cfg: Dict[str, Any]) -> None:
        """Initialize controller, engine, and playlist options from persistent storage."""
        # 1. Restore Repeat Mode and Auto-Next
        repeat_str = self.state_store.get_repeat_mode() or cfg.get("defaultRepeatMode", "off")
        self.playlist.set_repeat_mode(repeat_str)
        saved_auto_next = self.state_store.get_auto_next()
        auto_next = saved_auto_next if saved_auto_next is not None else cfg.get("defaultAutoNext", True)
        self.playlist.set_auto_next(auto_next)

        # 2. Restore Volume
        saved_vol = self.state_store.get_volume()
        if saved_vol is not None:
            vol = float(saved_vol)
        else:
            vol = float(cfg.get("volume", 100))
        self.engine.volume = max(0.0, min(150.0, vol))

        # 3. Restore Speed
        saved_speed = self.state_store.get_speed()
        if saved_speed is not None:
            spd = float(saved_speed)
        else:
            spd = float(cfg.get("defaultSpeed", 1.0))
        self.engine.speed = max(0.1, min(4.0, spd))

        # 4. Restore Bass Equalizer Gain
        saved_bass = self.state_store.get_setting("bass_gain", 0.0)
        try:
            self.engine.bass_gain = float(saved_bass) if saved_bass is not None else 0.0
        except (ValueError, TypeError):
            self.engine.bass_gain = 0.0

        # 5. Restore playback session if enabled
        if cfg.get("rememberPlaybackState", False):
            self.restore_session(auto_play=False)

    def _apply_config_to_input_layer(self, cfg: Dict[str, Any]) -> None:
        """Propagate seek/speed/volume step sizes to input_layer."""
        if not self.input_layer:
            return
        self.input_layer.seek_normal = float(cfg.get("seekStepNormal", 5.0))
        self.input_layer.seek_slow = float(cfg.get("seekStepSlow", 1.0))
        self.input_layer.seek_fast = float(cfg.get("seekStepFast", 30.0))
        self.input_layer.seek_ultrafast = float(cfg.get("seekStepUltrafast", 300.0))


    # -------------------------------------------------------------------------
    # Lifecycle Management
    # -------------------------------------------------------------------------

    def start(self) -> bool:
        """Starts the underlying mpv daemon and named pipe client."""
        with self._lock:
            if self._is_terminating:
                return False
            return self.engine.start()

    def shutdown(self) -> None:
        """Gracefully shuts down media playback, saves active position, and terminates engine."""
        with self._lock:
            self._is_terminating = True
            if hasattr(self.speech, "cancel_debounced_seek"):
                self.speech.cancel_debounced_seek()
            if getConfigValue("rememberPlaybackState", False):
                self.save_session()
            else:
                self.state_store.clear_last_session()
            self.save_current_position()
            self.engine.shutdown()

    # -------------------------------------------------------------------------
    # Recents & Export Properties (Delegated to Sub-Controllers)
    # -------------------------------------------------------------------------

    @property
    def _recents_focus_active(self) -> bool:
        return self.recents_manager.focus_active

    @_recents_focus_active.setter
    def _recents_focus_active(self, val: bool) -> None:
        self.recents_manager.focus_active = val

    @property
    def _recents_focus_category(self) -> Optional[str]:
        return self.recents_manager.focus_category

    @_recents_focus_category.setter
    def _recents_focus_category(self, val: Optional[str]) -> None:
        self.recents_manager.focus_category = val

    @property
    def _recents_playlist_idx(self) -> int:
        return self.recents_manager.playlist_idx

    @_recents_playlist_idx.setter
    def _recents_playlist_idx(self, val: int) -> None:
        self.recents_manager.playlist_idx = val

    @property
    def _recents_container_idx(self) -> int:
        return self.recents_manager.playlist_idx

    @_recents_container_idx.setter
    def _recents_container_idx(self, val: int) -> None:
        self.recents_manager.playlist_idx = val

    @property
    def _recents_track_idx(self) -> int:
        return self.recents_manager.track_idx

    @_recents_track_idx.setter
    def _recents_track_idx(self, val: int) -> None:
        self.recents_manager.track_idx = val

    @property
    def _recents_last_interaction(self) -> float:
        return self.recents_manager.last_interaction

    @_recents_last_interaction.setter
    def _recents_last_interaction(self, val: float) -> None:
        self.recents_manager.last_interaction = val

    @property
    def _export_busy(self) -> bool:
        return self.export_coordinator.is_busy

    @_export_busy.setter
    def _export_busy(self, val: bool) -> None:
        self.export_coordinator.is_busy = val

    def terminate(self) -> None:
        """Full cleanup hook for plugin termination."""
        if hasattr(self.speech, "cancel_debounced_seek"):
            self.speech.cancel_debounced_seek()
        self.shutdown()

    # -------------------------------------------------------------------------
    # Core Playback Controls
    # -------------------------------------------------------------------------

    def toggle_play_pause(self) -> bool:
        """
        Toggles playback state (play <-> pause).
        If stopped, idle, or EOF reached: restarts playback of current track.
        """
        with self._lock:
            if hasattr(self.speech, "cancel_debounced_seek"):
                self.speech.cancel_debounced_seek()

            log_info("CONTROLLER", "toggle_play_pause invoked: running=%s, loaded=%s, paused=%s", self.engine.is_running, getattr(self.engine, "is_loaded", False), getattr(self.engine, "paused", False))

            if getattr(self, "_is_resolving_stream", False):
                self.speech.speak(_("Loading stream, please wait..."))
                return False

            if self.playlist.is_empty() and getConfigValue("rememberPlaybackState", False):
                if self.restore_session(auto_play=False):
                    cur_track = self.playlist.get_current_track()
                    if cur_track:
                        return self.play_track(cur_track)

            if not self.engine.is_running:
                self.start()
                cur_track = self.playlist.get_current_track()
                if cur_track:
                    return self.play_track(cur_track)
                return False

            # Engine running but idle (nothing loaded) or finished:
            # Replay the active track from playlist instead of toggling pause into void
            if not getattr(self.engine, "is_loaded", False):
                cur_track = self.playlist.get_current_track()
                if cur_track:
                    return self.play_track(cur_track)
                return False

            time_pos = getattr(self.engine, "time_pos", 0.0)
            duration = getattr(self.engine, "duration", 0.0)
            is_eof = getattr(self.engine, "eof_reached", False) or (duration > 0 and time_pos >= duration - 0.5)

            if is_eof:
                cur_track = self.playlist.get_current_track()
                if cur_track:
                    return self.play_track(cur_track)
                self.engine.seek_absolute(0.0)
                self.engine.resume()
                self.speech.announce_playback_state("playing")
                return False

            new_pause = self.engine.toggle_pause()
            if new_pause:
                self.save_current_position()
                if getattr(self, "_restore_last_session", True):
                    self.save_session()
                self.speech.announce_playback_state("paused")
            else:
                self.speech.announce_playback_state("playing")
            return new_pause

    def toggle_pause(self) -> bool:
        """Alias for toggle_play_pause."""
        return self.toggle_play_pause()

    def play(self) -> bool:
        """Explicitly starts or resumes playback."""
        with self._lock:
            if getattr(self, "_is_resolving_stream", False):
                self.speech.speak(_("Loading stream, please wait..."))
                return False
            if not self.engine.is_running or not getattr(self.engine, "path", None):
                cur_track = self.playlist.get_current_track()
                if cur_track:
                    return self.play_track(cur_track)
                return False
            res = self.engine.resume()
            self.speech.announce_playback_state("playing")
            return res

    def pause(self) -> bool:
        """Explicitly pauses playback and saves resume position."""
        with self._lock:
            if not self.engine.is_running:
                return False
            # Never set mpv's pause flag while nothing is loaded - it would
            # stick and freeze the next loaded track at 0:00.
            if not getattr(self.engine, "is_loaded", False) and not getattr(self.engine, "path", None):
                return False
            self.save_current_position()
            res = self.engine.pause()
            self.speech.announce_playback_state("paused")
            return res

    def stop(self) -> bool:
        """Stops playback, rewinds to start (0:00), clears saved position, and announces stopped."""
        log_info("CONTROLLER", "stop invoked: is_running=%s, last_loaded=%s", self.engine.is_running, self._last_loaded_path)
        with self._lock:
            if hasattr(self.speech, "cancel_debounced_seek"):
                self.speech.cancel_debounced_seek()
            if getattr(self, "_is_resolving_stream", False):
                self._is_resolving_stream = False
                self._resolving_track_path = None
                self._stream_play_generation += 1
            self._stream_auto_retries = 0
            cur_path = self._last_loaded_path or getattr(self.engine, "path", None)
            if not cur_path:
                cur_track = self.playlist.get_current_track()
                if cur_track:
                    cur_path = cur_track.path
            if cur_path:
                self.state_store.clear_position(cur_path)
            self._pending_resume_pos = 0.0

            if not self.engine.is_running:
                self.speech.announce_playback_state("stopped")
                return True

            self.engine.pause()
            self.engine.seek_absolute(0.0)
            with self.engine._lock:
                self.engine.time_pos = 0.0
                self.engine.paused = True
            self.speech.announce_playback_state("stopped")
            return True

    def toggle_mute(self) -> bool:
        """Toggles mute state and announces result."""
        with self._lock:
            if not self.engine.is_running:
                return False
            new_mute = self.engine.toggle_mute()
            self.speech.announce_playback_state("muted" if new_mute else "unmuted")
            return new_mute

    def adjust_volume(self, delta: float) -> float:
        """Adjusts playback volume (+/-5%) with speech feedback."""
        with self._lock:
            if not self.engine.is_running:
                self.start()
            new_vol = self.engine.adjust_volume(delta)
            self.speech.announce_volume(new_vol)
            self.state_store.save_volume(int(new_vol))
            setConfigValue("volume", int(new_vol))
            saveConfig()
            return new_vol

    def adjust_bass(self, delta: float) -> float:
        """Raises or lowers the bass level (+/- 3 dB steps) with speech feedback."""
        with self._lock:
            if not self.engine.is_running:
                self.start()
            new_gain = self.engine.adjust_bass(delta)
            self.state_store.save_setting("bass_gain", float(new_gain))
            setConfigValue("bassGain", float(new_gain))
            saveConfig()
            if new_gain:
                self.speech.speak(_("Bass: %s dB") % (f"+{new_gain:g}" if new_gain > 0 else f"{new_gain:g}"))
            else:
                self.speech.speak(_("Bass: normal"))
            return new_gain

    def set_volume(self, volume: float) -> float:
        """Sets exact volume level."""
        with self._lock:
            if not self.engine.is_running:
                self.start()
            new_vol = self.engine.set_volume(volume)
            self.speech.announce_volume(new_vol)
            self.state_store.save_volume(int(new_vol))
            setConfigValue("volume", int(new_vol))
            saveConfig()
            return new_vol

    # -------------------------------------------------------------------------
    # Granular Seek Controls & Debouncing
    # -------------------------------------------------------------------------

    def seek(self, delta_sec: float) -> bool:
        """
        Relative seek with acoustic tactile click and coalesced 250ms speech announcement.
        """
        with self._lock:
            if not self.engine.is_running:
                return False

            dur = self.engine.duration
            cur_pos = self.engine.time_pos
            target_pos = cur_pos + delta_sec

            res = self.engine.seek(delta_sec)
            new_pos = self.engine.time_pos

            # Dispatch seek event to debouncer
            self.speech.on_seek_performed(
                delta_sec=delta_sec,
                current_pos=new_pos,
                duration=dur,
                play_click=True
            )
            return res

    def seek_percent(self, percent: int) -> bool:
        """Jumps to percentage of duration (10% to 90% via number keys)."""
        with self._lock:
            if not self.engine.is_running:
                return False
            res = self.engine.seek_percent(percent)
            dur = self.engine.duration
            target_pos = (percent / 100.0) * dur if dur > 0 else 0.0
            self.speech.announce_percent_jump(percent, target_pos)
            return res

    def seek_absolute(self, pos_sec: float) -> bool:
        """Seeks to an absolute timestamp in seconds."""
        with self._lock:
            if not self.engine.is_running:
                return False
            return self.engine.seek_absolute(pos_sec)

    def jump_to_track_start(self) -> bool:
        """Jumps directly to the beginning (0:00) of the current playing track (Home key)."""
        with self._lock:
            if not self.engine.is_running:
                return False
            res = self.engine.seek_absolute(0.0)
            self.speech.announce_percent_jump(0, 0.0)
            return res

    def jump_to_track_end(self) -> bool:
        """Jumps directly to the end of the current playing track (End key)."""
        with self._lock:
            if not self.engine.is_running:
                return False
            dur = self.engine.duration
            if dur and dur > 2.0:
                target = max(0.0, dur - 1.0)
                res = self.engine.seek_absolute(target)
                self.speech.speak(_("Track end"))
                return res
            elif dur and dur > 0:
                res = self.engine.seek_absolute(dur)
                self.speech.speak(_("Track end"))
                return res
            return False

    # -------------------------------------------------------------------------
    # Pitch-Preserved Speed Engine
    # -------------------------------------------------------------------------

    def adjust_speed(self, delta: float) -> float:
        """Fine-tunes speed (+/-0.1x) with speech feedback."""
        with self._lock:
            if not self.engine.is_running:
                self.start()
            new_speed = self.engine.adjust_speed(delta)
            self.speech.announce_speed(new_speed, is_preset=False)
            self.state_store.save_speed(new_speed)
            setConfigValue("defaultSpeed", float(new_speed))
            saveConfig()
            return new_speed

    def cycle_speed_preset(self, forward: bool = True) -> float:
        """Cycles preset speeds (1.0x, 1.25x, 1.5x, 1.75x, 2.0x, 2.5x, 3.0x, 4.0x)."""
        with self._lock:
            if not self.engine.is_running:
                self.start()
            new_speed = self.engine.cycle_speed_preset(forward=forward)
            self.speech.announce_speed(new_speed, is_preset=True)
            self.state_store.save_speed(new_speed)
            setConfigValue("defaultSpeed", float(new_speed))
            saveConfig()
            return new_speed

    def set_speed(self, speed: float) -> float:
        """Sets exact speed multiplier."""
        with self._lock:
            if not self.engine.is_running:
                self.start()
            new_speed = self.engine.set_speed(speed)
            self.speech.announce_speed(new_speed, is_preset=False)
            self.state_store.save_speed(new_speed)
            setConfigValue("defaultSpeed", float(new_speed))
            saveConfig()
            return new_speed

    # -------------------------------------------------------------------------
    # A-B Segment Repeat & Track Repeat
    # -------------------------------------------------------------------------

    def set_ab_point_a(self) -> float:
        """Marks Point A (start of A-B loop) with acoustic tone and speech feedback."""
        with self._lock:
            if not self.engine.is_running:
                return 0.0
            pos = self.engine.set_ab_point_a()
            self.speech.announce_point_a(pos)
            return pos

    def set_ab_point_b(self) -> Tuple[float, bool]:
        """Marks Point B (end of A-B loop) with speech announcement."""
        with self._lock:
            if not self.engine.is_running:
                return 0.0, False
            pos, is_valid = self.engine.set_ab_point_b()
            if is_valid:
                self.speech.announce_point_b(pos)
                if self.engine.ab_loop_a is not None:
                    self.speech.announce_ab_loop_active(self.engine.ab_loop_a, pos)
            return pos, is_valid

    def toggle_repeat(self) -> str:
        """
        Toggles repeat mode:
        If A-B points exist -> toggles A-B segment repeat.
        Otherwise -> cycles repeat mode: Track -> Playlist -> Off.
        """
        with self._lock:
            if not self.engine.is_running:
                return "off"

            # Check if A-B loop points are marked or cached
            has_ab = (
                (self.engine.ab_loop_a is not None and self.engine.ab_loop_b is not None)
                or (getattr(self.engine, "_cached_ab_a", None) is not None and getattr(self.engine, "_cached_ab_b", None) is not None)
            )
            if has_ab:
                res = self.engine.toggle_repeat()
                if res == "ab_loop_on":
                    a = self.engine.ab_loop_a if self.engine.ab_loop_a is not None else getattr(self.engine, "_cached_ab_a", 0.0)
                    b = self.engine.ab_loop_b if self.engine.ab_loop_b is not None else getattr(self.engine, "_cached_ab_b", 0.0)
                    self.speech.announce_ab_loop_active(a or 0.0, b or 0.0)
                elif res == "ab_loop_off":
                    self.speech.announce_repeat_mode("off")
                return res
            else:
                # Cycle playlist repeat modes: OFF -> TRACK -> PLAYLIST -> OFF
                new_mode = self.playlist.cycle_repeat_mode()
                if new_mode == RepeatMode.TRACK:
                    self.engine.set_track_repeat(True)
                    self.speech.announce_repeat_mode("track")
                    return "track_repeat_on"
                elif new_mode == RepeatMode.PLAYLIST:
                    self.engine.set_track_repeat(False)
                    self.speech.announce_repeat_mode("playlist")
                    return "playlist_repeat_on"
                else:
                    self.engine.set_track_repeat(False)
                    self.speech.announce_repeat_mode("off")
                    return "off"

    def clear_ab_points(self) -> None:
        """Clears all marked A-B loop points."""
        with self._lock:
            if not self.engine.is_running:
                return
            self.engine.clear_ab_points()
            self.speech.announce_ab_loop_cleared()

    # -------------------------------------------------------------------------
    # Chapter Navigation & Audio Track Cycling
    # -------------------------------------------------------------------------

    def next_chapter(self) -> bool:
        """Jumps to next chapter and announces title/index with start time."""
        with self._lock:
            if not self.engine.is_running:
                return False

            # 1. Native mpv chapters for local media containers
            if self.engine.chapter_count > 0:
                cur_chap = self.engine.chapter if self.engine.chapter is not None else -1
                target_idx = min(self.engine.chapter_count - 1, cur_chap + 1) if cur_chap >= 0 else 0
                res = self.engine.next_chapter()
                if res:
                    self._active_native_chapter_idx = target_idx
                    self._suppress_next_auto_chapter = True
                    chap_info = self.engine.get_chapter_info(target_idx) if hasattr(self.engine, "get_chapter_info") else None
                    chap_num = target_idx + 1
                    title = chap_info.get("title") if chap_info else self.engine.get_current_chapter_title()
                    start_time = float(chap_info["time"]) if (chap_info and chap_info.get("time") is not None) else self.engine.get_current_chapter_start_time()
                    self.speech.announce_chapter(chap_num, title, start_time=start_time)
                    return True

            # 2. Extracted stream chapters for YouTube / online media
            cur_track = self.playlist.get_current_track()
            chapters = getattr(self, "_current_stream_chapters", None) or (cur_track.chapters if cur_track else None) or []
            if chapters:
                cur_time = self.engine.time_pos or 0.0
                next_idx = None
                for i, ch in enumerate(chapters):
                    if float(ch.get("start_time", 0.0)) > (cur_time + 0.5):
                        next_idx = i
                        break

                if next_idx is not None:
                    target_ch = chapters[next_idx]
                    target_sec = float(target_ch.get("start_time", 0.0))
                    title = target_ch.get("title", f"Chapter {next_idx + 1}")
                    self._active_stream_chapter_idx = next_idx
                    self._suppress_next_auto_chapter = True
                    self.engine.seek_absolute(target_sec)
                    self.speech.announce_chapter(next_idx + 1, title, start_time=target_sec)
                    return True

            self.speech.announce_no_chapters()
            return False

    def prev_chapter(self) -> bool:
        """Jumps to previous chapter and announces title/index with start time."""
        with self._lock:
            if not self.engine.is_running:
                return False

            # 1. Native mpv chapters for local media containers
            if self.engine.chapter_count > 0:
                cur_chap = self.engine.chapter if self.engine.chapter is not None else 0
                cur_time = self.engine.time_pos or 0.0
                cur_info = self.engine.get_chapter_info(cur_chap) if hasattr(self.engine, "get_chapter_info") else None
                cur_start = float(cur_info["time"]) if (cur_info and cur_info.get("time") is not None) else 0.0

                if (cur_time - cur_start) > 3.0 or cur_chap == 0:
                    target_idx = max(0, cur_chap)
                else:
                    target_idx = max(0, cur_chap - 1)

                res = self.engine.prev_chapter()
                if res:
                    self._active_native_chapter_idx = target_idx
                    self._suppress_next_auto_chapter = True
                    chap_info = self.engine.get_chapter_info(target_idx) if hasattr(self.engine, "get_chapter_info") else None
                    chap_num = target_idx + 1
                    title = chap_info.get("title") if chap_info else self.engine.get_current_chapter_title()
                    start_time = float(chap_info["time"]) if (chap_info and chap_info.get("time") is not None) else self.engine.get_current_chapter_start_time()
                    self.speech.announce_chapter(chap_num, title, start_time=start_time)
                    return True

            # 2. Extracted stream chapters for YouTube / online media
            cur_track = self.playlist.get_current_track()
            chapters = getattr(self, "_current_stream_chapters", None) or (cur_track.chapters if cur_track else None) or []
            if chapters:
                cur_time = self.engine.time_pos or 0.0
                cur_ch_idx = 0
                for i, ch in enumerate(chapters):
                    if float(ch.get("start_time", 0.0)) <= cur_time + 0.5:
                        cur_ch_idx = i

                ch_start = float(chapters[cur_ch_idx].get("start_time", 0.0))
                if (cur_time - ch_start) > 3.0 or cur_ch_idx == 0:
                    target_idx = cur_ch_idx
                else:
                    target_idx = max(0, cur_ch_idx - 1)

                target_ch = chapters[target_idx]
                target_sec = float(target_ch.get("start_time", 0.0))
                title = target_ch.get("title", f"Chapter {target_idx + 1}")
                self._active_stream_chapter_idx = target_idx
                self._suppress_next_auto_chapter = True
                self.engine.seek_absolute(target_sec)
                self.speech.announce_chapter(target_idx + 1, title, start_time=target_sec)
                return True

            self.speech.announce_no_chapters()
            return False

    def cycle_audio_track(self) -> bool:
        """Cycles audio tracks / language streams in video and audio files or online streams."""
        with self._lock:
            if not self.engine.is_running:
                return False

            # 1. If currently playing an online stream with multi-language audio tracks
            if self._stream_audio_tracks and len(self._stream_audio_tracks) > 1:
                total = len(self._stream_audio_tracks)
                self._stream_audio_track_idx = (self._stream_audio_track_idx + 1) % total
                target = self._stream_audio_tracks[self._stream_audio_track_idx]
                cur_pos = self.engine.get_elapsed_time()
                is_paused = getattr(self.engine, "paused", False)

                self._pending_resume_pos = cur_pos if cur_pos >= 0.5 else None
                self._silence_resume_announcement = True
                self.engine.load_stream(target["url"], target.get("http_headers"))
                if is_paused:
                    self.engine.pause()

                t_id = self._stream_audio_track_idx + 1
                title = target.get("title")
                lang = target.get("lang")
                self.speech.announce_audio_track(t_id, title, lang)
                return True

            # 2. Local media with container tracks
            success, track_info, total = self.engine.cycle_audio_track()
            if total <= 1:
                self.speech.announce_no_other_audio_tracks()
                return False
            if success and track_info:
                t_id = track_info.get("id", 1)
                title = track_info.get("title")
                lang = track_info.get("lang")
                self.speech.announce_audio_track(t_id, title, lang)
                return True
            return False

    # -------------------------------------------------------------------------
    # Playlist & Queue Navigation
    # -------------------------------------------------------------------------

    def play_track(self, track: Track) -> bool:
        """Loads and begins playback of a specific track (local file or online stream)."""
        if not track or not track.path:
            return False

        # Online stream tracks are resolved asynchronously via yt-dlp
        if getattr(track, "is_stream", False):
            return self._play_stream_track(track)

        with self._lock:
            self._is_resolving_stream = False
            self._resolving_track_path = None
            self._stream_auto_retries = 0
            self._active_stream_source_target = None
            self._active_stream_source_url = None
            self._active_stream_has_more = False
            self._current_stream_chapters = list(getattr(track, "chapters", [])) if getattr(track, "chapters", None) else []
            # Invalidate any in-flight online stream resolution
            self._stream_play_generation += 1
            target_path = track.path

            # 1. Save playback position of previous track before loading the new one
            if self._last_loaded_path and self._last_loaded_path != target_path:
                self.save_current_position(target_path=self._last_loaded_path)

            # 2. Retrieve saved position for THIS specific track (if not already set by session restore)
            if self._pending_resume_pos is None or self._pending_resume_pos < 0.5:
                cfg = getConfig()
                if cfg.get("resumePosition", True):
                    saved_pos = self.state_store.get_position(
                        target_path,
                        current_duration=getattr(track, "duration", None)
                    )
                    if saved_pos and saved_pos >= 1.0:
                        self._pending_resume_pos = saved_pos
                    else:
                        self._pending_resume_pos = None
                else:
                    self._pending_resume_pos = None

            # 3. Update currently loaded path
            self._last_loaded_path = target_path

            # 5. Load into mpv engine (clearing any stream HTTP headers first)
            self.engine.set_http_headers(None)
            if hasattr(self, "history_sync") and self.history_sync:
                self.history_sync.stop_session(reason="track_switch")
            success = self.engine.load_file(target_path, append=False)
            if success:
                self.state_store.save_recent_file(target_path)
                self._load_sponsor_segments_for_url(target_path)

                # Announce active track
                orig_idx = self.playlist.current_index + 1
                total = self.playlist.count
                self.speech.announce_track(orig_idx, total, track.display_name)
            return success

    def next_track(self, manual: bool = True) -> Optional[Track]:
        """Advances to the next track in playlist."""
        with self._lock:
            next_t = self.playlist.next_track(manual=manual)
            if next_t:
                self.play_track(next_t)
                # Prefetch more tracks if near the end of an online stream playlist/search
                self._check_stream_queue_auto_extend()
                return next_t
            else:
                # Boundary reached
                if manual:
                    self.speech.announce_boundary(is_start=False)
                return None

    def prev_track(self) -> Optional[Track]:
        """Navigates to the previous track in playlist."""
        with self._lock:
            prev_t = self.playlist.prev_track()
            if prev_t:
                self.play_track(prev_t)
                return prev_t
            else:
                self.speech.announce_boundary(is_start=True)
                return None

    def jump_to_first_track(self) -> Optional[Track]:
        """Jumps directly to the first track in the playlist (Control + Home)."""
        with self._lock:
            if self.playlist.is_empty():
                self.speech.announce_boundary(is_start=True)
                return None
            first_t = self.playlist.first_track()
            if first_t:
                self.play_track(first_t)
                return first_t
            return None

    def jump_to_last_track(self) -> Optional[Track]:
        """Jumps directly to the last track in the playlist (Control + End)."""
        with self._lock:
            if self.playlist.is_empty():
                self.speech.announce_boundary(is_start=False)
                return None
            last_t = self.playlist.last_track()
            if last_t:
                self.play_track(last_t)
                return last_t
            return None

    def toggle_auto_next(self) -> bool:
        """Toggles auto-next track playback."""
        with self._lock:
            new_val = self.playlist.toggle_auto_next()
            self.speech.announce_auto_next(new_val)
            self.state_store.save_auto_next(new_val)
            return new_val

    def toggle_shuffle(self) -> bool:
        """Toggles playlist shuffle mode."""
        with self._lock:
            new_val = self.playlist.toggle_shuffle()
            self.speech.announce_shuffle(new_val)
            self.state_store.save_shuffle(new_val)
            return new_val

    # -------------------------------------------------------------------------
    # Speech Query Commands (i, Ctrl+i, Shift+i)
    # -------------------------------------------------------------------------

    def speak_media_info(self) -> None:
        """Speaks full media title, duration, and playlist index."""
        with self._lock:
            info = self.engine.get_media_info()
            cur_track = self.playlist.get_current_track()
            title = (cur_track.display_name if cur_track else "") or info.get("title") or ""
            dur = info.get("duration", 0.0)
            idx = self.playlist.current_index + 1
            total = self.playlist.count
            is_loaded = bool(info.get("is_loaded") or cur_track is not None)
            self.speech.speak_media_info(
                title=title,
                duration=dur,
                current_index=idx,
                total_tracks=total,
                is_loaded=is_loaded
            )

    def speak_remaining_time(self) -> None:
        """
        Speaks remaining playback time in formatted string.
        Accounts for active playback speed (e.g. at 2.0x, remaining time is halved).
        Double-pressing in quick succession announces unscaled track remaining time.
        """
        with self._lock:
            now = time.time()
            is_double = (now - getattr(self, "_last_remaining_time_press", 0.0)) < 0.6
            self._last_remaining_time_press = now

            rem = self.engine.get_remaining_time()
            dur = self.engine.get_duration()
            speed = getattr(self.engine, "speed", 1.0)
            is_loaded = bool(self.engine.is_loaded or dur > 0)
            self.speech.speak_remaining_time(
                rem,
                duration=dur,
                is_loaded=is_loaded,
                speed=speed,
                is_raw=is_double
            )


    def speak_elapsed_time(self) -> None:
        """Speaks elapsed playback time in formatted string with speed scaling."""
        with self._lock:
            now = time.time()
            is_double = (now - getattr(self, "_last_elapsed_time_press", 0.0)) < 0.6
            self._last_elapsed_time_press = now

            el = self.engine.get_elapsed_time()
            dur = self.engine.get_duration()
            speed = getattr(self.engine, "speed", 1.0)
            is_loaded = bool(self.engine.is_loaded or dur > 0)
            self.speech.speak_elapsed_time(
                el,
                is_loaded=is_loaded,
                speed=speed,
                is_raw=is_double
            )

    # -------------------------------------------------------------------------
    # Dialogs & Windows Explorer Integration
    # -------------------------------------------------------------------------

    def _get_last_browse_dir(self) -> str:
        """Retrieves directory of the last played file or last browsed folder."""
        saved_dir = self.state_store.get_setting("last_browse_dir")
        if saved_dir and isinstance(saved_dir, str) and os.path.isdir(saved_dir):
            return os.path.abspath(saved_dir)

        last_path = self._last_loaded_path
        if last_path and os.path.exists(last_path) and not last_path.startswith("http"):
            if os.path.isdir(last_path):
                return os.path.abspath(last_path)
            return os.path.abspath(os.path.dirname(last_path))

        recent = self.state_store.get_recent_files()
        if recent:
            for r in recent:
                p = r.get("file_path") if isinstance(r, dict) else r
                if p and isinstance(p, str) and not str(p).startswith("http") and os.path.exists(p):
                    return os.path.abspath(os.path.dirname(p) if os.path.isfile(p) else p)

        return os.path.expanduser("~")

    def on_config_updated(self, cfg: Optional[Dict[str, Any]] = None) -> None:
        """Called when user applies updated settings from NVDA Settings panel."""
        if cfg is None:
            cfg = getConfig()
        with self._lock:
            if self.input_layer is not None:
                self._apply_config_to_input_layer(cfg)
                self.input_layer.invalidate_keymap_cache()
            if self.speech is not None:
                self.speech.reload_config()
            if "defaultAutoNext" in cfg:
                self.playlist.set_auto_next(bool(cfg["defaultAutoNext"]))
            if "defaultRepeatMode" in cfg:
                self.playlist.set_repeat_mode(str(cfg["defaultRepeatMode"]))
            if "defaultSpeed" in cfg:
                try:
                    spd = float(cfg["defaultSpeed"])
                    self.engine.speed = spd
                    if self.engine.is_running:
                        self.engine.set_speed(spd)
                    self.state_store.save_speed(spd)
                except Exception:
                    pass
            if "volume" in cfg:
                try:
                    vol = float(cfg["volume"])
                    self.engine.volume = vol
                    if self.engine.is_running:
                        self.engine.set_volume(vol)
                    self.state_store.save_volume(int(vol))
                except Exception:
                    pass
            if "sponsorBlockEnabled" in cfg and self.engine:
                try:
                    self.engine.set_sponsor_block_enabled(bool(cfg["sponsorBlockEnabled"]))
                except Exception:
                    pass

    def open_file_dialog(self) -> None:
        """Opens native file dialog to select and play a media file."""
        self._exit_player_mode_for_dialog()
        default_dir = self._get_last_browse_dir()
        prompt_open_file_dialog(
            on_file_selected=self._on_file_selected,
            on_cancelled=self._on_dialog_cancelled,
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
            default_dir=default_dir
        )

    def open_folder_dialog(self) -> None:
        """Opens native folder browser dialog to queue and play an entire folder."""
        self._exit_player_mode_for_dialog()
        default_dir = self._get_last_browse_dir()
        prompt_open_folder_dialog(
            on_folder_selected=self._on_folder_selected,
            on_cancelled=self._on_dialog_cancelled,
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
            default_dir=default_dir
        )

    def _on_dialog_cancelled(self) -> None:
        """Invoked when user cancels an open file/folder dialog."""
        self._check_auto_enter_player_mode()

    def get_toggle_gesture_display(self) -> str:
        """Retrieves active toggle shortcut string dynamically from NVDA."""
        try:
            gh = sys.modules.get("globalPluginHandler", globalPluginHandler)
            for plugin in getattr(gh, "runningPlugins", []):
                if plugin.__class__.__module__.endswith("HeadlessPlayer"):
                    if hasattr(plugin, "getGesturesForScript"):
                        script_func = getattr(plugin, "script_togglePlayerMode", None)
                        if script_func:
                            gestures = plugin.getGesturesForScript(script_func)
                            if gestures:
                                return ", ".join(
                                    str(g).replace("kb:", "").replace("control", "Ctrl").replace("shift", "Shift").replace("nvda", "NVDA").replace("insert", "Insert").replace("capslock", "CapsLock")
                                    for g in gestures
                                )
        except Exception as e:
            logger.debug("Error querying active toggle gesture: %s", e)
        return "NVDA+Ctrl+Shift+P / Insert+Ctrl+Shift+P"

    def show_shortcuts_help(self) -> None:
        """
        Presents the accessible shortcuts help window.
        Player Mode exits automatically so the help window is immediately readable.
        """
        self._exit_player_mode_for_dialog()
        toggle_str = self.get_toggle_gesture_display()
        prompt_help_dialog(
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
            custom_toggle_gesture=toggle_str
        )

    def open_settings(self) -> None:
        """
        Ctrl + Shift + S: Exits player mode and opens NVDA Settings dialog focused on HeadlessPlayer panel.
        """
        def _do_open():
            opened = False
            has_gui = False
            try:
                gm = sys.modules.get("gui", gui)
                if gm and hasattr(gm, "mainFrame") and gm.mainFrame:
                    has_gui = True
                    # Method 1: Modern NVDA (2019.3+) via popupSettingsDialog with settingsDialogs.NVDASettingsDialog
                    settings_dialogs = getattr(gm, "settingsDialogs", None)
                    settings_dialog_cls = getattr(settings_dialogs, "NVDASettingsDialog", None) if settings_dialogs else getattr(gm, "NVDASettingsDialog", None)
                    popup_func = getattr(gm.mainFrame, "popupSettingsDialog", None) or getattr(gm.mainFrame, "_popupSettingsDialog", None)

                    if popup_func and callable(popup_func) and settings_dialog_cls:
                        try:
                            popup_func(settings_dialog_cls, initialCategory=HeadlessPlayerSettingsPanel)
                            opened = True
                        except TypeError:
                            try:
                                popup_func(settings_dialog_cls, HeadlessPlayerSettingsPanel)
                                opened = True
                            except TypeError:
                                try:
                                    popup_func(settings_dialog_cls)
                                    opened = True
                                except Exception:
                                    pass

                    # Method 2: Direct popupSettingsDialog if it accepts category directly in custom builds
                    if not opened and popup_func and callable(popup_func):
                        try:
                            popup_func(initialCategory=HeadlessPlayerSettingsPanel)
                            opened = True
                        except TypeError:
                            pass

                    # Method 3: onPreferencesSettingsCommand fallback
                    if not opened:
                        pref_cmd = (
                            getattr(gm.mainFrame, "onPreferencesSettingsCommand", None)
                            or getattr(gm.mainFrame, "onPreferenceSettings", None)
                        )
                        if pref_cmd and callable(pref_cmd):
                            try:
                                try:
                                    evt = wx.CommandEvent() if wx else None
                                    pref_cmd(evt)
                                except Exception:
                                    pref_cmd(None)
                                opened = True
                            except Exception as e_pref:
                                logger.debug("onPreferencesSettingsCommand failed: %s", e_pref)

                    # Method 4: Direct NVDASettingsDialog instantiation if all else fails
                    if not opened and settings_dialog_cls:
                        try:
                            dlg = settings_dialog_cls(gm.mainFrame, initialCategory=HeadlessPlayerSettingsPanel)
                            dlg.ShowModal()
                            dlg.Destroy()
                            opened = True
                        except Exception as e_dlg:
                            logger.debug("Direct NVDASettingsDialog instantiation failed: %s", e_dlg)

            except Exception as e:
                logger.error("Failed to open HeadlessPlayer settings panel: %s", e, exc_info=True)

            if has_gui and not opened:
                logger.warning("Could not launch NVDA settings dialog; notifying user")
                if hasattr(self, "speech") and self.speech:
                    self.speech.speak(_("Could not open settings dialog"))

        # Exit player mode first so user has full keyboard access
        self._exit_player_mode_for_dialog()

        wx_mod = sys.modules.get("wx", wx)
        if wx_mod is not None and hasattr(wx_mod, "CallAfter"):
            try:
                wx_mod.CallAfter(_do_open)
            except Exception:
                _do_open()
        else:
            _do_open()

    open_settings_dialog = open_settings

    # -------------------------------------------------------------------------
    # Recent Media History Navigation (Delegated to RecentsManager)
    # -------------------------------------------------------------------------

    def is_recents_focus_active(self) -> bool:
        """Returns True if the user is currently actively browsing the recents list."""
        return self.recents_manager.is_focus_active()

    def cancel_recents_focus(self) -> None:
        """Exits recents browsing mode."""
        self.recents_manager.cancel_focus()

    def clear_recents_focus(self) -> None:
        """Exits recents browsing mode."""
        self.recents_manager.clear_focus()

    def recent_playlist_next(self) -> None:
        """Ctrl + .: Move forward (towards newer / end) in recent playlists."""
        self.recents_manager.playlist_next()

    recent_container_next = recent_playlist_next

    def recent_playlist_prev(self) -> None:
        """Ctrl + ,: Move backward (towards older / start) in recent playlists."""
        self.recents_manager.playlist_prev()

    recent_container_prev = recent_playlist_prev

    def recent_playlist_first(self) -> None:
        """Ctrl + Shift + ,: Jump to first / oldest playlist in recent history."""
        self.recents_manager.playlist_first()

    recent_container_first = recent_playlist_first

    def recent_playlist_last(self) -> None:
        """Ctrl + Shift + .: Jump to last / newest playlist in recent history."""
        self.recents_manager.playlist_last()

    recent_container_last = recent_playlist_last

    def recent_track_next(self) -> None:
        """.: Move forward (towards newer / end) in recent tracks."""
        self.recents_manager.track_next()

    def recent_track_prev(self) -> None:
        """,: Move backward (towards older / start) in recent tracks."""
        self.recents_manager.track_prev()

    def recent_track_first(self) -> None:
        """Shift + ,: Jump to first / oldest track in recent history."""
        self.recents_manager.track_first()

    def recent_track_last(self) -> None:
        """Shift + .: Jump to last / newest track in recent history."""
        self.recents_manager.track_last()

    def _navigate_recents(self, category: str, delta: int) -> None:
        self.recents_manager.navigate(category, delta)

    def _jump_recents(self, category: str, to_oldest: bool) -> None:
        self.recents_manager.jump(category, to_oldest)

    def recent_play_focused(self) -> bool:
        """Plays the currently focused item from recents browsing."""
        return self.recents_manager.play_focused()

    def recent_open_focused(self) -> bool:
        """Opens/browses the currently focused recent item (e.g. opens search dialog for search results)."""
        return self.recents_manager.open_focused()

    recent_activate_focused = recent_open_focused

    def recent_delete_focused(self) -> bool:
        """Removes the currently focused recent item from the database."""
        return self.recents_manager.delete_focused()


    def close_player(self) -> None:
        """
        Completely closes and stops the media player:
        1. Saves current playback session if enabled.
        2. Stops mpv playback and releases media resources.
        3. Shuts down / terminates background engine process.
        4. Clears active playlist queue.
        5. Exits Player Mode and announces 'Player closed'.
        """
        with self._lock:
            if hasattr(self, "history_sync") and self.history_sync:
                self.history_sync.stop_session(reason="stop")
            if getConfigValue("rememberPlaybackState", False):
                self.save_session()
            else:
                self.state_store.clear_last_session()
            self.save_current_position()
            self.engine.stop()
            self.engine.shutdown()
            self.playlist.clear()
            self._last_loaded_path = ""
            self._current_stream_chapters = []
            if self.input_layer:
                self.input_layer.set_player_mode(False, announce=False)
            self.speech.announce_player_closed()

    def _on_sponsor_skipped(self, category: str, start: float, end: float) -> None:
        """Invoked when engine automatically skips a SponsorBlock segment."""
        logger.info("Controller: SponsorBlock skipped %s segment [%.2f -> %.2f]", category, start, end)
        self.speech.announce_sponsor_skipped(category)

    def _load_sponsor_segments_for_url(self, url: str) -> None:
        """Fetches SponsorBlock skip segments asynchronously for YouTube URLs/IDs."""
        if not self.engine:
            return
        self.engine.clear_sponsor_segments()
        if not getConfigValue("sponsorBlockEnabled", True):
            return

        video_id = extract_youtube_id(url)
        if not video_id:
            return

        current_gen = self._stream_play_generation

        def worker(vid: str, gen: int) -> None:
            try:
                cats_str = str(getConfigValue("sponsorBlockCategories", "sponsor,selfpromo,interaction,intro,outro"))
                cats = [c.strip() for c in cats_str.split(",") if c.strip()]
                segs = fetch_sponsor_segments(vid, categories=cats)
                with self._lock:
                    if gen != self._stream_play_generation:
                        return
                    if segs and self.engine:
                        self.engine.set_sponsor_segments(segs)
            except Exception as e:
                logger.debug("Error in SponsorBlock worker for %s: %s", vid, e)

        threading.Thread(target=worker, args=(video_id, current_gen), daemon=True, name="HeadlessPlayer-SponsorBlock").start()

    def load_from_explorer(self) -> None:
        """Extracts active selection from Windows Explorer and loads into playlist."""
        paths = get_active_explorer_or_focus_paths(filter_supported=True, expand_folders=True)
        if not paths:
            self.speech.announce_no_explorer_selection()
            return

        with self._lock:
            if len(paths) == 1 and os.path.isfile(paths[0]):
                target_path = os.path.normcase(os.path.abspath(paths[0]))
                cur_track = self.playlist.get_current_track()
                cur_path = os.path.normcase(os.path.abspath(cur_track.path)) if (cur_track and cur_track.path) else None

                # If the exact same file is already loaded and active in the player:
                if cur_path == target_path and self.engine.is_running:
                    self.engine.seek_absolute(0.0)
                    if getattr(self.engine, "paused", False):
                        self.engine.play()
                    self.speech.announce_playback_restarted()
                    return

                first_track = self.playlist.load_file_with_folder(paths[0], append=False)
                if first_track:
                    self.speech.announce_loaded_files(self.playlist.count, total_duration=self.playlist.total_duration)
                    self.play_track(first_track)
                    self._check_auto_enter_player_mode()
                else:
                    self.speech.announce_no_explorer_selection()
            else:
                count = self.playlist.load_paths(paths, append=False)
                if count > 0:
                    self.speech.announce_loaded_files(count, total_duration=self.playlist.total_duration)
                    first_track = self.playlist.get_current_track()
                    if first_track:
                        self.play_track(first_track)
                        self._check_auto_enter_player_mode()
                else:
                    self.speech.announce_no_explorer_selection()

    # -------------------------------------------------------------------------
    # YouTube & Online Streaming (U key)
    # -------------------------------------------------------------------------

    def _exit_player_mode_for_dialog(self) -> None:
        """
        Fully exits Player Mode before presenting an interactive dialog,
        so the dialog opens immediately without needing Escape first.
        Player Mode re-activates automatically when playback starts
        (autoEnterPlayerMode).
        """
        if self.input_layer and self.input_layer.is_active:
            self.input_layer.set_player_mode(False, announce=False)

    def _check_streaming_available(self) -> bool:
        """Verifies the yt-dlp engine is usable, speaking an accurate reason if not."""
        if stream_engine.is_available():
            return True
        if sys.version_info < (3, 10):
            self.speech.speak(_(
                "Online streaming is unavailable. It requires NVDA 2024.1 or later."
            ))
        else:
            self.speech.speak(_(
                "The streaming engine failed to load. "
                "Try updating it from HeadlessPlayer settings."
            ))
        return False

    def open_url_dialog(self) -> None:
        """
        Opens the URL / YouTube search entry box (U key in Player Mode).
        Accepts a YouTube URL, any supported website URL, or free text to
        search YouTube interactively. Player Mode exits automatically so
        the box is immediately ready for typing.
        """
        if not self._check_streaming_available():
            return

        self._exit_player_mode_for_dialog()

        prompt_url_input(
            on_submit=self._on_url_or_search_submitted,
            on_cancelled=None,
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
        )

    def _canonical_current_track_path(self) -> Optional[str]:
        """Returns the stable, canonical URL or file path for the active track, never an ephemeral proxy URL."""
        cur_track = self.playlist.get_current_track()
        cand = (cur_track.path if (cur_track and cur_track.path) else None) or self._last_loaded_path
        if cand and not ("127.0.0.1" in str(cand) or "localhost" in str(cand)):
            return str(cand).strip()
        eng_path = getattr(self.engine, "path", None)
        if eng_path and not ("127.0.0.1" in str(eng_path) or "localhost" in str(eng_path)):
            return str(eng_path).strip()
        if cur_track and hasattr(cur_track, "metadata"):
            meta_id = cur_track.metadata.get("id")
            if meta_id:
                return f"https://www.youtube.com/watch?v={meta_id}"
        return None

    def _copy_to_clipboard(self, target: str) -> bool:
        """Copies file (CF_HDROP + CF_UNICODETEXT) or URL to the Windows clipboard."""
        return copy_to_clipboard(target)

    def copy_current_url(self) -> None:
        """
        Copies the current track's source URL (for online streams) or its
        file path (for local files) to the Windows clipboard (V key).
        For local files, places both CF_HDROP (file object) and CF_UNICODETEXT
        onto the clipboard so pasting in WhatsApp/Telegram/Explorer pastes the FILE.
        Never copies internal/ephemeral localhost proxy URLs.
        """
        cur = self.playlist.get_current_track()
        target_path = self._canonical_current_track_path()
        if not target_path:
            self.speech.speak(_("Nothing is currently loaded."))
            return

        if target_path.startswith("youtube:"):
            vid = target_path.split(":", 1)[1]
            target_path = f"https://www.youtube.com/watch?v={vid}"

        copied = self._copy_to_clipboard(target_path)
        if copied:
            is_stream = bool(
                (cur and getattr(cur, "is_stream", False))
                or target_path.startswith(("http://", "https://", "ytdl://", "custom://"))
            )
            if is_stream:
                self.speech.speak(_("Link copied to clipboard."))
            else:
                self.speech.speak(_("File and path copied to clipboard."))
        else:
            self.speech.speak(_("Could not copy to clipboard."))

    def _speak_async(self, text: str) -> None:
        wx_mod = sys.modules.get("wx", wx)
        if wx_mod is not None and hasattr(wx_mod, "CallAfter"):
            try:
                wx_mod.CallAfter(self.speech.speak, text)
            except Exception:
                self.speech.speak(text)
        else:
            self.speech.speak(text)

    def copy_direct_url(self) -> None:
        """Shift+V: copies the direct audio media link of the playing online item."""
        cur = self.playlist.get_current_track()
        if not cur or not getattr(cur, "is_stream", False):
            self.speech.speak(_("No online stream is playing."))
            return
        info = self._current_stream_info or {}
        url = str(info.get("direct_url") or "")
        if not url or (info.get("webpage_url") and info.get("id") and info.get("id") not in cur.path):
            try:
                info = stream_engine.resolve_stream(cur.path)
                url = str(info.get("direct_url") or "")
            except Exception as e:
                logger.error("copy_direct_url resolve failed: %s", e)
                url = ""
        if not url:
            url = str(info.get("stream_url") or "")
            if url.startswith("http://127.0.0.1"):
                url = ""
        if not url:
            self.speech.speak(_("The direct audio link is not available yet."))
            return
        if self._copy_to_clipboard(url):
            self.speech.speak(_("Direct audio link copied to clipboard."))
        else:
            self.speech.speak(_("Could not copy to clipboard."))

    # -------------------------------------------------------------------------
    # Clip Exporter & Encoding (Delegated to ExportCoordinator)
    # -------------------------------------------------------------------------

    def _export_range(self) -> Tuple[Optional[float], Optional[float], str]:
        """Returns (start, end, scenario): both points, A + current position as B, or nothing selected."""
        return self.export_coordinator.export_range()

    def _export_source(self, cur: Any) -> Any:
        return self.export_coordinator.export_source(cur)

    def export_clip(self) -> None:
        """D key: opens the Clip Exporter for the A-B selection or full item."""
        self.export_coordinator.export_clip()

    def quick_export(self) -> None:
        """Shift+D: exports the A-B selection immediately with remembered settings."""
        self.export_coordinator.quick_export()

    def _run_export(self, source: Any, settings: Dict[str, Any], start: Optional[float], end: Optional[float], filename: str, folder: str) -> None:
        self.export_coordinator.run_export(source, settings, start, end, filename, folder)


    def open_account_feed(self) -> None:
        """
        Opens the YouTube account browser (P key): recommendations,
        subscriptions, watch later, liked videos, history, and trending -
        presented in the same interactive results list used for search.
        Personal sections require sign-in cookies enabled in settings.
        """
        if not self._check_streaming_available():
            return

        self._exit_player_mode_for_dialog()

        items = stream_engine.get_account_sections()
        show_results_dialog(
            _("YouTube Account & Feeds"),
            items,
            self,
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
            is_playlist_context=False,
        )

    def _on_url_or_search_submitted(self, text: str) -> None:
        threading.Thread(
            target=self._handle_url_or_search,
            args=(text,),
            daemon=True,
            name="HeadlessPlayer-UrlSearch"
        ).start()

    def _handle_url_or_search(self, text: str) -> None:
        """Background worker: classifies the U-box input and acts on it."""
        cfg = getConfig()
        try:
            extracted_url = stream_engine.extract_url(text)
            if extracted_url:
                url = extracted_url
                self.speech.speak(_("Loading URL, please wait..."))
                limit = int(cfg.get("maxStreamPlaylistItems", 50))
                title, items, is_multi = stream_engine.probe_url(url, limit=limit)

                if is_multi:
                    videos = [
                        it for it in items
                        if getattr(it, "kind", "") in (stream_engine.ITEM_VIDEO, stream_engine.ITEM_SHORTS)
                    ]
                    if videos and len(videos) == len(items):
                        # Pure playlist: queue it and track source_target for auto-extension
                        self.play_stream_items(videos, start_index=0, listing_title=title, source_target=url, source_type="listing", batch_size=limit)
                    else:
                        # Mixed listing (e.g. channel root): open the browser dialog
                        show_results_dialog(
                            title or url,
                            items,
                            self,
                            suspend_capture=self._suspend_input,
                            resume_capture=self._resume_input,
                            is_playlist_context=bool(videos),
                            source_type="listing",
                            source_target=url,
                            batch_size=limit,
                        )
                else:
                    self.play_stream_items(items, start_index=0, listing_title=title)
            else:
                # Free text: interactive YouTube search
                self.speech.speak(_("Searching YouTube, please wait..."))
                limit = int(cfg.get("searchResultsCount", 20))
                log_debug("CONTROLLER", "Interactive YouTube search started: text='%s', limit=%d", text, limit)
                results = stream_engine.search_youtube(text, limit=limit)
                log_debug("CONTROLLER", "Interactive YouTube search finished: %d results found", len(results) if results else 0)
                if not results:
                    self.speech.speak(_("No results found."))
                    return
                show_results_dialog(
                    _("YouTube results for: %s") % text,
                    results,
                    self,
                    suspend_capture=self._suspend_input,
                    resume_capture=self._resume_input,
                    is_playlist_context=False,
                    source_type="search",
                    source_target=text,
                    batch_size=limit,
                )
        except Exception as e:
            logger.error("URL/search handling failed: %s", e, exc_info=True)
            log_exception("CONTROLLER", f"URL/search handling failed for text='{text}'", e)
            self.speech.speak(self._stream_error_message(e))

    def _stream_error_message(self, exc: Exception) -> str:
        """Builds an accurate spoken error message for a streaming failure."""
        if stream_engine.is_cookie_error(str(exc)):
            return _(
                "Could not read sign-in cookies from your browser. "
                "Set a manual cookies.txt file in HeadlessPlayer settings instead."
            )
        return _(
            "Operation failed. Check your internet connection, "
            "or update yt-dlp from HeadlessPlayer settings."
        )

    def play_stream_items(
        self,
        items: Sequence[Any],
        start_index: int = 0,
        listing_title: str = "",
        source_target: Optional[str] = None,
        source_url: Optional[str] = None,
        source_type: str = "listing",
        batch_size: Optional[int] = None,
    ) -> bool:
        """
        Queues a sequence of online StreamItems as the active playlist
        (behaving exactly like a local folder queue) and starts playback.
        """
        target = source_target or source_url

        playable_items = [
            it for it in items
            if getattr(it, "kind", "") in (stream_engine.ITEM_VIDEO, stream_engine.ITEM_SHORTS)
            or getattr(it, "is_stream", False)
            or (not getattr(it, "kind", "") and (hasattr(it, "url") or hasattr(it, "path")))
        ]
        if not playable_items:
            self.speech.speak(_("No playable items found."))
            return False

        # Recompute start index within the filtered playable list
        if 0 <= start_index < len(items) and items[start_index] in playable_items:
            start_index = playable_items.index(items[start_index])
        else:
            start_index = max(0, min(start_index, len(playable_items) - 1))

        tracks = []
        for it in playable_items:
            meta = dict(getattr(it, "metadata", {}) or {})
            meta.update({"is_live": bool(getattr(it, "is_live", False)), "listing": listing_title})
            tracks.append(
                Track(
                    path=getattr(it, "url", None) or getattr(it, "path", ""),
                    title=getattr(it, "title", ""),
                    duration=getattr(it, "duration", None),
                    metadata=meta,
                )
            )

        with self._lock:
            first = self.playlist.load_stream_tracks(tracks, start_index=start_index, append=False)
            if target:
                self._active_stream_source_target = target
                self._active_stream_source_url = target
                self._active_stream_source_type = source_type
                self._active_stream_next_idx = len(items) + 1
                self._active_stream_batch_size = batch_size or len(items) or 50
                self._active_stream_has_more = True
                self._active_stream_fetching = False
            else:
                self._active_stream_source_target = None
                self._active_stream_source_url = None
                self._active_stream_source_type = "listing"
                self._active_stream_has_more = False

        if not first:
            self.speech.speak(_("No playable items found."))
            return False

        if target and len(tracks) > 1:
            try:
                db = get_db_manager()
                db.save_recent_container(
                    path=target,
                    title=listing_title or target,
                    container_type="search" if source_type == "search" else "playlist"
                )
            except Exception as e:
                logger.debug("Error saving recent playlist container: %s", e)

        if len(tracks) > 1:
            self.speech.announce_loaded_files(len(tracks), total_duration=self.playlist.total_duration)
        res = self.play_track(first)

        self._check_auto_enter_player_mode()
        return res

    def play_search_as_playlist(self, query: str) -> None:
        """
        Searches YouTube in the background for query and plays the results directly
        as a continuous stream playlist without opening any GUI dialog.
        """
        if not query:
            return
        self.speech.speak(_("Searching YouTube, please wait..."))

        def worker() -> None:
            try:
                cfg = getConfig()
                limit = int(cfg.get("searchResultsCount", 20))
                results = stream_engine.search_youtube(query, limit=limit)
                if not results:
                    self.speech.speak(_("No results found."))
                    return
                lvl_items = [
                    it for it in results
                    if getattr(it, "kind", "") in (stream_engine.ITEM_VIDEO, stream_engine.ITEM_SHORTS)
                ]
                if not lvl_items:
                    lvl_items = results
                self.play_stream_items(
                    lvl_items,
                    start_index=0,
                    listing_title=_("YouTube results for: %s") % query,
                    source_target=query,
                    source_type="search",
                    batch_size=limit,
                )
            except Exception as e:
                logger.error("Error playing search playlist for '%s': %s", query, e, exc_info=True)
                self.speech.speak(self._stream_error_message(e))

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-PlaySearchPlaylist").start()

    def open_search_dialog(self, query: str) -> None:
        """
        Asynchronously searches YouTube in background thread and opens results dialog
        without blocking the NVDA keyboard hook thread.
        """
        if not query:
            return
        threading.Thread(
            target=self._handle_url_or_search,
            args=(query,),
            daemon=True,
            name="HeadlessPlayer-OpenSearchDialog"
        ).start()

    def play_stream_listing(self, url: str, listing_title: str = "") -> None:
        """
        Loads an online playlist or channel stream URL in the background,
        initializes the active stream source for seamless auto-paging,
        and starts playback.
        """
        self.speech.speak(_("Loading playlist, please wait..."))

        def worker() -> None:
            try:
                cfg = getConfig()
                limit = int(cfg.get("maxStreamPlaylistItems", 50))
                title, items = stream_engine.fetch_listing(url, limit=limit, start_index=1)
                self.play_stream_items(
                    items,
                    start_index=0,
                    listing_title=title or listing_title,
                    source_target=url,
                    source_type="listing",
                    batch_size=limit,
                )
            except Exception as e:
                logger.error("Playlist expansion failed: %s", e, exc_info=True)
                self.speech.speak(self._stream_error_message(e))

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-PlayListing").start()

    def _check_stream_queue_auto_extend(self) -> None:
        """Asynchronously loads the next batch of tracks for an active online playlist/listing or search query."""
        with self._lock:
            target = getattr(self, "_active_stream_source_target", None) or getattr(self, "_active_stream_source_url", None)
            stype = getattr(self, "_active_stream_source_type", "listing")
            has_more = getattr(self, "_active_stream_has_more", False)
            fetching = getattr(self, "_active_stream_fetching", False)
            if not target or not has_more or fetching:
                return
            # A purely local playlist must never auto-extend from online sources
            if not any(getattr(t, "is_stream", False) for t in self.playlist._tracks):
                self._active_stream_source_target = None
                self._active_stream_source_url = None
                self._active_stream_has_more = False
                return
            count = self.playlist.count
            if count >= 500:
                self._active_stream_has_more = False
                return
            cur_orig = self.playlist.original_index
            if count == 0 or cur_orig < max(0, count - 10):
                return
            self._active_stream_fetching = True
            start_idx = self._active_stream_next_idx
            bsize = self._active_stream_batch_size

        def worker() -> None:
            try:
                if stype == "search":
                    new_items = stream_engine.search_youtube(target, limit=bsize, start_index=start_idx)
                else:
                    _title, new_items = stream_engine.fetch_listing(target, limit=bsize, start_index=start_idx)

                playable = [
                    it for it in new_items
                    if getattr(it, "kind", "") in (stream_engine.ITEM_VIDEO, stream_engine.ITEM_SHORTS)
                    or getattr(it, "is_stream", False)
                    or (not getattr(it, "kind", "") and (hasattr(it, "url") or hasattr(it, "path")))
                ]
                with self._lock:
                    current_target = getattr(self, "_active_stream_source_target", None) or getattr(self, "_active_stream_source_url", None)
                    if current_target == target:
                        if not playable:
                            self._active_stream_has_more = False
                        else:
                            new_tracks = []
                            for it in playable:
                                meta = dict(getattr(it, "metadata", {}) or {})
                                meta.update({"is_live": bool(getattr(it, "is_live", False))})
                                new_tracks.append(
                                    Track(
                                        path=getattr(it, "url", None) or getattr(it, "path", ""),
                                        title=getattr(it, "title", ""),
                                        duration=getattr(it, "duration", None),
                                        metadata=meta,
                                    )
                                )
                            self.playlist.load_stream_tracks(new_tracks, append=True)
                            self._active_stream_next_idx = start_idx + len(new_items)
                            # has_more: True only if we got a full page
                            self._active_stream_has_more = len(new_items) >= bsize
            except Exception as ex:
                logger.debug("Stream queue auto-extend failed (%s, target=%s): %s", stype, target, ex)
            finally:
                with self._lock:
                    self._active_stream_fetching = False

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-QueueExtend").start()

    def _play_stream_track(self, track: Track) -> bool:
        """
        Starts asynchronous resolution and playback of an online stream track.
        The direct audio URL is (re)extracted at play time so links never expire.
        """
        with self._lock:
            # If this exact track is already resolving in background, debounce and do not spawn duplicate threads
            if getattr(self, "_is_resolving_stream", False) and getattr(self, "_resolving_track_path", None) == track.path:
                self.speech.speak(_("Loading stream, please wait..."))
                return True

            self._is_resolving_stream = True
            self._resolving_track_path = track.path

            if self._last_loaded_path and self._last_loaded_path != track.path:
                self.save_current_position(target_path=self._last_loaded_path)

            self._stream_play_generation += 1
            generation = self._stream_play_generation
            self._current_stream_chapters = list(getattr(track, "chapters", [])) if getattr(track, "chapters", None) else []

            if self._pending_resume_pos is None or self._pending_resume_pos < 0.5:
                cfg = getConfig()
                if cfg.get("resumePosition", True) and not track.metadata.get("is_live"):
                    saved_pos = self.state_store.get_position(
                        track.path,
                        current_duration=getattr(track, "duration", None)
                    )
                    self._pending_resume_pos = saved_pos if (saved_pos and saved_pos >= 1.0) else None
                else:
                    self._pending_resume_pos = None

            self._last_loaded_path = track.path

            orig_idx = self.playlist.current_index + 1
            total = self.playlist.count

        self.speech.speak(_("Loading: %s") % track.display_name)
        threading.Thread(
            target=self._resolve_and_play_stream,
            args=(track, generation, orig_idx, total),
            daemon=True,
            name="HeadlessPlayer-StreamResolve"
        ).start()
        return True

    def _resolve_and_play_stream(self, track: Track, generation: int, orig_idx: int, total: int) -> None:
        """Background worker: resolves the stream URL then loads it into mpv."""
        with self._lock:
            if generation != self._stream_play_generation or self._is_terminating:
                return

        try:
            info = stream_engine.resolve_stream(track.path)
        except Exception as e:
            logger.error("Stream resolution failed for %s: %s", track.path, e)
            with self._lock:
                stale = generation != self._stream_play_generation
                if not stale:
                    self._is_resolving_stream = False
                    self._resolving_track_path = None
            if not stale:
                self.engine.stop()
                if stream_engine.is_cookie_error(str(e)):
                    self.speech.speak(self._stream_error_message(e))
                else:
                    self.speech.speak(_(
                        "Could not play this stream. Check your internet connection, "
                        "or update yt-dlp from HeadlessPlayer settings."
                    ))
            return

        with self._lock:
            if generation != self._stream_play_generation or self._is_terminating:
                return

            self._is_resolving_stream = False
            self._resolving_track_path = None

            # Enrich track metadata from the full extraction
            if info.get("title") and (not track.title or track.title == track.path):
                track.title = info["title"]
            if info.get("duration"):
                track.duration = float(info["duration"])
            if info.get("is_live"):
                track.metadata["is_live"] = True
                self._pending_resume_pos = None

            if info.get("chapters"):
                track.chapters = list(info["chapters"])
                track.metadata["chapters"] = list(info["chapters"])
                self._current_stream_chapters = list(info["chapters"])
            else:
                self._current_stream_chapters = []

            success = self.engine.load_stream(info["stream_url"], info.get("http_headers"))
            if success:
                self.state_store.save_recent_file(track.path)
                self._load_sponsor_segments_for_url(track.path or info.get("webpage_url") or info.get("id"))

                self._current_stream_info = dict(info)
                self._stream_audio_tracks = list(info.get("audio_tracks", []))
                self._stream_audio_track_idx = 0
                self.speech.announce_track(orig_idx, total, track.display_name)
                self._check_stream_queue_auto_extend()
                self._prefetch_next_stream_track()
            else:
                self.speech.speak(_("Playback engine failed to start."))

    def _prefetch_next_stream_track(self) -> Optional[threading.Thread]:
        """
        Asynchronously pre-resolves the next online stream track in background.
        Primes stream_engine._resolve_cache so advancing tracks (PageDown / Tab)
        starts instantly with zero network delay.
        """
        with self._lock:
            if not self.playlist or self.playlist.is_empty():
                return None
            cur_idx = self.playlist.current_index
            total = self.playlist.count
            if cur_idx + 1 >= total:
                return None
            next_t = self.playlist.get_track_at(cur_idx + 1)
            if not next_t or not getattr(next_t, "is_stream", False) or not next_t.path:
                return None
            target_path = next_t.path

        def worker(path: str) -> None:
            try:
                stream_engine.resolve_stream(path)
            except Exception as e:
                logger.debug("Background stream pre-fetch ignored error for %s: %s", path, e)

        t = threading.Thread(
            target=worker,
            args=(target_path,),
            daemon=True,
            name="HeadlessPlayer-StreamPrefetch"
        )
        t.start()
        if "unittest" in sys.modules:
            t.join(timeout=0.2)
        return t

    def _current_track_is_live_stream(self, path: Optional[str] = None) -> bool:
        if path:
            for t in getattr(self.playlist, "_tracks", []):
                if getattr(t, "path", None) == path:
                    return bool(getattr(t, "is_stream", False) and getattr(t, "metadata", {}).get("is_live"))
        cur = self.playlist.get_current_track()
        return bool(cur and getattr(cur, "is_stream", False) and cur.metadata.get("is_live"))

    def _on_file_selected(self, file_path: str) -> None:
        """Callback when user selects a file in open file dialog."""
        if not file_path or not os.path.exists(file_path):
            return

        folder_dir = os.path.dirname(os.path.abspath(file_path))
        if os.path.isdir(folder_dir):
            self.state_store.save_setting("last_browse_dir", folder_dir)

        with self._lock:
            track = self.playlist.load_file_with_folder(file_path, append=False)
            if track:
                self.speech.announce_loaded_files(self.playlist.count, total_duration=self.playlist.total_duration)
                self.play_track(track)
                self._check_auto_enter_player_mode()

    def _on_folder_selected(self, folder_path: str) -> None:
        """Callback when user selects a folder in folder browser dialog."""
        if not folder_path or not os.path.isdir(folder_path):
            return

        self.state_store.save_setting("last_browse_dir", os.path.abspath(folder_path))

        with self._lock:
            count = self.playlist.load_folder(folder_path, recursive=False, append=False)
            if count > 0:
                try:
                    db = get_db_manager()
                    db.save_recent_playlist(path=folder_path, container_type="folder")
                except Exception as e:
                    logger.debug("Error saving recent folder playlist: %s", e)
                self.speech.announce_loaded_files(count, total_duration=self.playlist.total_duration)
                first_track = self.playlist.get_current_track()
                if first_track:
                    self.play_track(first_track)
                    self._check_auto_enter_player_mode()
            else:
                self.speech.announce_no_media_in_folder()

    def load_folder(self, folder_path: str) -> None:
        """Loads and plays an entire folder."""
        self._on_folder_selected(folder_path)

    def load_file(self, file_path: str) -> None:
        """Loads and plays a single media file."""
        self._on_file_selected(file_path)

    def _suspend_input(self) -> None:
        if self.input_layer:
            self.input_layer.suspend()

    def _resume_input(self) -> None:
        if self.input_layer:
            self.input_layer.resume()

    def _check_auto_enter_player_mode(self) -> None:
        """Enters Player Mode if autoEnterPlayerMode setting is True."""
        cfg = getConfig()
        if cfg.get("autoEnterPlayerMode", True) and self.input_layer:
            if not self.input_layer.is_active:
                self.input_layer.set_player_mode(True, announce=True)

    # -------------------------------------------------------------------------
    # Position Resume & State Storage
    # -------------------------------------------------------------------------

    def save_current_position(self, target_path: Optional[str] = None) -> None:
        """Saves active playback position to the persistent StateStore."""
        # The position in the mpv engine belongs strictly to what is currently loaded in the engine!
        track_path = target_path or self._last_loaded_path
        if not track_path:
            track_path = self._canonical_current_track_path()
        if not track_path:
            return

        # Never persist positions for live streams (they have no fixed timeline)
        if self._current_track_is_live_stream(track_path):
            return

        # If track_path is an internal localhost proxy URL, resolve to canonical ID/URL
        if "127.0.0.1" in str(track_path) or "localhost" in str(track_path):
            canonical = self._canonical_current_track_path()
            if canonical and not ("127.0.0.1" in str(canonical) or "localhost" in str(canonical)):
                track_path = canonical
            else:
                return

        pos = getattr(self.engine, "time_pos", 0.0)
        dur = getattr(self.engine, "duration", None)

        if pos and pos > 0:
            self.state_store.save_position(
                file_path=track_path,
                position_sec=pos,
                duration_sec=dur
            )

    def save_session(self) -> None:
        """
        Saves current playback session (playlist queue, current index, playback position,
        shuffle, repeat mode, auto-next, and stream metadata) into state_store.
        """
        with self._lock:
            if self.playlist.is_empty():
                return
            cur_pos = getattr(self.engine, "time_pos", 0.0) or 0.0
            if cur_pos <= 0.0 and self._pending_resume_pos and self._pending_resume_pos >= 0.5:
                cur_pos = self._pending_resume_pos
            if cur_pos <= 0.0:
                cur_track = self.playlist.get_current_track()
                if cur_track and cur_track.path:
                    saved = self.state_store.get_position(cur_track.path)
                    if saved and saved >= 1.0:
                        cur_pos = saved
            st_target = getattr(self, "_active_stream_source_target", None)
            st_type = getattr(self, "_active_stream_source_type", "listing")
            if not any(getattr(t, "is_stream", False) for t in self.playlist._tracks):
                st_target = None
            tracks = [t.to_dict() if hasattr(t, "to_dict") else t.path for t in self.playlist._tracks]
            self.state_store.save_last_session(
                tracks=tracks,
                current_index=self.playlist.original_index,
                position=cur_pos,
                shuffle=self.playlist.shuffle,
                repeat_mode=self.playlist.repeat_mode.value,
                auto_next=self.playlist.auto_next,
                source_target=st_target,
                source_type=st_type
            )
            log_info("CONTROLLER", "Playback session saved: %d tracks, idx=%d, pos=%.2f",
                     len(tracks), self.playlist.original_index, cur_pos)

    def restore_session(self, auto_play: bool = False) -> bool:
        """
        Restores the last saved playback session (tracks, position, queue, stream metadata).
        Returns True if a session was successfully restored, False otherwise.
        """
        with self._lock:
            if not self.playlist.is_empty():
                return False
            st = self.state_store.get_last_session()
            if not st:
                return False
            tracks_data = st.get("tracks", [])
            if not tracks_data:
                return False

            self.playlist.from_dict(st)
            if self.playlist.is_empty():
                return False

            cur_track = self.playlist.get_current_track()
            if cur_track:
                self._last_loaded_path = cur_track.path
                self._current_stream_chapters = list(getattr(cur_track, "chapters", []))
                pos = float(st.get("position", 0.0))
                if pos >= 0.5:
                    self._pending_resume_pos = pos

            if st.get("source_target"):
                self._active_stream_source_target = st["source_target"]
                self._active_stream_source_url = st["source_target"]
                self._active_stream_source_type = st.get("source_type", "listing")
                self._active_stream_next_idx = len(tracks_data) + 1
                self._active_stream_batch_size = 50
                self._active_stream_has_more = True

            log_info("CONTROLLER", "Playback session restored: %d tracks, current_index=%d, pos=%.2f",
                     self.playlist.count, self.playlist.original_index, float(st.get("position", 0.0)))

            if auto_play and cur_track:
                self.play_track(cur_track)

            return True

    # -------------------------------------------------------------------------
    # Engine Event Handlers
    # -------------------------------------------------------------------------

    def _on_engine_file_loaded(self) -> None:
        """Fired when mpv finishes parsing a newly loaded media file."""
        with self._lock:
            self._is_resolving_stream = False
            self._resolving_track_path = None
            self._stream_auto_retries = 0
            self._active_native_chapter_idx = None
            self._active_stream_chapter_idx = None
            self._suppress_next_auto_chapter = False

            cur = self.playlist.get_current_track()
            if cur and (not cur.duration or cur.duration <= 0):
                dur = getattr(self.engine, "duration", None)
                if dur and dur > 0:
                    cur.duration = dur

            if cur and cur.path:
                try:
                    db = get_db_manager()
                    is_stream = bool(getattr(cur, "is_stream", False) or cur.path.startswith(("http://", "https://", "youtube:", "ytdl://", "custom://")))
                    parent_f = ""
                    if not is_stream and os.path.exists(cur.path):
                        parent_f = os.path.basename(os.path.dirname(os.path.abspath(cur.path)))
                    channel_info = ""
                    if hasattr(cur, "metadata") and isinstance(cur.metadata, dict):
                        channel_info = cur.metadata.get("channel") or cur.metadata.get("uploader") or ""
                    db.save_recent_track(
                        path=cur.path,
                        title=cur.title,
                        track_type="stream" if is_stream else "file",
                        parent_folder=parent_f,
                        platform_or_channel=channel_info
                    )
                except Exception as e:
                    logger.debug("Error saving recent track: %s", e)

            if self._pending_resume_pos is not None and self._pending_resume_pos >= 0.5:
                target = self._pending_resume_pos
                self._pending_resume_pos = None
                self.engine.seek_absolute(target)
                if not getattr(self, "_silence_resume_announcement", False):
                    self.speech.announce_resume_position(target)
                self._silence_resume_announcement = False

        if getattr(self, "_restore_last_session", True):
            self.save_session()


    def _on_engine_track_end(self, reason: str) -> None:
        """Fired when playback of current media item finishes."""
        threading.Thread(
            target=self._handle_track_end,
            args=(reason,),
            daemon=True,
            name="HeadlessPlayer-TrackEnd"
        ).start()

    def _handle_track_end(self, reason: str) -> None:
        """Asynchronously handles track completion to prevent IPC reader stalls."""
        if hasattr(self, "history_sync") and self.history_sync:
            self.history_sync.stop_session(reason="eof" if reason == "eof" else "stop")

        with self._lock:
            cur_path = self._last_loaded_path or getattr(self.engine, "path", None)
            cur_track = self.playlist.get_current_track()
            dur = getattr(self.engine, "duration", 0.0) or (cur_track.duration if cur_track else 0.0) or 0.0
            cur_pos = getattr(self.engine, "time_pos", 0.0) or 0.0
            is_stream = bool(cur_track and getattr(cur_track, "is_stream", False))

            if reason == "eof":
                # Check if playback finished cleanly or terminated prematurely
                is_clean_finish = False
                if dur > 15.0:
                    is_clean_finish = cur_pos >= max(0.0, dur - 8.0)
                elif dur > 0:
                    is_clean_finish = cur_pos >= max(0.0, dur - 3.0)
                elif not is_stream:
                    # Non-stream local media with unknown duration
                    is_clean_finish = True
                else:
                    # Stream with unknown duration or live stream:
                    # Do not treat as clean auto-next completion
                    is_clean_finish = False

                if is_clean_finish:
                    self._stream_auto_retries = 0
                    # Clear completed position in state store
                    if cur_path:
                        self.state_store.clear_position(cur_path)

                    # Coordinate auto-next or track repeat
                    next_t = self.playlist.on_track_ended()
                    if next_t:
                        self._last_loaded_path = None
                        self.play_track(next_t)
                        self._check_stream_queue_auto_extend()
                    else:
                        self._last_loaded_path = None
                else:
                    # Premature EOF (network drop, socket closure, demuxer stall)
                    logger.warning(
                        "Track '%s' ended prematurely at pos=%.2f / dur=%.2f (is_stream=%s, reason=%s)",
                        cur_path, cur_pos, dur, is_stream, reason
                    )
                    # Preserve playback position so progress is never lost
                    if cur_path and cur_pos > 0.5:
                        self.state_store.save_position(cur_path, cur_pos, dur)

                    if is_stream and cur_track:
                        auto_retries = getattr(self, "_stream_auto_retries", 0)
                        if auto_retries < 2:
                            self._stream_auto_retries = auto_retries + 1
                            logger.info(
                                "Auto-reconnecting stream for '%s' at %.2f (attempt %d/2)",
                                cur_track.display_name, cur_pos, self._stream_auto_retries
                            )
                            # Invalidate cached stream URL to force re-resolution with fresh token
                            try:
                                stream_engine.clear_resolve_cache()
                            except Exception:
                                pass
                            self._pending_resume_pos = cur_pos
                            self._silence_resume_announcement = True
                            self.speech.speak(_("Reconnecting..."))
                            self.play_track(cur_track)
                            return
                        else:
                            self._stream_auto_retries = 0
                            self.engine.stop()
                            self.speech.speak(_(
                                "Playback of this stream failed. Press Space to retry."
                            ))
                            return
                    else:
                        self.engine.stop()
                        self.speech.speak(_("Playback stopped."))
                        return

            elif reason in ("stop", "quit"):
                self.save_current_position()
            elif reason == "error":
                cur = self.playlist.get_current_track()
                if cur and getattr(cur, "is_stream", False):
                    # Drop the cached (bad/expired) stream URL so a retry
                    # performs a fresh extraction.
                    try:
                        stream_engine.clear_resolve_cache()
                    except Exception:
                        pass
                    self.speech.speak(_(
                        "Playback of this stream failed. Press Space to retry."
                    ))

    def _on_engine_property_change(self, name: str, data: Any) -> None:
        """Fired on mpv property change events (heartbeat auto-save and chapter transition announcements)."""
        # Periodic 60s session heartbeat auto-save
        if name == "time-pos" and data is not None:
            now = time.time()
            if getattr(self, "_restore_last_session", True) and (now - getattr(self, "_last_heartbeat_save_time", 0.0)) >= 60.0:
                self._last_heartbeat_save_time = now
                self.save_session()

        if not getConfigValue("announceChapterAuto", True):
            return

        if not self.speech.is_announcement_enabled("chapter"):
            return

        # 1. Native mpv container chapters
        if name == "chapter" and data is not None:
            try:
                ch_idx = int(data)
            except (ValueError, TypeError):
                return

            with self._lock:
                if self._suppress_next_auto_chapter:
                    self._suppress_next_auto_chapter = False
                    self._active_native_chapter_idx = ch_idx
                    return

                if self._active_native_chapter_idx is not None and ch_idx != self._active_native_chapter_idx:
                    self._active_native_chapter_idx = ch_idx
                    chap_num = ch_idx + 1
                    chap_info = self.engine.get_chapter_info(ch_idx) if hasattr(self.engine, "get_chapter_info") else None
                    title = chap_info.get("title") if chap_info else self.engine.get_current_chapter_title()
                    start_time = float(chap_info["time"]) if (chap_info and chap_info.get("time") is not None) else self.engine.get_current_chapter_start_time()
                    self.speech.announce_chapter(chap_num, title, start_time=start_time)
                else:
                    self._active_native_chapter_idx = ch_idx

        # 2. Extracted stream chapters for YouTube / online media
        elif name == "time-pos" and data is not None:
            chapters = getattr(self, "_current_stream_chapters", None)
            if not chapters:
                return

            try:
                pos = float(data)
            except (ValueError, TypeError):
                return

            cur_ch_idx = None
            for i in range(len(chapters) - 1, -1, -1):
                st = float(chapters[i].get("start_time", 0.0))
                if pos >= (st - 0.2):
                    cur_ch_idx = i
                    break

            if cur_ch_idx is None:
                cur_ch_idx = 0

            with self._lock:
                if self._suppress_next_auto_chapter:
                    self._suppress_next_auto_chapter = False
                    self._active_stream_chapter_idx = cur_ch_idx
                    return

                if self._active_stream_chapter_idx is not None and cur_ch_idx != self._active_stream_chapter_idx:
                    self._active_stream_chapter_idx = cur_ch_idx
                    target_ch = chapters[cur_ch_idx]
                    target_sec = float(target_ch.get("start_time", 0.0))
                    title = target_ch.get("title", f"Chapter {cur_ch_idx + 1}")
                    self.speech.announce_chapter(cur_ch_idx + 1, title, start_time=target_sec)
                elif self._active_stream_chapter_idx is None:
                    self._active_stream_chapter_idx = cur_ch_idx

    def _on_engine_playback_restart(self) -> None:
        """Fired when mpv restarts playback after seeking."""
        pass

    def _on_engine_seek(self) -> None:
        """Fired on mpv seek events."""
        pass


# Global singleton instance
_global_controller: Optional[PlayerController] = None
_controller_lock = threading.Lock()


def get_controller() -> Optional[PlayerController]:
    """Returns the global PlayerController singleton instance."""
    global _global_controller
    with _controller_lock:
        return _global_controller


def set_controller(instance: Optional[PlayerController]) -> None:
    """Sets or clears the global PlayerController singleton."""
    global _global_controller
    with _controller_lock:
        _global_controller = instance
