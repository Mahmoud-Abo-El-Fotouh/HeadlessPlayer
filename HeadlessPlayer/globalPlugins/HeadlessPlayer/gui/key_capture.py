# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Key capture dialog and shortcut suggestion mapping for Headless Media Player.
"""

import logging
import sys
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("HeadlessPlayer.KeyCapture")

try:
    import addonHandler
    addonHandler.initTranslation()
except Exception:
    pass

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

try:
    import wx
    import gui
    from gui import guiHelper
except Exception:
    wx = None
    gui = None
    guiHelper = None


def _get_wx() -> Any:
    if wx is not None:
        return wx
    for mod_name in (
        "globalPlugins.HeadlessPlayer.gui.key_capture",
        "globalPlugins.HeadlessPlayer.gui.shortcuts_dialog",
        "globalPlugins.HeadlessPlayer.gui.settings_panel",
        "globalPlugins.HeadlessPlayer.settings_panel",
    ):
        m = sys.modules.get(mod_name)
        if m and getattr(m, "wx", None) is not None:
            return m.wx
    return None


ACTION_DISPLAY_NAMES: List[Tuple[str, str]] = [
    ("play_pause", _("Play / Pause toggle")),
    ("stop", _("Stop and rewind to beginning")),
    ("mute", _("Mute / Unmute audio")),
    ("vol_up", _("Volume Up (+5%)")),
    ("vol_down", _("Volume Down (-5%)")),
    ("bass_up", _("Bass Up (+3 dB)")),
    ("bass_down", _("Bass Down (-3 dB)")),
    ("seek_forward", _("Normal Seek Forward")),
    ("seek_backward", _("Normal Seek Backward")),
    ("seek_slow_forward", _("Slow / Precise Seek Forward")),
    ("seek_slow_backward", _("Slow / Precise Seek Backward")),
    ("seek_fast_forward", _("Fast Seek Forward")),
    ("seek_fast_backward", _("Fast Seek Backward")),
    ("seek_ultrafast_forward", _("Ultrafast Seek Forward")),
    ("seek_ultrafast_backward", _("Ultrafast Seek Backward")),
    ("speed_up", _("Fine Speed Up (+0.1x)")),
    ("speed_down", _("Fine Speed Down (-0.1x)")),
    ("speed_preset_up", _("Next Preset Speed")),
    ("speed_preset_down", _("Previous Preset Speed")),
    ("next_track", _("Next Track in Playlist")),
    ("prev_track", _("Previous Track in Playlist")),
    ("track_start", _("Jump to start of current track")),
    ("track_end", _("Jump to end of current track")),
    ("first_track", _("First Track in Playlist")),
    ("last_track", _("Last Track in Playlist")),
    ("next_chapter", _("Next Chapter")),
    ("prev_chapter", _("Previous Chapter")),
    ("point_a", _("Mark A-B Loop Start (Point A)")),
    ("point_b", _("Mark A-B Loop End (Point B)")),
    ("toggle_repeat", _("Toggle Repeat Mode")),
    ("clear_loop", _("Clear A-B Loop Points")),
    ("open_file", _("Open File Dialog")),
    ("open_folder", _("Open Folder Dialog")),
    ("open_url", _("Open URL / YouTube Search Box")),
    ("copy_url", _("Copy Current Track Link / Path to Clipboard")),
    ("account_feed", _("Open YouTube Account & Feeds Browser")),
    ("load_explorer", _("Load from Windows Explorer")),
    ("toggle_auto_next", _("Toggle Auto-Next")),
    ("toggle_shuffle", _("Toggle Shuffle")),
    ("media_info", _("Speak Full Media Info")),
    ("remaining_time", _("Speak Remaining Time")),
    ("elapsed_time", _("Speak Elapsed Time")),
    ("show_help", _("Show Shortcuts Help Dialog")),
    ("cycle_audio_track", _("Cycle Audio Track / Languages")),
    ("copy_direct_url", _("Copy Direct Audio Link of Current Stream")),
    ("export_clip", _("Export / Download Clip (A-B selection or whole item)")),
    ("quick_export", _("Quick Export with remembered settings")),
    ("recent_playlist_next", _("Recent Playlists: Next / Newer")),
    ("recent_playlist_prev", _("Recent Playlists: Previous / Older")),
    ("recent_playlist_first", _("Recent Playlists: Jump to Oldest")),
    ("recent_playlist_last", _("Recent Playlists: Jump to Newest")),
    ("recent_track_next", _("Recent Tracks: Next / Newer")),
    ("recent_track_prev", _("Recent Tracks: Previous / Older")),
    ("recent_track_first", _("Recent Tracks: Jump to Oldest")),
    ("recent_track_last", _("Recent Tracks: Jump to Newest")),
    ("recent_delete", _("Remove Focused Recent Item from History")),
    ("open_settings", _("Open HeadlessPlayer Settings Panel")),
    ("close_player", _("Close Player (Quit)")),
    ("exit_mode", _("Exit Player Mode")),
]

ACTION_CATEGORIES: List[Tuple[str, str]] = [
    ("all", _("All Actions")),
    ("playback", _("Playback & Core Controls")),
    ("navigation", _("Navigation & Chapters")),
    ("recents", _("Recent Media & History")),
    ("audio", _("Audio, Volume & Speed")),
    ("streaming", _("Files, Streaming & Information")),
]

ACTION_CATEGORY_MAP: Dict[str, str] = {
    "copy_direct_url": "streaming",
    "export_clip": "streaming",
    "quick_export": "streaming",
    "open_settings": "streaming",
    "play_pause": "playback",
    "stop": "playback",
    "point_a": "playback",
    "point_b": "playback",
    "toggle_repeat": "playback",
    "clear_loop": "playback",
    "toggle_auto_next": "playback",
    "toggle_shuffle": "playback",
    "close_player": "playback",
    "exit_mode": "playback",
    "show_help": "playback",

    "seek_forward": "navigation",
    "seek_backward": "navigation",
    "seek_slow_forward": "navigation",
    "seek_slow_backward": "navigation",
    "seek_fast_forward": "navigation",
    "seek_fast_backward": "navigation",
    "seek_ultrafast_forward": "navigation",
    "seek_ultrafast_backward": "navigation",
    "next_track": "navigation",
    "prev_track": "navigation",
    "track_start": "navigation",
    "track_end": "navigation",
    "first_track": "navigation",
    "last_track": "navigation",
    "next_chapter": "navigation",
    "prev_chapter": "navigation",

    "recent_playlist_next": "recents",
    "recent_playlist_prev": "recents",
    "recent_playlist_first": "recents",
    "recent_playlist_last": "recents",
    "recent_track_next": "recents",
    "recent_track_prev": "recents",
    "recent_track_first": "recents",
    "recent_track_last": "recents",
    "recent_delete": "recents",

    "mute": "audio",
    "vol_up": "audio",
    "vol_down": "audio",
    "bass_up": "audio",
    "bass_down": "audio",
    "speed_up": "audio",
    "speed_down": "audio",
    "speed_preset_up": "audio",
    "speed_preset_down": "audio",
    "cycle_audio_track": "audio",

    "open_file": "streaming",
    "open_folder": "streaming",
    "open_url": "streaming",
    "copy_url": "streaming",
    "account_feed": "streaming",
    "load_explorer": "streaming",
    "media_info": "streaming",
    "remaining_time": "streaming",
    "elapsed_time": "streaming",
}


def get_all_key_suggestions() -> List[Tuple[str, str]]:
    """
    Returns list of (canonical_key_id, display_label) for keyboard keys and shortcuts.
    Provides searchable English and Arabic suggestions.
    """
    return [
        ("space", "Space"),
        ("control", "Control"),
        ("shift", "Shift"),
        ("alt", "Alt"),
        ("tab", "Tab"),
        ("shift+tab", "Shift + Tab"),
        ("escape", "Escape"),
        ("return", "Enter / Return"),
        ("backspace", "Backspace"),
        ("pagedown", "Page Down"),
        ("pageup", "Page Up"),
        ("home", "Home"),
        ("end", "End"),
        ("control+home", "Control + Home"),
        ("control+end", "Control + End"),
        ("shift+home", "Shift + Home"),
        ("shift+end", "Shift + End"),
        ("insert", "Insert"),
        ("delete", "Delete"),
        ("leftarrow", "Left Arrow"),
        ("rightarrow", "Right Arrow"),
        ("uparrow", "Up Arrow"),
        ("downarrow", "Down Arrow"),
        ("alt+leftarrow", "Alt + Left Arrow"),
        ("alt+rightarrow", "Alt + Right Arrow"),
        ("alt+uparrow", "Alt + Up Arrow"),
        ("alt+downarrow", "Alt + Down Arrow"),
        ("control+leftarrow", "Control + Left Arrow"),
        ("control+rightarrow", "Control + Right Arrow"),
        ("control+uparrow", "Control + Up Arrow"),
        ("control+downarrow", "Control + Down Arrow"),
        ("shift+leftarrow", "Shift + Left Arrow"),
        ("shift+rightarrow", "Shift + Right Arrow"),
        ("shift+uparrow", "Shift + Up Arrow"),
        ("shift+downarrow", "Shift + Down Arrow"),
        ("control+shift+leftarrow", "Control + Shift + Left Arrow"),
        ("control+shift+rightarrow", "Control + Shift + Right Arrow"),
        ("a", "A"),
        ("b", "B"),
        ("c", "C"),
        ("d", "D"),
        ("e", "E"),
        ("f", "F"),
        ("g", "G"),
        ("h", "H"),
        ("i", "I"),
        ("j", "J"),
        ("k", "K"),
        ("l", "L"),
        ("m", "M"),
        ("n", "N"),
        ("o", "O"),
        ("p", "P"),
        ("q", "Q"),
        ("r", "R"),
        ("s", "S"),
        ("t", "T"),
        ("u", "U"),
        ("v", "V"),
        ("w", "W"),
        ("x", "X"),
        ("y", "Y"),
        ("z", "Z"),
        ("control+i", "Control + I"),
        ("shift+i", "Shift + I"),
        ("shift+b", "Shift + B"),
        ("control+a", "Control + A"),
        ("control+s", "Control + S"),
        ("control+space", "Control + Space"),
        ("shift+space", "Shift + Space"),
        ("alt+space", "Alt + Space"),
        (".", "."),
        (",", ","),
        ("shift+.", "Shift + ."),
        ("shift+,", "Shift + ,"),
        ("control+.", "Control + ."),
        ("control+,", "Control + ,"),
        ("control+shift+.", "Control + Shift + ."),
        ("control+shift+,", "Control + Shift + ,"),
        ("control+shift+s", "Control + Shift + S"),
        ("0", "0 (0%)"),
        ("1", "1 (10%)"),
        ("2", "2 (20%)"),
        ("3", "3 (30%)"),
        ("4", "4 (40%)"),
        ("5", "5 (50%)"),
        ("6", "6 (60%)"),
        ("7", "7 (70%)"),
        ("8", "8 (80%)"),
        ("9", "9 (90%)"),
        ("f1", "F1"),
        ("f2", "F2"),
        ("f3", "F3"),
        ("f4", "F4"),
        ("f5", "F5"),
        ("f6", "F6"),
        ("f7", "F7"),
        ("f8", "F8"),
        ("f9", "F9"),
        ("f10", "F10"),
        ("f11", "F11"),
        ("f12", "F12"),
        ("[", "[ Left Bracket"),
        ("]", "] Right Bracket"),
        (";", "; Semicolon"),
        ("'", "' Quote"),
        (",", ", Comma"),
        (".", ". Period"),
        ("/", "/ Slash"),
        ("-", "- Minus"),
        ("=", "= Equals"),
    ]


ARABIC_TO_ENGLISH_KEY_MAP: Dict[str, str] = {
    "ض": "q", "ص": "w", "ث": "e", "ق": "r", "ف": "t", "غ": "y", "ع": "u",
    "ه": "i", "خ": "o", "ح": "p", "ج": "[", "د": "]", "ش": "a", "س": "s",
    "ي": "d", "ب": "f", "ل": "g", "ا": "h", "أ": "h", "إ": "h", "آ": "h",
    "ت": "j", "ن": "k", "م": "l", "ك": ";", "ط": "'", "ئ": "z", "ء": "x",
    "ؤ": "c", "ر": "v", "ى": "n", "ة": "m", "و": ",", "ز": ".", "ظ": "/",
    "لا": "b", "لأ": "b", "لإ": "b", "لآ": "b",
    "ذ": "`", "؛": ";", "،": ",", "؟": "/", "ـ": "-", "«": "[", "»": "]",
}


_WxDialog = getattr(wx, "Dialog", object) if wx else object


class KeyCaptureDialog(_WxDialog):
    """
    Modal dialog to directly intercept and capture a keypress from the keyboard.
    """

    def __init__(self, parent: Any) -> None:
        _wx = _get_wx()
        if not _wx:
            return
        super().__init__(
            parent,
            title=_("Press Shortcut Key"),
            style=_wx.DEFAULT_DIALOG_STYLE
        )
        self.captured_key: Optional[str] = None
        self.InitUI()
        self.CenterOnParent()

    def InitUI(self) -> None:
        _wx = _get_wx()
        if not _wx or not guiHelper:
            return
        mainSizer = _wx.BoxSizer(_wx.VERTICAL)
        helper = guiHelper.BoxSizerHelper(self, sizer=mainSizer)

        prompt = _wx.StaticText(
            self,
            label=_(
                "Press any key or key combination on your keyboard now to assign it.\n"
                "Press Escape to cancel."
            )
        )
        helper.addItem(prompt)

        self.statusText = _wx.StaticText(self, label=_("Waiting for key press..."))
        helper.addItem(self.statusText)

        if hasattr(_wx, "Button"):
            self.cancelBtn = _wx.Button(self, _wx.ID_CANCEL, label=_("Cancel"))
            helper.addItem(self.cancelBtn)

        self.SetSizerAndFit(mainSizer)

        if hasattr(self, "Bind") and hasattr(_wx, "EVT_CHAR_HOOK"):
            self.Bind(_wx.EVT_CHAR_HOOK, self.onCharHook)

    def onCharHook(self, evt: Any) -> None:
        _wx = _get_wx()
        if not _wx:
            return

        key_code = evt.GetKeyCode()
        if key_code == _wx.WXK_ESCAPE and not (evt.ControlDown() or evt.AltDown() or evt.ShiftDown()):
            self.EndModal(_wx.ID_CANCEL)
            return

        # If only a modifier key itself was pressed, update prompt status and wait for base key
        if key_code in (_wx.WXK_CONTROL, getattr(_wx, "WXK_RAW_CONTROL", -1), _wx.WXK_SHIFT, _wx.WXK_ALT):
            mods = []
            if evt.ControlDown():
                mods.append("Control")
            if evt.AltDown():
                mods.append("Alt")
            if evt.ShiftDown():
                mods.append("Shift")
            if mods:
                self.statusText.SetLabel(_("Holding %s... Press a key to combine.") % (" + ".join(mods)))
            # Do not call evt.Skip(): skipping Alt activates the Windows window menu loop and corrupts capture
            return

        mods = []
        if evt.ControlDown():
            mods.append("control")
        if evt.AltDown():
            mods.append("alt")
        if evt.ShiftDown():
            mods.append("shift")

        key_name = ""
        if key_code == _wx.WXK_SPACE:
            key_name = "space"
        elif key_code == _wx.WXK_LEFT:
            key_name = "leftarrow"
        elif key_code == _wx.WXK_RIGHT:
            key_name = "rightarrow"
        elif key_code == _wx.WXK_UP:
            key_name = "uparrow"
        elif key_code == _wx.WXK_DOWN:
            key_name = "downarrow"
        elif key_code == _wx.WXK_PAGEUP:
            key_name = "pageup"
        elif key_code == _wx.WXK_PAGEDOWN:
            key_name = "pagedown"
        elif key_code == _wx.WXK_HOME:
            key_name = "home"
        elif key_code == _wx.WXK_END:
            key_name = "end"
        elif key_code == _wx.WXK_INSERT:
            key_name = "insert"
        elif key_code == _wx.WXK_DELETE:
            key_name = "delete"
        elif key_code == _wx.WXK_TAB:
            key_name = "tab"
        elif key_code in (_wx.WXK_RETURN, getattr(_wx, "WXK_NUMPAD_ENTER", -1)):
            key_name = "return"
        elif key_code == _wx.WXK_BACK:
            key_name = "backspace"
        elif ord('A') <= key_code <= ord('Z'):
            key_name = chr(key_code).lower()
        elif ord('0') <= key_code <= ord('9'):
            key_name = chr(key_code)
        elif _wx.WXK_F1 <= key_code <= _wx.WXK_F12:
            f_num = key_code - _wx.WXK_F1 + 1
            key_name = f"f{f_num}"
        else:
            try:
                ch = chr(key_code).lower()
                if ch in ARABIC_TO_ENGLISH_KEY_MAP:
                    key_name = ARABIC_TO_ENGLISH_KEY_MAP[ch]
                elif ch in ("[]();',./-="):
                    key_name = ch
            except Exception:
                pass

        if key_name:
            combo = "+".join(mods + [key_name]) if mods else key_name
            self.captured_key = combo
            self.EndModal(_wx.ID_OK)
        else:
            evt.Skip()
