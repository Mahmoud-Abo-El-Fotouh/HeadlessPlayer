# -*- coding: utf-8 -*-
from __future__ import annotations

"""
HeadlessPlayer NVDA Add-on - Utility Helpers
Provides time formatting and parsing, format validation, natural sorting,
and filesystem helpers for media playback and speech announcements.
"""

import ctypes
from ctypes import wintypes
import gettext
import math
import os
import re
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

try:
    import api
except Exception:
    api = None

try:
    import wx
except Exception:
    wx = None

# Supported media file extensions (lowercase with leading dot)
SUPPORTED_AUDIO_EXTENSIONS = frozenset({
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".ogg",
    ".opus",
    ".aac",
})

SUPPORTED_VIDEO_EXTENSIONS = frozenset({
    ".mp4",
    ".mkv",
    ".avi",
    ".webm",
    ".mov",
    ".ts",
})

ALL_SUPPORTED_EXTENSIONS = SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS

# Regular expression for natural sorting split
_NATURAL_SORT_REGEX = re.compile(r"(\d+)")


def format_time(
    seconds: Optional[Union[float, int]],
    always_include_hours: bool = False
) -> str:
    """
    Formats a duration in seconds into 'HH:MM:SS' or 'MM:SS'.
    
    Args:
        seconds: Duration in seconds (can be float, int, or None).
        always_include_hours: If True, always includes the HH: field.
        
    Returns:
        Formatted string (e.g. '04:15', '01:23:45', '-00:30').
    """
    if seconds is None:
        return "00:00:00" if always_include_hours else "00:00"

    try:
        sec_val = float(seconds)
    except (ValueError, TypeError):
        return "00:00:00" if always_include_hours else "00:00"

    if math.isnan(sec_val) or math.isinf(sec_val):
        return "00:00:00" if always_include_hours else "00:00"

    total_sec = int(round(abs(sec_val)))
    # Prevent negative zero (e.g. -0.04s displaying as "-00:00")
    is_negative = sec_val < 0 and total_sec > 0

    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60

    prefix = "-" if is_negative else ""

    if hours > 0 or always_include_hours:
        return f"{prefix}{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{prefix}{minutes:02d}:{secs:02d}"


def parse_time(time_str: str) -> float:
    """
    Parses a time string formatted as 'HH:MM:SS', 'MM:SS', or 'SS' into seconds.
    
    Args:
        time_str: String to parse (e.g., '01:23:45', '5:30', '90', '-00:30').
        
    Returns:
        Duration in seconds as a float.
        
    Raises:
        ValueError: If time_str cannot be parsed into a valid duration.
    """
    if not isinstance(time_str, str):
        raise ValueError(f"Expected string, got {type(time_str).__name__}")

    cleaned = time_str.strip()
    if not cleaned:
        raise ValueError("Cannot parse empty time string")

    is_negative = False
    if cleaned.startswith("-"):
        is_negative = True
        cleaned = cleaned[1:].strip()
    elif cleaned.startswith("+"):
        cleaned = cleaned[1:].strip()

    parts = cleaned.split(":")
    if len(parts) == 1:
        try:
            val = float(parts[0])
            return -val if is_negative else val
        except ValueError:
            raise ValueError(f"Invalid seconds value: {time_str}")
    elif len(parts) == 2:
        try:
            minutes = int(parts[0])
            secs = float(parts[1])
            if minutes < 0 or secs < 0:
                raise ValueError
            val = minutes * 60.0 + secs
            return -val if is_negative else val
        except ValueError:
            raise ValueError(f"Invalid MM:SS time string: {time_str}")
    elif len(parts) == 3:
        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            secs = float(parts[2])
            if hours < 0 or minutes < 0 or secs < 0:
                raise ValueError
            val = hours * 3600.0 + minutes * 60.0 + secs
            return -val if is_negative else val
        except ValueError:
            raise ValueError(f"Invalid HH:MM:SS time string: {time_str}")
    else:
        raise ValueError(f"Too many colon-separated parts in time string: {time_str}")


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

_TRANSLATION_CACHE: Dict[str, Any] = {}


