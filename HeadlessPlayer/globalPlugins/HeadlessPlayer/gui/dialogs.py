# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Safe wx Native File & Folder Dialog Utilities.
Dispatches native Windows file and folder selection dialogs safely to the
wxPython main loop with gui.mainFrame.prePopup() / postPopup() brackets
and modal keyboard capture suspension/resumption callbacks.
"""

from __future__ import annotations
import logging
import os
import threading
from typing import Any, Callable, List, Optional

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

try:
    import ui
except Exception:
    ui = None

try:
    from ..utils.config_spec import getKeymap, getConfig
except ImportError:
    try:
        from ..config_spec import getKeymap, getConfig
    except ImportError:
        try:
            from config_spec import getKeymap, getConfig
        except ImportError:
            getKeymap = lambda: {}
            getConfig = lambda: {}

try:
    from ..utils import get_media_dialog_wildcard
except ImportError:
    try:
        from ..utils.explorer import get_media_dialog_wildcard
    except ImportError:
        from utils import get_media_dialog_wildcard

try:
    from .. import _  # type: ignore
except (ImportError, ValueError):
    try:
        from . import _  # type: ignore
    except (ImportError, ValueError):
        try:
            _ = _  # type: ignore
        except NameError:
            _ = lambda text: text

logger = logging.getLogger("HeadlessPlayer.DialogUtils")

# Test mock handler hook for unit tests running outside wx GUI
_test_dialog_handler: Optional[Callable[[str, dict], Any]] = None


def set_dialog_test_handler(handler: Optional[Callable[[str, dict], Any]]) -> None:
    """
    Sets an optional test handler for mocking dialog responses in headless tests.
    """
    global _test_dialog_handler
    _test_dialog_handler = handler


def prompt_open_file_dialog(
    on_file_selected: Callable[[str], None],
    on_cancelled: Optional[Callable[[], None]] = None,
    suspend_capture: Optional[Callable[[], None]] = None,
    resume_capture: Optional[Callable[[], None]] = None,
    parent_window: Any = None,
    title: Optional[str] = None,
    default_dir: Optional[str] = None,
    wildcard: Optional[str] = None
) -> None:
    """
    Presents a native single file selection dialog safely on the wx main thread.
    
    Args:
        on_file_selected: Callback invoked with the selected absolute file path.
        on_cancelled: Callback invoked if user cancels the dialog.
        suspend_capture: Callback to temporarily suspend modal keyboard capture.
        resume_capture: Callback to resume modal keyboard capture upon dismissal.
        parent_window: Parent wx window (defaults to gui.mainFrame).
        title: Dialog title.
        default_dir: Initial directory to open.
        wildcard: Custom file filter wildcard string.
    """
    # Check test hook first
    if _test_dialog_handler is not None:
        try:
            if suspend_capture:
                suspend_capture()
            res = _test_dialog_handler("file", {
                "title": title,
                "default_dir": default_dir,
                "wildcard": wildcard,
            })
            if resume_capture:
                resume_capture()
            if res:
                on_file_selected(os.path.abspath(res))
            elif on_cancelled:
                on_cancelled()
        except Exception as e:
            logger.error(f"Error in test dialog handler: {e}")
            if resume_capture:
                resume_capture()
            if on_cancelled:
                on_cancelled()
        return

    def _show_dialog() -> None:
        if not wx or not gui:
            logger.warning("wx or gui module not available; cannot display FileDialog")
            if on_cancelled:
                on_cancelled()
            return

        # 1. Suspend modal keyboard capture before opening dialog
        if suspend_capture:
            try:
                suspend_capture()
            except Exception as e:
                logger.warning(f"Error suspending keyboard capture: {e}")

        # 2. Pre-popup NVDA GUI notification
        parent = parent_window or getattr(gui, "mainFrame", None)
        if hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "prePopup"):
            try:
                gui.mainFrame.prePopup()
            except Exception:
                pass

        selected_path: Optional[str] = None
        dlg_title = title or _("Select Media File")
        dlg_wildcard = wildcard or get_media_dialog_wildcard()
        initial_dir = default_dir or os.path.expanduser("~")

        try:
            dlg = wx.FileDialog(
                parent=parent,
                message=dlg_title,
                defaultDir=initial_dir,
                wildcard=dlg_wildcard,
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
            )
            with dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    path = dlg.GetPath()
                    if path and os.path.exists(path):
                        selected_path = os.path.abspath(path)
        except Exception as e:
            logger.error(f"Error displaying wx.FileDialog: {e}")
            selected_path = None
        finally:
            # 3. Post-popup NVDA GUI notification
            if hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "postPopup"):
                try:
                    gui.mainFrame.postPopup()
                except Exception:
                    pass

            # 4. Resume modal keyboard capture upon dismissal
            if resume_capture:
                try:
                    resume_capture()
                except Exception as e:
                    logger.warning(f"Error resuming keyboard capture: {e}")

        # 5. Dispatch result callback
        if selected_path:
            try:
                on_file_selected(selected_path)
            except Exception as e:
                logger.error(f"Error in on_file_selected callback: {e}")
        elif on_cancelled:
            try:
                on_cancelled()
            except Exception as e:
                logger.error(f"Error in on_cancelled callback: {e}")

    if suspend_capture:
        try:
            suspend_capture()
        except Exception:
            pass

    if wx is not None and hasattr(wx, "CallAfter"):
        try:
            wx.CallAfter(_show_dialog)
        except Exception:
            t = threading.Thread(target=_show_dialog, daemon=True)
            t.start()
    else:
        t = threading.Thread(target=_show_dialog, daemon=True)
        t.start()


def prompt_open_files_dialog(
    on_files_selected: Callable[[List[str]], None],
    on_cancelled: Optional[Callable[[], None]] = None,
    suspend_capture: Optional[Callable[[], None]] = None,
    resume_capture: Optional[Callable[[], None]] = None,
    parent_window: Any = None,
    title: Optional[str] = None,
    default_dir: Optional[str] = None,
    wildcard: Optional[str] = None
) -> None:
    """
    Presents a native multiple-file selection dialog safely on the wx main thread.
    """
    if _test_dialog_handler is not None:
        try:
            if suspend_capture:
                suspend_capture()
            res = _test_dialog_handler("files", {
                "title": title,
                "default_dir": default_dir,
                "wildcard": wildcard,
            })
            if resume_capture:
                resume_capture()
            if res:
                paths = [os.path.abspath(p) for p in res]
                on_files_selected(paths)
            elif on_cancelled:
                on_cancelled()
        except Exception as e:
            logger.error(f"Error in test dialog handler: {e}")
            if resume_capture:
                resume_capture()
            if on_cancelled:
                on_cancelled()
        return

    def _show_dialog() -> None:
        if not wx or not gui:
            logger.warning("wx or gui module not available; cannot display FileDialog")
            if on_cancelled:
                on_cancelled()
            return

        if suspend_capture:
            try:
                suspend_capture()
            except Exception:
                pass

        parent = parent_window or getattr(gui, "mainFrame", None)
        if hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "prePopup"):
            try:
                gui.mainFrame.prePopup()
            except Exception:
                pass

        selected_paths: List[str] = []
        dlg_title = title or _("Select Media Files")
        dlg_wildcard = wildcard or get_media_dialog_wildcard()
        initial_dir = default_dir or os.path.expanduser("~")

        try:
            dlg = wx.FileDialog(
                parent=parent,
                message=dlg_title,
                defaultDir=initial_dir,
                wildcard=dlg_wildcard,
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE
            )
            with dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    paths = dlg.GetPaths()
                    for p in paths:
                        if p and os.path.exists(p):
                            selected_paths.append(os.path.abspath(p))
        except Exception as e:
            logger.error(f"Error displaying multi wx.FileDialog: {e}")
            selected_paths = []
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

        if selected_paths:
            try:
                on_files_selected(selected_paths)
            except Exception as e:
                logger.error(f"Error in on_files_selected callback: {e}")
        elif on_cancelled:
            try:
                on_cancelled()
            except Exception:
                pass

    if suspend_capture:
        try:
            suspend_capture()
        except Exception:
            pass

    if wx is not None and hasattr(wx, "CallAfter"):
        try:
            wx.CallAfter(_show_dialog)
        except Exception:
            t = threading.Thread(target=_show_dialog, daemon=True)
            t.start()
    else:
        t = threading.Thread(target=_show_dialog, daemon=True)
        t.start()


def prompt_open_folder_dialog(
    on_folder_selected: Callable[[str], None],
    on_cancelled: Optional[Callable[[], None]] = None,
    suspend_capture: Optional[Callable[[], None]] = None,
    resume_capture: Optional[Callable[[], None]] = None,
    parent_window: Any = None,
    title: Optional[str] = None,
    default_dir: Optional[str] = None
) -> None:
    """
    Presents a native folder browser dialog safely on the wx main thread.
    
    Args:
        on_folder_selected: Callback invoked with the selected absolute folder path.
        on_cancelled: Callback invoked if user cancels the dialog.
        suspend_capture: Callback to temporarily suspend modal keyboard capture.
        resume_capture: Callback to resume modal keyboard capture upon dismissal.
        parent_window: Parent wx window (defaults to gui.mainFrame).
        title: Dialog title.
        default_dir: Initial directory to select.
    """
    if _test_dialog_handler is not None:
        try:
            if suspend_capture:
                suspend_capture()
            res = _test_dialog_handler("folder", {
                "title": title,
                "default_dir": default_dir,
            })
            if resume_capture:
                resume_capture()
            if res:
                on_folder_selected(os.path.abspath(res))
            elif on_cancelled:
                on_cancelled()
        except Exception as e:
            logger.error(f"Error in test dialog handler: {e}")
            if resume_capture:
                resume_capture()
            if on_cancelled:
                on_cancelled()
        return

    def _show_dialog() -> None:
        if not wx or not gui:
            logger.warning("wx or gui module not available; cannot display DirDialog")
            if on_cancelled:
                on_cancelled()
            return

        if suspend_capture:
            try:
                suspend_capture()
            except Exception:
                pass

        parent = parent_window or getattr(gui, "mainFrame", None)
        if hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "prePopup"):
            try:
                gui.mainFrame.prePopup()
            except Exception:
                pass

        selected_folder: Optional[str] = None
        dlg_title = title or _("Select Folder to Play")
        initial_dir = default_dir or os.path.expanduser("~")

        try:
            dlg = wx.DirDialog(
                parent=parent,
                message=dlg_title,
                defaultPath=initial_dir,
                style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST
            )
            with dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    folder = dlg.GetPath()
                    if folder and os.path.isdir(folder):
                        selected_folder = os.path.abspath(folder)
        except Exception as e:
            logger.error(f"Error displaying wx.DirDialog: {e}")
            selected_folder = None
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

        if selected_folder:
            try:
                on_folder_selected(selected_folder)
            except Exception as e:
                logger.error(f"Error in on_folder_selected callback: {e}")
        elif on_cancelled:
            try:
                on_cancelled()
            except Exception:
                pass

    if suspend_capture:
        try:
            suspend_capture()
        except Exception:
            pass

    if wx is not None and hasattr(wx, "CallAfter"):
        try:
            wx.CallAfter(_show_dialog)
        except Exception:
            t = threading.Thread(target=_show_dialog, daemon=True)
            t.start()
    else:
        t = threading.Thread(target=_show_dialog, daemon=True)
        t.start()


def generate_help_text(custom_toggle_gesture: Optional[str] = None) -> str:
    """
    Generates a structured, localized help guide for Headless Media Player shortcuts.
    Dynamically includes customized toggle gestures if modified by the user.
    """
    toggle_str = custom_toggle_gesture or "NVDA+Ctrl+Shift+P / Insert+Ctrl+Shift+P"

    try:
        keymap = getKeymap()
    except Exception:
        keymap = {}

    try:
        cfg = getConfig()
    except Exception:
        cfg = {}

    s_norm = int(cfg.get("seekStepNormal", 5))
    s_slow = int(cfg.get("seekStepSlow", 1))
    s_fast = int(cfg.get("seekStepFast", 30))
    s_ultra = int(cfg.get("seekStepUltrafast", 300))

    def _fmt_seconds(sec: int) -> str:
        if sec >= 60 and sec % 60 == 0:
            m = sec // 60
            return _("%d minutes") % m if m > 1 else _("1 minute")
        return _("%d seconds") % sec if sec != 1 else _("1 second")

    str_norm = _fmt_seconds(s_norm)
    str_slow = _fmt_seconds(s_slow)
    str_fast = _fmt_seconds(s_fast)
    str_ultra = _fmt_seconds(s_ultra)

    def _fmt_single_key(raw_combo: str) -> str:
        parts = raw_combo.strip().split("+")
        formatted_parts = []
        for p in parts:
            p = p.strip()
            low = p.lower()
            if low in ("ctrl", "control"):
                formatted_parts.append("Ctrl")
            elif low == "shift":
                formatted_parts.append("Shift")
            elif low == "alt":
                formatted_parts.append("Alt")
            elif low == "space":
                formatted_parts.append("Space")
            elif low in ("escape", "esc"):
                formatted_parts.append("Escape")
            elif low in ("pageup", "page_up", "prior"):
                formatted_parts.append("Page Up")
            elif low in ("pagedown", "page_down", "next"):
                formatted_parts.append("Page Down")
            elif low in ("home", "extendedhome"):
                formatted_parts.append("Home")
            elif low in ("end", "extendedend"):
                formatted_parts.append("End")
            elif low in ("leftarrow", "left"):
                formatted_parts.append("Left Arrow")
            elif low in ("rightarrow", "right"):
                formatted_parts.append("Right Arrow")
            elif low in ("uparrow", "up"):
                formatted_parts.append("Up Arrow")
            elif low in ("downarrow", "down"):
                formatted_parts.append("Down Arrow")
            elif low in ("delete", "del"):
                formatted_parts.append("Delete")
            elif low == "tab":
                formatted_parts.append("Tab")
            elif low == ".":
                formatted_parts.append(".")
            elif low == ",":
                formatted_parts.append(",")
            elif len(p) == 1:
                formatted_parts.append(p.upper())
            else:
                formatted_parts.append(p.capitalize())
        return " + ".join(formatted_parts)

    def _fmt_key(raw_key: str) -> str:
        if not raw_key:
            return ""
        if raw_key.strip() == ",":
            return ","
        sub_combos = [k.strip() for k in raw_key.split(",") if k.strip()]
        if not sub_combos:
            return ""
        return ", ".join(_fmt_single_key(c) for c in sub_combos)

    k_play = _fmt_key(keymap.get("play_pause", "space"))
    k_stop = _fmt_key(keymap.get("stop", "s"))
    k_mute = _fmt_key(keymap.get("mute", "m"))
    k_vup = _fmt_key(keymap.get("vol_up", "uparrow"))
    k_vdown = _fmt_key(keymap.get("vol_down", "downarrow"))
    k_bup = _fmt_key(keymap.get("bass_up", "b"))
    k_bdown = _fmt_key(keymap.get("bass_down", "shift+b"))

    k_seek_f = _fmt_key(keymap.get("seek_forward", "rightarrow"))
    k_seek_b = _fmt_key(keymap.get("seek_backward", "leftarrow"))
    k_seek_sf = _fmt_key(keymap.get("seek_slow_forward", "alt+rightarrow"))
    k_seek_sb = _fmt_key(keymap.get("seek_slow_backward", "alt+leftarrow"))
    k_seek_ff = _fmt_key(keymap.get("seek_fast_forward", "control+rightarrow"))
    k_seek_fb = _fmt_key(keymap.get("seek_fast_backward", "control+leftarrow"))
    k_seek_uf = _fmt_key(keymap.get("seek_ultrafast_forward", "shift+rightarrow"))
    k_seek_ub = _fmt_key(keymap.get("seek_ultrafast_backward", "shift+leftarrow"))
    k_track_start = _fmt_key(keymap.get("track_start", "home"))
    k_track_end = _fmt_key(keymap.get("track_end", "end"))

    k_spd_down = _fmt_key(keymap.get("speed_down", "control+downarrow"))
    k_spd_up = _fmt_key(keymap.get("speed_up", "control+uparrow"))
    k_spd_pdown = _fmt_key(keymap.get("speed_preset_down", "shift+downarrow"))
    k_spd_pup = _fmt_key(keymap.get("speed_preset_up", "shift+uparrow"))

    k_pt_a = _fmt_key(keymap.get("point_a", "["))
    k_pt_b = _fmt_key(keymap.get("point_b", "]"))
    k_rep = _fmt_key(keymap.get("toggle_repeat", "r"))
    k_clr = _fmt_key(keymap.get("clear_loop", "c"))

    k_rc_prev = _fmt_key(keymap.get("recent_playlist_prev", keymap.get("recent_container_prev", "control+,")))
    k_rc_next = _fmt_key(keymap.get("recent_playlist_next", keymap.get("recent_container_next", "control+.")))
    k_rc_first = _fmt_key(keymap.get("recent_playlist_first", keymap.get("recent_container_first", "control+shift+,")))
    k_rc_last = _fmt_key(keymap.get("recent_playlist_last", keymap.get("recent_container_last", "control+shift+.")))
    k_rt_prev = _fmt_key(keymap.get("recent_track_prev", ","))
    k_rt_next = _fmt_key(keymap.get("recent_track_next", "."))
    k_rt_first = _fmt_key(keymap.get("recent_track_first", "shift+,"))
    k_rt_last = _fmt_key(keymap.get("recent_track_last", "shift+."))
    k_rc_del = _fmt_key(keymap.get("recent_delete", "delete"))

    k_prev = _fmt_key(keymap.get("prev_track", "pageup"))
    k_next = _fmt_key(keymap.get("next_track", "pagedown"))
    k_first = _fmt_key(keymap.get("first_track", "control+home"))
    k_last = _fmt_key(keymap.get("last_track", "control+end"))
    k_open = _fmt_key(keymap.get("open_file", "o"))
    k_folder = _fmt_key(keymap.get("open_folder", "f"))
    k_exp = _fmt_key(keymap.get("load_explorer", "e"))
    k_autonext = _fmt_key(keymap.get("toggle_auto_next", "n"))
    k_shuffle = _fmt_key(keymap.get("toggle_shuffle", "z"))

    k_url = _fmt_key(keymap.get("open_url", "u"))
    k_acc = _fmt_key(keymap.get("account_feed", "p"))
    k_curl = _fmt_key(keymap.get("copy_url", "v"))
    k_cdurl = _fmt_key(keymap.get("copy_direct_url", "shift+v"))
    k_clip = _fmt_key(keymap.get("export_clip", "d"))
    k_qclip = _fmt_key(keymap.get("quick_export", "shift+d"))

    k_pchap = _fmt_key(keymap.get("prev_chapter", "control+shift+leftarrow"))
    k_nchap = _fmt_key(keymap.get("next_chapter", "control+shift+rightarrow"))
    k_caudio = _fmt_key(keymap.get("cycle_audio_track", "a"))

    k_info = _fmt_key(keymap.get("media_info", "i"))
    k_rem = _fmt_key(keymap.get("remaining_time", "control+i"))
    k_elapsed = _fmt_key(keymap.get("elapsed_time", "shift+i"))

    k_settings = _fmt_key(keymap.get("open_settings", "control+shift+s"))
    k_help = _fmt_key(keymap.get("show_help", "h"))
    k_close = _fmt_key(keymap.get("close_player", "x"))
    k_exit = _fmt_key(keymap.get("exit_mode", "escape"))

    lines = [
        "=" * 60,
        _("HEADLESS MEDIA PLAYER — KEYBOARD SHORTCUTS REFERENCE"),
        "=" * 60,
        "",
        _("MODE ACTIVATION, SETTINGS & EXIT:"),
        f"  • {toggle_str} : " + _("Enter or exit Headless Player Mode."),
        f"  • {k_exit} : " + _("Exit Player Mode and return to normal desktop keyboard control."),
        f"  • {k_settings} : " + _("Open HeadlessPlayer Settings Panel in NVDA."),
        "  • Control : " + _("Silence speech immediately while in Player Mode."),
        f"  • {k_help} : " + _("Show this keyboard shortcuts help window."),
        f"  • {k_close} : " + _("Close / quit media player completely."),
        "",
        _("PLAYBACK & VOLUME CONTROLS:"),
        f"  • {k_play} : " + _("Play / Pause toggle (or play focused recent item while browsing history)."),
        f"  • {k_stop} : " + _("Stop playback and rewind to beginning."),
        f"  • {k_mute} : " + _("Mute / Unmute audio."),
        f"  • {k_vup} / {k_vdown} : " + _("Adjust volume (+/- 5%)."),
        f"  • {k_bup} / {k_bdown} : " + _("Raise / lower bass (+/- 3 dB)."),
        "",
        _("SEEKING & JUMPS:"),
        f"  • {k_seek_b} / {k_seek_f} : " + _("Normal seek (+/- %s).") % str_norm,
        f"  • {k_seek_sb} / {k_seek_sf} : " + _("Slow & precise seek (+/- %s).") % str_slow,
        f"  • {k_seek_fb} / {k_seek_ff} : " + _("Fast seek (+/- %s).") % str_fast,
        f"  • {k_seek_ub} / {k_seek_uf} : " + _("Ultrafast seek (+/- %s).") % str_ultra,
        f"  • {k_track_start} : " + _("Jump to start of current playing track."),
        f"  • {k_track_end} : " + _("Jump to end of current playing track."),
        "  • Number keys 1 to 9 (Top Row) : " + _("Jump directly to 10% through 90% of file duration."),
        "",
        _("PITCH-PRESERVED SPEED CONTROLS:"),
        f"  • {k_spd_down} / {k_spd_up} : " + _("Fine speed adjustment (+/- 0.1x)."),
        f"  • {k_spd_pdown} / {k_spd_pup} : " + _("Cycle preset speeds (1.0x, 1.5x, 1.75x, 2.0x, 2.5x, 3.0x)."),
        "",
        _("A-B SEGMENT LOOP & REPEAT MODES:"),
        f"  • {k_pt_a} : " + _("Mark start of loop (Point A)."),
        f"  • {k_pt_b} : " + _("Mark end of loop (Point B)."),
        f"  • {k_rep} : " + _("Toggle repeat: A-B loop (if marked) or cycle Single Track / Playlist / Off."),
        f"  • {k_clr} : " + _("Clear marked A-B loop points."),
        "",
        _("RECENT MEDIA & BROWSING HISTORY:"),
        f"  • {k_rc_prev} / {k_rc_next} : " + _("Browse recent playlists (folders & playlists) backward / forward."),
        f"  • {k_rc_first} / {k_rc_last} : " + _("Jump to oldest / newest recent playlist."),
        f"  • {k_rt_prev} / {k_rt_next} : " + _("Browse recent tracks (files & streams) backward / forward."),
        f"  • {k_rt_first} / {k_rt_last} : " + _("Jump to oldest / newest recent track."),
        f"  • Space : " + _("Play focused recent item immediately (active within 6 seconds of browsing)."),
        f"  • {k_rc_del} : " + _("Remove focused recent item from history database."),
        "  • Escape : " + _("Cancel recent browsing mode without leaving Player Mode."),
        "",
        _("PLAYLIST, FOLDERS & WINDOWS EXPLORER:"),
        "  • NVDA + Ctrl + Windows + e : " + _("Directly load and play focused/selected media from Explorer/Desktop without entering Player Mode."),
        f"  • {k_exp} : " + _("Play active selection directly from Windows Explorer / Desktop."),
        f"  • {k_open} : " + _("Open file dialog (select single media file)."),
        f"  • {k_folder} : " + _("Open folder dialog (load entire folder as playlist)."),
        f"  • {k_prev} / {k_next} : " + _("Previous / Next track in playlist."),
        f"  • {k_first} : " + _("Jump to first track in playlist."),
        f"  • {k_last} : " + _("Jump to last track in playlist."),
        f"  • {k_autonext} : " + _("Toggle Auto-Next track playback."),
        f"  • {k_shuffle} : " + _("Toggle playlist shuffle / random mode."),
        "",
        _("YOUTUBE & ONLINE STREAMING:"),
        f"  • {k_url} : " + _("Open URL / search box: paste a YouTube or website link to play it, or type text to search YouTube. Exits Player Mode automatically."),
        f"  • {k_acc} : " + _("Open YouTube account & feeds browser (recommendations, subscriptions, watch later, liked, history, trending)."),
        f"  • {k_curl} : " + _("Copy the current track's link (or file path) to the clipboard."),
        f"  • {k_cdurl} : " + _("Copy the direct audio media link of the playing YouTube item."),
        f"  • {k_clip} : " + _("Export the A-B selection (or the whole item) as MP3, M4A or MP4 video; with only point A set, the current position becomes B."),
        f"  • {k_qclip} : " + _("Quick export of the A-B selection with the remembered settings, no dialog."),
        "  • " + _("In search results: Enter on a video plays it; Enter on a playlist or channel opens it; Tab reaches the Play Playlist button; Backspace goes back."),
        "  • " + _("Online playlists behave exactly like local playlists (Next/Previous track, shuffle, repeat, resume)."),
        "",
        _("CHAPTERS & VIDEO AUDIO TRACKS:"),
        f"  • {k_pchap} / {k_nchap} : " + _("Jump to Previous / Next chapter."),
        f"  • {k_caudio} : " + _("Cycle audio tracks / languages in video files."),
        "",
        _("SPEECH QUERIES:"),
        f"  • {k_info} : " + _("Speak full media information (title, duration, playlist index)."),
        f"  • {k_rem} : " + _("Speak remaining playback time (accounts for playback speed)."),
        f"  • {k_rem} (%s) : " % _("pressed twice") + _("Speak original remaining playback time (unscaled by speed)."),
        f"  • {k_elapsed} : " + _("Speak elapsed playback time (accounts for playback speed)."),
        f"  • {k_elapsed} (%s) : " % _("pressed twice") + _("Speak original elapsed playback time (unscaled by speed)."),
        "=" * 60,
    ]
    return "\n".join(lines)


def prompt_help_dialog(
    suspend_capture: Optional[Callable[[], None]] = None,
    resume_capture: Optional[Callable[[], None]] = None,
    custom_toggle_gesture: Optional[str] = None
) -> None:
    """
    Presents the accessible shortcuts help window using a modal dialog.
    Safely suspends modal input while open and resumes when dismissed.
    """
    if _test_dialog_handler is not None:
        try:
            if suspend_capture:
                suspend_capture()
            _test_dialog_handler("help", {"toggle_gesture": custom_toggle_gesture})
        finally:
            if resume_capture:
                resume_capture()
        return

    def _show_help() -> None:
        try:
            if suspend_capture:
                try:
                    suspend_capture()
                except Exception:
                    pass

            help_title = _("Headless Media Player - Shortcuts Help")
            help_content = generate_help_text(custom_toggle_gesture)

            try:
                if not wx or not gui or not guiHelper:
                    raise RuntimeError("wx/gui not available")

                class _ShortcutsModalDialog(wx.Dialog):
                    def __init__(self) -> None:
                        parent = gui.mainFrame if gui and hasattr(gui, "mainFrame") else None
                        super().__init__(parent, title=help_title, size=(650, 500))
                        mainSizer = wx.BoxSizer(wx.VERTICAL)
                        helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

                        self.textCtrl = wx.TextCtrl(
                            self,
                            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.HSCROLL,
                            value=help_content
                        )
                        helper.addItem(self.textCtrl, flag=wx.EXPAND | wx.ALL, proportion=1)

                        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
                        self.closeBtn = wx.Button(self, wx.ID_CLOSE, label=_("&Close"))
                        self.closeBtn.Bind(wx.EVT_BUTTON, self.onClose)
                        btnSizer.Add(self.closeBtn, 0, wx.ALL, 5)
                        helper.addItem(btnSizer, flag=wx.ALIGN_RIGHT)

                        self.SetSizer(mainSizer)
                        self.textCtrl.SetFocus()

                    def onClose(self, evt: Any) -> None:
                        self.EndModal(wx.ID_CLOSE)

                if gui and hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "prePopup"):
                    gui.mainFrame.prePopup()
                try:
                    dlg = _ShortcutsModalDialog()
                    dlg.ShowModal()
                    dlg.Destroy()
                finally:
                    if gui and hasattr(gui, "mainFrame") and hasattr(gui.mainFrame, "postPopup"):
                        gui.mainFrame.postPopup()

            except Exception:
                try:
                    if ui and hasattr(ui, "browseableMessage"):
                        ui.browseableMessage(help_content, title=help_title)
                except Exception:
                    logger.info("[Help Dialog Output]\n%s", help_content)

        except Exception as e:
            logger.error("Error presenting shortcuts help dialog: %s", e)
        finally:
            if resume_capture:
                try:
                    resume_capture()
                except Exception:
                    pass

    if wx and hasattr(wx, "CallAfter"):
        wx.CallAfter(_show_help)
    else:
        t = threading.Thread(target=_show_help, daemon=True)
        t.start()

