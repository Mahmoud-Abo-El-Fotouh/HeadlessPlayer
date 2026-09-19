# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Yt-dlp streaming extractor updater dialog for Headless Media Player.
"""

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger("HeadlessPlayer.UpdaterDialog")

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
    from ..streaming import engine as stream_engine
except Exception:
    stream_engine = None

_WxDialog = getattr(wx, "Dialog", object) if wx else object


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
                if stream_engine and hasattr(stream_engine, "update_ytdlp"):
                    updated, msg = stream_engine.update_ytdlp(channel=self.channel, progress_cb=progress_cb)
                else:
                    updated, msg = False, "error:stream_engine_unavailable"
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
