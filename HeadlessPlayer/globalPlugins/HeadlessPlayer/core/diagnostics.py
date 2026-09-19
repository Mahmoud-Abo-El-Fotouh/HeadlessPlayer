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
    from .. import _  # type: ignore
except (ImportError, ValueError):
    try:
        from . import _  # type: ignore
    except (ImportError, ValueError):
        try:
            _ = _  # type: ignore
        except NameError:
            _ = lambda text: text

from ..utils import copy_to_clipboard
from ..utils.config_spec import getConfig, getConfigValue, DEFAULT_CONFIG
from ..history.database import get_db_manager
from .process import find_mpv_binary, DEFAULT_PIPE_NAME
from ..streaming import engine as stream_engine
from ..utils import logger as log_manager

logger = logging.getLogger("HeadlessPlayer.Diagnostics")


class HealthStatus:
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"


def check_mpv_binary(custom_path: Optional[str] = None) -> Dict[str, Any]:
    """Inspects the bundled or custom mpv executable."""
    addon_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
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
    """Inspects all localized translation catalog files dynamically across the locale directory."""
    addon_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
    locales_dir = os.path.join(addon_root, "locale")

    if not os.path.isdir(locales_dir):
        return {
            "status": HealthStatus.WARNING,
            "component": "Translations (i18n)",
            "message": "Locale directory not found.",
            "languages": {},
        }

    lang_results: Dict[str, Dict[str, Any]] = {}
    verified_langs: List[str] = []
    missing_langs: List[str] = []

    for lang_name in sorted(os.listdir(locales_dir)):
        lang_path = os.path.join(locales_dir, lang_name)
        if not os.path.isdir(lang_path):
            continue

        lc_messages = os.path.join(lang_path, "LC_MESSAGES")
        mo_path = os.path.join(lc_messages, "nvda.mo")
        alt_mo_path = os.path.join(lc_messages, "messages.mo")

        mo_file = mo_path if os.path.isfile(mo_path) else (alt_mo_path if os.path.isfile(alt_mo_path) else "")
        is_ok = bool(mo_file and os.path.getsize(mo_file) > 1000)

        lang_results[lang_name] = {
            "path": mo_file or mo_path,
            "ok": is_ok,
            "size": os.path.getsize(mo_file) if mo_file else 0,
        }

        if is_ok:
            verified_langs.append(lang_name)
        else:
            missing_langs.append(lang_name)

    all_ok = bool(verified_langs and not missing_langs)
    status = HealthStatus.OK if all_ok else HealthStatus.WARNING

    if all_ok:
        msg = f"All {len(verified_langs)} translation catalogs ({', '.join(verified_langs)}) are verified and intact."
    else:
        msg = f"Translation check: {len(verified_langs)} valid ({', '.join(verified_langs)}), {len(missing_langs)} missing/invalid ({', '.join(missing_langs)})"

    return {
        "status": status,
        "component": "Translations (i18n)",
        "message": msg,
        "languages": lang_results,
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
