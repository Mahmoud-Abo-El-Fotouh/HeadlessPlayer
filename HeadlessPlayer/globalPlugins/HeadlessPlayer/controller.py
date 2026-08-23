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
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

try:
    from . import _  # type: ignore
except (ImportError, ValueError):
    try:
        _ = _  # type: ignore
    except NameError:
        _ = lambda text: text

from .engine import HeadlessEngine, SPEED_PRESETS
from .playlist import Playlist, Track, RepeatMode
from .state_store import StateStore, get_state_store
from .tones_helper import ToneCueManager, tone_manager
from .speech_feedback import SpeechFeedback, get_speech_feedback
from .input_layer import ModalInputLayer
from .config_spec import getConfig, getConfigValue, setConfigValue, saveConfig
from .dialog_utils import prompt_open_file_dialog, prompt_open_folder_dialog, prompt_help_dialog
from .explorer_utils import get_active_explorer_or_focus_paths
from .utils import format_time, is_supported_media_file

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
        tone_mgr: Optional[ToneCueManager] = None,
        speech_feedback: Optional[SpeechFeedback] = None,
        input_layer: Optional[ModalInputLayer] = None,
        pipe_name: Optional[str] = None
    ) -> None:
        self._lock = threading.RLock()

        # Component instances
        self.state_store: StateStore = state_store if state_store is not None else get_state_store()
        self.tone_manager: ToneCueManager = tone_mgr if tone_mgr is not None else tone_manager
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

    def _apply_config_to_input_layer(self, cfg: Dict[str, Any]) -> None:
        """Propagate seek/speed/volume step sizes to input_layer."""
        if not self.input_layer:
            return
        self.input_layer.seek_normal = float(cfg.get("seekStepNormal", 5.0))
        self.input_layer.seek_slow = float(cfg.get("seekStepSlow", 1.0))
        self.input_layer.seek_fast = float(cfg.get("seekStepFast", 30.0))
        self.input_layer.seek_ultrafast = float(cfg.get("seekStepUltrafast", 300.0))

    def on_config_updated(self, cfg: Dict[str, Any]) -> None:
        """Invoked when user updates settings in NVDA Preferences -> Settings panel."""
        with self._lock:
            self._apply_config_to_input_layer(cfg)
            if "defaultRepeatMode" in cfg:
                self.playlist.set_repeat_mode(cfg["defaultRepeatMode"])
            if "defaultAutoNext" in cfg:
                self.playlist.set_auto_next(cfg["defaultAutoNext"])
            if "defaultSpeed" in cfg:
                spd = float(cfg["defaultSpeed"])
                self.engine.speed = spd
                if self.engine.is_running:
                    self.engine.set_speed(spd)
                self.state_store.save_speed(spd)
            if "volume" in cfg:
                vol = float(cfg["volume"])
                self.engine.volume = vol
                if self.engine.is_running:
                    self.engine.set_volume(vol)
                self.state_store.save_volume(int(vol))
            if "playModalTones" in cfg and self.tone_manager:
                self.tone_manager.is_enabled = bool(cfg["playModalTones"])

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
            self.save_current_position()
            self.engine.shutdown()

    def terminate(self) -> None:
        """Full cleanup hook for plugin termination."""
        if hasattr(self.speech, "cancel_debounced_seek"):
            self.speech.cancel_debounced_seek()
        self.shutdown()

    # -------------------------------------------------------------------------
    # Core Playback Controls
    # -------------------------------------------------------------------------

    def toggle_pause(self) -> bool:
        """Toggles play / pause state and announces status. If media reached end, restarts from beginning."""
        with self._lock:
            if not self.engine.is_running:
                # If playlist has tracks, start playback
                cur_track = self.playlist.get_current_track()
                if cur_track:
                    self.play_track(cur_track)
                    return False
                return False

            # Engine running but idle (nothing loaded): Space should (re)start
            # the current track, never cycle mpv's pause flag into the void.
            if not getattr(self.engine, "is_loaded", False) and not getattr(self.engine, "path", None):
                cur_track = self.playlist.get_current_track()
                if cur_track:
                    self.play_track(cur_track)
                return False

            time_pos = getattr(self.engine, "time_pos", 0.0)
            duration = getattr(self.engine, "duration", 0.0)
            is_eof = getattr(self.engine, "eof_reached", False) or (duration > 0 and time_pos >= duration - 0.5)

            if is_eof:
                # Track finished/stopped at end: restart from beginning
                self.engine.seek_absolute(0.0)
                self.engine.set_property("pause", False)
                self.engine.is_paused = False
                self.speech.announce_playback_state("playing")
                return False

            new_pause = self.engine.toggle_pause()
            if new_pause:
                self.save_current_position()
                self.speech.announce_playback_state("paused")
            else:
                self.speech.announce_playback_state("playing")
            return new_pause

    def play(self) -> bool:
        """Explicitly starts or resumes playback."""
        with self._lock:
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
        """Stops playback, saves position, rewinds to start, and announces stopped."""
        with self._lock:
            if hasattr(self.speech, "cancel_debounced_seek"):
                self.speech.cancel_debounced_seek()
            if not self.engine.is_running:
                return False
            self.save_current_position()
            res = self.engine.stop()
            self.speech.announce_playback_state("stopped")
            return res

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

            # Boundary hits
            if target_pos <= 0.0:
                self.tone_manager.play_boundary_hit()
            elif dur > 0 and target_pos >= dur:
                self.tone_manager.play_boundary_hit()

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
            self.tone_manager.play_seek_click()
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
            self.tone_manager.play_seek_click()
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
                self.tone_manager.play_seek_click()
                self.speech.speak(_("Track end"))
                return res
            elif dur and dur > 0:
                res = self.engine.seek_absolute(dur)
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
            self.tone_manager.play_point_a()
            self.speech.announce_point_a(pos)
            return pos

    def set_ab_point_b(self) -> Tuple[float, bool]:
        """Marks Point B (end of A-B loop) with acoustic cue and speech announcement."""
        with self._lock:
            if not self.engine.is_running:
                return 0.0, False
            pos, is_valid = self.engine.set_ab_point_b()
            if is_valid:
                self.tone_manager.play_point_b()
                self.tone_manager.play_loop_active()
                self.speech.announce_point_b(pos)
                if self.engine.ab_loop_a is not None:
                    self.speech.announce_ab_loop_active(self.engine.ab_loop_a, pos)
            else:
                self.tone_manager.play_boundary_hit()
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

            # Check if A-B loop points are marked
            if self.engine.ab_loop_a is not None and self.engine.ab_loop_b is not None:
                res = self.engine.toggle_repeat()
                if res == "ab_loop_on":
                    self.tone_manager.play_loop_active()
                    self.speech.announce_ab_loop_active(self.engine.ab_loop_a, self.engine.ab_loop_b)
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
        """Jumps to next chapter and announces title/index."""
        with self._lock:
            if not self.engine.is_running:
                return False
            res = self.engine.next_chapter()
            if res:
                chap_num = self.engine.chapter + 1
                title = self.engine.get_current_chapter_title()
                self.speech.announce_chapter(chap_num, title)
            else:
                self.speech.announce_no_chapters()
            return res

    def prev_chapter(self) -> bool:
        """Jumps to previous chapter and announces title/index."""
        with self._lock:
            if not self.engine.is_running:
                return False
            res = self.engine.prev_chapter()
            if res:
                chap_num = max(1, self.engine.chapter + 1)
                title = self.engine.get_current_chapter_title()
                self.speech.announce_chapter(chap_num, title)
            else:
                self.speech.announce_no_chapters()
            return res

    def cycle_audio_track(self) -> bool:
        """Cycles audio tracks / language streams in video files."""
        with self._lock:
            if not self.engine.is_running:
                return False
            res = self.engine.cycle_audio_track()
            info = self.engine.get_current_audio_track_info()
            if info:
                t_id = info.get("id", 1)
                title = info.get("title")
                lang = info.get("lang")
                self.speech.announce_audio_track(t_id, title, lang)
            return res

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
            # Invalidate any in-flight online stream resolution
            self._stream_play_generation += 1
            # 1. Save playback position of previous track before loading the new one
            self.save_current_position()

            # 2. Target track to load
            target_path = track.path

            # 3. Retrieve saved position for THIS specific track
            cfg = getConfig()
            if cfg.get("resumePosition", True):
                saved_pos = self.state_store.get_position(target_path)
                if saved_pos and saved_pos >= 1.0:
                    self._pending_resume_pos = saved_pos
                else:
                    self._pending_resume_pos = None
            else:
                self._pending_resume_pos = None

            # 4. Update currently loaded path
            self._last_loaded_path = target_path

            # 5. Load into mpv engine (clearing any stream HTTP headers first)
            self.engine.set_http_headers(None)
            success = self.engine.load_file(target_path, append=False)
            if success:
                self.state_store.save_recent_file(target_path)

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
                return next_t
            else:
                # Boundary reached
                self.tone_manager.play_boundary_hit()
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
                self.tone_manager.play_boundary_hit()
                self.speech.announce_boundary(is_start=True)
                return None

    def jump_to_first_track(self) -> Optional[Track]:
        """Jumps directly to the first track in the playlist (Control + Home)."""
        with self._lock:
            if self.playlist.is_empty():
                self.tone_manager.play_boundary_hit()
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
                self.tone_manager.play_boundary_hit()
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
        """Speaks remaining playback time in formatted string."""
        with self._lock:
            rem = self.engine.get_remaining_time()
            dur = self.engine.get_duration()
            is_loaded = bool(self.engine.is_loaded or dur > 0)
            self.speech.speak_remaining_time(rem, duration=dur, is_loaded=is_loaded)

    def speak_elapsed_time(self) -> None:
        """Speaks elapsed playback time in formatted string."""
        with self._lock:
            el = self.engine.get_elapsed_time()
            dur = self.engine.get_duration()
            is_loaded = bool(self.engine.is_loaded or dur > 0)
            self.speech.speak_elapsed_time(el, is_loaded=is_loaded)

    # -------------------------------------------------------------------------
    # Dialogs & Windows Explorer Integration
    # -------------------------------------------------------------------------

    def _get_last_browse_dir(self) -> str:
        """Retrieves directory of the last played file or last browsed folder."""
        last_path = self._last_loaded_path
        if last_path and os.path.exists(last_path):
            if os.path.isdir(last_path):
                return os.path.abspath(last_path)
            return os.path.abspath(os.path.dirname(last_path))

        recent = self.state_store.get_recent_files()
        if recent:
            for r in recent:
                if os.path.exists(r):
                    return os.path.abspath(os.path.dirname(r) if os.path.isfile(r) else r)

        return os.path.expanduser("~")

    def on_config_updated(self, cfg: dict) -> None:
        """Called when user applies updated settings from NVDA Settings panel."""
        with self._lock:
            if "defaultAutoNext" in cfg:
                self.playlist.set_auto_next(bool(cfg["defaultAutoNext"]))
            if "defaultRepeatMode" in cfg:
                self.playlist.set_repeat_mode(str(cfg["defaultRepeatMode"]))
            if "defaultSpeed" in cfg and hasattr(self.engine, "set_speed"):
                try:
                    spd = float(cfg["defaultSpeed"])
                    if not self.engine.is_loaded:
                        self.engine.speed = spd
                except Exception:
                    pass

    def open_file_dialog(self) -> None:
        """Opens native file dialog to select and play a media file."""
        default_dir = self._get_last_browse_dir()
        prompt_open_file_dialog(
            on_file_selected=self._on_file_selected,
            on_cancelled=None,
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
            default_dir=default_dir
        )

    def open_folder_dialog(self) -> None:
        """Opens native folder browser dialog to queue and play an entire folder."""
        default_dir = self._get_last_browse_dir()
        prompt_open_folder_dialog(
            on_folder_selected=self._on_folder_selected,
            on_cancelled=None,
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
            default_dir=default_dir
        )

    def get_toggle_gesture_display(self) -> str:
        """Retrieves active toggle shortcut string dynamically from NVDA."""
        try:
            import globalPluginHandler
            for plugin in getattr(globalPluginHandler, "runningPlugins", []):
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

    def load_from_explorer(self) -> None:
        """Extracts active selection from Windows Explorer and loads into playlist."""
        paths = get_active_explorer_or_focus_paths(filter_supported=True, expand_folders=True)
        if not paths:
            self.speech.announce_no_explorer_selection()
            return

        with self._lock:
            if len(paths) == 1 and os.path.isfile(paths[0]):
                first_track = self.playlist.load_file_with_folder(paths[0], append=False)
                if first_track:
                    self.speech.announce_loaded_files(self.playlist.count)
                    self.play_track(first_track)
                    self._check_auto_enter_player_mode()
                else:
                    self.speech.announce_no_explorer_selection()
            else:
                count = self.playlist.load_paths(paths, append=False)
                if count > 0:
                    self.speech.announce_loaded_files(count)
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
        import sys
        from . import stream_engine
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

        from .url_dialogs import prompt_url_input
        prompt_url_input(
            on_submit=self._on_url_or_search_submitted,
            on_cancelled=None,
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
        )

    def copy_current_url(self) -> None:
        """
        Copies the current track's source URL (for online streams) or its
        file path (for local files) to the Windows clipboard (V key).
        """
        cur = self.playlist.get_current_track()
        if not cur or not cur.path:
            self.speech.speak(_("Nothing is currently loaded."))
            return

        copied = False
        try:
            import api
            copied = api.copyToClip(cur.path)
        except Exception:
            # Fallback outside NVDA (tests): use wx clipboard if available
            try:
                import wx
                if wx.TheClipboard.Open():
                    wx.TheClipboard.SetData(wx.TextDataObject(cur.path))
                    wx.TheClipboard.Close()
                    copied = True
            except Exception:
                copied = False

        if copied:
            if getattr(cur, "is_stream", False):
                self.speech.speak(_("Link copied to clipboard."))
            else:
                self.speech.speak(_("File path copied to clipboard."))
        else:
            self.speech.speak(_("Could not copy to clipboard."))

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

        from . import stream_engine
        from .url_dialogs import show_results_dialog

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
        from . import stream_engine
        from .url_dialogs import show_results_dialog

        cfg = getConfig()
        try:
            if stream_engine.is_url(text):
                url = stream_engine.normalize_url(text)
                self.speech.speak(_("Loading URL, please wait..."))
                limit = int(cfg.get("maxStreamPlaylistItems", 300))
                title, items, is_multi = stream_engine.probe_url(url, limit=limit)

                if is_multi:
                    videos = [it for it in items if it.kind == stream_engine.ITEM_VIDEO]
                    if videos and len(videos) == len(items):
                        # Pure playlist: queue it exactly like a local folder playlist
                        self.play_stream_items(videos, start_index=0, listing_title=title)
                    else:
                        # Mixed listing (e.g. channel root): open the browser dialog
                        show_results_dialog(
                            title or url,
                            items,
                            self,
                            suspend_capture=self._suspend_input,
                            resume_capture=self._resume_input,
                            is_playlist_context=bool(videos),
                        )
                else:
                    self.play_stream_items(items, start_index=0, listing_title=title)
            else:
                # Free text: interactive YouTube search
                self.speech.speak(_("Searching YouTube, please wait..."))
                limit = int(cfg.get("searchResultsCount", 20))
                results = stream_engine.search_youtube(text, limit=limit)
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
                )
        except Exception as e:
            logger.error("URL/search handling failed: %s", e, exc_info=True)
            self.speech.speak(self._stream_error_message(e))

    def _stream_error_message(self, exc: Exception) -> str:
        """Builds an accurate spoken error message for a streaming failure."""
        from . import stream_engine
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
        listing_title: str = ""
    ) -> bool:
        """
        Queues a sequence of online StreamItems as the active playlist
        (behaving exactly like a local folder queue) and starts playback.
        """
        from . import stream_engine

        video_items = [it for it in items if getattr(it, "kind", "") == stream_engine.ITEM_VIDEO]
        if not video_items:
            self.speech.speak(_("No playable items found."))
            return False

        # Recompute start index within the filtered video list
        if 0 <= start_index < len(items) and items[start_index] in video_items:
            start_index = video_items.index(items[start_index])
        else:
            start_index = max(0, min(start_index, len(video_items) - 1))

        tracks = [
            Track(
                path=it.url,
                title=it.title,
                duration=it.duration if it.duration else None,
                metadata={"is_live": bool(it.is_live), "listing": listing_title},
            )
            for it in video_items
        ]

        with self._lock:
            first = self.playlist.load_stream_tracks(tracks, start_index=start_index, append=False)

        if not first:
            self.speech.speak(_("No playable items found."))
            return False

        if len(tracks) > 1:
            self.speech.announce_loaded_files(len(tracks))
        res = self.play_track(first)
        self._check_auto_enter_player_mode()
        return res

    def play_stream_listing(self, url: str, listing_title: str = "") -> None:
        """
        Expands a playlist / channel-tab URL in the background and plays
        all of its entries as the active queue ('Play Playlist' action).
        """
        self.speech.speak(_("Loading playlist, please wait..."))

        def worker() -> None:
            from . import stream_engine
            try:
                limit = int(getConfig().get("maxStreamPlaylistItems", 300))
                title, items = stream_engine.fetch_listing(url, limit=limit)
                self.play_stream_items(items, start_index=0, listing_title=title or listing_title)
            except Exception as e:
                logger.error("Playlist expansion failed: %s", e, exc_info=True)
                self.speech.speak(self._stream_error_message(e))

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-PlayListing").start()

    def _play_stream_track(self, track: Track) -> bool:
        """
        Starts asynchronous resolution and playback of an online stream track.
        The direct audio URL is (re)extracted at play time so links never expire.
        """
        with self._lock:
            self.save_current_position()
            self._stream_play_generation += 1
            generation = self._stream_play_generation
            self._last_loaded_path = track.path

            cfg = getConfig()
            if cfg.get("resumePosition", True) and not track.metadata.get("is_live"):
                saved_pos = self.state_store.get_position(track.path)
                self._pending_resume_pos = saved_pos if (saved_pos and saved_pos >= 1.0) else None
            else:
                self._pending_resume_pos = None

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
        from . import stream_engine
        try:
            info = stream_engine.resolve_stream(track.path)
        except Exception as e:
            logger.error("Stream resolution failed for %s: %s", track.path, e)
            with self._lock:
                stale = generation != self._stream_play_generation
            if not stale:
                from . import stream_engine as se
                if se.is_cookie_error(str(e)):
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

            # Enrich track metadata from the full extraction
            if info.get("title") and (not track.title or track.title == track.path):
                track.title = info["title"]
            if info.get("duration"):
                track.duration = float(info["duration"])
            if info.get("is_live"):
                track.metadata["is_live"] = True
                self._pending_resume_pos = None

            success = self.engine.load_stream(info["stream_url"], info.get("http_headers"))
            if success:
                self.state_store.save_recent_file(track.path)
                self.speech.announce_track(orig_idx, total, track.display_name)
            else:
                self.speech.speak(_("Playback engine failed to start."))

    def _current_track_is_live_stream(self) -> bool:
        cur = self.playlist.get_current_track()
        return bool(cur and getattr(cur, "is_stream", False) and cur.metadata.get("is_live"))

    def _on_file_selected(self, file_path: str) -> None:
        """Callback when user selects a file in open file dialog."""
        if not file_path or not os.path.exists(file_path):
            return

        with self._lock:
            track = self.playlist.load_file_with_folder(file_path, append=False)
            if track:
                self.speech.announce_loaded_files(self.playlist.count)
                self.play_track(track)
                self._check_auto_enter_player_mode()

    def _on_folder_selected(self, folder_path: str) -> None:
        """Callback when user selects a folder in folder browser dialog."""
        if not folder_path or not os.path.isdir(folder_path):
            return

        with self._lock:
            count = self.playlist.load_folder(folder_path, recursive=False, append=False)
            if count > 0:
                self.speech.announce_loaded_files(count)
                first_track = self.playlist.get_current_track()
                if first_track:
                    self.play_track(first_track)
                    self._check_auto_enter_player_mode()
            else:
                self.speech.announce_no_media_in_folder()

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

    def save_current_position(self) -> None:
        """Saves active playback position to the persistent StateStore."""
        track_path = self._last_loaded_path or getattr(self.engine, "path", None)
        if not track_path:
            cur_track = self.playlist.get_current_track()
            track_path = cur_track.path if (cur_track and cur_track.path) else None
        if not track_path:
            return

        # Never persist positions for live streams (they have no fixed timeline)
        if self._current_track_is_live_stream():
            return

        pos = getattr(self.engine, "time_pos", 0.0)
        dur = getattr(self.engine, "duration", None)

        if pos > 0:
            self.state_store.save_position(
                file_path=track_path,
                position_sec=pos,
                duration_sec=dur
            )

    # -------------------------------------------------------------------------
    # Engine Event Handlers
    # -------------------------------------------------------------------------

    def _on_engine_file_loaded(self) -> None:
        """Fired when mpv finishes parsing a newly loaded media file."""
        with self._lock:
            if self._pending_resume_pos is not None and self._pending_resume_pos >= 1.0:
                target = self._pending_resume_pos
                self._pending_resume_pos = None
                self.engine.seek_absolute(target)
                self.speech.announce_resume_position(target)

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
        with self._lock:
            cur_path = self._last_loaded_path or getattr(self.engine, "path", None)

            if reason == "eof":
                # Clear completed position in state store
                if cur_path:
                    self.state_store.clear_position(cur_path)

                # Coordinate auto-next or track repeat
                next_t = self.playlist.on_track_ended()
                if next_t:
                    self.play_track(next_t)
                else:
                    self._last_loaded_path = None
                    self.tone_manager.play_boundary_hit()
            elif reason in ("stop", "quit"):
                self.save_current_position()
            elif reason == "error":
                # mpv could not open the media (e.g. an expired or blocked
                # stream URL). Stay silent for local files (rare) but tell
                # the user clearly for online streams instead of dead air.
                cur = self.playlist.get_current_track()
                if cur and getattr(cur, "is_stream", False):
                    # Drop the cached (bad/expired) stream URL so a retry
                    # performs a fresh extraction.
                    try:
                        from . import stream_engine
                        stream_engine.clear_resolve_cache()
                    except Exception:
                        pass
                    self.tone_manager.play_boundary_hit()
                    self.speech.speak(_(
                        "Playback of this stream failed. Press Enter or Space to retry."
                    ))

    def _on_engine_property_change(self, name: str, data: Any) -> None:
        """Fired on mpv property change events."""
        pass

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