def get_translator_for_lang(lang: Optional[str] = None):
    """
    Returns a gettext translation function for the specified language code,
    or active NVDA translation function if lang is None or omitted.
    """
    if not lang:
        return _
    lang_clean = lang.lower().replace("-", "_").split("_")[0]
    if lang_clean in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[lang_clean]

    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(current_dir, "..", "..", "..", "locale", lang_clean, "LC_MESSAGES", "nvda.mo"),
        os.path.join(current_dir, "..", "..", "locale", lang_clean, "LC_MESSAGES", "nvda.mo"),
        os.path.join(current_dir, "..", "locale", lang_clean, "LC_MESSAGES", "nvda.mo"),
        os.path.join(current_dir, "locale", lang_clean, "LC_MESSAGES", "nvda.mo"),
    ]
    for mo_candidate in candidates:
        norm_path = os.path.normpath(mo_candidate)
        if os.path.isfile(norm_path):
            try:
                with open(norm_path, "rb") as f:
                    trans = gettext.GNUTranslations(f)
                    _TRANSLATION_CACHE[lang_clean] = trans.gettext
                    return trans.gettext
            except Exception:
                pass

    _TRANSLATION_CACHE[lang_clean] = _
    return _


def format_spoken_time(
    seconds: Optional[Union[float, int]],
    lang: Optional[str] = None
) -> str:
    """
    Formats duration into natural speech text for screen reader announcements.
    Purely internationalized via gettext (.po/.mo) translation catalogs with zero hardcoded language text.
    
    Args:
        seconds: Duration in seconds.
        lang: Optional language code (e.g. 'en', 'ar', 'fr'). If None, uses active NVDA locale.
        
    Returns:
        Spoken string (e.g. '1 hour 25 minutes 10 seconds' or localized equivalent).
    """
    translate_fn = get_translator_for_lang(lang)

    if seconds is None:
        return translate_fn("0 seconds")

    try:
        sec_val = float(seconds)
    except (ValueError, TypeError):
        return translate_fn("0 seconds")

    if math.isnan(sec_val) or math.isinf(sec_val):
        return translate_fn("0 seconds")

    total_sec = max(0, int(round(abs(sec_val))))
    if total_sec == 0:
        return translate_fn("0 seconds")

    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60

    def _get_unit(count: int, unit_name: str) -> str:
        if count <= 0:
            return ""
        if count == 1:
            return translate_fn(f"1 {unit_name}")
        if count == 2:
            return translate_fn(f"2 {unit_name}s")
        if 3 <= count <= 10:
            tmpl_3_10 = translate_fn(f"{{n}} {unit_name}s (3-10)")
            if tmpl_3_10 != f"{{n}} {unit_name}s (3-10)":
                return tmpl_3_10.format(n=count)
        return translate_fn(f"{{n}} {unit_name}s").format(n=count)

    parts = []
    if hours > 0:
        parts.append(_get_unit(hours, "hour"))
    if minutes > 0:
        parts.append(_get_unit(minutes, "minute"))
    if secs > 0 or not parts:
        parts.append(_get_unit(secs, "second"))

    sep = translate_fn("spoken_time_separator")
    if sep == "spoken_time_separator":
        sep = " "
    return sep.join(parts)


def is_supported_media_file(path_or_name: str) -> bool:
    """
    Checks if a given file path or file name has a supported audio or video extension.
    """
    if not path_or_name or not isinstance(path_or_name, str):
        return False
    _, ext = os.path.splitext(path_or_name)
    return ext.lower() in ALL_SUPPORTED_EXTENSIONS


def is_audio_file(path_or_name: str) -> bool:
    """Checks if a given file is a supported audio format."""
    if not path_or_name or not isinstance(path_or_name, str):
        return False
    _, ext = os.path.splitext(path_or_name)
    return ext.lower() in SUPPORTED_AUDIO_EXTENSIONS


def is_video_file(path_or_name: str) -> bool:
    """Checks if a given file is a supported video format."""
    if not path_or_name or not isinstance(path_or_name, str):
        return False
    _, ext = os.path.splitext(path_or_name)
    return ext.lower() in SUPPORTED_VIDEO_EXTENSIONS


