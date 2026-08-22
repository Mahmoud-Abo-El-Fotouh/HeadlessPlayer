"""
HeadlessPlayer NVDA Add-on - Utility Helpers
Provides time formatting and parsing, format validation, natural sorting,
and filesystem helpers for media playback and speech announcements.
"""

from __future__ import annotations
import math
import os
import re
from typing import Iterable, List, Optional, Union

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

    is_negative = sec_val < 0
    total_sec = int(round(abs(sec_val)))

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


def format_spoken_time(
    seconds: Optional[Union[float, int]],
    lang: str = "en"
) -> str:
    """
    Formats duration into natural speech text for screen reader announcements.
    
    Args:
        seconds: Duration in seconds.
        lang: 'en' for English or 'ar' for Arabic.
        
    Returns:
        Spoken string (e.g. '1 hour 25 minutes 10 seconds' or '3 minutes 5 seconds').
    """
    if seconds is None:
        return "0 seconds" if lang == "en" else "0 ثانية"

    try:
        sec_val = float(seconds)
    except (ValueError, TypeError):
        return "0 seconds" if lang == "en" else "0 ثانية"

    if math.isnan(sec_val) or math.isinf(sec_val):
        return "0 seconds" if lang == "en" else "0 ثانية"

    total_sec = max(0, int(round(abs(sec_val))))
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60

    if lang == "ar":
        parts = []
        if hours > 0:
            parts.append(f"{hours} ساعة" if hours > 2 else ("ساعة واحدة" if hours == 1 else "ساعتان"))
        if minutes > 0:
            parts.append(f"{minutes} دقيقة" if minutes > 2 else ("دقيقة واحدة" if minutes == 1 else "دقيقتان"))
        if secs > 0 or not parts:
            parts.append(f"{secs} ثانية" if secs > 2 else ("ثانية واحدة" if secs == 1 else "ثانيتان"))
        return " و ".join(parts)
    else:
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
        if secs > 0 or not parts:
            parts.append(f"{secs} second" if secs == 1 else f"{secs} seconds")
        return " ".join(parts)


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


def natural_sort_key(s: str) -> List[Union[int, str]]:
    """
    Generates a natural sort key list that sorts digit sequences numerically.
    Case-insensitive.
    
    Example:
        'track10.mp3' -> ['track', 10, '.mp3']
        'track2.mp3'  -> ['track', 2, '.mp3']
        Sorted: 'track2.mp3' comes before 'track10.mp3'.
    """
    if not isinstance(s, str):
        s = str(s)
    chunks = _NATURAL_SORT_REGEX.split(s.lower())
    return [int(text) if text.isdigit() else text for text in chunks if text]


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
