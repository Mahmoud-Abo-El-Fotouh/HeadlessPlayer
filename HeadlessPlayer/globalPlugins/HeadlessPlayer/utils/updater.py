# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Self-Updater Module.
Checks GitHub Releases for new add-on versions, presents release changelogs in an
accessible read-only text box, and downloads updates with live progress reporting
before launching NVDA's native installation workflow.
"""

from __future__ import annotations
import json
import logging
import os
import re
import sys
import tempfile
import threading
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("HeadlessPlayer.AddonUpdater")

try:
    import addonHandler
    addonHandler.initTranslation()
except Exception:
    addonHandler = None

try:
    from .. import _  # type: ignore
except (ImportError, ValueError):
    try:
        from . import _  # type: ignore
    except (ImportError, ValueError):
        try:
            _ = _  # type: ignore
        except NameError:
            _ = lambda s: s

try:
    import wx
    import gui
    from gui import guiHelper
except Exception:
    wx = None
    gui = None
    guiHelper = None

GITHUB_REPO = "Mahmoud-Abo-El-Fotouh/HeadlessPlayer"
USER_AGENT = "NVDA-Addon-HeadlessPlayer-Updater"


def parse_version(ver_str: str) -> Tuple[int, ...]:
    """Parses a version string (e.g. 'v1.2.2', '1.2.1') into a comparable tuple of ints padded with trailing zeros."""
    if not ver_str:
        return (0, 0, 0)
    clean = re.sub(r'^[vV]', '', str(ver_str).strip())
    parts = re.findall(r'\d+', clean)
    int_parts = [int(p) for p in parts] if parts else [0, 0, 0]
    while len(int_parts) < 3:
        int_parts.append(0)
    return tuple(int_parts)


def is_newer_version(latest_ver: str, current_ver: str) -> bool:
    """Returns True if latest_ver is strictly newer than current_ver, with length normalization."""
    t_latest = parse_version(latest_ver)
    t_cur = parse_version(current_ver)
    max_len = max(len(t_latest), len(t_cur))
    p_latest = t_latest + (0,) * (max_len - len(t_latest))
    p_cur = t_cur + (0,) * (max_len - len(t_cur))
    return p_latest > p_cur


def get_current_addon_version() -> str:
    """Retrieves the installed version of HeadlessPlayer add-on."""
    try:
        ah = sys.modules.get("addonHandler", addonHandler)
        if ah is not None and hasattr(ah, "getCodeAddon"):
            cur_addon = ah.getCodeAddon()
            if cur_addon and cur_addon.manifest:
                ver = cur_addon.manifest.get("version")
                if ver:
                    return str(ver).strip()
    except Exception as e:
        logger.debug("Could not query addonHandler for version: %s", e)

    # Fallback: parse manifest.ini in add-on root directory
    try:
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(cur_dir, "..", "..", ".."))
        manifest_path = os.path.join(root_dir, "manifest.ini")
        if not os.path.isfile(manifest_path):
            root_dir = os.path.abspath(os.path.join(cur_dir, "..", ".."))
            manifest_path = os.path.join(root_dir, "manifest.ini")
        if os.path.isfile(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("version"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            return parts[1].strip().strip('"').strip("'")
    except Exception as e:
        logger.debug("Could not read manifest.ini for version: %s", e)

    return "1.3.0"


def check_for_addon_update(
    repo: str = GITHUB_REPO,
    timeout: int = 12
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Queries GitHub API for the latest release of the add-on.

    Returns:
        (update_available: bool, update_info: dict, status_code: str)
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github.v3+json",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False, None, f"error:http_{resp.status}"
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            logger.warning("GitHub API rate limit exceeded: %s", e)
            return False, None, "error:rate_limit_exceeded"
        logger.warning("HTTP error querying GitHub Releases API: %s", e)
        return False, None, f"error:http_{e.code}"
    except Exception as e:
        logger.warning("Failed to query GitHub Releases API: %s", e)
        return False, None, f"error:{e}"

    if not isinstance(data, dict):
        return False, None, "error:invalid_response"

    tag_name = str(data.get("tag_name") or "")
    latest_ver = tag_name.lstrip("vV").strip()
    if not latest_ver:
        return False, None, "error:no_version_tag"

    cur_ver = get_current_addon_version()

    # Find the .nvda-addon asset
    addon_asset = None
    for asset in data.get("assets", []):
        name = str(asset.get("name") or "")
        if name.lower().endswith(".nvda-addon"):
            addon_asset = asset
            break

    if not addon_asset:
        logger.warning("Release %s found but no .nvda-addon asset attached", tag_name)
        return False, None, "error:no_addon_asset"

    update_info = {
        "tag_name": tag_name,
        "version": latest_ver,
        "current_version": cur_ver,
        "title": str(data.get("name") or f"HeadlessPlayer {latest_ver}"),
        "changelog": str(data.get("body") or _("No changelog description provided.")),
        "download_url": str(addon_asset.get("browser_download_url")),
        "asset_name": str(addon_asset.get("name")),
        "size_bytes": int(addon_asset.get("size", 0)),
        "published_at": str(data.get("published_at") or ""),
    }

    if is_newer_version(latest_ver, cur_ver):
        return True, update_info, "update_available"
    else:
        return False, update_info, "up_to_date"


def download_addon_file(
    download_url: str,
    dest_path: str,
    progress_cb: Optional[Callable[[int, int, float], None]] = None,
    timeout: int = 30
) -> bool:
    """
    Downloads the .nvda-addon file from download_url safely to a temporary .part file first.
    Atomically renames to dest_path upon verified completion.
    Cleans up incomplete/corrupted partial files if interrupted.
    """
    req = urllib.request.Request(
        download_url,
        headers={"User-Agent": USER_AGENT}
    )

    part_path = dest_path + ".part"
    for p in (part_path, dest_path):
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            try:
                raw_len = resp.headers.get("content-length", 0)
                total_size = int(raw_len) if raw_len else 0
            except (ValueError, TypeError):
                total_size = 0
            downloaded = 0
            chunk_size = 64 * 1024

            with open(part_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    pct = (downloaded / total_size * 100.0) if total_size > 0 else 0.0
                    if progress_cb:
                        progress_cb(downloaded, total_size, pct)

        if total_size > 0 and downloaded < total_size:
            raise IOError(f"Incomplete download: received {downloaded} of {total_size} bytes")

        if not os.path.isfile(part_path) or os.path.getsize(part_path) == 0:
            raise IOError("Downloaded file is empty")

        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        os.replace(part_path, dest_path)
        return True

    except Exception as e:
        logger.error("Download failed for %s: %s", download_url, e)
        for p in (part_path, dest_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        raise


# ---------------------------------------------------------------------------
# Accessible wxPython Update Dialog
# ---------------------------------------------------------------------------

_WxDialog = getattr(wx, "Dialog", object) if wx else object


class AddonUpdateDialog(_WxDialog):
    """
    Accessible dialog presenting add-on update details, release changelog in a
    read-only multi-line text box, live download progress, and direct installation trigger.
    """

    def __init__(self, parent: Any, update_info: Dict[str, Any]) -> None:
        if not wx:
            return
        super().__init__(
            parent,
            title=_("Headless Media Player - Add-on Update Available"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        self.update_info = update_info
        self._is_downloading = False
        self.downloaded_file_path: Optional[str] = None
        self.InitUI()
        self.CenterOnParent()

    def InitUI(self) -> None:
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        helper = guiHelper.BoxSizerHelper(self, sizer=mainSizer)

        cur_v = self.update_info.get("current_version", "")
        new_v = self.update_info.get("version", "")
        size_mb = self.update_info.get("size_bytes", 0) / (1024 * 1024)

        # 1. Header Information Label
        header_text = _("A new version (%s) of Headless Media Player is available! (Current version: %s)") % (new_v, cur_v)
        self.headerLabel = wx.StaticText(self, label=header_text)
        helper.addItem(self.headerLabel)

        # 2. Changelog / Release Description Section
        changelog_label = _("What's New in Version %s:") % new_v
        helper.addItem(wx.StaticText(self, label=changelog_label))

        body_text = self.update_info.get("changelog", "").strip()
        self.changelogCtrl = wx.TextCtrl(
            self,
            value=body_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
            size=(520, 220)
        )
        helper.addItem(self.changelogCtrl)

        # 3. Download Progress Status Label & Gauge
        initial_status = _("Ready to download. Download size: %.2f MB") % size_mb
        self.progressLabel = wx.StaticText(self, label=initial_status)
        helper.addItem(self.progressLabel)

        self.progressBar = wx.Gauge(self, range=100, size=(520, 20), style=wx.GA_HORIZONTAL)
        helper.addItem(self.progressBar)

        # 4. Action Buttons (Update / Install & Cancel)
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)

        self.updateBtn = wx.Button(self, label=_("&Download and Install Update"))
        self.updateBtn.SetDefault()
        self.updateBtn.Bind(wx.EVT_BUTTON, self.onStartDownload)
        btnSizer.Add(self.updateBtn, 0, wx.ALL, 5)

        btnSizer.AddStretchSpacer()

        self.closeBtn = wx.Button(self, wx.ID_CANCEL, label=_("&Close"))
        self.closeBtn.Bind(wx.EVT_BUTTON, self.onClose)
        btnSizer.Add(self.closeBtn, 0, wx.ALL, 5)

        helper.addItem(btnSizer)
        self.SetSizerAndFit(mainSizer)

    def onStartDownload(self, evt: Any) -> None:
        """Starts downloading the add-on package in a background worker thread."""
        if self._is_downloading:
            return

        self._is_downloading = True
        self.updateBtn.Disable()
        self.updateBtn.SetLabel(_("Downloading update..."))
        self.progressLabel.SetLabel(_("Connecting to download server..."))

        def progress_callback(downloaded: int, total: int, pct: float) -> None:
            wx.CallAfter(self._update_progress_ui, downloaded, total, pct)

        def worker() -> None:
            url = self.update_info.get("download_url", "")
            asset_name = self.update_info.get("asset_name", "HeadlessPlayer.nvda-addon")
            temp_dir = tempfile.gettempdir()
            dest = os.path.join(temp_dir, asset_name)

            try:
                success = download_addon_file(url, dest, progress_cb=progress_callback)
                if success:
                    wx.CallAfter(self._on_download_complete, dest)
                else:
                    wx.CallAfter(self._on_download_failed, _("Downloaded file is empty."))
            except Exception as e:
                logger.error("Error downloading add-on update: %s", e)
                wx.CallAfter(self._on_download_failed, str(e))

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-DownloadWorker").start()

    def _update_progress_ui(self, downloaded: int, total: int, pct: float) -> None:
        if not self:
            return
        pct_int = min(100, max(0, int(pct)))
        self.progressBar.SetValue(pct_int)

        down_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024) if total > 0 else 0.0

        if total_mb > 0:
            msg = _("Downloaded %.2f MB of %.2f MB (%d%%)") % (down_mb, total_mb, pct_int)
        else:
            msg = _("Downloaded %.2f MB") % down_mb

        self.progressLabel.SetLabel(msg)

    def _on_download_complete(self, file_path: str) -> None:
        self._is_downloading = False
        self.downloaded_file_path = file_path
        self.progressBar.SetValue(100)
        self.progressLabel.SetLabel(_("Download complete! Launching add-on installation..."))

        # Launch NVDA native installation workflow: prefer addonHandler for portable & installed NVDA
        installed = False
        try:
            ah = sys.modules.get("addonHandler", addonHandler)
            if ah is not None and hasattr(ah, "installAddonPackage"):
                bundle = ah.AddonBundle(file_path)
                ah.installAddonPackage(bundle)
                installed = True
        except Exception as e:
            logger.debug("addonHandler.installAddonPackage attempt: %s", e)

        if not installed:
            try:
                os.startfile(file_path)
                installed = True
            except Exception as e:
                logger.error("Could not start add-on file via os.startfile: %s", e)

        self.EndModal(wx.ID_OK)

    def _on_download_failed(self, error_msg: str) -> None:
        self._is_downloading = False
        self.updateBtn.Enable()
        self.updateBtn.SetLabel(_("&Retry Download"))
        self.progressLabel.SetLabel(_("Download failed: %s") % error_msg)

        if gui and hasattr(gui, "messageBox"):
            gui.messageBox(
                _("Failed to download the add-on update.\n\nDetails: %s") % error_msg,
                _("Download Failed"),
                wx.OK | wx.ICON_ERROR
            )

    def onClose(self, evt: Any) -> None:
        self.EndModal(wx.ID_CANCEL)


def cleanup_temp_addon_packages() -> None:
    """
    Sweeps the system temp directory and removes any leftover HeadlessPlayer .nvda-addon files
    to ensure installer files never take up permanent disk space.
    """
    temp_dir = tempfile.gettempdir()
    try:
        if not os.path.isdir(temp_dir):
            return
        for fname in os.listdir(temp_dir):
            if fname.startswith("HeadlessPlayer") and fname.endswith(".nvda-addon"):
                fpath = os.path.join(temp_dir, fname)
                try:
                    os.remove(fpath)
                    logger.debug("Cleaned up temp addon package: %s", fpath)
                except Exception:
                    pass
    except Exception as e:
        logger.debug("Error sweeping temp add-on files: %s", e)


try:
    import atexit
    atexit.register(cleanup_temp_addon_packages)
    cleanup_temp_addon_packages()
except Exception:
    pass