def natural_sort_key(s: str) -> List[Tuple[int, Union[int, str]]]:
    """
    Generates a natural sort key list that sorts digit sequences numerically.
    Uses type-tagged tuples (0, int) and (1, str) to guarantee crash-free
    comparison in Python 3 across mixed numeric and alphabetic items.
    Case-insensitive.
    """
    if not isinstance(s, str):
        s = str(s)
    chunks = _NATURAL_SORT_REGEX.split(s.lower())
    return [
        (0, int(text)) if text.isdigit() else (1, text)
        for text in chunks
        if text
    ]


def natural_sort(items: Iterable[str]) -> List[str]:
    """
    Returns a new list of strings sorted according to natural human ordering.
    """
    return sorted(items, key=natural_sort_key)


def filter_and_sort_media_files(file_paths: Iterable[str]) -> List[str]:
    """
    Filters a sequence of file paths to only include supported media files,
    and returns them sorted in natural order.
    """
    supported = [p for p in file_paths if is_supported_media_file(p)]
    return natural_sort(supported)


def find_media_files_in_dir(
    dir_path: str,
    recursive: bool = False
) -> List[str]:
    """
    Finds all supported media files in a directory in natural order.
    
    Args:
        dir_path: Directory path to scan.
        recursive: If True, scans subdirectories recursively.
        
    Returns:
        List of absolute file paths sorted in natural order.
    """
    if not os.path.isdir(dir_path):
        return []

    collected: List[str] = []
    if recursive:
        for root, _, files in os.walk(dir_path):
            for file in files:
                full_path = os.path.join(root, file)
                if is_supported_media_file(full_path):
                    collected.append(full_path)
    else:
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if entry.is_file() and is_supported_media_file(entry.name):
                        collected.append(entry.path)
        except OSError:
            return []

    return natural_sort(collected)


def get_media_dialog_wildcard() -> str:
    """
    Returns the standard wxPython file dialog wildcard string for supported media.
    """
    all_audio_pattern = ";".join(f"*{ext}" for ext in sorted(SUPPORTED_AUDIO_EXTENSIONS))
    all_video_pattern = ";".join(f"*{ext}" for ext in sorted(SUPPORTED_VIDEO_EXTENSIONS))
    all_media_pattern = f"{all_audio_pattern};{all_video_pattern}"

    return (
        f"Media Files ({all_media_pattern})|{all_media_pattern}|"
        f"Audio Files ({all_audio_pattern})|{all_audio_pattern}|"
        f"Video Files ({all_video_pattern})|{all_video_pattern}|"
        f"All Files (*.*)|*.*"
    )


# ---------------------------------------------------------------------------
# Standard NVDA Logger Helpers
# ---------------------------------------------------------------------------

try:
    from .logging import log_debug as _lm_log_debug, log_exception as _lm_log_exception
except Exception:
    _lm_log_debug = None
    _lm_log_exception = None

try:
    from logHandler import log as _logger
except ImportError:
    import logging
    _logger = logging.getLogger("HeadlessPlayer")


def log_info(tag: str, message: str, *args: Any) -> None:
    """Logs an info-level message directly to NVDA log and log_manager."""
    if _lm_log_debug:
        try:
            _lm_log_debug(tag, message, *args)
        except Exception:
            pass
    if args:
        try:
            _logger.info(f"[HeadlessPlayer:{tag}] {message % args}")
        except Exception:
            _logger.info(f"[HeadlessPlayer:{tag}] {message} {args}")
    else:
        _logger.info(f"[HeadlessPlayer:{tag}] {message}")


def log_debug(tag: str, message: str, *args: Any) -> None:
    """Logs a debug-level message to NVDA log and log_manager."""
    if _lm_log_debug:
        try:
            _lm_log_debug(tag, message, *args)
        except Exception:
            pass
    if args:
        try:
            _logger.debug(f"[HeadlessPlayer:{tag}] {message % args}")
        except Exception:
            _logger.debug(f"[HeadlessPlayer:{tag}] {message} {args}")
    else:
        _logger.debug(f"[HeadlessPlayer:{tag}] {message}")


