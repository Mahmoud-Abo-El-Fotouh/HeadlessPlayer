# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Accessible shortcuts configuration dialog for Headless Media Player.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("HeadlessPlayer.ShortcutsDialog")

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

try:
    import ui
except Exception:
    ui = None

try:
    from ..utils.config_spec import (
        getConfig,
        saveConfig,
        DEFAULT_KEYMAP,
        getKeymap,
        setKeymap,
        parseKeymapKeys,
    )
except ImportError:
    from ..config_spec import (
        getConfig,
        saveConfig,
        DEFAULT_KEYMAP,
        getKeymap,
        setKeymap,
        parseKeymapKeys,
    )

try:
    from ..core.controller import get_controller
except Exception:
    def get_controller() -> Any:
        return None

from .key_capture import (
    _WxDialog,
    KeyCaptureDialog,
    ACTION_DISPLAY_NAMES,
    ACTION_CATEGORIES,
    ACTION_CATEGORY_MAP,
    get_all_key_suggestions,
)


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
        keys = parseKeymapKeys(key_id)
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
        existing = parseKeymapKeys(self.current_keymap.get(action_id, ""))
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
                keys = parseKeymapKeys(k_val)
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
            existing = parseKeymapKeys(self.current_keymap.get(act_id, ""))
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
