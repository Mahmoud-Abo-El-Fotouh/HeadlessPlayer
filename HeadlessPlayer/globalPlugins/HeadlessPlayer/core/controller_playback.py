# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Controller Playback Mixin.
Handles core media playback, seeking, volume, speed, equalization, A-B looping, and track cycling.
"""

from __future__ import annotations
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

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

from ..playlist import RepeatMode
from ..utils.config_spec import getConfig, getConfigValue, setConfigValue, saveConfig
from ..utils import format_time, log_debug, log_exception, log_info

logger = logging.getLogger("HeadlessPlayer.ControllerPlayback")


class _DiskSaveDebouncer:
    """
    Coalesces rapid settings/state writes (volume, bass, speed) to disk.
    Defers disk I/O by 500ms so bursts of rapid adjustments perform a single disk commit.
    Provides immediate synchronous flush on shutdown or stop.
    """

    def __init__(self, delay_sec: float = 0.5) -> None:
        self.delay_sec = delay_sec
        self._pending: Dict[str, Tuple[Any, Callable[[Any], None]]] = {}
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    def debounce(self, key: str, value: Any, commit_fn: Callable[[Any], None]) -> None:
        with self._lock:
            self._pending[key] = (value, commit_fn)
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._timer = threading.Timer(self.delay_sec, self._flush_internal)
            self._timer.daemon = True
            self._timer.start()

    def _flush_internal(self) -> None:
        with self._lock:
            self._timer = None
            to_commit = dict(self._pending)
            self._pending.clear()

        for key, (val, commit_fn) in to_commit.items():
            try:
                commit_fn(val)
            except Exception as e:
                logger.debug("Error during debounced disk commit for %s: %s", key, e)

    def flush(self) -> None:
        """Immediately commits all pending disk writes synchronously."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            to_commit = dict(self._pending)
            self._pending.clear()

        for key, (val, commit_fn) in to_commit.items():
            try:
                commit_fn(val)
            except Exception as e:
                logger.debug("Error during immediate disk flush for %s: %s", key, e)

    def cancel(self) -> None:
        """Cancels any pending timer and clears pending writes without committing."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending.clear()


class ControllerPlaybackMixin:
    """
    Mixin providing playback control, seeking, volume, speed, and looping operations.
    """

    @property
    def disk_debouncer(self) -> _DiskSaveDebouncer:
        if not hasattr(self, "_disk_save_debouncer") or self._disk_save_debouncer is None:
            self._disk_save_debouncer = _DiskSaveDebouncer(delay_sec=0.5)
        return self._disk_save_debouncer

    def _debounce_volume_save(self, volume: int) -> None:
        def commit(vol: int) -> None:
            self.state_store.save_volume(int(vol))
            setConfigValue("volume", int(vol))
            saveConfig()
        self.disk_debouncer.debounce("volume", int(volume), commit)

    def _debounce_bass_save(self, gain: float) -> None:
        def commit(g: float) -> None:
            self.state_store.save_setting("bass_gain", float(g))
            setConfigValue("bassGain", float(g))
            saveConfig()
        self.disk_debouncer.debounce("bass", float(gain), commit)

    def _debounce_speed_save(self, speed: float) -> None:
        def commit(s: float) -> None:
            self.state_store.save_speed(s)
            setConfigValue("defaultSpeed", float(s))
        self.disk_debouncer.debounce("speed", float(speed), commit)

    def flush_pending_disk_saves(self) -> None:
        """Flushes any coalesced volume, bass, or speed settings to disk immediately."""
        if hasattr(self, "_disk_save_debouncer") and self._disk_save_debouncer is not None:
            self._disk_save_debouncer.flush()

    def cancel_pending_disk_saves(self) -> None:
        """Cancels any coalesced volume, bass, or speed settings without writing to disk."""
        if hasattr(self, "_disk_save_debouncer") and self._disk_save_debouncer is not None:
            self._disk_save_debouncer.cancel()

    def toggle_play_pause(self) -> bool:
        """
        Toggles playback state (play <-> pause).
        If stopped, idle, or EOF reached: restarts playback of current track.
        """
        with self._lock:
            if hasattr(self.speech, "cancel_debounced_seek"):
                self.speech.cancel_debounced_seek()

            log_info("CONTROLLER", "toggle_play_pause invoked: running=%s, loaded=%s, paused=%s",
                     self.engine.is_running, getattr(self.engine, "is_loaded", False), getattr(self.engine, "paused", False))

            if getattr(self, "_is_resolving_stream", False):
                self.speech.speak(_("Loading stream, please wait..."))
                return False

            if not self.engine.is_running:
                self.start()
                cur_track = self.playlist.get_current_track()
                if cur_track:
                    return self.play_track(cur_track)
                return False

            cur_track = self.playlist.get_current_track()
            is_stream = bool(cur_track and getattr(cur_track, "is_stream", False))
            is_unloaded = (
                not getattr(self.engine, "is_loaded", False)
                or getattr(self.engine, "eof_reached", False)
                or (is_stream and getattr(self, "_stream_ended", False))
            )
            if is_unloaded:
                if cur_track:
                    resume_pos = self._pending_resume_pos
                    self._pending_resume_pos = None
                    self._stream_ended = False
                    if resume_pos is None or resume_pos < 0.0:
                        resume_pos = 0.0
                    return self.play_track(cur_track, resume_pos=resume_pos)
                self.speech.announce_no_media()
                return False

            dur = getattr(self.engine, "duration", 0.0) or 0.0
            cur_pos = getattr(self.engine, "time_pos", 0.0) or 0.0
            if dur > 5.0 and cur_pos >= (dur - 1.0):
                if cur_track:
                    self._stream_ended = False
                    return self.play_track(cur_track, resume_pos=0.0)
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
            cur_track = self.playlist.get_current_track()
            is_stream = bool(cur_track and getattr(cur_track, "is_stream", False))
            is_unloaded = (
                not self.engine.is_running
                or not getattr(self.engine, "is_loaded", False)
                or getattr(self.engine, "eof_reached", False)
                or (is_stream and getattr(self, "_stream_ended", False))
            )
            if is_unloaded:
                if cur_track:
                    resume_pos = self._pending_resume_pos
                    self._pending_resume_pos = None
                    self._stream_ended = False
                    if resume_pos is None or resume_pos < 0.0:
                        resume_pos = 0.0
                    return self.play_track(cur_track, resume_pos=resume_pos)
                return False
            res = self.engine.resume()
            self.speech.announce_playback_state("playing")
            return res

    def pause(self) -> bool:
        """Explicitly pauses playback and saves resume position."""
        with self._lock:
            if not self.engine.is_running:
                return False
            if not getattr(self.engine, "is_loaded", False) and not getattr(self.engine, "path", None):
                return False
            self.save_current_position()
            res = self.engine.pause()
            self.speech.announce_playback_state("paused")
            return res

    def stop(self) -> bool:
        """Stops playback, rewinds to start (0:00), clears saved position, and announces stopped."""
        self.flush_pending_disk_saves()
        log_info("CONTROLLER", "stop invoked: is_running=%s, last_loaded=%s", self.engine.is_running, self._last_loaded_path)
        with self._lock:
            if hasattr(self.speech, "cancel_debounced_seek"):
                self.speech.cancel_debounced_seek()
            if getattr(self, "_is_resolving_stream", False):
                self._is_resolving_stream = False
                self._resolving_track_path = None
                self._stream_play_generation += 1
            self._stream_auto_retries = 0
            self._stream_ended = False
            cur_path = self._last_loaded_path or getattr(self.engine, "path", None)
            if not cur_path:
                cur_track = self.playlist.get_current_track()
                if cur_track:
                    cur_path = cur_track.path
            if cur_path:
                self.state_store.clear_position(cur_path)
            self._pending_resume_pos = 0.0
            self._explicit_stop_cleared = True

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
            self._debounce_volume_save(int(new_vol))
            return new_vol

    def adjust_bass(self, delta: float) -> float:
        """Raises or lowers the bass level (+/- 3 dB steps) with speech feedback."""
        with self._lock:
            if not self.engine.is_running:
                self.start()
            new_gain = self.engine.adjust_bass(delta)
            self._debounce_bass_save(float(new_gain))
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
            self._debounce_volume_save(int(new_vol))
            return new_vol

    def seek(self, delta_sec: float) -> bool:
        """Relative seek with acoustic tactile click and coalesced 250ms speech announcement."""
        with self._lock:
            if not self.engine.is_running:
                return False

            cur_track = self.playlist.get_current_track()
            dur = self.engine.duration or (getattr(cur_track, "duration", 0.0) or 0.0)
            cur_pos = self.engine.time_pos or 0.0
            target_pos = max(0.0, min(dur, cur_pos + delta_sec)) if dur > 0 else max(0.0, cur_pos + delta_sec)

            is_unloaded = (not getattr(self.engine, "is_loaded", False) or getattr(self.engine, "eof_reached", False) or getattr(self, "_stream_ended", False))
            if is_unloaded and cur_track:
                self._pending_resume_pos = target_pos
                with self.engine._lock:
                    self.engine.time_pos = target_pos
                self.speech.on_seek_performed(
                    delta_sec=delta_sec,
                    current_pos=target_pos,
                    duration=dur,
                    play_click=True
                )
                return True

            res = self.engine.seek(delta_sec)
            new_pos = self.engine.time_pos

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
            cur_track = self.playlist.get_current_track()
            dur = self.engine.duration or (getattr(cur_track, "duration", 0.0) or 0.0)
            target_pos = (percent / 100.0) * dur if dur > 0 else 0.0

            is_unloaded = (not getattr(self.engine, "is_loaded", False) or getattr(self.engine, "eof_reached", False) or getattr(self, "_stream_ended", False))
            if is_unloaded and cur_track:
                self._pending_resume_pos = target_pos
                with self.engine._lock:
                    self.engine.time_pos = target_pos
                self.speech.announce_percent_jump(percent, target_pos)
                return True

            res = self.engine.seek_percent(percent)
            self.speech.announce_percent_jump(percent, target_pos)
            return res

    def seek_absolute(self, pos_sec: float) -> bool:
        """Seeks to an absolute timestamp in seconds."""
        with self._lock:
            if not self.engine.is_running:
                return False
            is_unloaded = (not getattr(self.engine, "is_loaded", False) or getattr(self.engine, "eof_reached", False) or getattr(self, "_stream_ended", False))
            if is_unloaded:
                self._pending_resume_pos = pos_sec
                with self.engine._lock:
                    self.engine.time_pos = pos_sec
                return True
            return self.engine.seek_absolute(pos_sec)

    def jump_to_track_start(self) -> bool:
        """Jumps directly to the beginning (0:00) of the current playing track (Home key)."""
        with self._lock:
            if not self.engine.is_running:
                return False
            is_unloaded = (not getattr(self.engine, "is_loaded", False) or getattr(self.engine, "eof_reached", False) or getattr(self, "_stream_ended", False))
            cur_track = self.playlist.get_current_track()
            if is_unloaded and cur_track:
                self._pending_resume_pos = 0.0
                with self.engine._lock:
                    self.engine.time_pos = 0.0
                self.speech.announce_percent_jump(0, 0.0)
                return True

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
            elif dur and dur > 0:
                target = max(0.0, min(dur - 0.1, dur * 0.95))
            else:
                return False
            res = self.engine.seek_absolute(target)
            self.speech.speak(_("Track end"))
            return res

    def adjust_speed(self, delta: float) -> float:
        """Fine-tunes speed (+/-0.1x) with speech feedback."""
        with self._lock:
            if not self.engine.is_running:
                self.start()
            new_speed = self.engine.adjust_speed(delta)
            self.speech.announce_speed(new_speed, is_preset=False)
            self._debounce_speed_save(new_speed)
            return new_speed

    def cycle_speed_preset(self, forward: bool = True) -> float:
        """Cycles preset speeds (1.0x, 1.25x, 1.5x, 1.75x, 2.0x, 2.5x, 3.0x, 4.0x)."""
        with self._lock:
            if not self.engine.is_running:
                self.start()
            new_speed = self.engine.cycle_speed_preset(forward=forward)
            self.speech.announce_speed(new_speed, is_preset=True)
            self._debounce_speed_save(new_speed)
            return new_speed

    def set_speed(self, speed: float) -> float:
        """Sets exact speed multiplier."""
        with self._lock:
            if not self.engine.is_running:
                self.start()
            new_speed = self.engine.set_speed(speed)
            self.speech.announce_speed(new_speed, is_preset=False)
            self._debounce_speed_save(new_speed)
            return new_speed

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
                if self.engine.ab_loop_a is not None:
                    self.speech.announce_ab_loop_active(self.engine.ab_loop_a, pos)
                else:
                    self.speech.announce_point_b(pos)
            else:
                self.speech.speak(_("Point B must be set after Point A"))
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

            has_ab = (
                (self.engine.ab_loop_a is not None and self.engine.ab_loop_b is not None)
                or (getattr(self.engine, "_cached_ab_a", None) is not None and getattr(self.engine, "_cached_ab_b", None) is not None)
            )
            if has_ab:
                # Cycle: Active A-B Loop -> Track Repeat -> Playlist Repeat -> Repeat Off -> Active A-B Loop
                if self.engine.ab_loop_active:
                    self.engine.toggle_repeat()  # deactivates A-B loop in mpv
                    self.playlist.set_repeat_mode(RepeatMode.TRACK)
                    self.engine.set_track_repeat(True)
                    self.speech.announce_repeat_mode("track")
                    return "track_repeat_on"
                elif self.playlist.repeat_mode == RepeatMode.TRACK:
                    self.playlist.set_repeat_mode(RepeatMode.PLAYLIST)
                    self.engine.set_track_repeat(False)
                    self.speech.announce_repeat_mode("playlist")
                    return "playlist_repeat_on"
                elif self.playlist.repeat_mode == RepeatMode.PLAYLIST:
                    self.playlist.set_repeat_mode(RepeatMode.OFF)
                    self.engine.set_track_repeat(False)
                    self.speech.announce_repeat_mode("off")
                    return "off"
                else:
                    # Repeat is off -> reactivate A-B loop
                    res = self.engine.toggle_repeat()
                    a = self.engine.ab_loop_a if self.engine.ab_loop_a is not None else getattr(self.engine, "_cached_ab_a", 0.0)
                    b = self.engine.ab_loop_b if self.engine.ab_loop_b is not None else getattr(self.engine, "_cached_ab_b", 0.0)
                    self.speech.announce_ab_loop_active(a or 0.0, b or 0.0)
                    return "ab_loop_on"
            else:
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

    def next_chapter(self) -> bool:
        """Jumps to next chapter and announces title/index with start time."""
        with self._lock:
            if not self.engine.is_running:
                return False

            if self.engine.chapter_count > 0:
                cur_chap = self.engine.chapter if self.engine.chapter is not None else -1
                target_idx = min(self.engine.chapter_count - 1, cur_chap + 1) if cur_chap >= 0 else 0
                res = self.engine.next_chapter()
                if res:
                    self._active_native_chapter_idx = target_idx
                    self._suppress_auto_chapter_count = getattr(self, "_suppress_auto_chapter_count", 0) + 1
                    self._suppress_next_auto_chapter = True
                    chap_info = self.engine.get_chapter_info(target_idx) if hasattr(self.engine, "get_chapter_info") else None
                    chap_num = target_idx + 1
                    title = chap_info.get("title") if chap_info else self.engine.get_current_chapter_title()
                    start_time = float(chap_info["time"]) if (chap_info and chap_info.get("time") is not None) else self.engine.get_current_chapter_start_time()
                    self.speech.announce_chapter(chap_num, title, start_time=start_time)
                    return True

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
                    self._suppress_auto_chapter_count = getattr(self, "_suppress_auto_chapter_count", 0) + 1
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

            if self.engine.chapter_count > 0:
                cur_chap = self.engine.chapter if self.engine.chapter is not None else 0
                cur_time = self.engine.time_pos or 0.0
                cur_info = self.engine.get_chapter_info(cur_chap) if hasattr(self.engine, "get_chapter_info") else None
                cur_start = float(cur_info["time"]) if (cur_info and cur_info.get("time") is not None) else 0.0

                if (cur_time - cur_start) > 3.0 or cur_chap == 0:
                    target_idx = max(0, cur_chap)
                else:
                    target_idx = max(0, cur_chap - 1)

                if target_idx == cur_chap:
                    res = self.engine.seek_absolute(cur_start)
                else:
                    res = self.engine.prev_chapter()
                if res:
                    self._active_native_chapter_idx = target_idx
                    self._suppress_auto_chapter_count = getattr(self, "_suppress_auto_chapter_count", 0) + 1
                    self._suppress_next_auto_chapter = True
                    chap_info = self.engine.get_chapter_info(target_idx) if hasattr(self.engine, "get_chapter_info") else None
                    chap_num = target_idx + 1
                    title = chap_info.get("title") if chap_info else self.engine.get_current_chapter_title()
                    start_time = float(chap_info["time"]) if (chap_info and chap_info.get("time") is not None) else self.engine.get_current_chapter_start_time()
                    self.speech.announce_chapter(chap_num, title, start_time=start_time)
                    return True

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
                self._suppress_auto_chapter_count = getattr(self, "_suppress_auto_chapter_count", 0) + 1
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

            if self._stream_audio_tracks and len(self._stream_audio_tracks) > 1:
                total = len(self._stream_audio_tracks)
                self._stream_audio_track_idx = (self._stream_audio_track_idx + 1) % total
                target = self._stream_audio_tracks[self._stream_audio_track_idx]
                target_url = target.get("url") or target.get("manifest_url")
                if not target_url:
                    self.speech.announce_no_other_audio_tracks()
                    return False

                cur_pos = self.engine.get_elapsed_time()
                is_paused = getattr(self.engine, "paused", False)

                self._pending_resume_pos = cur_pos if cur_pos >= 0.5 else None
                self._silence_resume_announcement = True
                self.engine.load_stream(target_url, target.get("http_headers"))
                if is_paused:
                    self.engine.pause()

                t_id = self._stream_audio_track_idx + 1
                title = target.get("title")
                lang = target.get("lang")
                self.speech.announce_audio_track(t_id, title, lang)
                return True

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
