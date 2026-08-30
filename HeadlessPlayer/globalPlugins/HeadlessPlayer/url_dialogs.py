# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - URL Input & Interactive YouTube Search Dialogs.
Provides the 'U' key URL/search entry box and the accessible search results
browser supporting videos, playlists, and channels with drill-down navigation.
"""

from __future__ import annotations
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import wx
except Exception:
    wx = None

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
    ITEM_SHORTS,
    ITEM_PLAYLIST,
    ITEM_CHANNEL,
    ITEM_LISTING,
)
from .utils import format_time, log_debug, log_exception

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

        # Check clipboard for pre-fill if it contains a URL
        default_val = ""
        try:
            import api
            clip_text = api.getClipData()
            if clip_text and isinstance(clip_text, str):
                extracted = stream_engine.extract_url(clip_text)
                if extracted:
                    default_val = extracted
        except Exception:
            pass

        text: Optional[str] = None
        submitted = False
        try:
            dlg = wx.TextEntryDialog(
                getattr(gui, "mainFrame", None),
                _("Enter a URL (YouTube or any website) to play, or text to search YouTube:"),
                _("Play URL or Search YouTube"),
                value=default_val,
            )
            with dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    submitted = True
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
        elif submitted and not text:
            _ui_message(_("No search query entered."))
            if on_cancelled:
                try:
                    on_cancelled()
                except Exception:
                    pass
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
    if item.kind == ITEM_SHORTS:
        return _("Shorts")
    if item.kind == ITEM_PLAYLIST:
        return _("Playlist")
    if item.kind == ITEM_CHANNEL:
        return _("Channel")
    if item.kind == ITEM_LISTING:
        return _("Section")
    if item.is_live:
        return _("Live")
    return _("Video")


LOAD_MORE_KIND = "load_more"


def _item_display(item: StreamItem) -> str:
    """Formats a StreamItem into a rich, screen-reader friendly label."""
    if item.kind == LOAD_MORE_KIND:
        return _("— [Load more items...] —")
    parts: List[str] = []
    kind_lbl = _kind_label(item)
    if kind_lbl:
        parts.append(f"[{kind_lbl}]")
    if item.title:
        parts.append(item.title)
    if item.uploader and item.kind != ITEM_CHANNEL:
        clean_up = item.uploader.strip()
        if clean_up and clean_up not in (item.title or ""):
            parts.append(clean_up)
    if item.duration and item.duration > 0:
        parts.append(format_time(item.duration))
    return " — ".join(parts)


def _channel_sections(channel: StreamItem) -> List[StreamItem]:
    """Builds synthetic browsable sections for a channel."""
    base = channel.url.rstrip("/")
    return [
        StreamItem(ITEM_LISTING, base + "/videos", _("Videos of %s") % channel.title),
        StreamItem(ITEM_LISTING, base + "/shorts", _("Shorts of %s") % channel.title),
        StreamItem(ITEM_LISTING, base + "/playlists", _("Playlists of %s") % channel.title),
        StreamItem(ITEM_LISTING, base + "/streams", _("Live streams of %s") % channel.title),
    ]


class _Level:
    """One drill-down level in the results browser with dynamic auto-paging."""

    def __init__(
        self,
        title: str,
        items: List[StreamItem],
        is_playlist_context: bool,
        source_type: str = "custom",
        source_target: str = "",
        batch_size: int = 50,
        has_more: bool = True,
    ) -> None:
        self.title = title
        self.items = list(items)
        self.is_playlist_context = is_playlist_context
        self.source_type = source_type
        self.source_target = source_target
        self.batch_size = max(1, batch_size)
        self.next_start_idx = len(items) + 1
        self.has_more = bool(has_more and len(items) >= self.batch_size)
        self.is_fetching = False


def show_results_dialog(
    title: str,
    items: List[StreamItem],
    controller: Any,
    suspend_capture: Optional[Callable[[], None]] = None,
    resume_capture: Optional[Callable[[], None]] = None,
    is_playlist_context: bool = False,
    source_type: str = "custom",
    source_target: str = "",
    batch_size: Optional[int] = None,
) -> None:
    """
    Presents the interactive results browser on the wx main thread with
    seamless background pagination.
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
                source_type=source_type,
                source_target=source_target,
                batch_size=batch_size,
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
    """Accessible drill-down browser for search results and listings with infinite scroll."""

    def __init__(
        self,
        parent: Any,
        title: str,
        items: List[StreamItem],
        controller: Any,
        is_playlist_context: bool,
        source_type: str = "custom",
        source_target: str = "",
        batch_size: Optional[int] = None,
    ) -> None:
        import wx
        super().__init__(
            parent,
            title=title or _("YouTube Search Results"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.controller = controller
        self._stack: List[_Level] = []
        bsize = batch_size if batch_size is not None else max(len(items), 20)
        self._level = _Level(
            title,
            items,
            is_playlist_context,
            source_type=source_type,
            source_target=source_target,
            batch_size=bsize,
            has_more=bool(items and len(items) >= bsize),
        )
        self._display_items: List[StreamItem] = []
        self._busy = False
        self._manual_load_requested = False

        mainSizer = wx.BoxSizer(wx.VERTICAL)

        self.listCtrl = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
            size=(600, 360),
        )
        self.listCtrl.InsertColumn(0, _("Search Results & Streams"), width=570)
        self.listCtrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.onActivate)
        self.listCtrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.onSelectionChanged)
        self.listCtrl.Bind(wx.EVT_KEY_DOWN, self.onListKeyDown)
        self.listCtrl.Bind(wx.EVT_KEY_UP, self.onListKeyUp)
        mainSizer.Add(self.listCtrl, 1, wx.EXPAND | wx.ALL, 8)

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
        self.listCtrl.SetFocus()

    def onCharHook(self, evt: Any) -> None:
        import wx
        code = evt.GetKeyCode()
        focused = self.FindFocus()
        if focused is self.listCtrl:
            if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                self.onActivate(evt)
                return
            if code == wx.WXK_BACK:
                self.onBack(evt)
                return
        evt.Skip()

    # -- helpers -----------------------------------------------------------

    def _current_item(self) -> Optional[StreamItem]:
        sel = self.listCtrl.GetFirstSelected()
        if 0 <= sel < len(self._display_items):
            return self._display_items[sel]
        return None

    def _set_selection(self, index: int) -> None:
        import wx
        count = self.listCtrl.GetItemCount()
        if count <= 0:
            return
        idx = max(0, min(int(index), count - 1))
        self.listCtrl.SetItemState(
            idx,
            wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
            wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
        )
        self.listCtrl.EnsureVisible(idx)
        self.listCtrl.Focus(idx)

    def _refresh_list(self, select: int = 0) -> None:
        self.listCtrl.DeleteAllItems()
        level = self._level
        display_items = list(level.items)
        if level.has_more and level.source_type in ("search", "listing"):
            display_items.append(StreamItem(LOAD_MORE_KIND, "", _("— [Load more items...] —")))
        self._display_items = display_items
        for i, it in enumerate(display_items):
            self.listCtrl.InsertItem(i, _item_display(it))
        if display_items:
            select = max(0, min(select, len(display_items) - 1))
            self._set_selection(select)
        self.SetTitle(self._level.title or _("YouTube Search Results"))
        self.backBtn.Enable(bool(self._stack))
        self._update_buttons()

    def _update_buttons(self) -> None:
        item = self._current_item()
        if not item or item.kind == LOAD_MORE_KIND:
            self.playPlaylistBtn.Enable(False)
            self.playBtn.Enable(False)
            self.openBtn.Enable(bool(item and item.kind == LOAD_MORE_KIND))
            return
        is_pl = bool(item.kind in (ITEM_PLAYLIST, ITEM_LISTING))
        is_drill = bool(item.kind in (ITEM_PLAYLIST, ITEM_CHANNEL, ITEM_LISTING))
        is_video = bool(item.kind in (ITEM_VIDEO, ITEM_SHORTS))
        # Play Playlist: on a playlist item, or on a video inside a playlist context
        self.playPlaylistBtn.Enable(is_pl or (is_video and self._level.is_playlist_context))
        self.playBtn.Enable(is_video)
        self.openBtn.Enable(is_drill)

    # -- events ------------------------------------------------------------

    def onSelectionChanged(self, evt: Any) -> None:
        self._update_buttons()
        self._check_auto_load_more()

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

    def onListKeyUp(self, evt: Any) -> None:
        import wx
        evt.Skip()
        self._check_auto_load_more()

    def _check_auto_load_more(self) -> None:
        level = self._level
        if not level.has_more or self._busy or level.is_fetching:
            return
        if level.source_type not in ("search", "listing"):
            return
        import time
        now = time.time()
        if now - getattr(self, "_last_scroll_check_time", 0.0) < 0.25:
            return
        self._last_scroll_check_time = now

        sel = self.listCtrl.GetFirstSelected()
        total = len(level.items)
        # Predictive pre-fetch: trigger automatically when user reaches 60% of the list
        # or is within 15 items of the end, so new items are ready before reaching the end.
        threshold = max(0, min(total - 15, int(total * 0.6)))
        if 0 <= sel < total and sel >= threshold:
            self._trigger_load_more(manual=False)

    def _trigger_load_more(self, manual: bool = False) -> None:
        level = self._level
        log_debug("DIALOG", "_trigger_load_more called: manual=%s, is_fetching=%s, has_more=%s, stype='%s', target='%s', start_idx=%d, bsize=%d",
                  manual, level.is_fetching, level.has_more, level.source_type, level.source_target, level.next_start_idx, level.batch_size)
        if not level.has_more:
            if manual:
                _ui_message(_("No more items found."))
            return

        if level.is_fetching:
            if manual:
                _ui_message(_("Loading more items, please wait..."))
                self._manual_load_requested = True
            return

        level.is_fetching = True
        self._manual_load_requested = self._manual_load_requested or manual
        if manual:
            _ui_message(_("Loading more items..."))

        stype = level.source_type
        target = level.source_target
        start_idx = level.next_start_idx
        bsize = level.batch_size

        def worker() -> None:
            new_items: List[StreamItem] = []
            error: Optional[Exception] = None
            log_debug("WORKER", "Paging worker starting: stype='%s', target='%s', start_idx=%d, bsize=%d", stype, target, start_idx, bsize)
            t0 = time.time()
            try:
                if stype == "search":
                    new_items = stream_engine.search_youtube(target, limit=bsize, start_index=start_idx)
                elif stype == "listing":
                    _t, new_items = stream_engine.fetch_listing(target, limit=bsize, start_index=start_idx)
            except Exception as e:
                logger.warning("Dynamic page load failed (%s, start=%d): %s", stype, start_idx, e)
                log_exception("WORKER", f"Dynamic page load failed ({stype}, start={start_idx})", e)
                error = e
                new_items = []
            finally:
                t1 = time.time()
                log_debug("WORKER", "Paging worker finished in %.2fs: returned %d items (error: %s)", t1 - t0, len(new_items), error)
                # Always schedule the callback — even on error — so is_fetching is cleared
                try:
                    wx.CallAfter(self._on_page_loaded, level, start_idx, bsize, new_items)
                except Exception as ex:
                    log_exception("WORKER", "Failed to schedule wx.CallAfter for _on_page_loaded", ex)
                    level.is_fetching = False

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-AutoPaging").start()

    def _on_page_loaded(self, level: _Level, start_idx: int, bsize: int, new_items: List[StreamItem]) -> None:
        if not self or not hasattr(self, "listCtrl") or not self.listCtrl:
            return
        try:
            if not getattr(self.listCtrl, "thisown", True):
                return
        except Exception:
            return

        level.is_fetching = False
        manual = getattr(self, "_manual_load_requested", False)
        self._manual_load_requested = False

        log_debug("DIALOG", "_on_page_loaded entered: start_idx=%d, bsize=%d, new_items=%d, manual=%s, is_current_level=%s",
                  start_idx, bsize, len(new_items), manual, (self._level is level))

        # No items at all → definitely no more pages
        if not new_items:
            level.has_more = False
            log_debug("DIALOG", "_on_page_loaded: new_items is empty -> setting has_more=False")
            if self._level is level and hasattr(self, "listCtrl") and self.listCtrl:
                cur_sel = self.listCtrl.GetFirstSelected()
                self._refresh_list(select=cur_sel)
                if manual:
                    _ui_message(_("No more items found."))
            return

        # Deduplicate against already-displayed items
        existing_urls = {it.url for it in level.items}
        filtered = [it for it in new_items if it.url not in existing_urls]

        log_debug("DIALOG", "_on_page_loaded: deduplicated items from %d to %d (existing items: %d)",
                  len(new_items), len(filtered), len(level.items))

        # Always advance next_start_idx so we don't re-fetch the same page
        level.next_start_idx = start_idx + len(new_items)

        # has_more: True only if we got a FULL page
        level.has_more = len(new_items) >= bsize

        if not filtered:
            # All duplicates — nothing new to show
            log_debug("DIALOG", "_on_page_loaded: all items were duplicates! has_more=%s", level.has_more)
            if self._level is level and hasattr(self, "listCtrl") and self.listCtrl:
                cur_sel = self.listCtrl.GetFirstSelected()
                self._refresh_list(select=cur_sel)
                if manual:
                    if level.has_more:
                        self._trigger_load_more(manual=True)
                    else:
                        _ui_message(_("No more items found."))
            return

        prev_count = len(level.items)
        level.items.extend(filtered)

        if self._level is level and hasattr(self, "listCtrl") and self.listCtrl:
            list_count_before = self.listCtrl.GetItemCount()
            had_placeholder = list_count_before > prev_count
            log_debug("DIALOG", "_on_page_loaded updating listCtrl: prev_items=%d, new_items=%d, total_now=%d, list_before=%d, had_placeholder=%s",
                      prev_count, len(filtered), len(level.items), list_count_before, had_placeholder)

            if had_placeholder:
                # Remove the old placeholder from the end
                self.listCtrl.DeleteItem(self.listCtrl.GetItemCount() - 1)

            # Append all new unique items directly to wx.ListCtrl without resetting content
            for it in filtered:
                self.listCtrl.InsertItem(self.listCtrl.GetItemCount(), _item_display(it))

            # Add new placeholder if more pages exist
            if level.has_more and level.source_type in ("search", "listing"):
                self.listCtrl.InsertItem(self.listCtrl.GetItemCount(), _item_display(StreamItem(LOAD_MORE_KIND, "", _("— [Load more items...] —"))))

            # Update internal display_items
            display_items = list(level.items)
            if level.has_more and level.source_type in ("search", "listing"):
                display_items.append(StreamItem(LOAD_MORE_KIND, "", _("— [Load more items...] —")))
            self._display_items = display_items

            current_sel = self.listCtrl.GetFirstSelected()
            if manual or current_sel >= prev_count:
                target_sel = prev_count
                log_debug("DIALOG", "_on_page_loaded moving selection to target_sel=%d (new listCtrl count: %d)",
                          target_sel, self.listCtrl.GetItemCount())
                self._set_selection(target_sel)
                if hasattr(self, "FindFocus") and self.FindFocus() is self.listCtrl:
                    self.listCtrl.SetFocus()
                self._update_buttons()
                _ui_message(_("%d more items loaded: %s") % (len(filtered), _item_display(level.items[target_sel])))
            else:
                log_debug("DIALOG", "_on_page_loaded silently expanded list to %d items (user remains on item %d)",
                          self.listCtrl.GetItemCount(), current_sel)
                self._update_buttons()

    def onActivate(self, evt: Any) -> None:
        """Enter / double-click: play videos/shorts, drill into playlists & channels, or load more."""
        item = self._current_item()
        log_debug("DIALOG", "onActivate clicked on item: %s", getattr(item, 'title', None))
        if not item or self._busy:
            return
        if item.kind == LOAD_MORE_KIND:
            self._trigger_load_more(manual=True)
            return
        if item.kind in (ITEM_VIDEO, ITEM_SHORTS):
            self._play_video(item)
        elif item.kind == ITEM_CHANNEL:
            self._enter_channel(item)
        else:
            self._enter_listing(item)

    def onPlayPlaylist(self, evt: Any) -> None:
        item = self._current_item()
        if self._busy or not item or item.kind == LOAD_MORE_KIND:
            return
        if item.kind in (ITEM_PLAYLIST, ITEM_LISTING):
            self._close_and(lambda: self.controller.play_stream_listing(
                item.url, listing_title=item.title))
        elif self._level.items:
            # Play the whole current level as a queue from the selected item
            sel = max(0, self.listCtrl.GetFirstSelected())
            source_target = self._level.source_target if self._level.source_type in ("listing", "search") else None
            source_type = self._level.source_type
            batch_size = self._level.batch_size
            lvl_items = [it for it in self._level.items if it.kind in (ITEM_VIDEO, ITEM_SHORTS)]
            if not lvl_items:
                lvl_items = self._level.items
            self._close_and(lambda: self.controller.play_stream_items(
                lvl_items,
                start_index=sel,
                listing_title=self._level.title,
                source_target=source_target,
                source_type=source_type,
                batch_size=batch_size,
            ))

    def onBack(self, evt: Any) -> None:
        if self._stack:
            level, sel = self._stack.pop()
            self._level = level
            self._refresh_list(select=sel)
            self.listCtrl.SetFocus()

    # -- actions -----------------------------------------------------------

    def _play_video(self, item: StreamItem) -> None:
        # Queue all playable items in the current level so playback continues smoothly through the search/listing
        videos = [it for it in self._level.items if it.kind in (ITEM_VIDEO, ITEM_SHORTS)]
        if not videos:
            videos = [item]
        try:
            start = videos.index(item)
        except ValueError:
            start = 0
        lvl_title = self._level.title
        source_target = self._level.source_target if self._level.source_type in ("search", "listing") else None
        source_type = self._level.source_type
        batch_size = self._level.batch_size
        self._close_and(lambda: self.controller.play_stream_items(
            videos,
            start_index=start,
            listing_title=lvl_title,
            source_target=source_target,
            source_type=source_type,
            batch_size=batch_size,
        ))

    def _enter_channel(self, item: StreamItem) -> None:
        # Channels expand instantly to synthetic sections (Videos / Shorts / Playlists / Live)
        self._push_level(_Level(
            item.title,
            _channel_sections(item),
            False,
            source_type="channel_sections",
            source_target=item.url,
            has_more=False,
        ))

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
                limit = int(getConfig().get("maxStreamPlaylistItems", 50))
            except Exception:
                limit = 50
            try:
                title, sub_items = stream_engine.fetch_listing(item.url, limit=limit, start_index=1)
            except Exception as e:
                logger.error("Listing fetch failed: %s", e)
                wx.CallAfter(self._on_listing_failed, str(e))
                return
            wx.CallAfter(self._on_listing_loaded, item, title, sub_items, limit)

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-Listing").start()

    def _on_listing_failed(self, error_text: str = "") -> None:
        if not self or not hasattr(self, "listCtrl") or not self.listCtrl:
            return
        self._busy = False
        if stream_engine.is_cookie_error(error_text):
            _ui_message(_(
                "Could not read sign-in cookies from your browser. "
                "Set a manual cookies.txt file in HeadlessPlayer settings instead."
            ))
        else:
            _ui_message(_("Could not load this item. Check your connection or update yt-dlp from settings."))

    def _on_listing_loaded(self, item: StreamItem, title: str, sub_items: List[StreamItem], batch_size: int = 50) -> None:
        if not self or not hasattr(self, "listCtrl") or not self.listCtrl:
            return
        try:
            if not getattr(self.listCtrl, "thisown", True):
                return
        except Exception:
            return
        self._busy = False
        if not sub_items:
            _ui_message(_("No items found."))
            return
        is_queue = item.kind in (ITEM_PLAYLIST, ITEM_LISTING) and any(
            it.kind in (ITEM_VIDEO, ITEM_SHORTS) for it in sub_items
        )
        self._push_level(_Level(
            title or item.title,
            sub_items,
            is_queue,
            source_type="listing",
            source_target=item.url,
            batch_size=batch_size,
            has_more=bool(sub_items and len(sub_items) >= batch_size),
        ))

    def _push_level(self, level: _Level) -> None:
        self._stack.append((self._level, max(0, self.listCtrl.GetFirstSelected())))
        self._level = level
        self._refresh_list()
        self.listCtrl.SetFocus()
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
