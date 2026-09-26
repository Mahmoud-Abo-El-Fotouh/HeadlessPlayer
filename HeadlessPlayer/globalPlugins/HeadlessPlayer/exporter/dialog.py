# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Clip Exporter dialog (D key).
Screen-reader friendly wx dialog: filename, format, quality, video quality,
audio-to-story conversion, destination folder, remember settings.
"""

from __future__ import annotations
import logging
import os
import sys
from typing import Any, Callable, Dict, List, Optional

try:
    import wx
except Exception:
    wx = None

try:
    import gui
    from gui import guiHelper
except Exception:
    gui = None
    guiHelper = None

from . import exporter as ce

logger = logging.getLogger("HeadlessPlayer.ExportDialog")

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


def format_labels(has_video: bool = True, audio_to_video: bool = False) -> List[tuple]:
    if has_video:
        return [
            ("mp3", _("Audio MP3 (works everywhere)")),
            ("m4a", _("Audio M4A / AAC (high purity)")),
            ("mp4", _("Video MP4 (H.264 + AAC, stories & chats)")),
        ]
    elif audio_to_video:
        return [
            ("mp4", _("Video MP4 (H.264 + AAC, stories & chats)")),
        ]
    else:
        return [
            ("mp3", _("Audio MP3 (works everywhere)")),
            ("m4a", _("Audio M4A / AAC (high purity)")),
        ]


def quality_labels() -> List[tuple]:
    return [
        ("high", _("Highest quality (original)")),
        ("story", _("Story optimized (small file, fast upload)")),
    ]


def prompt_export_dialog(
    source: Any,
    start: Optional[float],
    end: Optional[float],
    defaults: Dict[str, Any],
    on_submit: Callable[[Dict[str, Any]], None],
    on_cancelled: Optional[Callable[[], None]] = None,
    suspend_capture: Optional[Callable[[], None]] = None,
    resume_capture: Optional[Callable[[], None]] = None,
    intro_message: str = "",
) -> None:
    """Shows the exporter dialog on the wx main thread."""

    # Resolve module globals dynamically in case wx or gui were patched in unit tests
    mod = sys.modules.get("globalPlugins.HeadlessPlayer.exporter.dialog") or sys.modules.get("globalPlugins.HeadlessPlayer.export_dialog", sys.modules[__name__])
    cur_wx = getattr(mod, "wx", wx)
    cur_gui = getattr(mod, "gui", gui)
    cur_guiHelper = getattr(mod, "guiHelper", guiHelper)

    def _show() -> None:
        if not cur_wx or not cur_gui or not cur_guiHelper:
            logger.warning("wx unavailable; cannot show export dialog")
            if on_cancelled:
                on_cancelled()
            return

        if suspend_capture:
            try:
                suspend_capture()
            except Exception:
                pass
        if hasattr(cur_gui, "mainFrame") and hasattr(cur_gui.mainFrame, "prePopup"):
            try:
                cur_gui.mainFrame.prePopup()
            except Exception:
                pass

        result: Optional[Dict[str, Any]] = None
        try:
            if start is not None and end is not None:
                title = _("Export clip: %(title)s (from %(a)s to %(b)s, %(d)d seconds)") % {
                    "title": source.title, "a": ce.fmt_clock(start).replace("-", ":"),
                    "b": ce.fmt_clock(end).replace("-", ":"), "d": int(round(end - start)),
                }
            else:
                title = _("Download / export whole item: %s") % source.title
            dlg = cur_wx.Dialog(getattr(cur_gui, "mainFrame", None), title=title)
            sizer = cur_wx.BoxSizer(cur_wx.VERTICAL)
            helper = cur_guiHelper.BoxSizerHelper(dlg, sizer=sizer)
            if intro_message:
                helper.addItem(cur_wx.StaticText(dlg, label=intro_message))

            has_vid = bool(getattr(source, "has_video", False))
            initial_a2v = bool(defaults.get("audio_to_video", False)) if not has_vid else False

            fmts = format_labels(has_video=has_vid, audio_to_video=initial_a2v)
            quals = quality_labels()
            cur_fmt = str(defaults.get("format", "mp3"))
            if not has_vid and not initial_a2v and cur_fmt == "mp4":
                cur_fmt = "mp3"
            elif not has_vid and initial_a2v:
                cur_fmt = "mp4"
            cur_q = str(defaults.get("quality", "high"))

            nameCtrl = helper.addLabeledControl(_("File &name:"), cur_wx.TextCtrl)
            fmtChoice = helper.addLabeledControl(_("Export &format:"), cur_wx.Choice, choices=[l for _v, l in fmts])
            fmtChoice.SetSelection(next((i for i, (v, _l) in enumerate(fmts) if v == cur_fmt), 0))
            qChoice = helper.addLabeledControl(_("&Quality / size:"), cur_wx.Choice, choices=[l for _v, l in quals])
            qChoice.SetSelection(next((i for i, (v, _l) in enumerate(quals) if v == cur_q), 0))

            vq_labels = [v[0] for v in getattr(source, "video_options", [])]
            vqChoice = None
            if vq_labels:
                vqChoice = helper.addLabeledControl(_("&Video quality (YouTube):"), cur_wx.Choice, choices=vq_labels)
                want = str(defaults.get("video_quality") or "")
                if want in vq_labels:
                    vqChoice.SetSelection(vq_labels.index(want))
                else:
                    pref_idx = 0
                    for pref in ("720p", "1080p", "480p", "360p"):
                        if pref in vq_labels:
                            pref_idx = vq_labels.index(pref)
                            break
                    vqChoice.SetSelection(pref_idx)

            wavChk = None
            if not has_vid:
                wavChk = helper.addItem(cur_wx.CheckBox(dlg, label=_("Convert audio to a story video (MP4 with animated &waveform)")))
                wavChk.SetValue(initial_a2v)

            folderCtrl = helper.addLabeledControl(_("Save &to folder:"), cur_wx.TextCtrl)
            folderCtrl.SetValue(str(defaults.get("folder") or ce.get_export_folder()))
            browseBtn = helper.addItem(cur_wx.Button(dlg, label=_("&Browse...")))
            rememberChk = helper.addItem(cur_wx.CheckBox(dlg, label=_("&Remember these settings for Quick Export (Shift+D)")))
            rememberChk.SetValue(True)

            known_exts = {"mp3", "m4a", "mp4", "wav", "flac", "opus", "mkv", "avi", "webm"}

            def _ext() -> str:
                i = fmtChoice.GetSelection()
                if isinstance(i, int) and 0 <= i < len(fmts):
                    return fmts[i][0]
                return "mp4" if (wavChk is not None and wavChk.GetValue()) else "mp3"

            def _on_wav_toggle(evt: Any = None) -> None:
                nonlocal fmts
                is_a2v = bool(wavChk.GetValue()) if wavChk is not None else False
                fmts = format_labels(has_video=has_vid, audio_to_video=is_a2v)
                new_choices = [l for _v, l in fmts]
                if hasattr(fmtChoice, "Clear") and hasattr(fmtChoice, "Append"):
                    fmtChoice.Clear()
                    for ch in new_choices:
                        fmtChoice.Append(ch)
                    fmtChoice.SetSelection(0)
                elif hasattr(fmtChoice, "SetItems"):
                    fmtChoice.SetItems(new_choices)
                    fmtChoice.SetSelection(0)
                _refresh_name()
                if evt is not None:
                    evt.Skip()

            def _refresh_name(evt: Any = None) -> None:
                cur = nameCtrl.GetValue().strip()
                root = cur
                if cur:
                    for ke in known_exts:
                        if cur.lower().endswith("." + ke):
                            root = cur[:-(len(ke) + 1)].rstrip(".")
                            break
                if not root:
                    suggested = ce.suggest_filename(source.title, start, end, "")
                    root = suggested.rstrip(".")
                nameCtrl.SetValue(root + "." + _ext())
                is_video = _ext() == "mp4"
                if vqChoice is not None:
                    vqChoice.Enable(is_video and not (wavChk is not None and wavChk.GetValue()))
                if evt is not None:
                    evt.Skip()

            def _browse(evt: Any) -> None:
                d = cur_wx.DirDialog(dlg, message=_("Select export folder"), defaultPath=folderCtrl.GetValue() or ce.get_export_folder())
                with d:
                    if d.ShowModal() == cur_wx.ID_OK:
                        folderCtrl.SetValue(d.GetPath())

            fmtChoice.Bind(cur_wx.EVT_CHOICE, _refresh_name)
            if wavChk is not None:
                wavChk.Bind(cur_wx.EVT_CHECKBOX, _on_wav_toggle)
            browseBtn.Bind(cur_wx.EVT_BUTTON, _browse)
            _refresh_name()

            buttons = cur_wx.StdDialogButtonSizer()
            ok = cur_wx.Button(dlg, cur_wx.ID_OK, label=_("&Export"))
            ok.SetDefault()
            buttons.AddButton(ok)
            buttons.AddButton(cur_wx.Button(dlg, cur_wx.ID_CANCEL, label=_("Cancel")))
            buttons.Realize()
            helper.addItem(buttons)
            dlg.SetSizerAndFit(sizer)
            dlg.CentreOnScreen()
            nameCtrl.SetFocus()
            nameCtrl.SelectAll()
            with dlg:
                if dlg.ShowModal() == cur_wx.ID_OK:
                    i = fmtChoice.GetSelection()
                    j = qChoice.GetSelection()
                    is_a2v = bool(wavChk.GetValue()) if wavChk is not None else False
                    sel_fmt = fmts[i][0] if (isinstance(i, int) and 0 <= i < len(fmts)) else _ext()
                    if not has_vid and not is_a2v and sel_fmt == "mp4":
                        sel_fmt = "mp3"
                    result = {
                        "filename": nameCtrl.GetValue().strip() or ce.suggest_filename(source.title, start, end, sel_fmt),
                        "format": sel_fmt,
                        "quality": quals[j][0] if (isinstance(j, int) and 0 <= j < len(quals)) else "high",
                        "video_quality": (vq_labels[vqChoice.GetSelection()] if vqChoice is not None and vqChoice.GetSelection() >= 0 else ""),
                        "audio_to_video": is_a2v,
                        "folder": folderCtrl.GetValue().strip() or ce.get_export_folder(),
                        "remember": bool(rememberChk.GetValue()),
                    }
        except Exception as e:
            logger.error("Error showing export dialog: %s", e, exc_info=True)
        finally:
            if hasattr(cur_gui, "mainFrame") and hasattr(cur_gui.mainFrame, "postPopup"):
                try:
                    cur_gui.mainFrame.postPopup()
                except Exception:
                    pass
            if resume_capture:
                try:
                    resume_capture()
                except Exception:
                    pass

        if result is not None:
            on_submit(result)
        elif on_cancelled:
            on_cancelled()

    if cur_wx and hasattr(cur_wx, "CallAfter"):
        if hasattr(cur_wx, "GetApp"):
            if cur_wx.GetApp():
                cur_wx.CallAfter(_show)
            else:
                _show()
        else:
            cur_wx.CallAfter(_show)
    else:
        _show()
