# -*- coding: utf-8 -*-
from __future__ import annotations
"""
HeadlessPlayer Settings Panel for NVDA Preferences -> Settings Dialog.
Provides accessible wxPython configuration controls for speech feedback, seek step sizes, and playback defaults.
"""

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple
import webbrowser

logger = logging.getLogger("HeadlessPlayer.SettingsPanel")

try:
    import addonHandler
    addonHandler.initTranslation()
except Exception:
    pass

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
    from gui.settingsDialogs import SettingsPanel
except Exception:
    # Fallback placeholders when running in environments without wx/gui
    wx = None
    gui = None
    guiHelper = None

    class SettingsPanel:  # type: ignore
        title = ""
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

try:
    import ui
except Exception:
    ui = None

from .config_spec import (
    getConfig,
    saveConfig,
    setConfigValue,
    DEFAULT_KEYMAP,
    getKeymap,
    setKeymap,
)

try:
    from . import stream_engine
except Exception:
    try:
        import stream_engine
    except Exception:
        stream_engine = None

try:
    from . import addon_updater
    from .addon_updater import AddonUpdateDialog
except Exception:
    try:
        import addon_updater
        from addon_updater import AddonUpdateDialog
    except Exception:
        addon_updater = None
        AddonUpdateDialog = None

try:
    from .controller import get_controller
except Exception:
    def get_controller() -> Any:
        return None

try:
    from .engine import get_engine
except Exception:
    def get_engine() -> Any:
        return None

try:
    from .state_store import get_state_store
except Exception:
    def get_state_store() -> Any:
        return None


ACTION_DISPLAY_NAMES: List[Tuple[str, str]] = [
    ("play_pause", _("Play / Pause toggle")),
    ("stop", _("Stop and rewind to beginning")),
    ("mute", _("Mute / Unmute audio")),
    ("vol_up", _("Volume Up (+5%)")),
    ("vol_down", _("Volume Down (-5%)")),
    ("bass_up", _("Bass Up (+3 dB)")),
    ("bass_down", _("Bass Down (-3 dB)")),
    ("seek_forward", _("Normal Seek Forward (Right Arrow)")),
    ("seek_backward", _("Normal Seek Backward (Left Arrow)")),
    ("seek_slow_forward", _("Slow / Precise Seek Forward (Alt+Right)")),
    ("seek_slow_backward", _("Slow / Precise Seek Backward (Alt+Left)")),
    ("seek_fast_forward", _("Fast Seek Forward (Ctrl+Right)")),
    ("seek_fast_backward", _("Fast Seek Backward (Ctrl+Left)")),
    ("seek_ultrafast_forward", _("Ultrafast Seek Forward (Shift+Right)")),
    ("seek_ultrafast_backward", _("Ultrafast Seek Backward (Shift+Left)")),
    ("speed_up", _("Fine Speed Up (+0.1x)")),
    ("speed_down", _("Fine Speed Down (-0.1x)")),
    ("speed_preset_up", _("Next Preset Speed")),
    ("speed_preset_down", _("Previous Preset Speed")),
    ("next_track", _("Next Track in Playlist")),
    ("prev_track", _("Previous Track in Playlist")),
    ("track_start", _("Jump to start of current track (Home)")),
    ("track_end", _("Jump to end of current track (End)")),
    ("first_track", _("First Track in Playlist (Control+Home)")),
    ("last_track", _("Last Track in Playlist (Control+End)")),
    ("next_chapter", _("Next Chapter (Ctrl+Shift+Right)")),
    ("prev_chapter", _("Previous Chapter (Ctrl+Shift+Left)")),
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
    ("recent_playlist_next", _("Recent Playlists: Next / Newer (Ctrl+.)")),
    ("recent_playlist_prev", _("Recent Playlists: Previous / Older (Ctrl+,)")),
    ("recent_playlist_first", _("Recent Playlists: Jump to Oldest (Ctrl+Shift+,)")),
    ("recent_playlist_last", _("Recent Playlists: Jump to Newest (Ctrl+Shift+.)")),
    ("recent_track_next", _("Recent Tracks: Next / Newer (.)")),
    ("recent_track_prev", _("Recent Tracks: Previous / Older (,)")),
    ("recent_track_first", _("Recent Tracks: Jump to Oldest (Shift+,)")),
    ("recent_track_last", _("Recent Tracks: Jump to Newest (Shift+.)")),
    ("recent_delete", _("Remove Focused Recent Item from History (Delete)")),
    ("open_settings", _("Open HeadlessPlayer Settings Panel (Ctrl+Shift+S)")),
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
}


_WxDialog = getattr(wx, "Dialog", object) if wx else object


class KeyCaptureDialog(_WxDialog):
    """
    Modal dialog to directly intercept and capture a keypress from the keyboard.
    """

    def __init__(self, parent: Any) -> None:
        if not wx:
            return
        super().__init__(
            parent,
            title=_("Press Shortcut Key"),
            style=wx.DEFAULT_DIALOG_STYLE
        )
        self.captured_key: Optional[str] = None
        self.InitUI()
        self.CenterOnParent()

    def InitUI(self) -> None:
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        helper = guiHelper.BoxSizerHelper(self, sizer=mainSizer)

        prompt = wx.StaticText(
            self,
            label=_(
                "Press any key or key combination on your keyboard now to assign it.\n"
                "Press Escape to cancel."
            )
        )
        helper.addItem(prompt)

        self.statusText = wx.StaticText(self, label=_("Waiting for key press..."))
        helper.addItem(self.statusText)

        if hasattr(wx, "Button"):
            self.cancelBtn = wx.Button(self, wx.ID_CANCEL, label=_("Cancel"))
            helper.addItem(self.cancelBtn)

        self.SetSizerAndFit(mainSizer)

        if hasattr(self, "Bind") and hasattr(wx, "EVT_CHAR_HOOK"):
            self.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)

    def onCharHook(self, evt: Any) -> None:
        key_code = evt.GetKeyCode()
        if key_code == wx.WXK_ESCAPE and not (evt.ControlDown() or evt.AltDown() or evt.ShiftDown()):
            self.EndModal(wx.ID_CANCEL)
            return

        # If only a modifier key itself was pressed, update prompt status and wait for base key
        if key_code in (wx.WXK_CONTROL, getattr(wx, "WXK_RAW_CONTROL", -1), wx.WXK_SHIFT, wx.WXK_ALT):
            mods = []
            if evt.ControlDown():
                mods.append("Control")
            if evt.AltDown():
                mods.append("Alt")
            if evt.ShiftDown():
                mods.append("Shift")
            if mods:
                self.statusText.SetLabel(_("Holding %s... Press a key to combine.") % (" + ".join(mods)))
            evt.Skip()
            return

        mods = []
        if evt.ControlDown():
            mods.append("control")
        if evt.AltDown():
            mods.append("alt")
        if evt.ShiftDown():
            mods.append("shift")

        key_name = ""
        if key_code == wx.WXK_SPACE:
            key_name = "space"
        elif key_code == wx.WXK_LEFT:
            key_name = "leftarrow"
        elif key_code == wx.WXK_RIGHT:
            key_name = "rightarrow"
        elif key_code == wx.WXK_UP:
            key_name = "uparrow"
        elif key_code == wx.WXK_DOWN:
            key_name = "downarrow"
        elif key_code == wx.WXK_PAGEUP:
            key_name = "pageup"
        elif key_code == wx.WXK_PAGEDOWN:
            key_name = "pagedown"
        elif key_code == wx.WXK_HOME:
            key_name = "home"
        elif key_code == wx.WXK_END:
            key_name = "end"
        elif key_code == wx.WXK_INSERT:
            key_name = "insert"
        elif key_code == wx.WXK_DELETE:
            key_name = "delete"
        elif key_code == wx.WXK_TAB:
            key_name = "tab"
        elif key_code in (wx.WXK_RETURN, getattr(wx, "WXK_NUMPAD_ENTER", -1)):
            key_name = "return"
        elif key_code == wx.WXK_BACK:
            key_name = "backspace"
        elif ord('A') <= key_code <= ord('Z'):
            key_name = chr(key_code).lower()
        elif ord('0') <= key_code <= ord('9'):
            key_name = chr(key_code)
        elif wx.WXK_F1 <= key_code <= wx.WXK_F12:
            f_num = key_code - wx.WXK_F1 + 1
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
            self.EndModal(wx.ID_OK)
        else:
            evt.Skip()


