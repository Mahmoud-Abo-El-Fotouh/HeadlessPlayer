# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Controller Queries Mixin.
Handles spoken feedback queries, remaining/elapsed time calculations, shortcuts help, and settings dialog launch.
"""

from __future__ import annotations
import logging
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

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
except Exception:
    wx = None

try:
    import gui
except Exception:
    gui = None

try:
    import globalPluginHandler
except Exception:
    globalPluginHandler = None

from ..gui.dialogs import prompt_help_dialog
from ..gui.settings_panel import HeadlessPlayerSettingsPanel
from ..utils.config_spec import getConfig, getConfigValue
from ..utils import format_time, log_debug, log_exception

logger = logging.getLogger("HeadlessPlayer.ControllerQueries")


class ControllerQueriesMixin:
    """
    Mixin providing spoken query commands, time calculations, help modal, and settings launcher.
    """

    def speak_media_info(self) -> None:
        """Speaks full media title, duration, and playlist index."""
        with self._lock:
            info = self.engine.get_media_info()
            cur_track = self.playlist.get_current_track()
            title = (cur_track.display_name if cur_track else "") or info.get("title") or ""
            dur = info.get("duration", 0.0)
            idx = self.playlist.current_index + 1
            total = self.playlist.count
            is_loaded = bool(info.get("is_loaded") or cur_track is not None)
            self.speech.speak_media_info(
                title=title,
                duration=dur,
                current_index=idx,
                total_tracks=total,
                is_loaded=is_loaded
            )

    def speak_remaining_time(self) -> None:
        """
        Speaks remaining playback time in formatted string.
        Accounts for active playback speed (e.g. at 2.0x, remaining time is halved).
        Double-pressing in quick succession announces unscaled track remaining time.
        """
        with self._lock:
            now = time.time()
            is_double = (now - getattr(self, "_last_remaining_time_press", 0.0)) < 0.6
            self._last_remaining_time_press = now

            rem = self.engine.get_remaining_time()
            dur = self.engine.get_duration()
            speed = getattr(self.engine, "speed", 1.0)
            is_loaded = bool(self.engine.is_loaded or dur > 0)
            self.speech.speak_remaining_time(
                rem,
                duration=dur,
                is_loaded=is_loaded,
                speed=speed,
                is_raw=is_double
            )

    def speak_elapsed_time(self) -> None:
        """Speaks elapsed playback time in formatted string with speed scaling."""
        with self._lock:
            now = time.time()
            is_double = (now - getattr(self, "_last_elapsed_time_press", 0.0)) < 0.6
            self._last_elapsed_time_press = now

            el = self.engine.get_elapsed_time()
            dur = self.engine.get_duration()
            speed = getattr(self.engine, "speed", 1.0)
            is_loaded = bool(self.engine.is_loaded or dur > 0)
            self.speech.speak_elapsed_time(
                el,
                is_loaded=is_loaded,
                speed=speed,
                is_raw=is_double
            )

    def _speak_async(self, text: str) -> None:
        wx_mod = sys.modules.get("wx", wx)
        if wx_mod is not None and hasattr(wx_mod, "CallAfter"):
            try:
                wx_mod.CallAfter(self.speech.speak, text)
            except Exception:
                self.speech.speak(text)
        else:
            self.speech.speak(text)

    def get_toggle_gesture_display(self) -> str:
        """Retrieves active toggle shortcut string dynamically from NVDA."""
        try:
            gh = sys.modules.get("globalPluginHandler", globalPluginHandler)
            for plugin in getattr(gh, "runningPlugins", []):
                if plugin.__class__.__module__.endswith("HeadlessPlayer"):
                    if hasattr(plugin, "getGesturesForScript"):
                        script_func = getattr(plugin, "script_togglePlayerMode", None)
                        if script_func:
                            gestures = plugin.getGesturesForScript(script_func)
                            if gestures:
                                return ", ".join(
                                    str(g).replace("kb:", "").replace("control", "Ctrl").replace("shift", "Shift").replace("nvda", "NVDA").replace("insert", "Insert").replace("capslock", "CapsLock")
                                    for g in gestures
                                )
        except Exception as e:
            logger.debug("Error querying active toggle gesture: %s", e)
        return "NVDA+Ctrl+Shift+P / Insert+Ctrl+Shift+P"

    def show_shortcuts_help(self) -> None:
        """Presents the accessible shortcuts help window."""
        self._exit_player_mode_for_dialog()
        toggle_str = self.get_toggle_gesture_display()
        prompt_help_dialog(
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
            custom_toggle_gesture=toggle_str
        )

    def open_settings(self) -> None:
        """Ctrl + Shift + S: Exits player mode and opens NVDA Settings dialog focused on HeadlessPlayer panel."""
        def _do_open():
            opened = False
            has_gui = False
            try:
                gm = sys.modules.get("gui", gui)
                if gm and hasattr(gm, "mainFrame") and gm.mainFrame:
                    has_gui = True
                    settings_dialogs = getattr(gm, "settingsDialogs", None)
                    settings_dialog_cls = getattr(settings_dialogs, "NVDASettingsDialog", None) if settings_dialogs else getattr(gm, "NVDASettingsDialog", None)
                    popup_func = getattr(gm.mainFrame, "popupSettingsDialog", None) or getattr(gm.mainFrame, "_popupSettingsDialog", None)

                    if popup_func and callable(popup_func) and settings_dialog_cls:
                        try:
                            popup_func(settings_dialog_cls, initialCategory=HeadlessPlayerSettingsPanel)
                            opened = True
                        except TypeError:
                            try:
                                popup_func(settings_dialog_cls, HeadlessPlayerSettingsPanel)
                                opened = True
                            except TypeError:
                                try:
                                    popup_func(settings_dialog_cls)
                                    opened = True
                                except Exception:
                                    pass

                    if not opened and popup_func and callable(popup_func):
                        try:
                            popup_func(initialCategory=HeadlessPlayerSettingsPanel)
                            opened = True
                        except TypeError:
                            pass

                    if not opened:
                        pref_cmd = (
                            getattr(gm.mainFrame, "onPreferencesSettingsCommand", None)
                            or getattr(gm.mainFrame, "onPreferenceSettings", None)
                        )
                        if pref_cmd and callable(pref_cmd):
                            try:
                                try:
                                    evt = wx.CommandEvent() if wx else None
                                    pref_cmd(evt)
                                except Exception:
                                    pref_cmd(None)
                                opened = True
                            except Exception as e_pref:
                                logger.debug("onPreferencesSettingsCommand failed: %s", e_pref)

                    if not opened and settings_dialog_cls:
                        try:
                            dlg = settings_dialog_cls(gm.mainFrame, initialCategory=HeadlessPlayerSettingsPanel)
                            dlg.ShowModal()
                            dlg.Destroy()
                            opened = True
                        except Exception as e_dlg:
                            logger.debug("Direct NVDASettingsDialog instantiation failed: %s", e_dlg)

            except Exception as e:
                logger.error("Failed to open HeadlessPlayer settings panel: %s", e, exc_info=True)

            if has_gui and not opened:
                logger.warning("Could not launch NVDA settings dialog; notifying user")
                if hasattr(self, "speech") and self.speech:
                    self.speech.speak(_("Could not open settings dialog"))

        self._exit_player_mode_for_dialog()

        wx_mod = sys.modules.get("wx", wx)
        if wx_mod is not None and hasattr(wx_mod, "CallAfter"):
            try:
                wx_mod.CallAfter(_do_open)
            except Exception:
                _do_open()
        else:
            _do_open()

    open_settings_dialog = open_settings

    def close_player(self) -> None:
        """Completely closes and stops the media player."""
        with self._lock:
            if hasattr(self, "history_sync") and self.history_sync:
                self.history_sync.stop_session(reason="stop")
            if getConfigValue("rememberPlaybackState", False):
                self.save_session()
            else:
                self.state_store.clear_last_session()
            self.save_current_position()
            self.engine.stop()
            self.engine.shutdown()
            self.playlist.clear()
            self._last_loaded_path = ""
            self._current_stream_chapters = []
            if self.input_layer:
                self.input_layer.set_player_mode(False, announce=False)
            self.speech.announce_player_closed()

    def _on_dialog_cancelled(self) -> None:
        """Invoked when user cancels an open file/folder dialog."""
        self._check_auto_enter_player_mode()
