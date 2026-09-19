# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Extractor Backend Updater.
Manages updates, rollbacks, and factory resets for the bundled yt-dlp library from PyPI and GitHub.
"""

from __future__ import annotations
import json
import logging
import os
import re
import shutil
import sys
import tarfile
import tempfile
import threading
import urllib.request
import zipfile
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("HeadlessPlayer.StreamUpdater")

try:
    from ..utils.config_spec import getConfigValue
except ImportError:
    try:
        from config_spec import getConfigValue
    except ImportError:
        def getConfigValue(key: str, default: Any = None) -> Any:
            return default

_ADDON_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB_DIR = os.path.join(_ADDON_DIR, "lib")

if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

_ytdlp_module: Any = None
_ytdlp_import_error: Optional[str] = None
_ytdlp_import_lock = threading.Lock()

# Release channels
YTDLP_CHANNELS = ["stable", "nightly", "master"]

# Directories
BUNDLED_BACKUP_DIR = os.path.join(LIB_DIR, "yt_dlp_bundled")
PREVIOUS_BACKUP_DIR = os.path.join(LIB_DIR, "yt_dlp_previous")
META_FILE = os.path.join(LIB_DIR, "ytdlp_meta.json")

_PYPI_JSON_URL = "https://pypi.org/pypi/yt-dlp/json"
_GITHUB_NIGHTLY_API_URL = "https://api.github.com/repos/yt-dlp/yt-dlp-nightly-builds/releases/latest"
_GITHUB_MASTER_API_URL = "https://api.github.com/repos/yt-dlp/yt-dlp-master-builds/releases/latest"

_update_lock = threading.Lock()


def _get_paths() -> Tuple[str, str, str, str]:
    """Dynamically resolves LIB_DIR and backup paths to support test patching."""
    for mod_name in (
        "globalPlugins.HeadlessPlayer.stream_engine",
        "globalPlugins.HeadlessPlayer.streaming.engine",
        "globalPlugins.HeadlessPlayer.streaming",
        "globalPlugins.HeadlessPlayer.streaming.updater",
    ):
        mod = sys.modules.get(mod_name)
        if mod and "LIB_DIR" in mod.__dict__:
            lib_d = mod.__dict__["LIB_DIR"]
            bundled_d = mod.__dict__.get("BUNDLED_BACKUP_DIR", os.path.join(lib_d, "yt_dlp_bundled"))
            prev_d = mod.__dict__.get("PREVIOUS_BACKUP_DIR", os.path.join(lib_d, "yt_dlp_previous"))
            meta_f = mod.__dict__.get("META_FILE", os.path.join(lib_d, "ytdlp_meta.json"))
            return lib_d, bundled_d, prev_d, meta_f
    return LIB_DIR, BUNDLED_BACKUP_DIR, PREVIOUS_BACKUP_DIR, META_FILE


def _get_ytdlp() -> Any:
    """
    Lazily imports the bundled yt-dlp.
    Raises RuntimeError when unavailable.
    """
    global _ytdlp_module, _ytdlp_import_error
    with _ytdlp_import_lock:
        if _ytdlp_module is not None:
            return _ytdlp_module
        if _ytdlp_import_error is not None:
            raise RuntimeError(_ytdlp_import_error)
        try:
            import yt_dlp  # type: ignore
            _ytdlp_module = yt_dlp
            return _ytdlp_module
        except Exception as e:
            _ytdlp_import_error = str(e)
            logger.error("Failed to import bundled yt-dlp: %s", e)
            raise RuntimeError(_ytdlp_import_error)


def reset_ytdlp_state() -> None:
    """Clears cached import errors to allow retry after updates or environment fixes."""
    global _ytdlp_module, _ytdlp_import_error
    with _ytdlp_import_lock:
        _ytdlp_module = None
        _ytdlp_import_error = None


def is_available() -> bool:
    """True if the bundled yt-dlp library can be used on this NVDA/Python."""
    if _ytdlp_module is not None:
        return True
    if _ytdlp_import_error is not None:
        return False
    if sys.version_info < (3, 10):
        return False
    lib_dir, _, _, _ = _get_paths()
    return os.path.isfile(os.path.join(lib_dir, "yt_dlp", "version.py"))


def get_unavailable_reason() -> str:
    return _ytdlp_import_error or ""


def get_installed_version(pkg_dir: Optional[str] = None) -> str:
    """
    Returns the version string from yt_dlp/version.py in the specified directory
    or lib/yt_dlp by default, or empty string.
    """
    lib_dir, _, _, _ = _get_paths()
    if pkg_dir is None:
        ver_file = os.path.join(lib_dir, "yt_dlp", "version.py")
    elif pkg_dir.endswith(".py"):
        ver_file = pkg_dir
    else:
        v1 = os.path.join(pkg_dir, "version.py")
        v2 = os.path.join(pkg_dir, "yt_dlp", "version.py")
        ver_file = v1 if os.path.isfile(v1) else v2
    try:
        with open(ver_file, "r", encoding="utf-8") as fh:
            content = fh.read()
        m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", content)
        if m:
            return m.group(1)
    except OSError:
        pass
    return ""


def get_bundled_version() -> str:
    """
    Returns the version string of the installed yt-dlp without importing it.
    """
    return get_installed_version()


def _version_tuple(v: str) -> Tuple[int, ...]:
    """Converts standard version string into sortable numeric tuple."""
    parts = []
    for part in re.split(r"[\.-]", v):
        digits = re.findall(r"\d+", part)
        if digits:
            parts.append(int(digits[0]))
    return tuple(parts)


def _load_meta() -> Dict[str, Any]:
    _, _, _, meta_file = _get_paths()
    try:
        if os.path.isfile(meta_file):
            with open(meta_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as e:
        logger.debug("Failed to read yt-dlp metadata: %s", e)
    return {}


def _save_meta(data: Dict[str, Any]) -> None:
    lib_dir, _, _, meta_file = _get_paths()
    try:
        os.makedirs(lib_dir, exist_ok=True)
        with open(meta_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("Failed to save yt-dlp metadata: %s", e)


def ensure_bundled_snapshot() -> None:
    """
    Ensures that a pristine factory backup copy of yt_dlp exists in LIB_DIR/yt_dlp_bundled.
    This creates an immutable snapshot of the version originally shipped with the addon.
    """
    lib_dir, bundled_dir, _, _ = _get_paths()
    target_pkg = os.path.join(lib_dir, "yt_dlp")
    if os.path.isdir(target_pkg) and not os.path.isdir(bundled_dir):
        try:
            shutil.copytree(target_pkg, bundled_dir, dirs_exist_ok=True)
            logger.info("Created pristine factory snapshot of yt-dlp in %s", bundled_dir)
        except Exception as e:
            logger.warning("Could not create bundled snapshot: %s", e)


def can_rollback() -> bool:
    """Returns True if a valid previous version backup exists."""
    _, _, prev_dir, _ = _get_paths()
    prev_ver_file = os.path.join(prev_dir, "version.py")
    if not os.path.isfile(prev_ver_file):
        prev_ver_file = os.path.join(prev_dir, "yt_dlp", "version.py")
    return os.path.isfile(prev_ver_file)


def can_reset_bundled() -> bool:
    """Returns True if factory bundled backup exists."""
    _, bundled_dir, _, _ = _get_paths()
    bundled_ver_file = os.path.join(bundled_dir, "version.py")
    if not os.path.isfile(bundled_ver_file):
        bundled_ver_file = os.path.join(bundled_dir, "yt_dlp", "version.py")
    return os.path.isfile(bundled_ver_file)


def get_channel_info() -> Dict[str, Any]:
    """Returns metadata about current, previous, and bundled versions."""
    _, bundled_dir, prev_dir, _ = _get_paths()
    meta = _load_meta()
    installed_ver = get_bundled_version()
    prev_ver = get_installed_version(prev_dir) if can_rollback() else ""
    bundled_ver = get_installed_version(bundled_dir) if can_reset_bundled() else ""
    return {
        "installed_version": installed_ver or meta.get("installed_version", ""),
        "installed_channel": meta.get("installed_channel", "stable"),
        "previous_version": prev_ver or meta.get("previous_version", ""),
        "previous_channel": meta.get("previous_channel", ""),
        "bundled_version": bundled_ver,
        "can_rollback": can_rollback(),
        "can_reset_bundled": can_reset_bundled(),
    }


def _get_check_latest_version_fn() -> Callable[..., Tuple[str, str]]:
    for mod_name in (
        "globalPlugins.HeadlessPlayer.stream_engine",
        "globalPlugins.HeadlessPlayer.streaming.engine",
        "globalPlugins.HeadlessPlayer.streaming",
        "globalPlugins.HeadlessPlayer.streaming.updater",
    ):
        mod = sys.modules.get(mod_name)
        if mod and "check_latest_version" in mod.__dict__:
            fn = mod.__dict__["check_latest_version"]
            if fn is not check_latest_version:
                return fn
    return check_latest_version


def check_latest_version(channel: str = "stable", timeout: float = 15.0) -> Tuple[str, str]:
    """
    Queries the appropriate API for the newest yt-dlp release on the specified channel.
    Channels: 'stable', 'nightly', 'master'

    Returns:
        (latest_version, wheel_download_url)
    """
    channel = (channel or "stable").strip().lower()

    if channel == "stable":
        req = urllib.request.Request(
            _PYPI_JSON_URL,
            headers={"User-Agent": "HeadlessPlayer-NVDA-Addon"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        latest = str(data.get("info", {}).get("version", ""))
        archive_url = ""
        for f in data.get("releases", {}).get(latest, []):
            if str(f.get("filename", "")).endswith("py3-none-any.whl"):
                archive_url = str(f.get("url", ""))
                break
        if not archive_url:
            for f in data.get("releases", {}).get(latest, []):
                if str(f.get("filename", "")).endswith(".whl") or str(f.get("filename", "")).endswith(".tar.gz"):
                    archive_url = str(f.get("url", ""))
                    break
        if not archive_url:
            for f in data.get("urls", []):
                if str(f.get("filename", "")).endswith(".whl") or str(f.get("filename", "")).endswith(".tar.gz"):
                    archive_url = str(f.get("url", ""))
                    break
        return latest, archive_url

    elif channel in ("nightly", "master"):
        api_url = _GITHUB_NIGHTLY_API_URL if channel == "nightly" else _GITHUB_MASTER_API_URL
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "HeadlessPlayer-NVDA-Addon",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        latest = str(data.get("tag_name", "")).lstrip("v")
        if not latest:
            latest = str(data.get("name", "")).lstrip("v")

        archive_url = ""
        assets = data.get("assets", [])
        for asset in assets:
            name = str(asset.get("name", ""))
            if name.endswith("py3-none-any.whl") or (name.endswith(".whl") and "yt_dlp" in name):
                archive_url = str(asset.get("browser_download_url", ""))
                break
        if not archive_url:
            for asset in assets:
                name = str(asset.get("name", ""))
                if name == "yt-dlp.tar.gz" or name.endswith(".tar.gz") or name.endswith(".tgz"):
                    archive_url = str(asset.get("browser_download_url", ""))
                    break
        if not archive_url:
            for asset in assets:
                name = str(asset.get("name", ""))
                if name.endswith(".zip") and not name.endswith(".exe"):
                    archive_url = str(asset.get("browser_download_url", ""))
                    break
        if not archive_url:
            archive_url = str(data.get("tarball_url", "") or data.get("zipball_url", ""))

        return latest, archive_url

    else:
        raise ValueError(f"Unknown yt-dlp channel: {channel}")


def update_ytdlp(channel: Optional[str] = None, progress_cb: Optional[Callable[[str], None]] = None) -> Tuple[bool, str]:
    """
    Checks the chosen channel, downloads and installs the package into lib/yt_dlp.
    Automatically preserves previous version in lib/yt_dlp_previous and factory snapshot in lib/yt_dlp_bundled.

    Returns:
        (updated, message)
    """
    def report(stage: str, downloaded: int = 0, total: int = 0, pct: float = 0.0, extra: str = "") -> None:
        if progress_cb:
            try:
                try:
                    progress_cb(stage, downloaded, total, pct, extra)
                except TypeError:
                    progress_cb(stage)
            except Exception:
                pass

    if not channel:
        try:
            channel = getConfigValue("ytdlpUpdateChannel", "stable")
        except Exception:
            channel = "stable"
    channel = (channel or "stable").strip().lower()

    with _update_lock:
        ensure_bundled_snapshot()
        current = get_bundled_version()
        meta = _load_meta()
        current_channel = meta.get("installed_channel", "stable")

        report("checking", 0, 0, 0.0)
        try:
            check_fn = _get_check_latest_version_fn()
            latest, download_url = check_fn(channel=channel)
        except Exception as e:
            return False, f"error:network:{e}"

        if not download_url:
            return False, "error:no-download-url"

        if channel == current_channel and current and _version_tuple(latest) <= _version_tuple(current):
            return False, f"up-to-date:{current}"

        report("downloading", 0, 0, 0.0)
        tmp_dir = tempfile.mkdtemp(prefix="hp_ytdlp_")
        try:
            archive_path = os.path.join(tmp_dir, "yt_dlp_archive")
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "HeadlessPlayer-NVDA-Addon"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp, open(archive_path, "wb") as fh:
                try:
                    headers = getattr(resp, "headers", None)
                    if headers and hasattr(headers, "get"):
                        total_len = int(headers.get("Content-Length", 0) or 0)
                    elif hasattr(resp, "getheader"):
                        total_len = int(resp.getheader("Content-Length") or 0)
                    elif hasattr(resp, "info"):
                        info = resp.info()
                        total_len = int(info.get("Content-Length", 0) or 0) if hasattr(info, "get") else 0
                    else:
                        total_len = 0
                except (ValueError, TypeError, AttributeError):
                    total_len = 0
                downloaded = 0
                chunk_size = 65536
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    fh.write(chunk)
                    downloaded += len(chunk)
                    pct = (downloaded / total_len * 100.0) if total_len > 0 else 0.0
                    report("downloading", downloaded, total_len, pct)

            report("extracting", downloaded, total_len, 100.0)
            extract_dir = os.path.join(tmp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)

            report("installing", downloaded, total_len, 100.0)
            extracted = False
            if zipfile.is_zipfile(archive_path):
                try:
                    with zipfile.ZipFile(archive_path) as zf:
                        zf.extractall(extract_dir)
                    extracted = True
                except Exception as e:
                    logger.debug("Zipfile extraction failed: %s", e)

            if not extracted:
                try:
                    with tarfile.open(archive_path, "r:*") as tf:
                        tf.extractall(extract_dir)
                    extracted = True
                except Exception as e:
                    logger.debug("Tarfile extraction failed: %s", e)

            if not extracted:
                return False, "error:bad-archive"

            new_pkg = None
            for root, dirs, files in os.walk(extract_dir):
                if os.path.basename(root) == "yt_dlp" and ("version.py" in files or "__init__.py" in files):
                    new_pkg = root
                    break

            if not new_pkg or not os.path.isdir(new_pkg):
                return False, "error:bad-package-contents"

            lib_dir, bundled_dir, prev_dir, _ = _get_paths()
            target_pkg = os.path.join(lib_dir, "yt_dlp")
            os.makedirs(lib_dir, exist_ok=True)

            if os.path.isdir(target_pkg):
                if os.path.isdir(prev_dir):
                    shutil.rmtree(prev_dir, ignore_errors=True)
                shutil.move(target_pkg, prev_dir)

            shutil.copytree(new_pkg, target_pkg, dirs_exist_ok=True)

            try:
                ejs_dir = None
                for root, dirs, files in os.walk(extract_dir):
                    if os.path.basename(root) == "yt_dlp_ejs":
                        ejs_dir = root
                        break
                if ejs_dir:
                    target_ejs = os.path.join(lib_dir, "yt_dlp_ejs")
                    shutil.rmtree(target_ejs, ignore_errors=True)
                    shutil.copytree(ejs_dir, target_ejs, dirs_exist_ok=True)
            except Exception as ejs_err:
                logger.debug("yt-dlp-ejs update failed (non-fatal): %s", ejs_err)

            _save_meta({
                "installed_version": latest,
                "installed_channel": channel,
                "previous_version": current,
                "previous_channel": current_channel,
            })

            reset_ytdlp_state()
            report("done", downloaded, total_len, 100.0, latest)
            logger.info("Successfully updated yt-dlp to %s (%s channel).", latest, channel)
            return True, f"success:{latest}"

        except Exception as e:
            logger.error("Failed to update yt-dlp: %s", e, exc_info=True)
            return False, f"error:install:{e}"

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def rollback_ytdlp() -> Tuple[bool, str]:
    """Restores the previously installed yt-dlp version from lib/yt_dlp_previous."""
    with _update_lock:
        if not can_rollback():
            return False, "error:no-backup"

        lib_dir, _, prev_dir, _ = _get_paths()
        target_pkg = os.path.join(lib_dir, "yt_dlp")
        try:
            prev_ver = get_installed_version(prev_dir)
            cur_ver = get_bundled_version()
            meta = _load_meta()

            if os.path.isdir(target_pkg):
                shutil.rmtree(target_pkg, ignore_errors=True)

            src_pkg = prev_dir
            if not os.path.isfile(os.path.join(src_pkg, "version.py")) and os.path.isdir(os.path.join(src_pkg, "yt_dlp")):
                src_pkg = os.path.join(src_pkg, "yt_dlp")

            shutil.copytree(src_pkg, target_pkg, dirs_exist_ok=True)
            shutil.rmtree(prev_dir, ignore_errors=True)

            _save_meta({
                "installed_version": prev_ver,
                "installed_channel": meta.get("previous_channel", "stable"),
                "previous_version": cur_ver,
                "previous_channel": meta.get("installed_channel", "stable"),
            })

            reset_ytdlp_state()
            logger.info("Rolled back yt-dlp to previous version %s", prev_ver)
            return True, f"success:{prev_ver}"
        except Exception as e:
            logger.error("Failed to rollback yt-dlp: %s", e)
            return False, f"error:{e}"


def reset_to_bundled_ytdlp() -> Tuple[bool, str]:
    """Restores the pristine factory bundled yt-dlp snapshot from lib/yt_dlp_bundled."""
    with _update_lock:
        if not can_reset_bundled():
            return False, "error:no-bundled-backup"

        lib_dir, bundled_dir, prev_dir, _ = _get_paths()
        target_pkg = os.path.join(lib_dir, "yt_dlp")
        try:
            bundled_ver = get_installed_version(bundled_dir)
            cur_ver = get_bundled_version()
            meta = _load_meta()

            if os.path.isdir(target_pkg):
                if os.path.isdir(prev_dir):
                    shutil.rmtree(prev_dir, ignore_errors=True)
                shutil.move(target_pkg, prev_dir)

            src_pkg = bundled_dir
            if not os.path.isfile(os.path.join(src_pkg, "version.py")) and os.path.isdir(os.path.join(src_pkg, "yt_dlp")):
                src_pkg = os.path.join(src_pkg, "yt_dlp")

            shutil.copytree(src_pkg, target_pkg, dirs_exist_ok=True)

            _save_meta({
                "installed_version": bundled_ver,
                "installed_channel": "stable",
                "previous_version": cur_ver,
                "previous_channel": meta.get("installed_channel", "stable"),
            })

            reset_ytdlp_state()
            logger.info("Reset yt-dlp to factory bundled version %s", bundled_ver)
            return True, f"success:{bundled_ver}"
        except Exception as e:
            logger.error("Failed to reset yt-dlp to bundled version: %s", e)
            return False, f"error:{e}"
