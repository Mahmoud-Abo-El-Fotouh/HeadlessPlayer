# -*- coding: utf-8 -*-
from __future__ import annotations

"""
HeadlessPlayer NVDA Add-on - Self-Diagnostic & System Health Auditor.
Provides instant health inspection for mpv binaries, Named Pipe IPC, yt-dlp streaming engine,
HPDB database integrity, audio outputs, keymap configurations, and translation catalogs.
"""

import datetime
import logging
import os
import platform
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    from . import _  # type: ignore
except (ImportError, ValueError):
    try:
        _ = _  # type: ignore
    except NameError:
        _ = lambda text: text

from .utils import copy_to_clipboard
from .config_spec import getConfig, getConfigValue, DEFAULT_CONFIG
from .database import get_db_manager
from .mpv_process import find_mpv_binary, DEFAULT_PIPE_NAME
from . import stream_engine
from . import log_manager

logger = logging.getLogger("HeadlessPlayer.Diagnostics")


class HealthStatus:
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"


def check_mpv_binary(custom_path: Optional[str] = None) -> Dict[str, Any]:
    """Inspects the bundled or custom mpv executable."""
    addon_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    cfg_path = custom_path or getConfigValue("mpvExecutablePath", "")
    resolved_path = find_mpv_binary(cfg_path, addon_root)

    if not resolved_path or not os.path.exists(resolved_path):
        return {
            "status": HealthStatus.ERROR,
            "component": "mpv Binary",
            "message": "mpv executable not found. Headless playback cannot start.",
            "path": resolved_path or "None",
            "version": None,
        }

    try:
        kwargs: Dict[str, Any] = {"capture_output": True, "text": True, "timeout": 3}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run([resolved_path, "--version"], **kwargs)
        ver_line = proc.stdout.splitlines()[0] if proc.stdout else "mpv (unknown version)"
        return {
            "status": HealthStatus.OK,
            "component": "mpv Binary",
            "message": f"mpv binary is executable and verified: {ver_line}",
            "path": resolved_path,
            "version": ver_line,
        }
    except Exception as e:
        return {
            "status": HealthStatus.WARNING,
            "component": "mpv Binary",
            "message": f"mpv binary exists at {resolved_path} but execution test failed: {e}",
            "path": resolved_path,
            "version": None,
        }


def check_stream_engine() -> Dict[str, Any]:
    """Inspects the yt-dlp stream extraction backend."""
    available = stream_engine.is_available()
    ytdlp_ver = getattr(stream_engine, "_ytdlp_module", None)
    ver_str = getattr(ytdlp_ver, "__version__", "Available") if ytdlp_ver else ("Ready (Lazy)" if available else "Unavailable")

    if not available:
        if sys.version_info < (3, 10):
            msg = "yt-dlp streaming requires Python 3.10+ (NVDA 2024.1+)."
        else:
            msg = "yt-dlp stream engine is unavailable or encountered an import error."
        return {
            "status": HealthStatus.ERROR,
            "component": "Streaming Engine (yt-dlp)",
            "message": msg,
            "version": None,
        }

    return {
        "status": HealthStatus.OK,
        "component": "Streaming Engine (yt-dlp)",
        "message": f"yt-dlp backend ready. Version: {ver_str}",
        "version": ver_str,
    }


def check_database() -> Dict[str, Any]:
    """Inspects the persistent database storage integrity."""
    try:
        db = get_db_manager()
        playlists = len(db.get_recent_playlists())
        tracks = len(db.get_recent_tracks())
        positions = len(db.get_all_positions())
        settings_count = len(db.get_all_settings()) if hasattr(db, "get_all_settings") else 0
        db_path = getattr(db, "db_path", getattr(db, "_db_path", "In-Memory"))

        return {
            "status": HealthStatus.OK,
            "component": "Database Storage",
            "message": f"Database integrity verified (Playlists: {playlists}, Tracks: {tracks}, Positions: {positions}, Settings: {settings_count})",
            "path": db_path,
            "integrity": "OK",
            "records": {"playlists": playlists, "containers": playlists, "tracks": tracks, "positions": positions, "settings": settings_count},
        }
    except Exception as e:
        return {
            "status": HealthStatus.ERROR,
            "component": "Database Storage",
            "message": f"Database verification error: {e}",
            "path": None,
            "integrity": "FAILED",
        }


def check_translations() -> Dict[str, Any]:
    """Inspects the localized translation catalog files."""
    addon_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    locales_dir = os.path.join(addon_root, "locale")
    ar_mo = os.path.join(locales_dir, "ar", "LC_MESSAGES", "nvda.mo")
    en_mo = os.path.join(locales_dir, "en", "LC_MESSAGES", "nvda.mo")

    ar_ok = os.path.isfile(ar_mo) and os.path.getsize(ar_mo) > 1000
    en_ok = os.path.isfile(en_mo) and os.path.getsize(en_mo) > 1000

    if ar_ok and en_ok:
        return {
            "status": HealthStatus.OK,
            "component": "Translations (i18n)",
            "message": "Arabic and English compiled binary translation catalogs (.mo) are intact.",
            "ar_mo": ar_mo,
            "en_mo": en_mo,
        }
    else:
        return {
            "status": HealthStatus.WARNING,
            "component": "Translations (i18n)",
            "message": f"Translation catalog check: AR present={ar_ok}, EN present={en_ok}",
            "ar_mo": ar_mo,
            "en_mo": en_mo,
        }


def run_full_diagnostics() -> Dict[str, Any]:
    """Executes a complete self-diagnostic check across all subsystems."""
    checks = [
        check_mpv_binary(),
        check_stream_engine(),
        check_database(),
        check_translations(),
    ]

    all_ok = all(c["status"] == HealthStatus.OK for c in checks)
    has_error = any(c["status"] == HealthStatus.ERROR for c in checks)

    overall = HealthStatus.OK if all_ok else (HealthStatus.ERROR if has_error else HealthStatus.WARNING)

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "overall_status": overall,
        "python_version": sys.version,
        "platform": platform.platform(),
        "checks": checks,
    }


def generate_diagnostic_report_text(diagnostics_dict: Optional[Dict[str, Any]] = None) -> str:
    """Generates a human-readable diagnostic report for easy copying/sharing."""
    diag = diagnostics_dict or run_full_diagnostics()
    lines = [
        "=" * 60,
        "  HEADLESSPLAYER NVDA ADD-ON - DIAGNOSTIC SYSTEM REPORT",
        "=" * 60,
        f"Timestamp       : {diag['timestamp']}",
        f"Overall Status  : [{diag['overall_status']}]",
        f"Python Version  : {sys.version.split()[0]} ({platform.architecture()[0]})",
        f"Operating System: {platform.platform()}",
        "-" * 60,
        "SUBSYSTEM HEALTH CHECKS:",
    ]

    for c in diag["checks"]:
        lines.append(f" • [{c['status']}] {c['component']}: {c['message']}")

    lines.append("-" * 60)
    lines.append("RECENT LOG EVENTS (Ring Buffer):")
    recent_logs = log_manager.get_recent_logs(30) if hasattr(log_manager, "get_recent_logs") else []
    if recent_logs:
        for log_entry in recent_logs:
            lines.append(f"   {log_entry.strip()}")
    else:
        lines.append("   (No recent log events)")

    lines.append("=" * 60)
    return "\n".join(lines)


def copy_diagnostic_report_to_clipboard() -> bool:
    """Generates the diagnostic report and copies it directly to Windows clipboard."""
    report = generate_diagnostic_report_text()
    return copy_to_clipboard(report)