class HeadlessPlayerShortcutsDialog(_WxDialog):
    """
    Accessible configuration dialog for customizing Player Mode keyboard shortcuts
    with real-time searchable auto-complete suggestions and direct key capture.
    """

    def __init__(self, parent: Any) -> None:
        if not wx:
            return
        super().__init__(
            parent,
            title=_("Customize Player Mode Shortcuts"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        self.current_keymap = getKeymap()
        self.all_suggestions = get_all_key_suggestions()
        self.filtered_suggestions = list(self.all_suggestions)
        self.visible_actions: List[Tuple[str, str]] = list(ACTION_DISPLAY_NAMES)
        self.InitUI()
        self.CenterOnParent()

    def InitUI(self) -> None:
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        helper = guiHelper.BoxSizerHelper(self, sizer=mainSizer)

        introText = wx.StaticText(
            self,
            label=_(
                "Select a player action, then choose or search a key from the suggestions list,\n"
                "or press the 'Capture Key Directly' button to assign by pressing any key on your keyboard."
            )
        )
        helper.addItem(introText)

        # 0. Action Category Filter
        catChoices = [label for _val, label in ACTION_CATEGORIES]
        self.actionCategoryChoice = helper.addLabeledControl(
            _("&Filter Actions by Category:"),
            wx.Choice,
            choices=catChoices
        )
        self.actionCategoryChoice.SetSelection(0)
        self.actionCategoryChoice.Bind(wx.EVT_CHOICE, self.onCategoryChanged)

        # 1. Action Choice (displays Action Name + currently assigned shortcut for instant screen reader feedback)
        actionLabels = self._get_action_choice_labels()
        self.actionChoice = helper.addLabeledControl(
            _("&Player Action:"),
            wx.Choice,
            choices=actionLabels
        )
        self.actionChoice.SetSelection(0)
        self.actionChoice.Bind(wx.EVT_CHOICE, self.onActionChanged)

        # 2. Current assigned key indicator
        initial_action = self.visible_actions[0][0] if self.visible_actions else ACTION_DISPLAY_NAMES[0][0]
        initial_key = self.current_keymap.get(initial_action, "")
        self.currentKeyStatus = wx.StaticText(
            self,
            label=_("Current assigned key: %s") % self._format_key_display(initial_key)
        )
        helper.addItem(self.currentKeyStatus)

        # 2b. Secondary shortcut mode checkbox:
        # when checked, assignments are ADDED as an extra shortcut for the action
        # (e.g. Next Track = Page Down AND Tab) instead of replacing the current one.
        self.secondaryChk = wx.CheckBox(
            self,
            label=_("Add as an a&dditional shortcut (keep the current one)")
        )
        helper.addItem(self.secondaryChk)

        # 3. Search / Filter Box
        self.searchCtrl = helper.addLabeledControl(
            _("&Search Key Suggestions (type e.g. 'ta', 'control', 'page', 'arrow'):"),
            wx.TextCtrl
        )
        self.searchCtrl.Bind(wx.EVT_TEXT, self.onSearchFilter)

        # 4. Searchable Suggestions ListBox
        initial_choices = [label for _val, label in self.all_suggestions]
        self.suggestionsList = wx.ListBox(
            self,
            choices=initial_choices,
            style=wx.LB_SINGLE
        )
        self.suggestionsList.Bind(wx.EVT_LISTBOX_DCLICK, self.onSuggestionDoubleClicked)
        helper.addItem(self.suggestionsList)

        # 5. Middle Action Buttons (Assign, Capture, and Delete)
        actionBtnSizer = wx.BoxSizer(wx.HORIZONTAL)
        if hasattr(wx, "Button"):
            self.assignBtn = wx.Button(self, label=_("&Assign Selected Suggestion"))
            self.assignBtn.Bind(wx.EVT_BUTTON, self.onAssignSelectedSuggestion)
            actionBtnSizer.Add(self.assignBtn, 0, wx.ALL, 5)

            self.captureBtn = wx.Button(self, label=_("&Press Key on Keyboard Directly..."))
            self.captureBtn.Bind(wx.EVT_BUTTON, self.onCaptureKeyDirectly)
            actionBtnSizer.Add(self.captureBtn, 0, wx.ALL, 5)

            self.deleteBtn = wx.Button(self, label=_("&Delete Assigned Shortcut"))
            self.deleteBtn.Bind(wx.EVT_BUTTON, self.onDeleteShortcut)
            actionBtnSizer.Add(self.deleteBtn, 0, wx.ALL, 5)

        helper.addItem(actionBtnSizer)

        # 6. Dialog Bottom Control Buttons
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        if hasattr(wx, "Button"):
            self.resetBtn = wx.Button(self, label=_("&Reset to Defaults"))
            self.resetBtn.Bind(wx.EVT_BUTTON, self.onResetDefaults)
            btnSizer.Add(self.resetBtn, 0, wx.ALL, 5)

            self.exportBtn = wx.Button(self, label=_("&Export Shortcuts (JSON)..."))
            self.exportBtn.Bind(wx.EVT_BUTTON, self.onExportShortcuts)
            btnSizer.Add(self.exportBtn, 0, wx.ALL, 5)

            self.importBtn = wx.Button(self, label=_("&Import Shortcuts (JSON)..."))
            self.importBtn.Bind(wx.EVT_BUTTON, self.onImportShortcuts)
            btnSizer.Add(self.importBtn, 0, wx.ALL, 5)

            btnSizer.AddStretchSpacer()

            self.okBtn = wx.Button(self, wx.ID_OK, label=_("OK"))
            self.okBtn.SetDefault()
            self.okBtn.Bind(wx.EVT_BUTTON, self.onSaveAndClose)
            btnSizer.Add(self.okBtn, 0, wx.ALL, 5)

            self.cancelBtn = wx.Button(self, wx.ID_CANCEL, label=_("Cancel"))
            btnSizer.Add(self.cancelBtn, 0, wx.ALL, 5)

        helper.addItem(btnSizer)
        self.SetSizerAndFit(mainSizer)

    def _get_action_choice_labels(self) -> List[str]:
        labels = []
        for action_id, action_name in self.visible_actions:
            key_str = self.current_keymap.get(action_id, "")
            key_disp = self._format_key_display(key_str)
            labels.append(f"{action_name}: {key_disp}")
        return labels

    def _refresh_action_choice(self, preserve_index: Optional[int] = None) -> None:
        sel = preserve_index if preserve_index is not None else self.actionChoice.GetSelection()
        choices = self._get_action_choice_labels()
        self.actionChoice.Set(choices)
        if choices:
            idx = min(max(0, sel), len(choices) - 1)
            self.actionChoice.SetSelection(idx)

    def onCategoryChanged(self, evt: Any) -> None:
        cat_sel = self.actionCategoryChoice.GetSelection()
        if 0 <= cat_sel < len(ACTION_CATEGORIES):
            cat_id = ACTION_CATEGORIES[cat_sel][0]
            if cat_id == "all":
                self.visible_actions = list(ACTION_DISPLAY_NAMES)
            else:
                self.visible_actions = [
                    (a_id, a_name) for a_id, a_name in ACTION_DISPLAY_NAMES
                    if ACTION_CATEGORY_MAP.get(a_id) == cat_id
                ]
            self._refresh_action_choice(0)
            self.onActionChanged(None)

    def _format_single_key_display(self, key_id: str) -> str:
        for k_id, label in self.all_suggestions:
            if k_id.lower() == key_id.lower():
                return label
        return key_id.upper() if key_id else _("(Not Set)")

    def _format_key_display(self, key_id: str) -> str:
        """Formats a keymap value which may hold multiple comma-separated shortcuts."""
        if not key_id:
            return _("(Not Set)")
        keys = [k.strip() for k in key_id.split(",") if k.strip()]
        if not keys:
            return _("(Not Set)")
        return _(" and ").join(self._format_single_key_display(k) for k in keys)

    def _assign_key(self, action_id: str, key_id: str) -> None:
        """
        Assigns key_id to action_id. When the 'additional shortcut' checkbox is
        checked, the key is added next to the existing shortcut (up to 2 keys);
        otherwise it replaces all current shortcuts for the action.
        """
        key_id = key_id.strip().lower()
        existing = [
            k.strip() for k in self.current_keymap.get(action_id, "").split(",") if k.strip()
        ]
        as_secondary = bool(getattr(self, "secondaryChk", None) and self.secondaryChk.GetValue())

        if as_secondary and existing:
            if key_id in existing:
                new_keys = existing
            elif len(existing) >= 2:
                # Keep the primary, replace the secondary
                new_keys = [existing[0], key_id]
            else:
                new_keys = existing + [key_id]
        else:
            new_keys = [key_id]

        self.current_keymap[action_id] = ",".join(new_keys)

    def onActionChanged(self, evt: Any) -> None:
        sel = self.actionChoice.GetSelection()
        if 0 <= sel < len(self.visible_actions):
            action_id = self.visible_actions[sel][0]
            val = self.current_keymap.get(action_id, "")
            self.currentKeyStatus.SetLabel(_("Current assigned key: %s") % self._format_key_display(val))
        else:
            self.currentKeyStatus.SetLabel(_("Current assigned key: %s") % self._format_key_display(""))

    def onSearchFilter(self, evt: Any) -> None:
        query = self.searchCtrl.GetValue().strip().lower()
        if not query:
            self.filtered_suggestions = list(self.all_suggestions)
        else:
            self.filtered_suggestions = [
                (k_id, label) for k_id, label in self.all_suggestions
                if query in k_id.lower() or query in label.lower()
            ]

        choices = [label for _, label in self.filtered_suggestions]
        self.suggestionsList.Set(choices)
        if choices:
            self.suggestionsList.SetSelection(0)

    def _check_and_resolve_conflict(self, key_id: str, action_id: str, action_name: str) -> bool:
        target_norm = key_id.strip().lower()
        conflicts = []
        for act_id, k_val in self.current_keymap.items():
            if act_id != action_id:
                keys = [k.strip().lower() for k in k_val.split(",") if k.strip()]
                if target_norm in keys:
                    act_name = act_id
                    for a_id, a_name in ACTION_DISPLAY_NAMES:
                        if a_id == act_id:
                            act_name = a_name
                            break
                    conflicts.append((act_id, act_name))

        if not conflicts:
            return True

        conf_names = ", ".join(name for _, name in conflicts)
        key_label = self._format_single_key_display(target_norm)
        msg = _(
            "The shortcut '%s' is already assigned to '%s'.\n\n"
            "Do you want to reassign it to '%s' and remove it from '%s'?"
        ) % (key_label, conf_names, action_name, conf_names)
        title = _("Shortcut Conflict")

        confirmed = False
        if gui and hasattr(gui, "messageBox"):
            res = gui.messageBox(msg, title, wx.YES_NO | wx.ICON_QUESTION)
            confirmed = (res == wx.YES)
        elif hasattr(wx, "MessageBox"):
            res = wx.MessageBox(msg, title, wx.YES_NO | wx.ICON_QUESTION, self)
            confirmed = (res == wx.YES)
        else:
            confirmed = True

        if not confirmed:
            return False

        # Remove key from conflicting actions
        for act_id, _ in conflicts:
            existing = [k.strip() for k in self.current_keymap.get(act_id, "").split(",") if k.strip()]
            remaining = [k for k in existing if k.lower() != target_norm]
            self.current_keymap[act_id] = ",".join(remaining)

        return True

    def _do_assign_current_suggestion(self) -> None:
        sel = self.suggestionsList.GetSelection()
        if sel == wx.NOT_FOUND or sel < 0:
            if self.filtered_suggestions:
                sel = 0
                self.suggestionsList.SetSelection(0)
            else:
                if ui and hasattr(ui, "message"):
                    try:
                        ui.message(_("Please select a key from the suggestions list."))
                    except Exception:
                        pass
                return

        if 0 <= sel < len(self.filtered_suggestions):
            key_id = self.filtered_suggestions[sel][0]
            action_sel = self.actionChoice.GetSelection()
            if 0 <= action_sel < len(self.visible_actions):
                action_id, action_name = self.visible_actions[action_sel]
                if not self._check_and_resolve_conflict(key_id, action_id, action_name):
                    return
                self._assign_key(action_id, key_id)
                assigned_str = self.current_keymap.get(action_id, "")
                self.currentKeyStatus.SetLabel(
                    _("Current assigned key: %s") % self._format_key_display(assigned_str)
                )
                self._refresh_action_choice(action_sel)
                if ui and hasattr(ui, "message"):
                    try:
                        ui.message(_("Assigned %s to %s") % (self._format_key_display(assigned_str), action_name))
                    except Exception:
                        pass

    def onSuggestionDoubleClicked(self, evt: Any) -> None:
        self._do_assign_current_suggestion()

    def onAssignSelectedSuggestion(self, evt: Any) -> None:
        self._do_assign_current_suggestion()

    def onCaptureKeyDirectly(self, evt: Any) -> None:
        dlg = KeyCaptureDialog(self)
        if dlg.ShowModal() == wx.ID_OK and dlg.captured_key:
            captured = dlg.captured_key
            action_sel = self.actionChoice.GetSelection()
            if 0 <= action_sel < len(self.visible_actions):
                action_id, action_name = self.visible_actions[action_sel]
                if not self._check_and_resolve_conflict(captured, action_id, action_name):
                    dlg.Destroy()
                    return
                self._assign_key(action_id, captured)
                self.currentKeyStatus.SetLabel(
                    _("Current assigned key: %s") % self._format_key_display(self.current_keymap.get(action_id, ""))
                )
                self._refresh_action_choice(action_sel)
                self.searchCtrl.SetValue(captured)
                if ui and hasattr(ui, "message"):
                    try:
                        ui.message(_("Assigned %s to %s") % (self._format_key_display(self.current_keymap.get(action_id, "")), action_name))
                    except Exception:
                        pass
        dlg.Destroy()

    def onDeleteShortcut(self, evt: Any) -> None:
        """Deletes/unassigns the shortcut for the selected player action."""
        action_sel = self.actionChoice.GetSelection()
        if 0 <= action_sel < len(self.visible_actions):
            action_id, action_name = self.visible_actions[action_sel]
            self.current_keymap[action_id] = ""
            self.currentKeyStatus.SetLabel(
                _("Current assigned key: %s") % self._format_key_display("")
            )
            self._refresh_action_choice(action_sel)
            if ui and hasattr(ui, "message"):
                try:
                    ui.message(_("Shortcut deleted for %s") % action_name)
                except Exception:
                    pass

    def onResetDefaults(self, evt: Any) -> None:
        self.current_keymap = dict(DEFAULT_KEYMAP)
        self._refresh_action_choice(0)
        self.onActionChanged(None)
        if gui and hasattr(gui, "messageBox"):
            gui.messageBox(
                _("Player Mode shortcuts have been reset to factory defaults."),
                _("Shortcuts Reset"),
                wx.OK | wx.ICON_INFORMATION
            )

    def onExportShortcuts(self, evt: Any) -> None:
        with wx.FileDialog(
            self,
            message=_("Export Shortcuts to JSON File"),
            defaultFile="HeadlessPlayer_Shortcuts.json",
            wildcard=_("JSON Files (*.json)|*.json|All Files (*.*)|*.*"),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(self.current_keymap, f, indent=2, ensure_ascii=False)
                    msg = _("Shortcuts successfully exported to:\n%s") % path
                    title = _("Export Successful")
                    if gui and hasattr(gui, "messageBox"):
                        gui.messageBox(msg, title, wx.OK | wx.ICON_INFORMATION)
                    elif hasattr(wx, "MessageBox"):
                        wx.MessageBox(msg, title, wx.OK | wx.ICON_INFORMATION, self)
                except Exception as e:
                    logger.error("Failed to export shortcuts: %s", e)
                    err_msg = _("Failed to export shortcuts:\n%s") % str(e)
                    err_title = _("Export Error")
                    if gui and hasattr(gui, "messageBox"):
                        gui.messageBox(err_msg, err_title, wx.OK | wx.ICON_ERROR)
                    elif hasattr(wx, "MessageBox"):
                        wx.MessageBox(err_msg, err_title, wx.OK | wx.ICON_ERROR, self)

    def onImportShortcuts(self, evt: Any) -> None:
        with wx.FileDialog(
            self,
            message=_("Import Shortcuts from JSON File"),
            wildcard=_("JSON Files (*.json)|*.json|All Files (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                try:
                    with open(path, "r", encoding="utf-8") as src_f:
                        imported = json.load(src_f)
                    if not isinstance(imported, dict):
                        raise ValueError(_("Invalid shortcuts format: expected a JSON object."))
                    valid_action_ids = set(a_id for a_id, _ in ACTION_DISPLAY_NAMES)
                    count = 0
                    for k, v in imported.items():
                        if k in valid_action_ids and isinstance(v, str):
                            self.current_keymap[k] = v.strip().lower()
                            count += 1
                    self._refresh_action_choice()
                    self.onActionChanged(None)
                    msg = _("Successfully imported %d shortcuts from:\n%s") % (count, path)
                    title = _("Import Successful")
                    if gui and hasattr(gui, "messageBox"):
                        gui.messageBox(msg, title, wx.OK | wx.ICON_INFORMATION)
                    elif hasattr(wx, "MessageBox"):
                        wx.MessageBox(msg, title, wx.OK | wx.ICON_INFORMATION, self)
                except Exception as e:
                    logger.error("Failed to import shortcuts: %s", e)
                    err_msg = _("Failed to import shortcuts:\n%s") % str(e)
                    err_title = _("Import Error")
                    if gui and hasattr(gui, "messageBox"):
                        gui.messageBox(err_msg, err_title, wx.OK | wx.ICON_ERROR)
                    elif hasattr(wx, "MessageBox"):
                        wx.MessageBox(err_msg, err_title, wx.OK | wx.ICON_ERROR, self)

    def onSaveAndClose(self, evt: Any) -> None:
        setKeymap(self.current_keymap)
        saveConfig()
        try:
            ctrl = get_controller()
            if ctrl:
                if hasattr(ctrl, "on_config_updated"):
                    ctrl.on_config_updated(getConfig())
                if hasattr(ctrl, "input_layer") and ctrl.input_layer:
                    ctrl.input_layer.invalidate_keymap_cache()
        except Exception:
            pass
        self.EndModal(wx.ID_OK)


class YtdlpUpdateDialog(_WxDialog):
    """
    Accessible modal dialog presenting live streaming engine (yt-dlp) update progress,
    gauge percentage, size downloaded, and status reporting.
    """

    def __init__(self, parent: Any, channel: str = "stable", current_version: str = "") -> None:
        if not wx:
            return
        super().__init__(
            parent,
            title=_("Streaming Engine Update (yt-dlp)"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        self.channel = channel
        self.current_version = current_version
        self.updated_version: Optional[str] = None
        self.is_success: bool = False
        self.result_message: str = ""
        self._last_spoken_pct = -1
        self.InitUI()
        self.CenterOnParent()
        self.StartUpdate()

    def InitUI(self) -> None:
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        helper = guiHelper.BoxSizerHelper(self, sizer=mainSizer)

        chan_label = self.channel.capitalize()
        header_text = _("Updating streaming engine on %s channel (Current version: %s)") % (chan_label, self.current_version or _("Unknown"))
        self.headerLabel = wx.StaticText(self, label=header_text)
        helper.addItem(self.headerLabel)

        self.statusLabel = wx.StaticText(self, label=_("Connecting to update server..."))
        helper.addItem(self.statusLabel)

        self.progressBar = wx.Gauge(self, range=100, size=(480, 20), style=wx.GA_HORIZONTAL)
        helper.addItem(self.progressBar)

        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        btnSizer.AddStretchSpacer()
        self.actionBtn = wx.Button(self, wx.ID_CANCEL, label=_("&Cancel"))
        self.actionBtn.Bind(wx.EVT_BUTTON, self.onActionBtn)
        btnSizer.Add(self.actionBtn, 0, wx.ALL, 5)

        helper.addItem(btnSizer)
        self.SetSizerAndFit(mainSizer)

    def StartUpdate(self) -> None:
        if ui and hasattr(ui, "message"):
            try:
                ui.message(_("Checking for streaming engine updates on %s channel, please wait...") % self.channel.capitalize())
            except Exception:
                pass

        def progress_cb(stage: str, downloaded: int = 0, total: int = 0, pct: float = 0.0, extra: str = "") -> None:
            wx.CallAfter(self._on_progress, stage, downloaded, total, pct, extra)

        def worker() -> None:
            try:
                updated, msg = stream_engine.update_ytdlp(channel=self.channel, progress_cb=progress_cb)
            except Exception as e:
                updated, msg = False, f"error:unexpected:{e}"
            wx.CallAfter(self._on_complete, updated, msg)

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-YtdlpUpdateDialog").start()

    def _on_progress(self, stage: str, downloaded: int = 0, total: int = 0, pct: float = 0.0, extra: str = "") -> None:
        try:
            if not self or not getattr(self, "thisown", True):
                return
            if not hasattr(self, "progressBar") or not self.progressBar or not getattr(self.progressBar, "thisown", True):
                return
            if not hasattr(self, "statusLabel") or not self.statusLabel or not getattr(self.statusLabel, "thisown", True):
                return
        except Exception:
            return

        pct_int = min(100, max(0, int(pct)))
        self.progressBar.SetValue(pct_int)

        if stage == "checking":
            self.statusLabel.SetLabel(_("Checking for updates on %s channel...") % self.channel.capitalize())
        elif stage == "downloading":
            down_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024) if total > 0 else 0.0
            if total_mb > 0:
                msg = _("Downloading update: %.2f MB of %.2f MB (%d%%)") % (down_mb, total_mb, pct_int)
            else:
                msg = _("Downloading update: %.2f MB") % down_mb
            self.statusLabel.SetLabel(msg)

            # Announce milestones to screen reader
            if pct_int in (25, 50, 75) and pct_int != self._last_spoken_pct:
                self._last_spoken_pct = pct_int
                if ui and hasattr(ui, "message"):
                    try:
                        ui.message(_("Downloading: %d%%") % pct_int)
                    except Exception:
                        pass
        elif stage == "extracting":
            self.statusLabel.SetLabel(_("Extracting streaming engine package..."))
        elif stage == "installing":
            self.statusLabel.SetLabel(_("Installing update into add-on directory..."))

    def _on_complete(self, updated: bool, message: str) -> None:
        try:
            if not self or not getattr(self, "thisown", True):
                return
            if not hasattr(self, "progressBar") or not self.progressBar or not getattr(self.progressBar, "thisown", True):
                return
            if not hasattr(self, "statusLabel") or not self.statusLabel or not getattr(self.statusLabel, "thisown", True):
                return
            if not hasattr(self, "actionBtn") or not self.actionBtn or not getattr(self.actionBtn, "thisown", True):
                return
        except Exception:
            return

        self.is_success = updated
        self.result_message = message
        self.progressBar.SetValue(100 if updated else 0)

        if updated:
            new_ver = message.split(":", 1)[1] if ":" in message else ""
            self.updated_version = new_ver
            success_text = _(
                "Streaming engine updated successfully to version %s!\n"
                "Please restart NVDA to activate the new version."
            ) % new_ver
            self.statusLabel.SetLabel(success_text)
            self.actionBtn.SetLabel(_("&Close"))
            self.actionBtn.SetId(wx.ID_OK)
            self.actionBtn.SetDefault()
            self.actionBtn.SetFocus()

            if ui and hasattr(ui, "message"):
                try:
                    ui.message(_("Streaming engine updated successfully to version %s. Restart NVDA to activate.") % new_ver)
                except Exception:
                    pass
        elif message.startswith("up-to-date"):
            cur = message.split(":", 1)[1] if ":" in message else ""
            msg_text = _("The streaming engine is already up to date on the %s channel (version %s).") % (self.channel.capitalize(), cur)
            self.statusLabel.SetLabel(msg_text)
            self.actionBtn.SetLabel(_("&Close"))
            self.actionBtn.SetId(wx.ID_OK)
            self.actionBtn.SetDefault()
            self.actionBtn.SetFocus()
            if ui and hasattr(ui, "message"):
                try:
                    ui.message(msg_text)
                except Exception:
                    pass
        else:
            err_text = _("Could not update the streaming engine.\nDetails: %s") % message
            self.statusLabel.SetLabel(err_text)
            self.actionBtn.SetLabel(_("&Close"))
            self.actionBtn.SetId(wx.ID_CANCEL)
            self.actionBtn.SetDefault()
            self.actionBtn.SetFocus()
            if ui and hasattr(ui, "message"):
                try:
                    ui.message(_("Update failed: %s") % message)
                except Exception:
                    pass

    def onActionBtn(self, evt: Any) -> None:
        self.EndModal(self.actionBtn.GetId())


SPEED_CHOICES: List[Tuple[str, str]] = [
    ("0.5", _("0.5x")),
    ("0.75", _("0.75x")),
    ("1.0", _("1.0x (Normal)")),
    ("1.25", _("1.25x")),
    ("1.5", _("1.5x")),
    ("1.75", _("1.75x")),
    ("2.0", _("2.0x")),
    ("2.5", _("2.5x")),
    ("3.0", _("3.0x")),
]

REPEAT_CHOICES: List[Tuple[str, str]] = [
    ("off", _("Off")),
    ("track", _("Repeat Current Track")),
    ("playlist", _("Repeat Entire Playlist")),
]

STREAM_QUALITY_CHOICES: List[Tuple[str, str]] = [
    ("high", _("High (Opus ~160 kbps - Best fidelity)")),
    ("medium", _("Medium (AAC ~128 kbps - Standard)")),
    ("low", _("Low (~64 kbps - Data saver)")),
]

YTDLP_CHANNEL_CHOICES: List[Tuple[str, str]] = [
    ("stable", _("Stable (PyPI - Recommended)")),
    ("nightly", _("Nightly (Daily YouTube Fixes)")),
    ("master", _("Master (Development)")),
]



class HeadlessPlayerSettingsPanel(SettingsPanel):
    """
    Settings panel category for Headless Media Player in NVDA Settings Dialog.
    """
    title = _("Headless Media Player")

    def makeSettings(self, settingsSizer: Any) -> None:
        if guiHelper is None or wx is None:
            return

        helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
        cfg = getConfig()

        # -------------------------------------------------------------
        # Category Selector at the top
        # -------------------------------------------------------------
        categoryChoices = [
            _("General & Playback"),
            _("Speech & Announcements"),
            _("Online Streaming & SponsorBlock"),
            _("Downloads & Clip Export"),
            _("Shortcuts, Updates & About"),
        ]
        self.categoryChoice = helper.addLabeledControl(
            _("&Category:"),
            wx.Choice,
            choices=categoryChoices
        )
        self.categoryChoice.SetSelection(0)
        if hasattr(wx, "EVT_CHOICE"):
            self.categoryChoice.Bind(wx.EVT_CHOICE, self.onCategoryChanged)

        # Create category container panels
        self.panelGeneral = wx.Panel(self)
        self.panelSpeech = wx.Panel(self)
        self.panelStreaming = wx.Panel(self)
        self.panelExport = wx.Panel(self)
        self.panelShortcuts = wx.Panel(self)

        self.categoryPanels = [
            self.panelGeneral,
            self.panelSpeech,
            self.panelStreaming,
            self.panelExport,
            self.panelShortcuts,
        ]

        # =============================================================
        # Category 1: General & Playback
        # =============================================================
        sizerGeneral = wx.BoxSizer(wx.VERTICAL)
        generalHelper = guiHelper.BoxSizerHelper(self.panelGeneral, sizer=sizerGeneral)

        # Section 1.1: Playback Defaults & Options
        playbackGroupLabel = _("Playback Defaults & Options")
        playbackBox = wx.StaticBox(self.panelGeneral, label=playbackGroupLabel)
        playbackGroup = guiHelper.BoxSizerHelper(
            self.panelGeneral,
            sizer=wx.StaticBoxSizer(playbackBox, wx.VERTICAL)
        )

        speedLabels = [label for val_opt, label in SPEED_CHOICES]
        self.defaultSpeedChoice = playbackGroup.addLabeledControl(
            _("Default playback s&peed:"),
            wx.Choice,
            choices=speedLabels
        )
        curSpeedStr = str(cfg.get("defaultSpeed", "1.0"))
        try:
            curSpeedVal = float(curSpeedStr)
        except (ValueError, TypeError):
            curSpeedVal = 1.0

        speedIdx = 2  # Default to "1.0"
        for i, (val, label) in enumerate(SPEED_CHOICES):
            if abs(float(val) - curSpeedVal) < 0.01:
                speedIdx = i
                break
        self.defaultSpeedChoice.SetSelection(speedIdx)

        repeatLabels = [label for rep_opt, label in REPEAT_CHOICES]
        self.defaultRepeatChoice = playbackGroup.addLabeledControl(
            _("Default &repeat mode:"),
            wx.Choice,
            choices=repeatLabels
        )
        curRepeat = str(cfg.get("defaultRepeatMode", "off")).lower()
        repeatIdx = 0
        for i, (val, label) in enumerate(REPEAT_CHOICES):
            if val.lower() == curRepeat:
                repeatIdx = i
                break
        self.defaultRepeatChoice.SetSelection(repeatIdx)

        self.autoNextChk = playbackGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Auto-advance to &next track when media finishes"))
        )
        self.autoNextChk.SetValue(bool(cfg.get("defaultAutoNext", True)))

        self.resumePositionChk = playbackGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Remember and &resume playback position for media"))
        )
        self.resumePositionChk.SetValue(bool(cfg.get("resumePosition", True)))

        self.rememberPlaybackStateChk = playbackGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Remember and &restore last playback session on reopening"))
        )
        self.rememberPlaybackStateChk.SetValue(bool(cfg.get("rememberPlaybackState", False)))

        self.autoEnterPlayerModeChk = playbackGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Automatically enter &Player Mode when loading new media"))
        )
        self.autoEnterPlayerModeChk.SetValue(bool(cfg.get("autoEnterPlayerMode", True)))

        generalHelper.addItem(playbackGroup.sizer)

        # Section 1.2: Seek Jump Step Sizes (Seconds)
        seekGroupLabel = _("Seek Jump Step Sizes (Seconds)")
        seekBox = wx.StaticBox(self.panelGeneral, label=seekGroupLabel)
        seekGroup = guiHelper.BoxSizerHelper(
            self.panelGeneral,
            sizer=wx.StaticBoxSizer(seekBox, wx.VERTICAL)
        )

        self.seekStepNormalCtrl = seekGroup.addLabeledControl(
            _("&Normal seek jump (Left/Right arrows):"),
            wx.SpinCtrl,
            min=1,
            max=3600,
            initial=int(cfg.get("seekStepNormal", 5))
        )

        self.seekStepSlowCtrl = seekGroup.addLabeledControl(
            _("&Slow / precise seek jump (Alt + Left/Right):"),
            wx.SpinCtrl,
            min=1,
            max=3600,
            initial=int(cfg.get("seekStepSlow", 1))
        )

        self.seekStepFastCtrl = seekGroup.addLabeledControl(
            _("&Fast seek jump (Ctrl + Left/Right):"),
            wx.SpinCtrl,
            min=1,
            max=3600,
            initial=int(cfg.get("seekStepFast", 30))
        )

        self.seekStepUltrafastCtrl = seekGroup.addLabeledControl(
            _("&Ultrafast seek jump (Shift + Left/Right):"),
            wx.SpinCtrl,
            min=5,
            max=7200,
            initial=int(cfg.get("seekStepUltrafast", 300))
        )

        generalHelper.addItem(seekGroup.sizer)

        # Section 1.3: Recent Media History
        recentsGroupLabel = _("Recent Media History")
        recentsBox = wx.StaticBox(self.panelGeneral, label=recentsGroupLabel)
        recentsGroup = guiHelper.BoxSizerHelper(
            self.panelGeneral,
            sizer=wx.StaticBoxSizer(recentsBox, wx.VERTICAL)
        )

        self.recentsEnabledChk = recentsGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("&Enable recent media history tracking"))
        )
        self.recentsEnabledChk.SetValue(bool(cfg.get("recentsEnabled", True)))

        self.recentsMaxEntriesCtrl = recentsGroup.addLabeledControl(
            _("&Maximum recent entries per category:"),
            wx.SpinCtrl,
            min=5,
            max=200,
            initial=int(cfg.get("recentsMaxEntries", 30))
        )

        self.recentsKeepFilesChk = recentsGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Keep recent &local files in history"))
        )
        self.recentsKeepFilesChk.SetValue(bool(cfg.get("recentsKeepFiles", True)))

        self.recentsKeepFoldersChk = recentsGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Keep recent local &folders in history"))
        )
        self.recentsKeepFoldersChk.SetValue(bool(cfg.get("recentsKeepFolders", True)))

        self.recentsKeepPlaylistsChk = recentsGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Keep recent &playlists in history"))
        )
        self.recentsKeepPlaylistsChk.SetValue(bool(cfg.get("recentsKeepPlaylists", True)))

        self.recentsKeepStreamsChk = recentsGroup.addItem(
            wx.CheckBox(self.panelGeneral, label=_("Keep recent online &streams in history"))
        )
        self.recentsKeepStreamsChk.SetValue(bool(cfg.get("recentsKeepStreams", True)))

        generalHelper.addItem(recentsGroup.sizer)
        self.panelGeneral.SetSizer(sizerGeneral)
        helper.addItem(self.panelGeneral)

        # =============================================================
        # Category 2: Speech & Announcements
        # =============================================================
        sizerSpeech = wx.BoxSizer(wx.VERTICAL)
        speechHelper = guiHelper.BoxSizerHelper(self.panelSpeech, sizer=sizerSpeech)

        speechGroupLabel = _("Speech Feedback & Announcements")
        speechBox = wx.StaticBox(self.panelSpeech, label=speechGroupLabel)
        speechGroup = guiHelper.BoxSizerHelper(
            self.panelSpeech,
            sizer=wx.StaticBoxSizer(speechBox, wx.VERTICAL)
        )

        self.announceVolumeChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce &volume changes"))
        )
        self.announceVolumeChk.SetValue(bool(cfg.get("announceVolume", True)))

        self.announceSeekChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce &seek position and jump offsets"))
        )
        self.announceSeekChk.SetValue(bool(cfg.get("announceSeek", True)))

        self.announceSpeedChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce playback s&peed adjustments"))
        )
        self.announceSpeedChk.SetValue(bool(cfg.get("announceSpeed", True)))

        self.announceTrackChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce &track titles and playlist navigation"))
        )
        self.announceTrackChk.SetValue(bool(cfg.get("announceTrack", True)))

        self.announceLoopChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce A-B &loop and segment markers"))
        )
        self.announceLoopChk.SetValue(bool(cfg.get("announceLoop", True)))

        self.announceChapterChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce &chapter markers and names"))
        )
        self.announceChapterChk.SetValue(bool(cfg.get("announceChapter", True)))

        self.announceChapterAutoChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce chapter transitions &automatically during playback"))
        )
        self.announceChapterAutoChk.SetValue(bool(cfg.get("announceChapterAuto", True)))

        self.announcePlaylistTotalDurationChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Announce playlist &total duration when loaded"))
        )
        self.announcePlaylistTotalDurationChk.SetValue(bool(cfg.get("announcePlaylistTotalDuration", False)))

        self.remainingTimeAccountsForSpeedChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Calculate remaining &time based on current playback speed"))
        )
        self.remainingTimeAccountsForSpeedChk.SetValue(bool(cfg.get("remainingTimeAccountsForSpeed", True)))

        self.elapsedTimeAccountsForSpeedChk = speechGroup.addItem(
            wx.CheckBox(self.panelSpeech, label=_("Calculate elapsed ti&me based on current playback speed"))
        )
        self.elapsedTimeAccountsForSpeedChk.SetValue(bool(cfg.get("elapsedTimeAccountsForSpeed", True)))

        speechHelper.addItem(speechGroup.sizer)

        self.panelSpeech.SetSizer(sizerSpeech)
        helper.addItem(self.panelSpeech)

        # =============================================================
        # Category 3: Online Streaming & SponsorBlock
        # =============================================================
        sizerStreaming = wx.BoxSizer(wx.VERTICAL)
        streamingHelper = guiHelper.BoxSizerHelper(self.panelStreaming, sizer=sizerStreaming)

        streamGroupLabel = _("YouTube & Online Streaming (yt-dlp)")
        streamBox = wx.StaticBox(self.panelStreaming, label=streamGroupLabel)
        streamGroup = guiHelper.BoxSizerHelper(
            self.panelStreaming,
            sizer=wx.StaticBoxSizer(streamBox, wx.VERTICAL)
        )

        ver_info = stream_engine.get_channel_info() if stream_engine and hasattr(stream_engine, "get_channel_info") else {}
        ver = ver_info.get("installed_version") or (stream_engine.get_bundled_version() if stream_engine and hasattr(stream_engine, "get_bundled_version") else None) or _("not installed")
        chan_name = str(ver_info.get("installed_channel", "stable")).capitalize()
        self.ytdlpVersionText = streamGroup.addItem(
            wx.StaticText(self.panelStreaming, label=_("Streaming engine (yt-dlp) version: %s (%s)") % (ver, chan_name))
        )

        channelLabels = [label for _val, label in YTDLP_CHANNEL_CHOICES]
        self.ytdlpChannelChoice = streamGroup.addLabeledControl(
            _("yt-dlp update &channel:"),
            wx.Choice,
            choices=channelLabels
        )
        curChan = str(cfg.get("ytdlpUpdateChannel", "stable")).lower()
        chanIdx = 0
        for i, (val, label) in enumerate(YTDLP_CHANNEL_CHOICES):
            if val.lower() == curChan:
                chanIdx = i
                break
        self.ytdlpChannelChoice.SetSelection(chanIdx)

        self.checkUpdatesBtn = streamGroup.addItem(
            wx.Button(self.panelStreaming, label=_("Check for &Updates of the streaming engine now..."))
        )
        self.rollbackYtdlpBtn = streamGroup.addItem(
            wx.Button(self.panelStreaming, label=_("&Revert streaming engine to previous version..."))
        )
        self.resetBundledYtdlpBtn = streamGroup.addItem(
            wx.Button(self.panelStreaming, label=_("Restore &original bundled streaming engine..."))
        )
        if hasattr(wx, "EVT_BUTTON"):
            self.checkUpdatesBtn.Bind(wx.EVT_BUTTON, self.onCheckYtdlpUpdates)
            self.rollbackYtdlpBtn.Bind(wx.EVT_BUTTON, self.onRollbackYtdlp)
            self.resetBundledYtdlpBtn.Bind(wx.EVT_BUTTON, self.onResetBundledYtdlp)

        self._refreshYtdlpButtons()

        qualityLabels = [label for _val, label in STREAM_QUALITY_CHOICES]
        self.streamAudioQualityChoice = streamGroup.addLabeledControl(
            _("Streaming audio &quality:"),
            wx.Choice,
            choices=qualityLabels
        )
        curQuality = str(cfg.get("streamAudioQuality", "high")).lower()
        qualityIdx = 0
        for i, (val, label) in enumerate(STREAM_QUALITY_CHOICES):
            if val.lower() == curQuality:
                qualityIdx = i
                break
        self.streamAudioQualityChoice.SetSelection(qualityIdx)

        self.searchResultsCountCtrl = streamGroup.addLabeledControl(
            _("Number of YouTube search &results:"),
            wx.SpinCtrl,
            min=5,
            max=50,
            initial=int(cfg.get("searchResultsCount", 20))
        )

        self.maxStreamItemsCtrl = streamGroup.addLabeledControl(
            _("&Maximum items loaded from an online playlist or channel:"),
            wx.SpinCtrl,
            min=10,
            max=1000,
            initial=int(cfg.get("maxStreamPlaylistItems", 300))
        )

        self.cookiesBrowserChoices: List[Tuple[str, str]] = [
            ("none", _("None (anonymous, default)")),
            ("firefox", _("Mozilla Firefox (compatible on Windows)")),
        ]
        self.cookiesBrowserChoice = streamGroup.addLabeledControl(
            _("Use sign-in coo&kies from browser (Firefox only on Windows):"),
            wx.Choice,
            choices=[label for val, label in self.cookiesBrowserChoices]
        )
        curBrowser = str(cfg.get("ytdlpCookiesBrowser", "none")).lower()
        if curBrowser not in ("none", "firefox"):
            curBrowser = "none"
        browserIdx = 0
        for i, (val, label) in enumerate(self.cookiesBrowserChoices):
            if val == curBrowser:
                browserIdx = i
                break
        self.cookiesBrowserChoice.SetSelection(browserIdx)

        self.cookiesFileCtrl = streamGroup.addLabeledControl(
            _("Manual sign-in cookies &file (cookies.txt in Netscape format):"),
            wx.TextCtrl
        )
        self.cookiesFileCtrl.SetValue(str(cfg.get("ytdlpCookiesFile", "") or ""))

        cookiesBtnSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.browseCookiesBtn = wx.Button(self.panelStreaming, label=_("&Browse for cookies file..."))
        cookiesBtnSizer.Add(self.browseCookiesBtn, 0, wx.RIGHT, 5)
        if hasattr(wx, "EVT_BUTTON"):
            self.browseCookiesBtn.Bind(wx.EVT_BUTTON, self.onBrowseCookiesFile)

        self.testCookiesBtn = wx.Button(self.panelStreaming, label=_("&Test cookies file validity..."))
        cookiesBtnSizer.Add(self.testCookiesBtn, 0)
        if hasattr(wx, "EVT_BUTTON"):
            self.testCookiesBtn.Bind(wx.EVT_BUTTON, self.onTestCookiesFile)

        streamGroup.addItem(cookiesBtnSizer)

        cookiesHint = wx.StaticText(
            self.panelStreaming,
            label=_(
                "Tip: On Windows, Chrome and Edge block automated cookie decryption. Use Firefox or "
                "export cookies.txt using a browser extension from a Private/Incognito window while signed in "
                "to YouTube. The manual cookies file takes priority over the browser choice above."
            )
        )
        cookiesHint.Wrap(560)
        streamGroup.addItem(cookiesHint)

        streamingHelper.addItem(streamGroup.sizer)

        # Section 3.2: SponsorBlock
        if hasattr(wx, "CheckBox") and hasattr(wx, "StaticBox"):
            sbGroupLabel = _("SponsorBlock (Auto-Skip YouTube Ads & Sponsors)")
            sbBox = wx.StaticBox(self.panelStreaming, label=sbGroupLabel)
            sbGroup = guiHelper.BoxSizerHelper(
                self.panelStreaming,
                sizer=wx.StaticBoxSizer(sbBox, wx.VERTICAL)
            )

            self.sponsorBlockEnabledChk = sbGroup.addItem(
                wx.CheckBox(
                    self.panelStreaming,
                    label=_("Enable &SponsorBlock (Auto-skip YouTube sponsors, promos & intros)")
                )
            )
            self.sponsorBlockEnabledChk.SetValue(bool(cfg.get("sponsorBlockEnabled", True)))

            self.announceSponsorSkipChk = sbGroup.addItem(
                wx.CheckBox(
                    self.panelStreaming,
                    label=_("&Announce when a sponsor or promo segment is skipped")
                )
            )
            self.announceSponsorSkipChk.SetValue(bool(cfg.get("announceSponsorSkip", True)))

            # Customizable categories to skip
            active_cats = set(
                c.strip().lower()
                for c in str(cfg.get("sponsorBlockCategories", "sponsor,selfpromo,interaction,intro,outro")).split(",")
                if c.strip()
            )

            self.sbCatSponsorChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip &sponsors and paid advertisements"))
            )
            self.sbCatSponsorChk.SetValue("sponsor" in active_cats)

            self.sbCatIntroChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip &intro animations and intermission breaks"))
            )
            self.sbCatIntroChk.SetValue("intro" in active_cats)

            self.sbCatOutroChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip &outro credits and end cards"))
            )
            self.sbCatOutroChk.SetValue("outro" in active_cats)

            self.sbCatSelfpromoChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip self-&promotions and unpaid merchandise"))
            )
            self.sbCatSelfpromoChk.SetValue("selfpromo" in active_cats)

            self.sbCatInteractionChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip subscribe and like inter&action reminders"))
            )
            self.sbCatInteractionChk.SetValue("interaction" in active_cats)

            self.sbCatMusicOfftopicChk = sbGroup.addItem(
                wx.CheckBox(self.panelStreaming, label=_("Skip non-&music sections in music videos"))
            )
            self.sbCatMusicOfftopicChk.SetValue("music_offtopic" in active_cats)

            streamingHelper.addItem(sbGroup.sizer)


        self.panelStreaming.SetSizer(sizerStreaming)
        helper.addItem(self.panelStreaming)

        # =============================================================
        # Category 4: Shortcuts, Updates & About
        # =============================================================
        sizerShortcuts = wx.BoxSizer(wx.VERTICAL)
        shortcutsHelper = guiHelper.BoxSizerHelper(self.panelShortcuts, sizer=sizerShortcuts)

        # Section 4.1: Player Mode Keyboard Shortcuts
        if hasattr(wx, "Button") and hasattr(wx, "StaticBox"):
            shortcutsGroupLabel = _("Player Mode Keyboard Shortcuts")
            shortcutsBox = wx.StaticBox(self.panelShortcuts, label=shortcutsGroupLabel)
            shortcutsGroup = guiHelper.BoxSizerHelper(
                self.panelShortcuts,
                sizer=wx.StaticBoxSizer(shortcutsBox, wx.VERTICAL)
            )

            self.customizeShortcutsBtn = shortcutsGroup.addItem(
                wx.Button(self.panelShortcuts, label=_("Customize Player Mode &Shortcuts..."))
            )
            if hasattr(wx, "EVT_BUTTON"):
                self.customizeShortcutsBtn.Bind(wx.EVT_BUTTON, self.onCustomizeShortcuts)

            shortcutsHelper.addItem(shortcutsGroup.sizer)

        # Section 4.2: Add-on Self-Updater
        if hasattr(wx, "Button") and hasattr(wx, "StaticBox"):
            addonUpdatesGroupLabel = _("Headless Media Player Add-on Updates")
            addonUpdatesBox = wx.StaticBox(self.panelShortcuts, label=addonUpdatesGroupLabel)
            addonUpdatesGroup = guiHelper.BoxSizerHelper(
                self.panelShortcuts,
                sizer=wx.StaticBoxSizer(addonUpdatesBox, wx.VERTICAL)
            )

            cur_ver_str = (addon_updater.get_current_addon_version() if addon_updater and hasattr(addon_updater, "get_current_addon_version") else "") or "1.0.0"
            self.addonVersionText = addonUpdatesGroup.addItem(
                wx.StaticText(self.panelShortcuts, label=_("Installed add-on version: %s") % cur_ver_str)
            )

            self.checkAddonUpdatesBtn = addonUpdatesGroup.addItem(
                wx.Button(self.panelShortcuts, label=_("Check for &Add-on Updates on GitHub..."))
            )
            if hasattr(wx, "EVT_BUTTON"):
                self.checkAddonUpdatesBtn.Bind(wx.EVT_BUTTON, self.onCheckAddonUpdates)

            shortcutsHelper.addItem(addonUpdatesGroup.sizer)

        # Section 4.3: About & Developer
        if hasattr(wx, "Button") and hasattr(wx, "StaticBox"):
            aboutGroupLabel = _("About & Developer")
            aboutBox = wx.StaticBox(self.panelShortcuts, label=aboutGroupLabel)
            aboutGroup = guiHelper.BoxSizerHelper(
                self.panelShortcuts,
                sizer=wx.StaticBoxSizer(aboutBox, wx.VERTICAL)
            )

            self.followDevBtn = aboutGroup.addItem(
                wx.Button(self.panelShortcuts, label=_("&Follow Developer on Telegram (Mahmoud Abo El Fotouh)..."))
            )
            if hasattr(wx, "EVT_BUTTON"):
                self.followDevBtn.Bind(wx.EVT_BUTTON, self.onFollowDeveloper)

            shortcutsHelper.addItem(aboutGroup.sizer)

        self.panelShortcuts.SetSizer(sizerShortcuts)
        helper.addItem(self.panelShortcuts)

        # =============================================================
        # Category: Downloads & Clip Export
        # =============================================================
        sizerExport = wx.BoxSizer(wx.VERTICAL)
        exportHelper = guiHelper.BoxSizerHelper(self.panelExport, sizer=sizerExport)
        exBox = wx.StaticBox(self.panelExport, label=_("Clip Export & Downloads (D / Shift+D)"))
        exGroup = guiHelper.BoxSizerHelper(self.panelExport, sizer=wx.StaticBoxSizer(exBox, wx.VERTICAL))
        self.exportFolderCtrl = exGroup.addLabeledControl(
            _("Default download &folder (empty = Downloads\\HeadlessPlayer):"), wx.TextCtrl)
        self.exportFolderCtrl.SetValue(str(cfg.get("exportFolder", "") or ""))
        self.browseExportFolderBtn = exGroup.addItem(wx.Button(self.panelExport, label=_("&Browse for folder...")))
        if hasattr(wx, "EVT_BUTTON"):
            self.browseExportFolderBtn.Bind(wx.EVT_BUTTON, self.onBrowseExportFolder)
        self.exportFormatChoices = [("mp3", _("Audio MP3")), ("m4a", _("Audio M4A / AAC")), ("mp4", _("Video MP4"))]
        self.exportFormatChoice = exGroup.addLabeledControl(
            _("Default export f&ormat:"), wx.Choice, choices=[l for _v, l in self.exportFormatChoices])
        curFmt = str(cfg.get("exportFormat", "mp3")).lower()
        self.exportFormatChoice.SetSelection(next((i for i, (v, _l) in enumerate(self.exportFormatChoices) if v == curFmt), 0))
        self.exportQualityChoices = [("high", _("Highest quality")), ("story", _("Story optimized (small file)"))]
        self.exportQualityChoice = exGroup.addLabeledControl(
            _("Default &quality:"), wx.Choice, choices=[l for _v, l in self.exportQualityChoices])
        curQ = str(cfg.get("exportQuality", "high")).lower()
        self.exportQualityChoice.SetSelection(next((i for i, (v, _l) in enumerate(self.exportQualityChoices) if v == curQ), 0))
        self.exportAutoCopyChk = exGroup.addItem(
            wx.CheckBox(self.panelExport, label=_("Automatically &copy the saved file path to the clipboard")))
        self.exportAutoCopyChk.SetValue(bool(cfg.get("exportAutoCopy", True)))
        exHint = wx.StaticText(self.panelExport, label=_(
            "D: export the A-B selection (or the whole item) as MP3, M4A or MP4 video; if only point A is set, "
            "the current position becomes point B. Shift+D: quick export with the settings remembered from the last dialog. "
            "Shift+V: copy the direct audio link of the playing YouTube item. Conversion is done by the bundled mpv encoder."
        ))
        exHint.Wrap(560)
        exGroup.addItem(exHint)
        exportHelper.addItem(exGroup.sizer)
        self.panelExport.SetSizer(sizerExport)
        helper.addItem(self.panelExport)

        # Initially show only the first category (General & Playback)
        self.panelGeneral.Show()
        self.panelSpeech.Hide()
        self.panelStreaming.Hide()
        self.panelExport.Hide()
        self.panelShortcuts.Hide()

    def onCategoryChanged(self, evt: Any) -> None:
        """Switches active settings category panel when user changes the dropdown."""
        if not hasattr(self, "categoryChoice") or not hasattr(self, "categoryPanels"):
            return
        sel = self.categoryChoice.GetSelection()
        for idx, p in enumerate(self.categoryPanels):
            if idx == sel:
                p.Show()
            else:
                p.Hide()
        self.Layout()
        if evt:
            try:
                evt.Skip()
            except Exception:
                pass


    def onFollowDeveloper(self, evt: Any) -> None:
        """Opens developer's Telegram link in the default browser."""
        try:
            webbrowser.open("https://t.me/mahmoud_EG_1")
        except Exception as e:
            logger.error("Failed to open developer Telegram link: %s", e)

    def onBrowseCookiesFile(self, evt: Any) -> None:
        """Opens a file picker for the manual cookies.txt file."""
        if not wx:
            return
        current = self.cookiesFileCtrl.GetValue().strip()
        start_dir = os.path.dirname(current) if current else os.path.expanduser("~")
        dlg = wx.FileDialog(
            self,
            message=_("Select cookies.txt file"),
            defaultDir=start_dir,
            wildcard=_("Cookies files (*.txt)|*.txt|All files (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )
        with dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                self.cookiesFileCtrl.SetValue(path)
                try:
                    if stream_engine and hasattr(stream_engine, "check_youtube_cookies_validity"):
                        valid, reason = stream_engine.check_youtube_cookies_validity(path)
                        if not valid and reason == "missing_auth_tokens":
                            if gui and hasattr(gui, "messageBox"):
                                gui.messageBox(
                                    _("Notice: The selected cookies file does not appear to contain YouTube authentication tokens.\n\n"
                                      "For YouTube account feeds (Recommendations, Subscriptions, History) to work reliably, "
                                      "please export cookies while signed in to your YouTube account in your browser."),
                                    _("Cookies Verification"),
                                    wx.OK | wx.ICON_WARNING
                                )
                except Exception:
                    pass

    def _refreshYtdlpButtons(self) -> None:
        """Refreshes the enabled status and labels of yt-dlp rollback and reset buttons."""
        if not wx:
            return
        try:
            ver_info = stream_engine.get_channel_info() if stream_engine and hasattr(stream_engine, "get_channel_info") else {}
            can_roll = bool(ver_info.get("can_rollback", False))
            can_reset = bool(ver_info.get("can_reset_bundled", False))
            prev_ver = ver_info.get("previous_version", "")

            if hasattr(self, "rollbackYtdlpBtn") and self.rollbackYtdlpBtn and getattr(self.rollbackYtdlpBtn, "thisown", True):
                if can_roll:
                    self.rollbackYtdlpBtn.Enable()
                    if prev_ver:
                        self.rollbackYtdlpBtn.SetLabel(_("&Revert to previous version (%s)...") % prev_ver)
                    else:
                        self.rollbackYtdlpBtn.SetLabel(_("&Revert streaming engine to previous version..."))
                else:
                    self.rollbackYtdlpBtn.Disable()
                    self.rollbackYtdlpBtn.SetLabel(_("&Revert streaming engine to previous version (none available)"))

            if hasattr(self, "resetBundledYtdlpBtn") and self.resetBundledYtdlpBtn and getattr(self.resetBundledYtdlpBtn, "thisown", True):
                if can_reset:
                    self.resetBundledYtdlpBtn.Enable()
                else:
                    self.resetBundledYtdlpBtn.Disable()
        except Exception as e:
            logger.debug("Error refreshing ytdlp buttons: %s", e)

    def onCheckYtdlpUpdates(self, evt: Any) -> None:
        """
        Checks the chosen channel for a newer yt-dlp streaming engine and installs it into
        the add-on using an accessible modal progress dialog with live progress bar and spoken announcements.
        """
        if not wx:
            return

        selected_channel = "stable"
        if hasattr(self, "ytdlpChannelChoice") and self.ytdlpChannelChoice and getattr(self.ytdlpChannelChoice, "thisown", True):
            sel = self.ytdlpChannelChoice.GetSelection()
            if 0 <= sel < len(YTDLP_CHANNEL_CHOICES):
                selected_channel = YTDLP_CHANNEL_CHOICES[sel][0]

        ver_info = stream_engine.get_channel_info() if stream_engine and hasattr(stream_engine, "get_channel_info") else {}
        cur_ver = ver_info.get("installed_version") or (stream_engine.get_bundled_version() if stream_engine and hasattr(stream_engine, "get_bundled_version") else "")

        dlg = YtdlpUpdateDialog(self, channel=selected_channel, current_version=cur_ver)
        dlg.ShowModal()

        if getattr(dlg, "is_success", False) and getattr(dlg, "updated_version", None):
            if hasattr(self, "ytdlpVersionText") and self.ytdlpVersionText and getattr(self.ytdlpVersionText, "thisown", True):
                self.ytdlpVersionText.SetLabel(
                    _("Streaming engine (yt-dlp) version: %s (%s - restart NVDA to activate)") % (dlg.updated_version, selected_channel.capitalize())
                )
        self._refreshYtdlpButtons()
        try:
            dlg.Destroy()
        except Exception:
            pass


    def onRollbackYtdlp(self, evt: Any) -> None:
        """Rolls back the streaming engine to the previous version."""
        if not wx or not stream_engine:
            return
        if gui and hasattr(gui, "messageBox"):
            res = gui.messageBox(
                _("Are you sure you want to revert the streaming engine to the previous version?"),
                _("Confirm Revert"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
            )
            if res != wx.YES:
                return

        success, msg = stream_engine.rollback_ytdlp()
        if success:
            ver = msg.split(":", 1)[1] if ":" in msg else ""
            text = _(
                "The streaming engine was successfully restored to version %s.\n"
                "Please restart NVDA to activate the changes."
            ) % ver
            caption = _("Revert Successful")
            icon = wx.ICON_INFORMATION
            if hasattr(self, "ytdlpVersionText"):
                self.ytdlpVersionText.SetLabel(
                    _("Streaming engine (yt-dlp) version: %s (restart NVDA to activate)") % ver
                )
        else:
            text = _("Failed to revert the streaming engine.\nDetails: %s") % msg
            caption = _("Revert Failed")
            icon = wx.ICON_ERROR

        self._refreshYtdlpButtons()
        if gui and hasattr(gui, "messageBox"):
            gui.messageBox(text, caption, wx.OK | icon)
        elif ui and hasattr(ui, "message"):
            try:
                ui.message(text)
            except Exception:
                pass

    def onResetBundledYtdlp(self, evt: Any) -> None:
        """Restores the original factory bundled streaming engine."""
        if not wx or not stream_engine:
            return
        if gui and hasattr(gui, "messageBox"):
            res = gui.messageBox(
                _("Are you sure you want to restore the original factory bundled streaming engine?\n"
                  "This will reset any downloaded updates."),
                _("Confirm Factory Reset"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
            )
            if res != wx.YES:
                return

        success, msg = stream_engine.reset_to_bundled_ytdlp()
        if success:
            ver = msg.split(":", 1)[1] if ":" in msg else ""
            text = _(
                "The streaming engine was reset to the original bundled version %s.\n"
                "Please restart NVDA to activate the changes."
            ) % ver
            caption = _("Reset Successful")
            icon = wx.ICON_INFORMATION
            if hasattr(self, "ytdlpVersionText"):
                self.ytdlpVersionText.SetLabel(
                    _("Streaming engine (yt-dlp) version: %s (restart NVDA to activate)") % ver
                )
        else:
            text = _("Failed to restore bundled streaming engine.\nDetails: %s") % msg
            caption = _("Reset Failed")
            icon = wx.ICON_ERROR

        self._refreshYtdlpButtons()
        if gui and hasattr(gui, "messageBox"):
            gui.messageBox(text, caption, wx.OK | icon)
        elif ui and hasattr(ui, "message"):
            try:
                ui.message(text)
            except Exception:
                pass

    def onCustomizeShortcuts(self, evt: Any) -> None:
        """Opens the accessible Player Mode shortcuts customization dialog."""
        if not wx:
            return
        dlg = HeadlessPlayerShortcutsDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def onCheckAddonUpdates(self, evt: Any) -> None:
        """
        Checks GitHub Releases for a newer version of the HeadlessPlayer add-on.
        If an update is found, presents the AddonUpdateDialog with changelog and live download progress.
        """
        if not wx:
            return

        self.checkAddonUpdatesBtn.Disable()
        self.checkAddonUpdatesBtn.SetLabel(_("Checking for add-on updates..."))
        if ui and hasattr(ui, "message"):
            try:
                ui.message(_("Checking for add-on updates, please wait..."))
            except Exception:
                pass

        def worker() -> None:
            try:
                if addon_updater and hasattr(addon_updater, "check_for_addon_update"):
                    available, info, status = addon_updater.check_for_addon_update()
                else:
                    available, info, status = False, None, "addon_updater unavailable"
            except Exception as e:
                available, info, status = False, None, f"error:{e}"
            wx.CallAfter(self._onAddonUpdateCheckFinished, available, info, status)

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-AddonUpdateCheck").start()

    def _onAddonUpdateCheckFinished(self, available: bool, info: Optional[dict], status: str) -> None:
        if not wx:
            return
        if not self or not hasattr(self, "checkAddonUpdatesBtn") or not self.checkAddonUpdatesBtn:
            return
        try:
            if not getattr(self.checkAddonUpdatesBtn, "thisown", True):
                return
            self.checkAddonUpdatesBtn.Enable()
            self.checkAddonUpdatesBtn.SetLabel(_("Check for &Add-on Updates on GitHub..."))
        except Exception:
            return

        if available and info and AddonUpdateDialog:
            dlg = AddonUpdateDialog(self, info)
            dlg.ShowModal()
            dlg.Destroy()
        elif status == "up_to_date" and info:
            cur_ver = info.get("current_version", "")
            text = _("You are already using the latest version of Headless Media Player (version %s).") % cur_ver
            caption = _("No Update Needed")
            if gui and hasattr(gui, "messageBox"):
                gui.messageBox(text, caption, wx.OK | wx.ICON_INFORMATION)
            elif ui and hasattr(ui, "message"):
                try:
                    ui.message(text)
                except Exception:
                    pass
        elif status == "error:rate_limit_exceeded":
            text = _(
                "GitHub API rate limit exceeded (maximum 60 requests per hour).\n"
                "Please wait a few minutes and try again."
            )
            caption = _("Rate Limit Exceeded")
            if gui and hasattr(gui, "messageBox"):
                gui.messageBox(text, caption, wx.OK | wx.ICON_WARNING)
            elif ui and hasattr(ui, "message"):
                try:
                    ui.message(text)
                except Exception:
                    pass
        else:
            text = _(
                "Could not check for add-on updates.\n"
                "Please check your internet connection and try again.\n\nDetails: %s"
            ) % status
            caption = _("Update Check Failed")
            if gui and hasattr(gui, "messageBox"):
                gui.messageBox(text, caption, wx.OK | wx.ICON_ERROR)
            elif ui and hasattr(ui, "message"):
                try:
                    ui.message(text)
                except Exception:
                    pass

    def onBrowseCookiesFile(self, evt: Any) -> None:
        if not wx:
            return
        current = self.cookiesFileCtrl.GetValue().strip().strip('"')
        start_dir = os.path.dirname(current) if current and os.path.isfile(current) else os.path.join(os.path.expanduser("~"), "Downloads")
        dlg = wx.FileDialog(
            self,
            message=_("Select Netscape format cookies.txt file"),
            defaultDir=start_dir,
            wildcard=_("Cookie files (*.txt)|*.txt|All files (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )
        with dlg:
            if dlg.ShowModal() == wx.ID_OK:
                chosen_path = dlg.GetPath()
                self.cookiesFileCtrl.SetValue(chosen_path)
                self.onTestCookiesFile(None)

    def onTestCookiesFile(self, evt: Any) -> None:
        path = self.cookiesFileCtrl.GetValue().strip().strip('"')
        valid, reason = stream_engine.check_youtube_cookies_validity(path)
        if valid:
            msg = _("The selected cookies file is valid and contains active YouTube authentication tokens.")
            caption = _("Cookies File Valid")
            icon = wx.ICON_INFORMATION
        elif reason == "expired":
            msg = _("The cookies file contains expired session tokens (LOGIN_INFO). Please export fresh cookies from an Incognito/Private window.")
            caption = _("Cookies Expired")
            icon = wx.ICON_WARNING
        elif reason == "missing_auth_tokens":
            msg = _("The cookies file does not contain necessary YouTube authentication tokens (LOGIN_INFO/SAPISID). Make sure you were logged in to YouTube when exporting.")
            caption = _("Incomplete Cookies")
            icon = wx.ICON_WARNING
        elif reason == "empty":
            msg = _("The cookies file is empty or does not contain any YouTube or Google domain cookies.")
            caption = _("Invalid Cookies")
            icon = wx.ICON_ERROR
        elif reason == "file_not_found":
            msg = _("The specified cookies file path does not exist.")
            caption = _("File Not Found")
            icon = wx.ICON_ERROR
        else:
            msg = _("No cookies file specified. Please browse for a valid cookies.txt file.")
            caption = _("No File Selected")
            icon = wx.ICON_WARNING

        if gui and hasattr(gui, "messageBox"):
            gui.messageBox(msg, caption, wx.OK | icon)
        elif ui and hasattr(ui, "message"):
            try:
                ui.message(f"{caption}: {msg}")
            except Exception:
                pass

    def onBrowseExportFolder(self, evt: Any) -> None:
        if not wx:
            return
        current = self.exportFolderCtrl.GetValue().strip()
        start_dir = current if current and os.path.isdir(current) else os.path.join(os.path.expanduser("~"), "Downloads")
        dlg = wx.DirDialog(self, message=_("Select download folder"), defaultPath=start_dir, style=wx.DD_DEFAULT_STYLE)
        with dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.exportFolderCtrl.SetValue(dlg.GetPath())

    def onSave(self) -> None:
        """
        Invoked when the user clicks OK or Apply in NVDA Settings.
        Commits all UI control values to the configuration store and informs the running engine.
        """
        if wx is None:
            return

        # Playback & Announcement settings
        for attr, key in (
            ("announceVolChk", "announceVolume"),
            ("announceSeekChk", "announceSeek"),
            ("announceSpeedChk", "announceSpeed"),
            ("announceTrackChk", "announceTrack"),
            ("announceLoopChk", "announceLoop"),
            ("announceChapterChk", "announceChapter"),
            ("announceChapterAutoChk", "announceChapterAuto"),
            ("announcePlaylistTotalDurationChk", "announcePlaylistTotalDuration"),
            ("remainingAccountsSpeedChk", "remainingTimeAccountsForSpeed"),
            ("elapsedAccountsSpeedChk", "elapsedTimeAccountsForSpeed"),
        ):
            if hasattr(self, attr):
                try:
                    setConfigValue(key, bool(getattr(self, attr).GetValue()))
                except Exception:
                    pass

        # Seek steps
        for attr, key in (
            ("seekStepNormalCtrl", "seekStepNormal"),
            ("seekStepSlowCtrl", "seekStepSlow"),
            ("seekStepFastCtrl", "seekStepFast"),
            ("seekStepUltrafastCtrl", "seekStepUltrafast"),
        ):
            if hasattr(self, attr):
                try:
                    setConfigValue(key, int(getattr(self, attr).GetValue()))
                except Exception:
                    pass

        # Default Speed
        if hasattr(self, "defaultSpeedChoice"):
            try:
                sel = self.defaultSpeedChoice.GetSelection()
                if 0 <= sel < len(SPEED_CHOICES):
                    spd_val = float(SPEED_CHOICES[sel][0])
                    setConfigValue("defaultSpeed", spd_val)
            except Exception:
                pass

        # Default Repeat Mode
        if hasattr(self, "defaultRepeatModeChoice"):
            try:
                sel = self.defaultRepeatModeChoice.GetSelection()
                if 0 <= sel < len(REPEAT_CHOICES):
                    mode_val = REPEAT_CHOICES[sel][0]
                    setConfigValue("defaultRepeatMode", mode_val)
            except Exception:
                pass

        if hasattr(self, "autoNextChk"):
            try:
                setConfigValue("autoNext", bool(self.autoNextChk.GetValue()))
            except Exception:
                pass

        if hasattr(self, "rememberPlaybackPositionChk"):
            try:
                setConfigValue("rememberPlaybackPosition", bool(self.rememberPlaybackPositionChk.GetValue()))
            except Exception:
                pass

        if hasattr(self, "rememberPlaybackStateChk"):
            try:
                val = bool(self.rememberPlaybackStateChk.GetValue())
                setConfigValue("rememberPlaybackState", val)
                if not val:
                    store = get_state_store()
                    if store and hasattr(store, "clear_last_session"):
                        store.clear_last_session()
            except Exception:
                pass
        if hasattr(self, "autoEnterPlayerModeChk"):
            try:
                setConfigValue("autoEnterPlayerMode", bool(self.autoEnterPlayerModeChk.GetValue()))
            except Exception:
                pass

        # Update recents history options
        if hasattr(self, "recentsEnabledChk"):
            try:
                setConfigValue("recentsEnabled", bool(self.recentsEnabledChk.GetValue()))
            except Exception:
                pass
        if hasattr(self, "recentsMaxEntriesCtrl"):
            try:
                setConfigValue("recentsMaxEntries", int(self.recentsMaxEntriesCtrl.GetValue()))
            except Exception:
                pass
        if hasattr(self, "recentsKeepFilesChk"):
            try:
                setConfigValue("recentsKeepFiles", bool(self.recentsKeepFilesChk.GetValue()))
            except Exception:
                pass
        if hasattr(self, "recentsKeepFoldersChk"):
            try:
                setConfigValue("recentsKeepFolders", bool(self.recentsKeepFoldersChk.GetValue()))
            except Exception:
                pass
        if hasattr(self, "recentsKeepPlaylistsChk"):
            try:
                setConfigValue("recentsKeepPlaylists", bool(self.recentsKeepPlaylistsChk.GetValue()))
            except Exception:
                pass
        if hasattr(self, "recentsKeepStreamsChk"):
            try:
                setConfigValue("recentsKeepStreams", bool(self.recentsKeepStreamsChk.GetValue()))
            except Exception:
                pass

        # Update YouTube & online streaming options
        if hasattr(self, "ytdlpChannelChoice"):
            try:
                chanSel = self.ytdlpChannelChoice.GetSelection()
                if 0 <= chanSel < len(YTDLP_CHANNEL_CHOICES):
                    setConfigValue("ytdlpUpdateChannel", YTDLP_CHANNEL_CHOICES[chanSel][0])
            except Exception:
                pass
        if hasattr(self, "streamAudioQualityChoice"):
            try:
                qualSel = self.streamAudioQualityChoice.GetSelection()
                if 0 <= qualSel < len(STREAM_QUALITY_CHOICES):
                    new_qual = STREAM_QUALITY_CHOICES[qualSel][0]
                    old_qual = getConfigValue("streamAudioQuality", "high")
                    setConfigValue("streamAudioQuality", new_qual)
                    if new_qual != old_qual:
                        if stream_engine and hasattr(stream_engine, "clear_resolve_cache"):
                            stream_engine.clear_resolve_cache()
            except Exception:
                pass
        if hasattr(self, "searchResultsCountCtrl"):
            try:
                setConfigValue("searchResultsCount", int(self.searchResultsCountCtrl.GetValue()))
            except Exception:
                pass
        if hasattr(self, "maxStreamItemsCtrl"):
            try:
                setConfigValue("maxStreamPlaylistItems", int(self.maxStreamItemsCtrl.GetValue()))
            except Exception:
                pass
        if hasattr(self, "cookiesBrowserChoice"):
            try:
                browserSel = self.cookiesBrowserChoice.GetSelection()
                if 0 <= browserSel < len(self.cookiesBrowserChoices):
                    setConfigValue("ytdlpCookiesBrowser", self.cookiesBrowserChoices[browserSel][0])
            except Exception:
                pass
        if hasattr(self, "cookiesFileCtrl"):
            try:
                setConfigValue("ytdlpCookiesFile", self.cookiesFileCtrl.GetValue().strip().strip('"'))
            except Exception:
                pass

        if hasattr(self, "exportFolderCtrl"):
            try:
                setConfigValue("exportFolder", self.exportFolderCtrl.GetValue().strip().strip('"'))
                i = self.exportFormatChoice.GetSelection()
                if 0 <= i < len(self.exportFormatChoices):
                    setConfigValue("exportFormat", self.exportFormatChoices[i][0])
                j = self.exportQualityChoice.GetSelection()
                if 0 <= j < len(self.exportQualityChoices):
                    setConfigValue("exportQuality", self.exportQualityChoices[j][0])
                setConfigValue("exportAutoCopy", bool(self.exportAutoCopyChk.GetValue()))
            except Exception:
                pass

        # Update SponsorBlock options
        if hasattr(self, "sponsorBlockEnabledChk"):
            setConfigValue("sponsorBlockEnabled", bool(self.sponsorBlockEnabledChk.GetValue()))
        if hasattr(self, "announceSponsorSkipChk"):
            setConfigValue("announceSponsorSkip", bool(self.announceSponsorSkipChk.GetValue()))
        if hasattr(self, "sbCatSponsorChk"):
            cats = []
            if self.sbCatSponsorChk.GetValue():
                cats.append("sponsor")
            if hasattr(self, "sbCatIntroChk") and self.sbCatIntroChk.GetValue():
                cats.append("intro")
            if hasattr(self, "sbCatOutroChk") and self.sbCatOutroChk.GetValue():
                cats.append("outro")
            if hasattr(self, "sbCatSelfpromoChk") and self.sbCatSelfpromoChk.GetValue():
                cats.append("selfpromo")
            if hasattr(self, "sbCatInteractionChk") and self.sbCatInteractionChk.GetValue():
                cats.append("interaction")
            if hasattr(self, "sbCatMusicOfftopicChk") and self.sbCatMusicOfftopicChk.GetValue():
                cats.append("music_offtopic")
            setConfigValue("sponsorBlockCategories", ",".join(cats))

        # Save to database store
        saveConfig()

        # Notify active player controller or engine of configuration update
        self._notifyActiveEngine(getConfig())

    def _notifyActiveEngine(self, cfg: dict) -> None:
        """
        Dispatches updated configuration to running controller or engine instances.
        """
        try:
            ctrl = get_controller()
            if ctrl is not None:
                if hasattr(ctrl, "on_config_updated"):
                    ctrl.on_config_updated(cfg)
                elif hasattr(ctrl, "onConfigUpdated"):
                    ctrl.onConfigUpdated(cfg)
        except Exception:
            pass

        try:
            engine = get_engine()
            if engine is not None:
                if hasattr(engine, "on_config_updated"):
                    engine.on_config_updated(cfg)
                elif hasattr(engine, "onConfigUpdated"):
                    engine.onConfigUpdated(cfg)
        except Exception:
            pass

    def onDiscard(self) -> None:
        """Invoked when the user cancels or discards settings changes."""
        pass
