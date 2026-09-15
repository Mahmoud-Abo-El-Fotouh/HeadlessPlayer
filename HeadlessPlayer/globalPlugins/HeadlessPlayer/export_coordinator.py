# -*- coding: utf-8 -*-
from __future__ import annotations

"""
HeadlessPlayer NVDA Add-on - Clip Export Coordinator.
Coordinates range detection, source descriptions, export dialog presentation,
and background encoding for media clips and full-length conversions.
"""

import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple

try:
    from . import _  # type: ignore
except (ImportError, ValueError):
    try:
        _ = _  # type: ignore
    except NameError:
        _ = lambda text: text

from . import clip_exporter
from .export_dialog import prompt_export_dialog
from .config_spec import getConfig
from .utils import format_time

logger = logging.getLogger("HeadlessPlayer.ExportCoordinator")


class ExportCoordinator:
    """
    Coordinates clip exporting, quick export, and background ffmpeg/mpv encoding tasks.
    """

    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self.is_busy: bool = False

    def export_range(self) -> Tuple[Optional[float], Optional[float], str]:
        """
        Returns (start, end, scenario): both points, A + current position as B,
        or nothing selected.
        """
        a = self.controller.engine.ab_loop_a
        b = self.controller.engine.ab_loop_b
        if a is not None and b is not None and b > a:
            return float(a), float(b), "ab"
        if a is not None:
            pos = float(self.controller.engine.time_pos or 0.0)
            if pos > float(a) + 0.5:
                try:
                    self.controller.engine.set_ab_point_b(pos)
                except Exception:
                    pass
                return float(a), pos, "a_auto"
        return None, None, "none"

    def export_source(self, cur: Any) -> Any:
        """Describes media export source for the given track item."""
        info = None
        if getattr(cur, "is_stream", False) and getattr(self.controller, "_current_stream_info", None):
            st_info = self.controller._current_stream_info
            vid_id = str(st_info.get("id") or "")
            wp_url = str(st_info.get("webpage_url") or "")
            last_loaded = getattr(self.controller, "_last_loaded_path", None)
            if (vid_id and vid_id in (cur.path or "")) or (wp_url and wp_url == (cur.path or "")) or (cur.path == last_loaded):
                info = st_info
        return clip_exporter.describe_source(cur.path, cur.display_name, info)

    def export_clip(self) -> None:
        """
        D key: opens the Clip Exporter for the A-B selection (or the whole
        item) of the playing media.
        """
        cur = self.controller.playlist.get_current_track()
        if not cur or not cur.path:
            self.controller.speech.speak(_("Nothing is currently loaded."))
            return
        if self.is_busy:
            self.controller.speech.speak(_("An export is already in progress, please wait."))
            return
        if self.controller._current_track_is_live_stream():
            self.controller.speech.speak(_("Live streams cannot be exported."))
            return
        start, end, scenario = self.export_range()
        if scenario == "a_auto":
            self.controller.speech.speak(_("End point set at the current position."))
        intro = ""
        if scenario == "none":
            if getattr(cur, "is_stream", False):
                intro = _("No A-B selection: the whole item will be downloaded. Press Escape and use [ and ] to select a part instead.")
                self.controller.speech.speak(_("No selection. Preparing to download the whole item; use [ and ] to select a part."))
            else:
                intro = _("No A-B selection: the whole file will be converted. Press Escape and use [ and ] to select a part instead.")
                self.controller.speech.speak(_("No selection. The whole file will be exported; use [ and ] to select a part."))
        else:
            self.controller.speech.speak(
                _("Preparing export from %(a)s to %(b)s...")
                % {"a": format_time(start), "b": format_time(end)}
            )

        def worker() -> None:
            try:
                source = self.export_source(cur)
            except Exception as e:
                if "LIVE" in str(e):
                    self.controller._speak_async(_("Live streams cannot be exported."))
                else:
                    logger.error("export source failed: %s", e, exc_info=True)
                    self.controller._speak_async(
                        self.controller._stream_error_message(e)
                        if getattr(cur, "is_stream", False) else str(e)
                    )
                return
            defaults = clip_exporter.get_default_settings()

            def on_submit(res: Dict[str, Any]) -> None:
                if res.get("remember"):
                    clip_exporter.remember_settings(res)
                self.run_export(source, res, start, end, res.get("filename", ""), res.get("folder", ""))

            self.controller._exit_player_mode_for_dialog()
            prompt_export_dialog(
                source, start, end, defaults, on_submit, None,
                suspend_capture=self.controller._suspend_input,
                resume_capture=self.controller._resume_input,
                intro_message=intro
            )

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-ExportPrep").start()

    def quick_export(self) -> None:
        """Shift+D: exports the A-B selection immediately with the remembered settings."""
        cur = self.controller.playlist.get_current_track()
        if not cur or not cur.path:
            self.controller.speech.speak(_("Nothing is currently loaded."))
            return
        if self.is_busy:
            self.controller.speech.speak(_("An export is already in progress, please wait."))
            return
        if self.controller._current_track_is_live_stream():
            self.controller.speech.speak(_("Live streams cannot be exported."))
            return
        start, end, scenario = self.export_range()
        if scenario == "none":
            self.controller.speech.speak(_("Set point A (and optionally B) first, then press Shift+D for quick export."))
            return
        self.controller.speech.speak(_("Quick export in progress..."))

        def worker() -> None:
            try:
                source = self.export_source(cur)
            except Exception as e:
                self.controller._speak_async(
                    _("Live streams cannot be exported.")
                    if "LIVE" in str(e)
                    else _("Quick export failed: %s") % str(e)[:100]
                )
                return
            settings = clip_exporter.get_default_settings()
            filename = clip_exporter.suggest_filename(source.title, start, end, settings["format"])
            self.run_export(source, settings, start, end, filename, settings["folder"])

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-QuickExport").start()

    def run_export(
        self,
        source: Any,
        settings: Dict[str, Any],
        start: Optional[float],
        end: Optional[float],
        filename: str,
        folder: str
    ) -> None:
        """Executes background clip export and announces outcome."""
        self.is_busy = True
        self.controller._export_busy = True
        fmt = str(settings.get("format", "mp3")).upper()
        if start is not None:
            self.controller._speak_async(_("Exporting %(fmt)s clip in the background...") % {"fmt": fmt})
        else:
            self.controller._speak_async(
                _("Downloading and converting the whole item to %(fmt)s in the background...") % {"fmt": fmt}
            )

        def on_done(path: Optional[str], err: Optional[Exception]) -> None:
            self.is_busy = False
            self.controller._export_busy = False
            if err or not path:
                self.controller._speak_async(_("Export failed: %s") % (str(err)[:120] if err else ""))
                return
            fname = os.path.basename(path)
            target_dir = os.path.dirname(path)
            default_downloads = os.path.normcase(os.path.abspath(os.path.join(os.path.expanduser("~"), "Downloads")))
            norm_target = os.path.normcase(os.path.abspath(target_dir))
            is_downloads = (norm_target == default_downloads or norm_target.startswith(default_downloads + os.sep))
            auto_copy = bool(getConfig().get("exportAutoCopy", True))
            copied = auto_copy and bool(self.controller._copy_to_clipboard(path))

            if is_downloads:
                if copied:
                    self.controller._speak_async(
                        _("Clip saved successfully as %s in the downloads folder. It is copied to the clipboard.") % fname
                    )
                else:
                    self.controller._speak_async(
                        _("Clip saved successfully as %s in the downloads folder.") % fname
                    )
            else:
                folder_name = os.path.basename(norm_target) or norm_target
                if copied:
                    self.controller._speak_async(
                        _("Clip saved successfully as %(file)s in %(folder)s. It is copied to the clipboard.")
                        % {"file": fname, "folder": folder_name}
                    )
                else:
                    self.controller._speak_async(
                        _("Clip saved successfully as %(file)s in %(folder)s.")
                        % {"file": fname, "folder": folder_name}
                    )

        clip_exporter.export_async(source, settings, start, end, filename, folder, on_done)
