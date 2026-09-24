# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Controller Navigation Mixin.
Handles playlist track advances, recents history navigation, file/folder loading, and Windows Explorer selection.
"""

from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

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

from ..playlist import Track
from ..utils.config_spec import getConfig
from ..gui.dialogs import prompt_open_file_dialog, prompt_open_folder_dialog
from ..utils.explorer import get_active_explorer_or_focus_paths
from ..utils import log_debug, log_exception

logger = logging.getLogger("HeadlessPlayer.ControllerNavigation")


class ControllerNavigationMixin:
    """
    Mixin providing queue navigation, folder/file discovery, Explorer capture, and Recents browsing.
    """

    def play_track(self, track: Track, resume_pos: Optional[float] = None) -> bool:
        """Loads and begins playback of a specific track (local file or online stream)."""
        if not track or not track.path:
            return False

        self._stream_ended = False
        if getattr(track, "is_stream", False):
            return self._play_stream_track(track, resume_pos=resume_pos)

        with self._lock:
            self._is_resolving_stream = False
            self._resolving_track_path = None
            self._stream_auto_retries = 0
            self._active_stream_source_target = None
            self._active_stream_source_url = None
            self._active_stream_has_more = False
            self._current_stream_chapters = list(getattr(track, "chapters", [])) if getattr(track, "chapters", None) else []
            self._stream_play_generation += 1
            self._explicit_stop_cleared = False
            target_path = track.path

            if self._last_loaded_path and self._last_loaded_path != target_path:
                self.save_current_position(target_path=self._last_loaded_path)

            if resume_pos is not None:
                self._pending_resume_pos = resume_pos if resume_pos >= 0.5 else None
            elif self._pending_resume_pos is not None and self._pending_resume_pos >= 0.5:
                pass
            else:
                cfg = getConfig()
                if cfg.get("resumePosition", True):
                    saved_pos = self.state_store.get_position(
                        target_path,
                        current_duration=getattr(track, "duration", None)
                    )
                    self._pending_resume_pos = saved_pos if (saved_pos and saved_pos >= 1.0) else None
                else:
                    self._pending_resume_pos = None

            self._last_loaded_path = target_path

            self.engine.set_http_headers(None)
            if hasattr(self, "history_sync") and self.history_sync:
                self.history_sync.stop_session(reason="track_switch")
            success = self.engine.load_file(target_path, append=False)
            if success:
                self.state_store.save_recent_file(target_path)
                self._load_sponsor_segments_for_url(target_path)

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
                self._check_stream_queue_auto_extend()
                return next_t
            else:
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

    def _on_file_selected(self, file_path: str) -> None:
        """Callback when user selects a file in open file dialog."""
        if not file_path or not os.path.isfile(file_path):
            return
        self.load_file(file_path)

    def _on_folder_selected(self, folder_path: str) -> None:
        """Callback when user selects a folder in open folder dialog."""
        if not folder_path or not os.path.isdir(folder_path):
            return
        self.load_folder(folder_path)

    def load_file(self, file_path: str, append: bool = False) -> bool:
        """Loads a single local media file with its folder siblings into the playlist."""
        with self._lock:
            track = self.playlist.load_file_with_folder(file_path, append=append)
            if track:
                parent_dir = os.path.dirname(os.path.abspath(file_path))
                self.state_store.save_setting("last_browse_dir", parent_dir)
                try:
                    from ..history.database import get_db_manager
                    db = get_db_manager()
                    folder_title = os.path.basename(parent_dir) or parent_dir
                    db.save_recent_container(
                        path=parent_dir,
                        title=folder_title,
                        container_type="folder"
                    )
                except Exception as e:
                    logger.debug("Failed to record recent container for loaded file: %s", e)
                self.speech.announce_loaded_files(self.playlist.count, total_duration=self.playlist.total_duration)
                self.play_track(track)
                self._check_auto_enter_player_mode()
                return True
            return False

    def load_folder(self, folder_path: str, append: bool = False) -> int:
        """Loads all supported media files in a folder into the playlist."""
        with self._lock:
            count = self.playlist.load_folder(folder_path, append=append)
            if count > 0:
                norm_folder = os.path.abspath(folder_path)
                self.state_store.save_setting("last_browse_dir", norm_folder)
                try:
                    from ..history.database import get_db_manager
                    db = get_db_manager()
                    folder_title = os.path.basename(os.path.normpath(folder_path)) or folder_path
                    db.save_recent_container(
                        path=norm_folder,
                        title=folder_title,
                        container_type="folder"
                    )
                except Exception as e:
                    logger.debug("Failed to record recent container for loaded folder: %s", e)
                self.speech.announce_loaded_files(count, total_duration=self.playlist.total_duration)
                cur = self.playlist.get_current_track()
                if cur:
                    self.play_track(cur)
                    self._check_auto_enter_player_mode()
            return count

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

                if cur_path == target_path and self.engine.is_running:
                    self.engine.seek_absolute(0.0)
                    if getattr(self.engine, "paused", False):
                        self.engine.play()
                    self.speech.announce_playback_restarted()
                    return

                first_track = self.playlist.load_file_with_folder(paths[0], append=False)
                if first_track:
                    parent_dir = os.path.dirname(os.path.abspath(paths[0]))
                    try:
                        from ..history.database import get_db_manager
                        db = get_db_manager()
                        folder_title = os.path.basename(parent_dir) or parent_dir
                        db.save_recent_container(
                            path=parent_dir,
                            title=folder_title,
                            container_type="folder"
                        )
                    except Exception as e:
                        logger.debug("Failed to record recent container for explorer file: %s", e)
                    self.speech.announce_loaded_files(self.playlist.count, total_duration=self.playlist.total_duration)
                    self.play_track(first_track)
                    self._check_auto_enter_player_mode()
                else:
                    self.speech.announce_no_explorer_selection()
            else:
                count = self.playlist.load_paths(paths, append=False)
                if count > 0:
                    for p in paths:
                        if os.path.isdir(p):
                            try:
                                from ..history.database import get_db_manager
                                db = get_db_manager()
                                norm_p = os.path.abspath(p)
                                db.save_recent_container(
                                    path=norm_p,
                                    title=os.path.basename(norm_p) or norm_p,
                                    container_type="folder"
                                )
                            except Exception as e:
                                logger.debug("Failed to record recent container for explorer dir: %s", e)
                    self.speech.announce_loaded_files(count, total_duration=self.playlist.total_duration)
                    first_track = self.playlist.get_current_track()
                    if first_track:
                        self.play_track(first_track)
                        self._check_auto_enter_player_mode()
                else:
                    self.speech.announce_no_explorer_selection()

    # -------------------------------------------------------------------------
    # Recents History Navigation
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
        self.recents_manager.playlist_prev()

    recent_container_next = recent_playlist_next

    def recent_playlist_prev(self) -> None:
        """Ctrl + ,: Move backward (towards older / start) in recent playlists."""
        self.recents_manager.playlist_next()

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
        self.recents_manager.track_prev()

    def recent_track_prev(self) -> None:
        """,: Move backward (towards older / start) in recent tracks."""
        self.recents_manager.track_next()

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