def log_error(tag: str, message: str, *args: Any) -> None:
    """Logs an error-level message to NVDA log and log_manager."""
    if _lm_log_debug:
        try:
            _lm_log_debug(tag, f"ERROR: {message}", *args)
        except Exception:
            pass
    if args:
        try:
            _logger.error(f"[HeadlessPlayer:{tag}] {message % args}")
        except Exception:
            _logger.error(f"[HeadlessPlayer:{tag}] {message} {args}")
    else:
        _logger.error(f"[HeadlessPlayer:{tag}] {message}")


def log_exception(tag: str, message: str, exc: Optional[BaseException] = None) -> None:
    """Logs an exception with traceback to NVDA log and log_manager."""
    if _lm_log_exception:
        try:
            _lm_log_exception(tag, message, exc)
        except Exception:
            pass
    _logger.exception(f"[HeadlessPlayer:{tag}] {message}")


def copy_to_clipboard(target: str) -> bool:
    """
    Copies target to the Windows clipboard.
    If target is an existing local file on disk, places BOTH CF_HDROP (file object)
    and CF_UNICODETEXT (clean path string) onto the clipboard.
    """
    target = str(target or "").strip()
    if not target:
        return False

    is_local_file = os.path.isabs(target) and os.path.exists(target)

    # 1. Official NVDA clipboard API
    api_success = False
    api_mod = sys.modules.get("api", api)
    if api_mod is not None:
        try:
            api_success = bool(api_mod.copyToClip(target))
        except Exception:
            pass

    if not is_local_file and api_success:
        return True

    # 2. Native Win32 dual format clipboard
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL

        CF_UNICODETEXT = 13
        CF_HDROP = 15
        GHND = 0x0042

        class DROPFILES(ctypes.Structure):
            _fields_ = [
                ("pFiles", wintypes.DWORD),
                ("pt", wintypes.POINT),
                ("fNC", wintypes.BOOL),
                ("fWide", wintypes.BOOL),
            ]

        for _ in range(5):
            h_drop = None
            h_text = None
            try:
                text_bytes = (target + "\x00").encode("utf-16-le")
                h_text = kernel32.GlobalAlloc(GHND, len(text_bytes))
                if h_text:
                    p_text = kernel32.GlobalLock(h_text)
                    if p_text:
                        ctypes.memmove(p_text, text_bytes, len(text_bytes))
                        kernel32.GlobalUnlock(h_text)

                if is_local_file:
                    wide_path = (target + "\x00\x00").encode("utf-16-le")
                    df_size = ctypes.sizeof(DROPFILES)
                    total_size = df_size + len(wide_path)
                    h_drop = kernel32.GlobalAlloc(GHND, total_size)
                    if h_drop:
                        p_drop = kernel32.GlobalLock(h_drop)
                        if p_drop:
                            df = DROPFILES()
                            df.pFiles = df_size
                            df.fWide = True
                            ctypes.memmove(p_drop, ctypes.byref(df), df_size)
                            ctypes.memmove(p_drop + df_size, wide_path, len(wide_path))
                            kernel32.GlobalUnlock(h_drop)

                opened = user32.OpenClipboard(0)
                if not opened:
                    opened = user32.OpenClipboard(user32.GetDesktopWindow())

                if opened:
                    try:
                        user32.EmptyClipboard()
                        if h_drop:
                            user32.SetClipboardData(CF_HDROP, h_drop)
                            h_drop = None
                        if h_text:
                            user32.SetClipboardData(CF_UNICODETEXT, h_text)
                            h_text = None
                        return True
                    finally:
                        user32.CloseClipboard()
            except Exception:
                pass
            finally:
                if h_drop:
                    kernel32.GlobalFree(h_drop)
                if h_text:
                    kernel32.GlobalFree(h_text)
            time.sleep(0.04)
    except Exception:
        pass

    # 3. wx fallback
    wx_mod = sys.modules.get("wx", wx)
    if wx_mod is not None:
        try:
            if wx_mod.TheClipboard.Open():
                if is_local_file:
                    fdo = wx_mod.FileDataObject()
                    fdo.AddFile(target)
                    wx_mod.TheClipboard.SetData(fdo)
                else:
                    wx_mod.TheClipboard.SetData(wx_mod.TextDataObject(target))
                wx_mod.TheClipboard.Flush()
                wx_mod.TheClipboard.Close()
                return True
        except Exception:
            pass

    return api_success
