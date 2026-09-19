# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Central Player Controller.
Coordinates the headless mpv audio engine, playlist and queue manager, persistent state store,
spoken feedback, and modal keyboard capture layer.
Decomposed into feature-focused mixins following Django separation of concerns.
"""

from __future__ import annotations
import logging
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from .. import _  # type: ignore
except (ImportError, ValueError):
    try:
        from . import _  # type: ignore
    except (ImportError, ValueError):
        try:
            _ = _  # type: ignore
        except NameError:
            def _(s: str) -> str:
                return s

from .engine import HeadlessEngine
from ..playlist import Playlist, Track, RepeatMode
from ..history.state_store import StateStore, get_state_store
from .speech import SpeechFeedback, get_speech_feedback
from ..input import ModalInputLayer
from ..utils.config_spec import getConfig, getConfigValue, setConfigValue, saveConfig
from ..utils import format_time, copy_to_clipboard, log_debug, log_exception, log_info
from ..history.database import get_db_manager
from ..history.recents import RecentsManager
from ..exporter.coordinator import ExportCoordinator
from ..streaming import engine as stream_engine

from .controller_playback import ControllerPlaybackMixin
from .controller_navigation import ControllerNavigationMixin
from .controller_streaming import ControllerStreamingMixin
from .controller_queries import ControllerQueriesMixin

logger = logging.getLogger("HeadlessPlayer.Controller")


class PlayerController(
    ControllerPlaybackMixin,
    ControllerNavigationMixin,
    ControllerStreamingMixin,
    ControllerQueriesMixin,
):
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
        repeat_str = self.state_store.get_repeat_mode() or cfg.get("defaultRepeatMode", "off")
        self.playlist.set_repeat_mode(repeat_str)
        saved_auto_next = self.state_store.get_auto_next()
        auto_next = saved_auto_next if saved_auto_next is not None else cfg.get("defaultAutoNext", True)
        self.playlist.set_auto_next(auto_next)

        saved_vol = self.state_store.get_volume()
        if saved_vol is not None:
            vol = float(saved_vol)
        else:
            vol = float(cfg.get("volume", 100))
        self.engine.volume = max(0.0, min(150.0, vol))

        saved_speed = self.state_store.get_speed()
        if saved_speed is not None:
            spd = float(saved_speed)
        else:
            spd = float(cfg.get("defaultSpeed", 1.0))
        self.engine.speed = max(0.1, min(4.0, spd))

        saved_bass = self.state_store.get_setting("bass_gain", 0.0)
        try:
            self.engine.bass_gain = float(saved_bass) if saved_bass is not None else 0.0
        except (ValueError, TypeError):
            self.engine.bass_gain = 0.0

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

    def terminate(self) -> None:
        """Terminates controller and engine."""
        self.shutdown()

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

    def _exit_player_mode_for_dialog(self) -> None:
        """Fully exits Player Mode before presenting an interactive dialog."""
        if self.input_layer and self.input_layer.is_active:
            self.input_layer.set_player_mode(False, announce=False)

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
    # Position Resume & Session State Storage
    # -------------------------------------------------------------------------

    def save_current_position(self, target_path: Optional[str] = None) -> None:
        """Saves active playback position to the persistent StateStore."""
        track_path = target_path or self._last_loaded_path
        if not track_path:
            track_path = self._canonical_current_track_path()
        if not track_path:
            return

        if self._current_track_is_live_stream(track_path):
            return

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
        """Saves current playback session into state_store."""
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
        """Restores the last saved playback session."""
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
                is_clean_finish = False
                if dur > 15.0:
                    is_clean_finish = cur_pos >= max(0.0, dur - 8.0)
                elif dur > 0:
                    is_clean_finish = cur_pos >= max(0.0, dur - 3.0)
                elif not is_stream:
                    is_clean_finish = True
                else:
                    is_clean_finish = False

                if is_clean_finish:
                    self._stream_auto_retries = 0
                    if cur_path:
                        self.state_store.clear_position(cur_path)

                    next_t = self.playlist.on_track_ended()
                    if next_t:
                        self._last_loaded_path = None
                        self.play_track(next_t)
                        self._check_stream_queue_auto_extend()
                    else:
                        self._last_loaded_path = None
                else:
                    logger.warning(
                        "Track '%s' ended prematurely at pos=%.2f / dur=%.2f (is_stream=%s, reason=%s)",
                        cur_path, cur_pos, dur, is_stream, reason
                    )
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
                    try:
                        stream_engine.clear_resolve_cache()
                    except Exception:
                        pass
                    self.speech.speak(_(
                        "Playback of this stream failed. Press Space to retry."
                    ))

    def _on_engine_property_change(self, name: str, data: Any) -> None:
        """Fired on mpv property change events."""
        if name == "time-pos" and data is not None:
            now = time.time()
            if getattr(self, "_restore_last_session", True) and (now - getattr(self, "_last_heartbeat_save_time", 0.0)) >= 60.0:
                self._last_heartbeat_save_time = now
                self.save_session()

        if not getConfigValue("announceChapterAuto", True):
            return

        if not self.speech.is_announcement_enabled("chapter"):
            return

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
