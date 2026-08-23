# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - URL Input & Interactive YouTube Search Dialogs.
Provides the 'U' key URL/search entry box and the accessible search results
browser supporting videos, playlists, and channels with drill-down navigation.
"""

from __future__ import annotations
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import addonHandler
    addonHandler.initTranslation()
except Exception:
    pass

try:
    _
except NameError:
    def _(s: str) -> str:
        return s

from . import stream_engine
from .stream_engine import (
    StreamItem,
    ITEM_VIDEO,
    ITEM_PLAYLIST,
    ITEM_CHANNEL,
    ITEM_LISTING,
)
from .utils import format_time

logger = logging.getLogger("HeadlessPlayer.UrlDialogs")


def _ui_message(text: str) -> None:
    try:
        import ui
        ui.message(text)
    except Exception:
        logger.info("[msg] %s", text)


# ---------------------------------------------------------------------------
# URL / Search text entry
# ---------------------------------------------------------------------------

def prompt_url_input(
    on_submit: Callable[[str], None],
    on_cancelled: Optional[Callable[[], None]] = None,
    suspend_capture: Optional[Callable[[], None]] = None,
    resume_capture: Optional[Callable[[], None]] = None,
) -> None:
    """
    Shows a text entry dialog for a URL (YouTube or any website) or a
    YouTube search query. Safely suspends Player Mode capture while open.
    """

    def _show() -> None:
        try:
            import wx
            import gui
        except ImportError:
            logger.warning("wx unavailable; cannot show URL input dialog")
            if on_cancelled:
                on_cancelled()
            return

        if suspend_capture:
            try:
                suspend_capture()
            except Exception:
                pass

        if hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "prePopup"):
            try:
                gui.mainFrame.prePopup()
            except Exception:
                pass

        text: Optional[str] = None
        try:
            dlg = wx.TextEntryDialog(
                getattr(gui, "mainFrame", None),
                _("Enter a URL (YouTube or any website) to play, or text to search YouTube:"),
                _("Play URL or Search YouTube"),
            )
            with dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    text = dlg.GetValue().strip()
        except Exception as e:
            logger.error("Error showing URL input dialog: %s", e)
        finally:
            if hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "postPopup"):
                try:
                    gui.mainFrame.postPopup()
                except Exception:
                    pass
            if resume_capture:
                try:
                    resume_capture()
                except Exception:
                    pass

        if text:
            try:
                on_submit(text)
            except Exception as e:
                logger.error("Error in URL submit callback: %s", e)
        elif on_cancelled:
            try:
                on_cancelled()
            except Exception:
                pass

    try:
        import wx
        wx.CallAfter(_show)
    except Exception:
        threading.Thread(target=_show, daemon=True).start()


# ---------------------------------------------------------------------------
# Interactive search results / listing browser
# ---------------------------------------------------------------------------

def _kind_label(item: StreamItem) -> str:
    if item.kind == ITEM_PLAYLIST:
        return _("Playlist")
    if item.kind == ITEM_CHANNEL:
        return _("Channel")
    if item.kind == ITEM_LISTING:
        return _("Section")
    if item.is_live:
        return _("Live")
    return _("Video")


def _item_display(item: StreamItem) -> str:
    parts = [f"{_kind_label(item)}: {item.title}"]
    if item.uploader:
        parts.append(item.uploader)
    if item.duration and item.duration > 0:
        parts.append(format_time(item.duration))
    return " — ".join(parts)


def _channel_sections(channel: StreamItem) -> List[StreamItem]:
    """Builds synthetic browsable sections for a channel."""
    base = channel.url.rstrip("/")
    return [
        StreamItem(ITEM_LISTING, base + "/videos", _("Videos of %s") % channel.title),
        StreamItem(ITEM_LISTING, base + "/playlists", _("Playlists of %s") % channel.title),
        StreamItem(ITEM_LISTING, base + "/streams", _("Live streams of %s") % channel.title),
    ]


class _Level:
    """One drill-down level in the results browser."""

    def __init__(self, title: str, items: List[StreamItem], is_playlist_context: bool) -> None:
        self.title = title
        self.items = items
        # True when this level's video entries form one coherent queue
        # (a playlist or channel tab) that should load as a playlist.
        self.is_playlist_context = is_playlist_context


def show_results_dialog(
    title: str,
    items: List[StreamItem],
    controller: Any,
    suspend_capture: Optional[Callable[[], None]] = None,
    resume_capture: Optional[Callable[[], None]] = None,
    is_playlist_context: bool = False,
) -> None:
    """
    Presents the interactive results browser on the wx main thread.

    Behavior:
    - Enter on a video: plays it (inside a playlist/channel level the whole
      level is queued as a playlist starting from that video).
    - Enter on a playlist or channel: drills into it.
    - Tab while a playlist is selected: reaches the 'Play Playlist' button.
    - Backspace: goes back one level.
    """

    def _show() -> None:
        try:
            import wx
            import gui
        except ImportError:
            logger.warning("wx unavailable; cannot show results dialog")
            return

        if suspend_capture:
            try:
                suspend_capture()
            except Exception:
                pass

        if hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "prePopup"):
            try:
                gui.mainFrame.prePopup()
            except Exception:
                pass

        try:
            dlg = _ResultsDialog(
                getattr(gui, "mainFrame", None),
                title,
                items,
                controller,
                is_playlist_context,
            )
            dlg.ShowModal()
            dlg.Destroy()
        except Exception as e:
            logger.error("Error in results dialog: %s", e, exc_info=True)
        finally:
            if hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "postPopup"):
                try:
                    gui.mainFrame.postPopup()
                except Exception:
                    pass
            if resume_capture:
                try:
                    resume_capture()
                except Exception:
                    pass

    try:
        import wx
        wx.CallAfter(_show)
    except Exception:
        logger.warning("wx.CallAfter unavailable; results dialog skipped")


try:
    import wx as _wx_mod
    _DialogBase = _wx_mod.Dialog
except Exception:
    _wx_mod = None
    _DialogBase = object


class _ResultsDialog(_DialogBase):
    """Accessible drill-down browser for search results and listings."""

    def __init__(
        self,
        parent: Any,
        title: str,
        items: List[StreamItem],
        controller: Any,
        is_playlist_context: bool,
    ) -> None:
        import wx
        super().__init__(
            parent,
            title=title or _("YouTube Search Results"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.controller = controller
        self._stack: List[_Level] = []
        self._level = _Level(title, items, is_playlist_context)
        self._busy = False

        mainSizer = wx.BoxSizer(wx.VERTICAL)

        self.listBox = wx.ListBox(self, choices=[], style=wx.LB_SINGLE, size=(560, 320))
        self.listBox.Bind(wx.EVT_LISTBOX_DCLICK, self.onActivate)
        self.listBox.Bind(wx.EVT_KEY_DOWN, self.onListKeyDown)
        self.listBox.Bind(wx.EVT_LISTBOX, self.onSelectionChanged)
        mainSizer.Add(self.listBox, 1, wx.EXPAND | wx.ALL, 8)

        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        # 'Play Playlist' intentionally comes first in tab order after the list,
        # so Tab while standing on a playlist lands on it directly.
        self.playPlaylistBtn = wx.Button(self, label=_("Play &Playlist"))
        self.playPlaylistBtn.Bind(wx.EVT_BUTTON, self.onPlayPlaylist)
        btnSizer.Add(self.playPlaylistBtn, 0, wx.ALL, 4)

        self.playBtn = wx.Button(self, label=_("&Play"))
        self.playBtn.Bind(wx.EVT_BUTTON, self.onActivate)
        btnSizer.Add(self.playBtn, 0, wx.ALL, 4)

        self.openBtn = wx.Button(self, label=_("&Open"))
        self.openBtn.Bind(wx.EVT_BUTTON, self.onActivate)
        btnSizer.Add(self.openBtn, 0, wx.ALL, 4)

        self.backBtn = wx.Button(self, label=_("&Back"))
        self.backBtn.Bind(wx.EVT_BUTTON, self.onBack)
        btnSizer.Add(self.backBtn, 0, wx.ALL, 4)

        self.closeBtn = wx.Button(self, wx.ID_CANCEL, label=_("&Close"))
        btnSizer.Add(self.closeBtn, 0, wx.ALL, 4)

        mainSizer.Add(btnSizer, 0, wx.ALIGN_CENTER | wx.ALL, 4)
        self.SetSizerAndFit(mainSizer)
        self.SetEscapeId(wx.ID_CANCEL)
        self.CenterOnParent()

        # Dialog-level guarantee: Enter while the list is focused ALWAYS
        # activates the selected item directly (video plays, playlist or
        # channel opens) - never routed to any button.
        self.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)

        self._refresh_list()
        self.listBox.SetFocus()

    def onCharHook(self, evt: Any) -> None:
        import wx
        code = evt.GetKeyCode()
        focused = self.FindFocus()
        if focused is self.listBox:
            if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                self.onActivate(evt)
                return
            if code == wx.WXK_BACK:
                self.onBack(evt)
                return
        evt.Skip()

    # -- helpers -----------------------------------------------------------

    def _current_item(self) -> Optional[StreamItem]:
        sel = self.listBox.GetSelection()
        if 0 <= sel < len(self._level.items):
            return self._level.items[sel]
        return None

    def _refresh_list(self, select: int = 0) -> None:
        choices = [_item_display(it) for it in self._level.items]
        self.listBox.Set(choices)
        if choices:
            select = max(0, min(select, len(choices) - 1))
            self.listBox.SetSelection(select)
        self.SetTitle(self._level.title or _("YouTube Search Results"))
        self.backBtn.Enable(bool(self._stack))
        self._update_buttons()

    def _update_buttons(self) -> None:
        item = self._current_item()
        is_pl = bool(item and item.kind in (ITEM_PLAYLIST, ITEM_LISTING))
        is_drill = bool(item and item.kind in (ITEM_PLAYLIST, ITEM_CHANNEL, ITEM_LISTING))
        is_video = bool(item and item.kind == ITEM_VIDEO)
        # Play Playlist: on a playlist item, or on a video inside a playlist context
        self.playPlaylistBtn.Enable(is_pl or (is_video and self._level.is_playlist_context))
        self.playBtn.Enable(is_video)
        self.openBtn.Enable(is_drill)

    # -- events ------------------------------------------------------------

    def onSelectionChanged(self, evt: Any) -> None:
        self._update_buttons()

    def onListKeyDown(self, evt: Any) -> None:
        import wx
        code = evt.GetKeyCode()
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.onActivate(evt)
            return
        if code == wx.WXK_BACK:
            self.onBack(evt)
            return
        evt.Skip()

    def onActivate(self, evt: Any) -> None:
        """Enter / double-click: play videos, drill into playlists & channels."""
        item = self._current_item()
        if not item or self._busy:
            return
        if item.kind == ITEM_VIDEO:
            self._play_video(item)
        elif item.kind == ITEM_CHANNEL:
            self._enter_channel(item)
        else:
            self._enter_listing(item)

    def onPlayPlaylist(self, evt: Any) -> None:
        item = self._current_item()
        if self._busy:
            return
        if item and item.kind in (ITEM_PLAYLIST, ITEM_LISTING):
            self._close_and(lambda: self.controller.play_stream_listing(
                item.url, listing_title=item.title))
        elif self._level.is_playlist_context and self._level.items:
            # Play the whole current level as a queue from the selected item
            sel = max(0, self.listBox.GetSelection())
            self._close_and(lambda: self.controller.play_stream_items(
                self._level.items, start_index=sel, listing_title=self._level.title))

    def onBack(self, evt: Any) -> None:
        if self._stack:
            level, sel = self._stack.pop()
            self._level = level
            self._refresh_list(select=sel)
            self.listBox.SetFocus()

    # -- actions -----------------------------------------------------------

    def _play_video(self, item: StreamItem) -> None:
        if self._level.is_playlist_context:
            # Behave exactly like local folders: queue the whole level,
            # starting from the chosen entry.
            videos = [it for it in self._level.items if it.kind == ITEM_VIDEO]
            try:
                start = videos.index(item)
            except ValueError:
                start = 0
            lvl_title = self._level.title
            self._close_and(lambda: self.controller.play_stream_items(
                videos, start_index=start, listing_title=lvl_title))
        else:
            self._close_and(lambda: self.controller.play_stream_items(
                [item], start_index=0, listing_title=item.title))

    def _enter_channel(self, item: StreamItem) -> None:
        # Channels expand instantly to synthetic sections (Videos / Playlists / Live)
        self._push_level(_Level(item.title, _channel_sections(item), False))

    def _enter_listing(self, item: StreamItem) -> None:
        import wx
        if getattr(item, "requires_login", False) and not stream_engine.login_cookies_enabled():
            _ui_message(_(
                "This section requires YouTube sign-in. Enable sign-in cookies from "
                "your browser in HeadlessPlayer settings, then try again."
            ))
            return
        self._busy = True
        _ui_message(_("Loading %s...") % item.title)

        def worker() -> None:
            try:
                from .config_spec import getConfig
                limit = int(getConfig().get("maxStreamPlaylistItems", 300))
            except Exception:
                limit = 300
            try:
                title, sub_items = stream_engine.fetch_listing(item.url, limit=limit)
            except Exception as e:
                logger.error("Listing fetch failed: %s", e)
                wx.CallAfter(self._on_listing_failed, str(e))
                return
            wx.CallAfter(self._on_listing_loaded, item, title, sub_items)

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-Listing").start()

    def _on_listing_failed(self, error_text: str = "") -> None:
        self._busy = False
        if stream_engine.is_cookie_error(error_text):
            _ui_message(_(
                "Could not read sign-in cookies from your browser. "
                "Set a manual cookies.txt file in HeadlessPlayer settings instead."
            ))
        else:
            _ui_message(_("Could not load this item. Check your connection or update yt-dlp from settings."))

    def _on_listing_loaded(self, item: StreamItem, title: str, sub_items: List[StreamItem]) -> None:
        self._busy = False
        if not sub_items:
            _ui_message(_("No items found."))
            return
        is_queue = item.kind in (ITEM_PLAYLIST, ITEM_LISTING) and any(
            it.kind == ITEM_VIDEO for it in sub_items
        )
        self._push_level(_Level(title or item.title, sub_items, is_queue))

    def _push_level(self, level: _Level) -> None:
        self._stack.append((self._level, max(0, self.listBox.GetSelection())))
        self._level = level
        self._refresh_list()
        self.listBox.SetFocus()
        _ui_message(_("%d items") % len(level.items))

    def _close_and(self, action: Callable[[], None]) -> None:
        import wx
        try:
            self.EndModal(wx.ID_OK)
        except Exception:
            pass
        try:
            action()
        except Exception as e:
            logger.error("Error launching playback from results dialog: %s", e)
