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
from typing import Any, Callable, List, Optional, Sequence, Union

try:
    from .utils import get_media_dialog_wildcard
except ImportError:
    from utils import get_media_dialog_wildcard

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
        try:
            import wx
            import gui
        except ImportError:
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

    try:
        import wx
        wx.CallAfter(_show_dialog)
    except Exception:
        # If not inside a wx main loop, run synchronously or dispatch to thread
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
        try:
            import wx
            import gui
        except ImportError:
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

    try:
        import wx
        wx.CallAfter(_show_dialog)
    except Exception:
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
        try:
            import wx
            import gui
        except ImportError:
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

    try:
        import wx
        wx.CallAfter(_show_dialog)
    except Exception:
        t = threading.Thread(target=_show_dialog, daemon=True)
        t.start()


def generate_help_text(custom_toggle_gesture: Optional[str] = None) -> str:
    """
    Generates a structured, localized help guide for Headless Media Player shortcuts.
    Dynamically includes customized toggle gestures if modified by the user.
    """
    toggle_str = custom_toggle_gesture or "NVDA+Ctrl+Shift+P / Insert+Ctrl+Shift+P"

    try:
        from .config_spec import getKeymap
        keymap = getKeymap()
    except Exception:
        try:
            from config_spec import getKeymap
            keymap = getKeymap()
        except Exception:
            keymap = {}

    k_play = keymap.get("play_pause", "Space").capitalize()
    k_stop = keymap.get("stop", "s")
    k_mute = keymap.get("mute", "m")
    k_vup = keymap.get("vol_up", "Up Arrow")
    k_vdown = keymap.get("vol_down", "Down Arrow")
    k_next = keymap.get("next_track", "Page Down").replace("pagedown", "Page Down").replace("next", "Page Down")
    k_prev = keymap.get("prev_track", "Page Up").replace("pageup", "Page Up").replace("prior", "Page Up")
    k_open = keymap.get("open_file", "o")
    k_folder = keymap.get("open_folder", "f")
    k_url = keymap.get("open_url", "u")
    k_exp = keymap.get("load_explorer", "e")
    k_autonext = keymap.get("toggle_auto_next", "n")
    k_shuffle = keymap.get("toggle_shuffle", "z")
    k_help = keymap.get("show_help", "h")
    k_exit = keymap.get("exit_mode", "Escape").capitalize()

    lines = [
        "=" * 60,
        _("HEADLESS MEDIA PLAYER — KEYBOARD SHORTCUTS REFERENCE"),
        "=" * 60,
        "",
        _("MODE ACTIVATION & EXIT:"),
        f"  • {toggle_str} : " + _("Enter or exit Headless Player Mode."),
        f"  • {k_exit} : " + _("Exit Player Mode and return to normal desktop keyboard control."),
        "  • Control : " + _("Silence speech immediately while in Player Mode."),
        f"  • {k_help} : " + _("Show this keyboard shortcuts help window."),
        "",
        _("PLAYBACK & VOLUME CONTROLS:"),
        f"  • {k_play} : " + _("Play / Pause toggle."),
        f"  • {k_stop} : " + _("Stop playback and rewind to beginning."),
        f"  • {k_mute} : " + _("Mute / Unmute audio."),
        f"  • {k_vup} / {k_vdown} : " + _("Adjust volume (+/- 5%)."),
        f"  • {keymap.get('bass_up', 'b')} / {keymap.get('bass_down', 'shift+b')} : " + _("Raise / lower bass (+/- 3 dB)."),
        "",
        _("SEEKING & JUMPS:"),
        "  • Left / Right Arrow : " + _("Normal seek (+/- 5 seconds)."),
        "  • Alt + Left / Right Arrow : " + _("Slow & precise seek (+/- 1 second)."),
        "  • Ctrl + Left / Right Arrow : " + _("Fast seek (+/- 30 seconds)."),
        "  • Shift + Left / Right Arrow : " + _("Ultrafast seek (+/- 5 minutes)."),
        f"  • {keymap.get('track_start', 'Home')} : " + _("Jump to start of current playing track."),
        f"  • {keymap.get('track_end', 'End')} : " + _("Jump to end of current playing track."),
        "  • Number keys 1 to 9 (Top Row) : " + _("Jump directly to 10% through 90% of file duration."),
        "",
        _("PITCH-PRESERVED SPEED CONTROLS:"),
        "  • Ctrl + Up / Down Arrow : " + _("Fine speed adjustment (+/- 0.1x)."),
        "  • Shift + Up / Down Arrow : " + _("Cycle preset speeds (1.0x, 1.5x, 1.75x, 2.0x, 2.5x, 3.0x)."),
        "",
        _("A-B SEGMENT LOOP & REPEAT MODES:"),
        "  • [ or ج : " + _("Mark start of loop (Point A)."),
        "  • ] or د : " + _("Mark end of loop (Point B)."),
        "  • r : " + _("Toggle repeat: A-B loop (if marked) or cycle Single Track / Playlist / Off."),
        "  • c : " + _("Clear marked A-B loop points."),
        "",
        _("PLAYLIST, FOLDERS & WINDOWS EXPLORER:"),
        "  • NVDA + Ctrl + Windows + e : " + _("Directly load and play focused/selected media from Explorer/Desktop without entering Player Mode."),
        f"  • {k_exp} : " + _("Play active selection directly from Windows Explorer / Desktop."),
        f"  • {k_open} : " + _("Open file dialog (select single media file)."),
        f"  • {k_folder} : " + _("Open folder dialog (load entire folder as playlist)."),
        f"  • {k_prev} / {k_next} : " + _("Previous / Next track in playlist."),
        f"  • {keymap.get('first_track', 'Ctrl+Home')} : " + _("Jump to first track in playlist."),
        f"  • {keymap.get('last_track', 'Ctrl+End')} : " + _("Jump to last track in playlist."),
        f"  • {k_autonext} : " + _("Toggle Auto-Next track playback."),
        f"  • {k_shuffle} : " + _("Toggle playlist shuffle / random mode."),
        "",
        _("YOUTUBE & ONLINE STREAMING:"),
        f"  • {k_url} : " + _("Open URL / search box: paste a YouTube or website link to play it, or type text to search YouTube. Exits Player Mode automatically."),
        f"  • {keymap.get('account_feed', 'p')} : " + _("Open YouTube account & feeds browser (recommendations, subscriptions, watch later, liked, history, trending)."),
        f"  • {keymap.get('copy_url', 'v')} : " + _("Copy the current track's link (or file path) to the clipboard."),
        "  • " + _("In search results: Enter on a video plays it; Enter on a playlist or channel opens it; Tab reaches the Play Playlist button; Backspace goes back."),
        "  • " + _("Online playlists behave exactly like local playlists (Next/Previous track, shuffle, repeat, resume)."),
        "",
        _("CHAPTERS & VIDEO AUDIO TRACKS:"),
        "  • Ctrl + Shift + Right / Left Arrow : " + _("Jump to Next / Previous chapter."),
        "  • a : " + _("Cycle audio tracks / languages in video files."),
        "",
        _("SPEECH QUERIES:"),
        "  • i : " + _("Speak full media information (title, duration, playlist index)."),
        "  • Ctrl + i : " + _("Speak remaining playback time."),
        "  • Shift + i : " + _("Speak elapsed playback time."),
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
                import wx
                import gui
                from gui import guiHelper

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
                    import ui
                    if hasattr(ui, "browseableMessage"):
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

    try:
        import wx
        wx.CallAfter(_show_help)
    except Exception:
        t = threading.Thread(target=_show_help, daemon=True)
        t.start()

