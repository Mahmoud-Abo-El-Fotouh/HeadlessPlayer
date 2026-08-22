# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Windows Explorer COM & Selection Extraction.
Extracts active selected media files and folders from Windows 10 Explorer,
Windows 11 tabbed Explorer, Desktop, or NVDA focus object tree.
"""

from __future__ import annotations
import logging
import os
from typing import Any, List, Optional, Sequence, Set

try:
    from .utils import (
        ALL_SUPPORTED_EXTENSIONS,
        filter_and_sort_media_files,
        find_media_files_in_dir,
        is_supported_media_file,
    )
except ImportError:
    from utils import (
        ALL_SUPPORTED_EXTENSIONS,
        filter_and_sort_media_files,
        find_media_files_in_dir,
        is_supported_media_file,
    )

logger = logging.getLogger("HeadlessPlayer.ExplorerUtils")

# CLSID for IShellWindows
CLSID_ShellWindows = "{9BA05972-F6A8-11CF-A442-00A0C90A8F39}"


def _get_foreground_window() -> int:
    """
    Returns the HWND of the current foreground window.
    Uses winUser if inside NVDA, ctypes otherwise.
    """
    try:
        import winUser
        return winUser.getForegroundWindow()
    except Exception:
        try:
            import ctypes
            return ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return 0


def _is_descendant_window(parent_hwnd: int, child_hwnd: int) -> bool:
    """
    Checks if child_hwnd is identical to or a child of parent_hwnd.
    """
    if parent_hwnd == child_hwnd:
        return True
    try:
        import winUser
        return winUser.isDescendantWindow(parent_hwnd, child_hwnd)
    except Exception:
        try:
            import ctypes
            return bool(ctypes.windll.user32.IsChild(parent_hwnd, child_hwnd))
        except Exception:
            return False


def get_explorer_selected_paths() -> List[str]:
    """
    Extracts paths of selected items or focused item in the active Windows Explorer window or Desktop.
    Supports Windows 10, Windows 11 (with tabbed Explorer), and Desktop selections.
    Uses comtypes.client (standard built-in to NVDA) and NVDA focus tree.
    
    Returns:
        List of absolute file/folder paths found in the active selection or open folder.
    """
    selected_paths: List[str] = []
    fg_hwnd = _get_foreground_window()

    # 1. Query open Explorer windows via comtypes (standard in NVDA)
    try:
        import comtypes.client
        from urllib.parse import unquote
        shell_app = comtypes.client.CreateObject("Shell.Application")
        windows = shell_app.Windows()
        count = getattr(windows, "Count", 0)

        matching_windows = []
        other_windows = []

        for i in range(count):
            try:
                w = windows.Item(i)
                win_hwnd = getattr(w, "HWND", 0)
                if win_hwnd and fg_hwnd and (win_hwnd == fg_hwnd or _is_descendant_window(win_hwnd, fg_hwnd) or _is_descendant_window(fg_hwnd, win_hwnd)):
                    matching_windows.append(w)
                else:
                    other_windows.append(w)
            except Exception:
                continue

        candidate_windows = matching_windows if matching_windows else other_windows

        for window in candidate_windows:
            try:
                doc = getattr(window, "Document", None)
                if not doc:
                    continue

                # 1.1 Selected items
                try:
                    sel = doc.SelectedItems()
                    if sel and hasattr(sel, "Count") and sel.Count > 0:
                        for idx in range(sel.Count):
                            item = sel.Item(idx)
                            p = getattr(item, "Path", "")
                            if p and os.path.exists(p):
                                selected_paths.append(os.path.abspath(p))
                        if selected_paths:
                            return selected_paths
                except Exception:
                    pass

                # 1.2 Focused item
                try:
                    focused = getattr(doc, "FocusedItem", None)
                    if focused:
                        f_path = getattr(focused, "Path", "")
                        if f_path and os.path.exists(f_path):
                            selected_paths.append(os.path.abspath(f_path))
                            return selected_paths
                except Exception:
                    pass

                # 1.3 Folder location URL (if matching foreground window)
                if matching_windows:
                    url = getattr(window, "LocationURL", "")
                    if url.startswith("file:///"):
                        dir_path = unquote(url[8:]).replace("/", "\\")
                        if os.path.isdir(dir_path):
                            selected_paths.append(os.path.abspath(dir_path))
                            return selected_paths

            except Exception as e:
                logger.debug("Error inspecting shell window via comtypes: %s", e)
                continue

    except Exception as e:
        logger.debug("comtypes Shell.Application query error: %s", e)

    # 2. Fallback: NVDA accessibility focus object tree
    focus_paths = _get_focus_explorer_paths()
    if focus_paths:
        selected_paths.extend(focus_paths)

    return selected_paths


def _get_focus_explorer_paths() -> List[str]:
    """
    Fallback method: inspects NVDA's active focus object when COM fails
    or when running under tabbed Windows 11 / hidden extensions.
    """
    paths: List[str] = []
    try:
        import api
    except ImportError:
        return paths

    try:
        focus = api.getFocusObject()
        if not focus:
            return paths

        # 1. If focus object exposes a file path directly
        for attr in ("value", "description", "name"):
            val = getattr(focus, attr, "")
            if isinstance(val, str) and val and os.path.exists(val):
                paths.append(os.path.abspath(val))
                return paths

        # 2. Extract focused item name
        name = getattr(focus, "name", "") or ""
        if not name:
            return paths

        # 3. Query all open Explorer folder directories via comtypes
        open_dirs: List[str] = []
        try:
            import comtypes.client
            from urllib.parse import unquote
            shell_app = comtypes.client.CreateObject("Shell.Application")
            windows = shell_app.Windows()
            for i in range(getattr(windows, "Count", 0)):
                try:
                    w = windows.Item(i)
                    doc = getattr(w, "Document", None)
                    if doc and hasattr(doc, "Folder") and doc.Folder:
                        p = getattr(doc.Folder.Self, "Path", "")
                        if p and os.path.isdir(p) and p not in open_dirs:
                            open_dirs.append(os.path.abspath(p))
                    url = getattr(w, "LocationURL", "")
                    if url.startswith("file:///"):
                        p = unquote(url[8:]).replace("/", "\\")
                        if os.path.isdir(p) and p not in open_dirs:
                            open_dirs.append(os.path.abspath(p))
                except Exception:
                    continue
        except Exception:
            pass

        # 4. Standard known directories + all open explorer folders
        search_dirs = list(open_dirs) + [
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop"),
            os.path.join(os.path.expanduser("~"), "Downloads"),
            os.path.join(os.path.expanduser("~"), "Music"),
            os.path.join(os.path.expanduser("~"), "Videos"),
            os.path.join(os.path.expanduser("~"), "Documents"),
        ]

        # Also add fixed / removable drive roots (D:\, E:\, etc.)
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:\\"
            if os.path.exists(drive) and drive not in search_dirs:
                search_dirs.append(drive)

        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            cand = os.path.join(d, name)
            if os.path.exists(cand):
                paths.append(os.path.abspath(cand))
                return paths
            for ext in ALL_SUPPORTED_EXTENSIONS:
                cand_ext = os.path.join(d, f"{name}{ext}")
                if os.path.exists(cand_ext):
                    paths.append(os.path.abspath(cand_ext))
                    return paths

            # Comprehensive filename / stem matching for hidden extensions
            try:
                name_clean = name.strip().lower()
                for fname in os.listdir(d):
                    fname_base = os.path.splitext(fname)[0].strip().lower()
                    fname_full = fname.strip().lower()
                    if fname_base == name_clean or fname_full == name_clean:
                        cand_match = os.path.join(d, fname)
                        if is_supported_media_file(cand_match) or os.path.isdir(cand_match):
                            paths.append(os.path.abspath(cand_match))
                            return paths
            except Exception:
                continue

    except Exception as e:
        logger.debug("Error inspecting NVDA focus object: %s", e)

    return paths


def filter_media_paths(
    paths: Sequence[str],
    allow_folders: bool = True
) -> List[str]:
    """
    Filters a list of extracted paths to only include valid supported media files
    or directories.
    
    Args:
        paths: Sequence of file or folder paths.
        allow_folders: If True, folder paths are retained.
        
    Returns:
        List of valid absolute paths.
    """
    valid: List[str] = []
    for p in paths:
        if not p:
            continue
        abs_p = os.path.abspath(p)
        if not os.path.exists(abs_p):
            continue
        if os.path.isdir(abs_p):
            if allow_folders:
                valid.append(abs_p)
        elif is_supported_media_file(abs_p):
            valid.append(abs_p)
    return valid


def expand_folder_paths(
    paths: Sequence[str],
    recursive: bool = False
) -> List[str]:
    """
    Expands any folders in the given path list into their contained media files
    sorted in natural order. Single files are preserved.
    
    Args:
        paths: Sequence of file or folder paths.
        recursive: If True, scans subdirectories recursively.
        
    Returns:
        List of media file paths.
    """
    expanded: List[str] = []
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        abs_p = os.path.abspath(p)
        if os.path.isdir(abs_p):
            files = find_media_files_in_dir(abs_p, recursive=recursive)
            expanded.extend(files)
        elif is_supported_media_file(abs_p):
            expanded.append(abs_p)
    return expanded


def get_active_explorer_or_focus_paths(
    filter_supported: bool = True,
    expand_folders: bool = False,
    recursive: bool = False
) -> List[str]:
    """
    High-level API: Retrieves active Explorer / Desktop / Focus selections,
    applies media filtering, and optionally expands folders.
    
    Args:
        filter_supported: If True, excludes unsupported file types.
        expand_folders: If True, replaces directory paths with their media contents.
        recursive: If expand_folders is True, whether to scan subdirectories recursively.
        
    Returns:
        List of resolved file/folder paths ready for playback or queuing.
    """
    raw_paths = get_explorer_selected_paths()
    if not raw_paths:
        return []

    if filter_supported:
        filtered = filter_media_paths(raw_paths, allow_folders=True)
    else:
        filtered = [os.path.abspath(p) for p in raw_paths if os.path.exists(p)]

    if expand_folders:
        return expand_folder_paths(filtered, recursive=recursive)

    return filtered
