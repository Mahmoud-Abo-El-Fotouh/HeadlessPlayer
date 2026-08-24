# -*- coding: utf-8 -*-
"""
HeadlessPlayer Settings Panel for NVDA Preferences -> Settings Dialog.
Provides accessible wxPython configuration controls for speech feedback, seek step sizes, and playback defaults.
"""

from typing import List, Optional, Tuple, Any

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

from .config_spec import (
    getConfig,
    saveConfig,
    setConfigValue,
    DEFAULT_CONFIG,
    DEFAULT_KEYMAP,
    getKeymap,
    setKeymap,
    resetKeymap
)


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
    ("close_player", _("Close Player (Quit)")),
    ("exit_mode", _("Exit Player Mode")),
]


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

        mods = []
        if evt.ControlDown() and key_code not in (wx.WXK_CONTROL, getattr(wx, "WXK_RAW_CONTROL", -1)):
            mods.append("control")
        if evt.AltDown() and key_code != wx.WXK_ALT:
            mods.append("alt")
        if evt.ShiftDown() and key_code != wx.WXK_SHIFT:
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
        elif key_code == wx.WXK_CONTROL:
            key_name = "control"
        elif key_code == wx.WXK_SHIFT:
            key_name = "shift"
        elif key_code == wx.WXK_ALT:
            key_name = "alt"
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
                if ch in ("[]();',./-="):
                    key_name = ch
            except Exception:
                pass

        if not key_name:
            evt.Skip()
            return

        final_key = f"{'+'.join(mods)}+{key_name}" if mods else key_name
        self.captured_key = final_key
        try:
            import ui
            ui.message(_("Captured: %s") % final_key)
        except Exception:
            pass
        self.EndModal(wx.ID_OK)


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

        # 1. Action Choice
        actionLabels = [label for _, label in ACTION_DISPLAY_NAMES]
        self.actionChoice = helper.addLabeledControl(
            _("&Player Action:"),
            wx.Choice,
            choices=actionLabels
        )
        self.actionChoice.SetSelection(0)
        self.actionChoice.Bind(wx.EVT_CHOICE, self.onActionChanged)

        # 2. Current assigned key indicator
        initial_action = ACTION_DISPLAY_NAMES[0][0]
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
        initial_choices = [label for _, label in self.all_suggestions]
        self.suggestionsList = wx.ListBox(
            self,
            choices=initial_choices,
            style=wx.LB_SINGLE
        )
        self.suggestionsList.Bind(wx.EVT_LISTBOX, self.onSuggestionSelected)
        self.suggestionsList.Bind(wx.EVT_LISTBOX_DCLICK, self.onSuggestionDoubleClicked)
        helper.addItem(self.suggestionsList)

        # 5. Middle Action Buttons (Assign & Capture)
        actionBtnSizer = wx.BoxSizer(wx.HORIZONTAL)
        if hasattr(wx, "Button"):
            self.assignBtn = wx.Button(self, label=_("&Assign Selected Suggestion"))
            self.assignBtn.Bind(wx.EVT_BUTTON, self.onAssignSelectedSuggestion)
            actionBtnSizer.Add(self.assignBtn, 0, wx.ALL, 5)

            self.captureBtn = wx.Button(self, label=_("&Press Key on Keyboard Directly..."))
            self.captureBtn.Bind(wx.EVT_BUTTON, self.onCaptureKeyDirectly)
            actionBtnSizer.Add(self.captureBtn, 0, wx.ALL, 5)

        helper.addItem(actionBtnSizer)

        # 6. Dialog Bottom Control Buttons
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        if hasattr(wx, "Button"):
            self.resetBtn = wx.Button(self, label=_("&Reset to Defaults"))
            self.resetBtn.Bind(wx.EVT_BUTTON, self.onResetDefaults)
            btnSizer.Add(self.resetBtn, 0, wx.ALL, 5)

            btnSizer.AddStretchSpacer()

            self.okBtn = wx.Button(self, wx.ID_OK, label=_("OK"))
            self.okBtn.SetDefault()
            self.okBtn.Bind(wx.EVT_BUTTON, self.onSaveAndClose)
            btnSizer.Add(self.okBtn, 0, wx.ALL, 5)

            self.cancelBtn = wx.Button(self, wx.ID_CANCEL, label=_("Cancel"))
            btnSizer.Add(self.cancelBtn, 0, wx.ALL, 5)

        helper.addItem(btnSizer)
        self.SetSizerAndFit(mainSizer)

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
        if 0 <= sel < len(ACTION_DISPLAY_NAMES):
            action_id = ACTION_DISPLAY_NAMES[sel][0]
            val = self.current_keymap.get(action_id, "")
            self.currentKeyStatus.SetLabel(_("Current assigned key: %s") % self._format_key_display(val))

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

    def onSuggestionSelected(self, evt: Any) -> None:
        sel = self.suggestionsList.GetSelection()
        if 0 <= sel < len(self.filtered_suggestions):
            key_id = self.filtered_suggestions[sel][0]
            action_sel = self.actionChoice.GetSelection()
            if 0 <= action_sel < len(ACTION_DISPLAY_NAMES):
                action_id = ACTION_DISPLAY_NAMES[action_sel][0]
                self._assign_key(action_id, key_id)
                self.currentKeyStatus.SetLabel(
                    _("Current assigned key: %s") % self._format_key_display(self.current_keymap.get(action_id, ""))
                )

    def onSuggestionDoubleClicked(self, evt: Any) -> None:
        self.onSuggestionSelected(evt)

    def onAssignSelectedSuggestion(self, evt: Any) -> None:
        self.onSuggestionSelected(evt)
        try:
            import ui
            action_sel = self.actionChoice.GetSelection()
            if 0 <= action_sel < len(ACTION_DISPLAY_NAMES):
                action_name = ACTION_DISPLAY_NAMES[action_sel][1]
                action_id = ACTION_DISPLAY_NAMES[action_sel][0]
                key_id = self.current_keymap.get(action_id, "")
                ui.message(_("Assigned %s to %s") % (self._format_key_display(key_id), action_name))
        except Exception:
            pass

    def onCaptureKeyDirectly(self, evt: Any) -> None:
        dlg = KeyCaptureDialog(self)
        if dlg.ShowModal() == wx.ID_OK and dlg.captured_key:
            captured = dlg.captured_key
            action_sel = self.actionChoice.GetSelection()
            if 0 <= action_sel < len(ACTION_DISPLAY_NAMES):
                action_id = ACTION_DISPLAY_NAMES[action_sel][0]
                self._assign_key(action_id, captured)
                self.currentKeyStatus.SetLabel(
                    _("Current assigned key: %s") % self._format_key_display(self.current_keymap.get(action_id, ""))
                )
                self.searchCtrl.SetValue(captured)
        dlg.Destroy()

    def onResetDefaults(self, evt: Any) -> None:
        self.current_keymap = dict(DEFAULT_KEYMAP)
        self.onActionChanged(None)
        if gui and hasattr(gui, "messageBox"):
            gui.messageBox(
                _("Player Mode shortcuts have been reset to factory defaults."),
                _("Shortcuts Reset"),
                wx.OK | wx.ICON_INFORMATION
            )

    def onSaveAndClose(self, evt: Any) -> None:
        setKeymap(self.current_keymap)
        saveConfig()
        try:
            from .controller import get_controller
            ctrl = get_controller()
            if ctrl and hasattr(ctrl, "on_config_updated"):
                ctrl.on_config_updated(getConfig())
        except Exception:
            pass
        self.EndModal(wx.ID_OK)


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
        # Section 1: Speech Feedback & Announcements Verbosity
        # -------------------------------------------------------------
        speechGroupLabel = _("Speech Feedback & Announcements")
        speechBox = wx.StaticBox(self, label=speechGroupLabel)
        speechGroup = guiHelper.BoxSizerHelper(
            self,
            sizer=wx.StaticBoxSizer(speechBox, wx.VERTICAL)
        )

        self.announceVolumeChk = speechGroup.addItem(
            wx.CheckBox(self, label=_("Announce &volume changes"))
        )
        self.announceVolumeChk.SetValue(bool(cfg.get("announceVolume", True)))

        self.announceSeekChk = speechGroup.addItem(
            wx.CheckBox(self, label=_("Announce &seek position and jump offsets"))
        )
        self.announceSeekChk.SetValue(bool(cfg.get("announceSeek", True)))

        self.announceSpeedChk = speechGroup.addItem(
            wx.CheckBox(self, label=_("Announce playback s&peed adjustments"))
        )
        self.announceSpeedChk.SetValue(bool(cfg.get("announceSpeed", True)))

        self.announceTrackChk = speechGroup.addItem(
            wx.CheckBox(self, label=_("Announce &track titles and playlist navigation"))
        )
        self.announceTrackChk.SetValue(bool(cfg.get("announceTrack", True)))

        self.announceLoopChk = speechGroup.addItem(
            wx.CheckBox(self, label=_("Announce A-B &loop and segment markers"))
        )
        self.announceLoopChk.SetValue(bool(cfg.get("announceLoop", True)))

        self.announceChapterChk = speechGroup.addItem(
            wx.CheckBox(self, label=_("Announce &chapter markers and names"))
        )
        self.announceChapterChk.SetValue(bool(cfg.get("announceChapter", True)))

        helper.addItem(speechGroup.sizer)

        # -------------------------------------------------------------
        # Section 2: Seek Jump Step Sizes (Seconds)
        # -------------------------------------------------------------
        seekGroupLabel = _("Seek Jump Step Sizes (Seconds)")
        seekBox = wx.StaticBox(self, label=seekGroupLabel)
        seekGroup = guiHelper.BoxSizerHelper(
            self,
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

        helper.addItem(seekGroup.sizer)

        # -------------------------------------------------------------
        # Section 3: Playback Defaults & Options
        # -------------------------------------------------------------
        playbackGroupLabel = _("Playback Defaults & Options")
        playbackBox = wx.StaticBox(self, label=playbackGroupLabel)
        playbackGroup = guiHelper.BoxSizerHelper(
            self,
            sizer=wx.StaticBoxSizer(playbackBox, wx.VERTICAL)
        )

        # Default Playback Speed Choice
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

        # Default Repeat Mode Choice
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

        # Auto-Next Checkbox
        self.autoNextChk = playbackGroup.addItem(
            wx.CheckBox(self, label=_("Auto-advance to &next track when media finishes"))
        )
        self.autoNextChk.SetValue(bool(cfg.get("defaultAutoNext", True)))

        # Resume Playback Position Checkbox
        self.resumePositionChk = playbackGroup.addItem(
            wx.CheckBox(self, label=_("Remember and &resume playback position for media"))
        )
        self.resumePositionChk.SetValue(bool(cfg.get("resumePosition", True)))

        # Audio Cues / Modal Tones Checkbox
        self.playModalTonesChk = playbackGroup.addItem(
            wx.CheckBox(self, label=_("Play audio &earcons when entering/exiting Player Mode"))
        )
        self.playModalTonesChk.SetValue(bool(cfg.get("playModalTones", False)))

        # Auto Enter Player Mode on Open
        self.autoEnterPlayerModeChk = playbackGroup.addItem(
            wx.CheckBox(self, label=_("Automatically enter &Player Mode when loading new media"))
        )
        self.autoEnterPlayerModeChk.SetValue(bool(cfg.get("autoEnterPlayerMode", True)))

        helper.addItem(playbackGroup.sizer)

        # -------------------------------------------------------------
        # Section 4: YouTube & Online Streaming (yt-dlp)
        # -------------------------------------------------------------
        from . import stream_engine

        streamGroupLabel = _("YouTube & Online Streaming (yt-dlp)")
        streamBox = wx.StaticBox(self, label=streamGroupLabel)
        streamGroup = guiHelper.BoxSizerHelper(
            self,
            sizer=wx.StaticBoxSizer(streamBox, wx.VERTICAL)
        )

        ver = stream_engine.get_bundled_version() or _("not installed")
        self.ytdlpVersionText = streamGroup.addItem(
            wx.StaticText(self, label=_("Streaming engine (yt-dlp) version: %s") % ver)
        )

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
            ("none", _("Disabled (no sign-in)")),
            ("firefox", "Firefox"),
            ("chrome", "Google Chrome"),
            ("edge", "Microsoft Edge"),
            ("brave", "Brave"),
            ("opera", "Opera"),
            ("vivaldi", "Vivaldi"),
        ]
        self.cookiesBrowserChoice = streamGroup.addLabeledControl(
            _("Use sign-in coo&kies from browser (for age-restricted or members-only content):"),
            wx.Choice,
            choices=[label for val, label in self.cookiesBrowserChoices]
        )
        curBrowser = str(cfg.get("ytdlpCookiesBrowser", "none")).lower()
        browserIdx = 0
        for i, (val, label) in enumerate(self.cookiesBrowserChoices):
            if val == curBrowser:
                browserIdx = i
                break
        self.cookiesBrowserChoice.SetSelection(browserIdx)

        # Manual cookies file: reliable sign-in even when the browser blocks
        # automatic cookie extraction (e.g. Chrome's app-bound encryption).
        self.cookiesFileCtrl = streamGroup.addLabeledControl(
            _("Manual sign-in cookies &file (cookies.txt in Netscape format):"),
            wx.TextCtrl
        )
        self.cookiesFileCtrl.SetValue(str(cfg.get("ytdlpCookiesFile", "") or ""))

        self.browseCookiesBtn = streamGroup.addItem(
            wx.Button(self, label=_("&Browse for cookies file..."))
        )
        if hasattr(wx, "EVT_BUTTON"):
            self.browseCookiesBtn.Bind(wx.EVT_BUTTON, self.onBrowseCookiesFile)

        cookiesHint = wx.StaticText(
            self,
            label=_(
                "Tip: export cookies.txt while signed in to YouTube using a browser "
                "extension such as 'Get cookies.txt LOCALLY' (Chrome/Edge) or "
                "'cookies.txt' (Firefox). The manual file takes priority over the "
                "browser choice above, and works even when Chrome blocks automatic "
                "cookie extraction."
            )
        )
        cookiesHint.Wrap(560)
        streamGroup.addItem(cookiesHint)

        self.checkUpdatesBtn = streamGroup.addItem(
            wx.Button(self, label=_("Check for &Updates of the streaming engine now..."))
        )
        if hasattr(wx, "EVT_BUTTON"):
            self.checkUpdatesBtn.Bind(wx.EVT_BUTTON, self.onCheckYtdlpUpdates)

        helper.addItem(streamGroup.sizer)

        # -------------------------------------------------------------
        # Section 5: SponsorBlock (YouTube Ad & Sponsor Skipping)
        # -------------------------------------------------------------
        if hasattr(wx, "CheckBox") and hasattr(wx, "StaticBox"):
            sbGroupLabel = _("SponsorBlock (Auto-Skip YouTube Ads & Sponsors)")
            sbBox = wx.StaticBox(self, label=sbGroupLabel)
            sbGroup = guiHelper.BoxSizerHelper(
                self,
                sizer=wx.StaticBoxSizer(sbBox, wx.VERTICAL)
            )

            self.sponsorBlockEnabledChk = sbGroup.addItem(
                wx.CheckBox(
                    self,
                    label=_("Enable &SponsorBlock (Auto-skip YouTube sponsors, promos & intros)")
                )
            )
            self.sponsorBlockEnabledChk.SetValue(bool(cfg.get("sponsorBlockEnabled", True)))

            self.announceSponsorSkipChk = sbGroup.addItem(
                wx.CheckBox(
                    self,
                    label=_("&Announce when a sponsor or promo segment is skipped")
                )
            )
            self.announceSponsorSkipChk.SetValue(bool(cfg.get("announceSponsorSkip", True)))

            helper.addItem(sbGroup.sizer)

        # -------------------------------------------------------------
        # Section 6: Customizable Shortcuts Dialog
        # -------------------------------------------------------------
        if hasattr(wx, "Button") and hasattr(wx, "StaticBox"):
            shortcutsGroupLabel = _("Player Mode Keyboard Shortcuts")
            shortcutsBox = wx.StaticBox(self, label=shortcutsGroupLabel)
            shortcutsGroup = guiHelper.BoxSizerHelper(
                self,
                sizer=wx.StaticBoxSizer(shortcutsBox, wx.VERTICAL)
            )

            self.customizeShortcutsBtn = shortcutsGroup.addItem(
                wx.Button(self, label=_("Customize Player Mode &Shortcuts..."))
            )
            if hasattr(wx, "EVT_BUTTON"):
                self.customizeShortcutsBtn.Bind(wx.EVT_BUTTON, self.onCustomizeShortcuts)

            helper.addItem(shortcutsGroup.sizer)

        # -------------------------------------------------------------
        # Section 6: Add-on Self-Updater
        # -------------------------------------------------------------
        if hasattr(wx, "Button") and hasattr(wx, "StaticBox"):
            addonUpdatesGroupLabel = _("Headless Media Player Add-on Updates")
            addonUpdatesBox = wx.StaticBox(self, label=addonUpdatesGroupLabel)
            addonUpdatesGroup = guiHelper.BoxSizerHelper(
                self,
                sizer=wx.StaticBoxSizer(addonUpdatesBox, wx.VERTICAL)
            )

            from . import addon_updater
            cur_ver_str = addon_updater.get_current_addon_version()
            self.addonVersionText = addonUpdatesGroup.addItem(
                wx.StaticText(self, label=_("Installed add-on version: %s") % cur_ver_str)
            )

            self.checkAddonUpdatesBtn = addonUpdatesGroup.addItem(
                wx.Button(self, label=_("Check for &Add-on Updates on GitHub..."))
            )
            if hasattr(wx, "EVT_BUTTON"):
                self.checkAddonUpdatesBtn.Bind(wx.EVT_BUTTON, self.onCheckAddonUpdates)

            helper.addItem(addonUpdatesGroup.sizer)

        # -------------------------------------------------------------
        # Section 8: About & Developer
        # -------------------------------------------------------------
        if hasattr(wx, "Button") and hasattr(wx, "StaticBox"):
            aboutGroupLabel = _("About & Developer")
            aboutBox = wx.StaticBox(self, label=aboutGroupLabel)
            aboutGroup = guiHelper.BoxSizerHelper(
                self,
                sizer=wx.StaticBoxSizer(aboutBox, wx.VERTICAL)
            )

            self.followDevBtn = aboutGroup.addItem(
                wx.Button(self, label=_("&Follow Developer on Telegram (Mahmoud Abo El Fotouh)..."))
            )
            if hasattr(wx, "EVT_BUTTON"):
                self.followDevBtn.Bind(wx.EVT_BUTTON, self.onFollowDeveloper)

            helper.addItem(aboutGroup.sizer)

    def onFollowDeveloper(self, evt: Any) -> None:
        """Opens developer's Telegram link in the default browser."""
        import webbrowser
        try:
            webbrowser.open("https://t.me/mahmoud_EG_1")
        except Exception as e:
            logger.error("Failed to open developer Telegram link: %s", e)

    def onBrowseCookiesFile(self, evt: Any) -> None:
        """Opens a file picker for the manual cookies.txt file."""
        if not wx:
            return
        import os
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
                self.cookiesFileCtrl.SetValue(dlg.GetPath())

    def onCheckYtdlpUpdates(self, evt: Any) -> None:
        """
        Checks PyPI for a newer yt-dlp streaming engine and installs it into
        the add-on in the background. YouTube extraction libraries break
        frequently, so this keeps the feature alive without reinstalling
        the whole add-on.
        """
        if not wx:
            return
        import threading
        from . import stream_engine

        self.checkUpdatesBtn.Disable()
        self.checkUpdatesBtn.SetLabel(_("Checking for updates..."))
        try:
            import ui
            ui.message(_("Checking for streaming engine updates, please wait..."))
        except Exception:
            pass

        def report_progress(stage: str) -> None:
            labels = {
                "checking": _("Checking for updates..."),
                "downloading": _("Downloading update..."),
                "installing": _("Installing update..."),
            }
            label = labels.get(stage)
            if label:
                wx.CallAfter(self.checkUpdatesBtn.SetLabel, label)

        def worker() -> None:
            try:
                updated, message = stream_engine.update_ytdlp(progress_cb=report_progress)
            except Exception as e:
                updated, message = False, f"error:unexpected:{e}"
            wx.CallAfter(self._onUpdateFinished, updated, message)

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-YtdlpUpdate").start()

    def _onUpdateFinished(self, updated: bool, message: str) -> None:
        if not wx:
            return
        self.checkUpdatesBtn.Enable()
        self.checkUpdatesBtn.SetLabel(_("Check for &Updates of the streaming engine now..."))

        if updated:
            new_ver = message.split(":", 1)[1] if ":" in message else ""
            text = _(
                "The streaming engine was updated successfully to version %s.\n"
                "Please restart NVDA to start using the new version."
            ) % new_ver
            caption = _("Update Installed")
            icon = wx.ICON_INFORMATION
            if hasattr(self, "ytdlpVersionText"):
                self.ytdlpVersionText.SetLabel(
                    _("Streaming engine (yt-dlp) version: %s (restart NVDA to activate)") % new_ver
                )
        elif message.startswith("up-to-date"):
            cur = message.split(":", 1)[1] if ":" in message else ""
            text = _("The streaming engine is already up to date (version %s).") % cur
            caption = _("No Update Needed")
            icon = wx.ICON_INFORMATION
        else:
            text = _(
                "Could not update the streaming engine.\n"
                "Check your internet connection and try again.\n\nDetails: %s"
            ) % message
            caption = _("Update Failed")
            icon = wx.ICON_ERROR

        if gui and hasattr(gui, "messageBox"):
            gui.messageBox(text, caption, wx.OK | icon)
        else:
            try:
                import ui
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
        import threading
        from . import addon_updater

        self.checkAddonUpdatesBtn.Disable()
        self.checkAddonUpdatesBtn.SetLabel(_("Checking for add-on updates..."))
        try:
            import ui
            ui.message(_("Checking for add-on updates, please wait..."))
        except Exception:
            pass

        def worker() -> None:
            try:
                available, info, status = addon_updater.check_for_addon_update()
            except Exception as e:
                available, info, status = False, None, f"error:{e}"
            wx.CallAfter(self._onAddonUpdateCheckFinished, available, info, status)

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-AddonUpdateCheck").start()

    def _onAddonUpdateCheckFinished(self, available: bool, info: Optional[dict], status: str) -> None:
        if not wx:
            return
        self.checkAddonUpdatesBtn.Enable()
        self.checkAddonUpdatesBtn.SetLabel(_("Check for &Add-on Updates on GitHub..."))

        if available and info:
            from .addon_updater import AddonUpdateDialog
            dlg = AddonUpdateDialog(self, info)
            dlg.ShowModal()
            dlg.Destroy()
        elif status == "up_to_date" and info:
            cur_ver = info.get("current_version", "")
            text = _("You are already using the latest version of Headless Media Player (version %s).") % cur_ver
            caption = _("No Update Needed")
            if gui and hasattr(gui, "messageBox"):
                gui.messageBox(text, caption, wx.OK | wx.ICON_INFORMATION)
            else:
                try:
                    import ui
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
            else:
                try:
                    import ui
                    ui.message(text)
                except Exception:
                    pass

    def onSave(self) -> None:
        """
        Invoked when the user clicks OK or Apply in NVDA Settings.
        Commits all UI control values to the configuration store and informs the running engine.
        """
        if wx is None:
            return

        # Update speech announcement flags
        if hasattr(self, "announceVolumeChk"):
            setConfigValue("announceVolume", bool(self.announceVolumeChk.GetValue()))
        if hasattr(self, "announceSeekChk"):
            setConfigValue("announceSeek", bool(self.announceSeekChk.GetValue()))
        if hasattr(self, "announceSpeedChk"):
            setConfigValue("announceSpeed", bool(self.announceSpeedChk.GetValue()))
        if hasattr(self, "announceTrackChk"):
            setConfigValue("announceTrack", bool(self.announceTrackChk.GetValue()))
        if hasattr(self, "announceLoopChk"):
            setConfigValue("announceLoop", bool(self.announceLoopChk.GetValue()))
        if hasattr(self, "announceChapterChk"):
            setConfigValue("announceChapter", bool(self.announceChapterChk.GetValue()))

        # Update seek step sizes
        if hasattr(self, "seekStepNormalCtrl"):
            setConfigValue("seekStepNormal", int(self.seekStepNormalCtrl.GetValue()))
        if hasattr(self, "seekStepSlowCtrl"):
            setConfigValue("seekStepSlow", int(self.seekStepSlowCtrl.GetValue()))
        if hasattr(self, "seekStepFastCtrl"):
            setConfigValue("seekStepFast", int(self.seekStepFastCtrl.GetValue()))
        if hasattr(self, "seekStepUltrafastCtrl"):
            setConfigValue("seekStepUltrafast", int(self.seekStepUltrafastCtrl.GetValue()))

        # Update default speed
        if hasattr(self, "defaultSpeedChoice"):
            speedSel = self.defaultSpeedChoice.GetSelection()
            if 0 <= speedSel < len(SPEED_CHOICES):
                setConfigValue("defaultSpeed", float(SPEED_CHOICES[speedSel][0]))

        # Update default repeat mode
        if hasattr(self, "defaultRepeatChoice"):
            repeatSel = self.defaultRepeatChoice.GetSelection()
            if 0 <= repeatSel < len(REPEAT_CHOICES):
                setConfigValue("defaultRepeatMode", REPEAT_CHOICES[repeatSel][0])

        # Update playback behavior options
        if hasattr(self, "autoNextChk"):
            setConfigValue("defaultAutoNext", bool(self.autoNextChk.GetValue()))
        if hasattr(self, "resumePositionChk"):
            setConfigValue("resumePosition", bool(self.resumePositionChk.GetValue()))
        if hasattr(self, "playModalTonesChk"):
            setConfigValue("playModalTones", bool(self.playModalTonesChk.GetValue()))
        if hasattr(self, "autoEnterPlayerModeChk"):
            setConfigValue("autoEnterPlayerMode", bool(self.autoEnterPlayerModeChk.GetValue()))

        # Update YouTube & online streaming options
        if hasattr(self, "searchResultsCountCtrl"):
            setConfigValue("searchResultsCount", int(self.searchResultsCountCtrl.GetValue()))
        if hasattr(self, "maxStreamItemsCtrl"):
            setConfigValue("maxStreamPlaylistItems", int(self.maxStreamItemsCtrl.GetValue()))
        if hasattr(self, "cookiesBrowserChoice"):
            browserSel = self.cookiesBrowserChoice.GetSelection()
            if 0 <= browserSel < len(self.cookiesBrowserChoices):
                setConfigValue("ytdlpCookiesBrowser", self.cookiesBrowserChoices[browserSel][0])
        if hasattr(self, "cookiesFileCtrl"):
            setConfigValue("ytdlpCookiesFile", self.cookiesFileCtrl.GetValue().strip().strip('"'))

        # Update SponsorBlock options
        if hasattr(self, "sponsorBlockEnabledChk"):
            setConfigValue("sponsorBlockEnabled", bool(self.sponsorBlockEnabledChk.GetValue()))
        if hasattr(self, "announceSponsorSkipChk"):
            setConfigValue("announceSponsorSkip", bool(self.announceSponsorSkipChk.GetValue()))

        # Save to SQLite store
        saveConfig()

        # Notify active player controller or engine of configuration update
        self._notifyActiveEngine(getConfig())

    def _notifyActiveEngine(self, cfg: dict) -> None:
        """
        Dispatches updated configuration to running controller or engine instances.
        """
        try:
            from .controller import get_controller
            ctrl = get_controller()
            if ctrl is not None:
                if hasattr(ctrl, "on_config_updated"):
                    ctrl.on_config_updated(cfg)
                elif hasattr(ctrl, "onConfigUpdated"):
                    ctrl.onConfigUpdated(cfg)
        except Exception:
            pass

        try:
            from .engine import get_engine
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
