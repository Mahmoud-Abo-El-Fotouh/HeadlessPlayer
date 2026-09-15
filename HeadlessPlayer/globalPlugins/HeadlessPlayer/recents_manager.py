# -*- coding: utf-8 -*-
from __future__ import annotations

"""
HeadlessPlayer NVDA Add-on - Recents Manager.
Provides navigation, jumping, playback, and deletion for recent folders,
playlists, files, and online streams.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

try:
    from . import _  # type: ignore
except (ImportError, ValueError):
    try:
        _ = _  # type: ignore
    except NameError:
        _ = lambda text: text

from .database import get_db_manager, disambiguate_recent_name
from .playlist import Track

logger = logging.getLogger("HeadlessPlayer.RecentsManager")


class RecentsManager:
    """
    Coordinates recents history browsing, focus state, and activation.
    """

    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self.playlist_idx: int = 0
        self.track_idx: int = 0
        self.focus_active: bool = False
        self.focus_category: Optional[str] = None
        self.last_interaction: float = 0.0

    @property
    def container_idx(self) -> int:
        return self.playlist_idx

    @container_idx.setter
    def container_idx(self, val: int) -> None:
        self.playlist_idx = val

    def is_focus_active(self) -> bool:
        """Returns True if a recent item is currently focused and within timeout."""
        if not self.focus_active:
            return False
        if time.time() - self.last_interaction > 5.0:
            self.focus_active = False
            self.focus_category = None
            return False
        return True

    def cancel_focus(self) -> None:
        """Cancels active recents focus state."""
        self.focus_active = False
        self.focus_category = None
        self.last_interaction = 0.0

    def clear_focus(self) -> None:
        """Alias for cancel_focus."""
        self.cancel_focus()

    def playlist_next(self) -> None:
        """Move forward (towards newer / end) in recent playlists."""
        self.navigate("playlist", delta=-1)

    container_next = playlist_next

    def playlist_prev(self) -> None:
        """Move backward (towards older / start) in recent playlists."""
        self.navigate("playlist", delta=1)

    container_prev = playlist_prev

    def playlist_first(self) -> None:
        """Jump to first / oldest playlist in recent history."""
        self.jump("playlist", to_oldest=True)

    container_first = playlist_first

    def playlist_last(self) -> None:
        """Jump to last / newest playlist in recent history."""
        self.jump("playlist", to_oldest=False)

    container_last = playlist_last

    def track_next(self) -> None:
        """Move forward (towards newer / end) in recent tracks."""
        self.navigate("track", delta=-1)

    def track_prev(self) -> None:
        """Move backward (towards older / start) in recent tracks."""
        self.navigate("track", delta=1)

    def track_first(self) -> None:
        """Jump to first / oldest track in recent history."""
        self.jump("track", to_oldest=True)

    def track_last(self) -> None:
        """Jump to last / newest track in recent history."""
        self.jump("track", to_oldest=False)

    def navigate(self, category: str, delta: int) -> None:
        """Navigates through recent items list."""
        db = get_db_manager()

        if category in ("playlist", "container"):
            items = db.get_recent_playlists()
            if not items:
                self.controller.speech.speak(_("No recent folders or playlists"))
                return
            if not self.is_focus_active() or self.focus_category not in ("playlist", "container"):
                idx = 0
            else:
                idx = self.playlist_idx + delta

            idx = max(0, min(idx, len(items) - 1))
            self.playlist_idx = idx
            self.focus_active = True
            self.focus_category = "playlist"
            self.last_interaction = time.time()

            item = items[idx]
            title = disambiguate_recent_name(item, items)
            display_num = len(items) - idx
            ctype = item.get("type", "folder")
            if ctype == "folder":
                msg = _("Recent folder: %s (%d of %d)") % (title, display_num, len(items))
            else:
                msg = _("Recent playlist: %s (%d of %d)") % (title, display_num, len(items))
            self.controller.speech.speak(msg)

        elif category == "track":
            items = db.get_recent_tracks()
            if not items:
                self.controller.speech.speak(_("No recent files or streams"))
                return
            if not self.is_focus_active() or self.focus_category != "track":
                idx = 0
            else:
                idx = self.track_idx + delta

            idx = max(0, min(idx, len(items) - 1))
            self.track_idx = idx
            self.focus_active = True
            self.focus_category = "track"
            self.last_interaction = time.time()

            item = items[idx]
            title = disambiguate_recent_name(item, items)
            display_num = len(items) - idx
            ttype = item.get("type", "file")
            if ttype == "file":
                msg = _("Recent file: %s (%d of %d)") % (title, display_num, len(items))
            else:
                msg = _("Recent stream: %s (%d of %d)") % (title, display_num, len(items))
            self.controller.speech.speak(msg)

    def jump(self, category: str, to_oldest: bool) -> None:
        """Jumps directly to the oldest or newest recent item."""
        db = get_db_manager()

        if category in ("playlist", "container"):
            items = db.get_recent_playlists()
            if not items:
                self.controller.speech.speak(_("No recent folders or playlists"))
                return
            idx = (len(items) - 1) if to_oldest else 0
            self.playlist_idx = idx
            self.focus_active = True
            self.focus_category = "playlist"
            self.last_interaction = time.time()

            item = items[idx]
            title = disambiguate_recent_name(item, items)
            display_num = len(items) - idx
            ctype = item.get("type", "folder")
            tag = _("oldest") if to_oldest else _("newest")
            if ctype == "folder":
                msg = _("Recent folder (%s): %s (%d of %d)") % (tag, title, display_num, len(items))
            else:
                msg = _("Recent playlist (%s): %s (%d of %d)") % (tag, title, display_num, len(items))
            self.controller.speech.speak(msg)

        elif category == "track":
            items = db.get_recent_tracks()
            if not items:
                self.controller.speech.speak(_("No recent files or streams"))
                return
            idx = (len(items) - 1) if to_oldest else 0
            self.track_idx = idx
            self.focus_active = True
            self.focus_category = "track"
            self.last_interaction = time.time()

            item = items[idx]
            title = disambiguate_recent_name(item, items)
            display_num = len(items) - idx
            ttype = item.get("type", "file")
            tag = _("oldest") if to_oldest else _("newest")
            if ttype == "file":
                msg = _("Recent file (%s): %s (%d of %d)") % (tag, title, display_num, len(items))
            else:
                msg = _("Recent stream (%s): %s (%d of %d)") % (tag, title, display_num, len(items))
            self.controller.speech.speak(msg)

    def play_focused(self) -> bool:
        """Plays the currently focused item from recents browsing."""
        if not self.is_focus_active():
            return False

        db = get_db_manager()

        if self.focus_category in ("playlist", "container"):
            items = db.get_recent_playlists()
            idx = self.playlist_idx
            if not items or idx < 0 or idx >= len(items):
                return False
            item = items[idx]
            self.cancel_focus()
            p = str(item.get("path", ""))
            ctype = item.get("type", "folder")
            if ctype == "folder" or os.path.isdir(p):
                self.controller.load_folder(p)
                return True
            else:
                if p.startswith(("http://", "https://", "youtube:")):
                    self.controller._handle_url_or_search(p)
                else:
                    self.controller.load_folder(p)
                return True

        elif self.focus_category == "track":
            items = db.get_recent_tracks()
            idx = self.track_idx
            if not items or idx < 0 or idx >= len(items):
                return False
            item = items[idx]
            self.cancel_focus()
            p = str(item.get("path", ""))
            ttype = item.get("type", "file")
            if ttype == "stream" or p.startswith(("http://", "https://", "youtube:", "ytdl://", "custom://")):
                tr = Track(
                    path=p,
                    title=item.get("title", p),
                    is_stream=True
                )
                self.controller.playlist.clear()
                self.controller.playlist.load_stream_tracks([tr], start_index=0)
                self.controller.play_track(tr)
                self.controller._check_auto_enter_player_mode()
                return True
            else:
                if os.path.exists(p):
                    self.controller.playlist.clear()
                    first_track = self.controller.playlist.load_file_with_folder(p, append=False)
                    if first_track:
                        self.controller.speech.announce_loaded_files(
                            self.controller.playlist.count,
                            total_duration=self.controller.playlist.total_duration
                        )
                        self.controller.play_track(first_track)
                        self.controller._check_auto_enter_player_mode()
                    return True
                else:
                    self.controller.speech.speak(_("File does not exist on disk"))
                    return True

        return False

    def delete_focused(self) -> bool:
        """Removes the currently focused recent item from the database."""
        if not self.focus_active and not self.is_focus_active():
            return False

        db = get_db_manager()

        if self.focus_category in ("playlist", "container"):
            items = db.get_recent_playlists()
            idx = self.playlist_idx
            if not items or idx < 0 or idx >= len(items):
                return False
            item = items[idx]
            p = str(item.get("path", ""))
            title = disambiguate_recent_name(item, items)
            db.delete_recent_playlist(p)
            self.controller.speech.speak(_("Removed from recent history: %s") % title)

            remaining = db.get_recent_playlists()
            if not remaining:
                self.cancel_focus()
                self.controller.speech.speak(_("No more recent folders or playlists"))
            else:
                self.playlist_idx = min(idx, len(remaining) - 1)
                self.last_interaction = time.time()
                new_item = remaining[self.playlist_idx]
                new_title = disambiguate_recent_name(new_item, remaining)
                display_num = len(remaining) - self.playlist_idx
                self.controller.speech.speak(f"{new_title} ({display_num} of {len(remaining)})")
            return True

        elif self.focus_category == "track":
            items = db.get_recent_tracks()
            idx = self.track_idx
            if not items or idx < 0 or idx >= len(items):
                return False
            item = items[idx]
            p = str(item.get("path", ""))
            title = disambiguate_recent_name(item, items)
            db.delete_recent_track(p)
            self.controller.speech.speak(_("Removed from recent history: %s") % title)

            remaining = db.get_recent_tracks()
            if not remaining:
                self.cancel_focus()
                self.controller.speech.speak(_("No more recent files or streams"))
            else:
                self.track_idx = min(idx, len(remaining) - 1)
                self.last_interaction = time.time()
                new_item = remaining[self.track_idx]
                new_title = disambiguate_recent_name(new_item, remaining)
                display_num = len(remaining) - self.track_idx
                self.controller.speech.speak(f"{new_title} ({display_num} of {len(remaining)})")
            return True

        return False
