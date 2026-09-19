# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Online Streaming Engine (yt-dlp backend).
Provides YouTube search, playlist/channel listing expansion, direct audio
stream URL resolution for YouTube and 1800+ other sites via the bundled
yt-dlp library, plus a self-update mechanism from PyPI.
"""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.request
import tarfile
import zipfile
from .utils import log_debug, log_exception

try:
    from .config_spec import getConfig, getConfigValue
except ImportError:
    try:
        from config_spec import getConfig, getConfigValue
    except ImportError:
        def getConfig() -> Dict[str, Any]:
            return {}
        def getConfigValue(key: str, default: Any = None) -> Any:
            return default

logger = logging.getLogger("HeadlessPlayer.StreamEngine")

try:
    import addonHandler
    addonHandler.initTranslation()
except Exception:
    pass

try:
    _
except NameError:
    def _(s: str) -> str:
        return s

# ---------------------------------------------------------------------------
# Bundled yt-dlp bootstrap
# ---------------------------------------------------------------------------

_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(_ADDON_DIR, "lib")

if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

_ytdlp_module: Any = None
_ytdlp_import_error: Optional[str] = None
_ytdlp_import_lock = threading.Lock()


def _get_ytdlp() -> Any:
    """
    Lazily imports the bundled yt-dlp (the import is slow, so it only happens
    on first actual use, never at NVDA startup).
    Raises RuntimeError when unavailable (e.g. NVDA older than 2024.1 / Python < 3.10).
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
    return os.path.isfile(os.path.join(LIB_DIR, "yt_dlp", "version.py"))


def get_unavailable_reason() -> str:
    return _ytdlp_import_error or ""


def get_installed_version(pkg_dir: Optional[str] = None) -> str:
    """
    Returns the version string from yt_dlp/version.py in the specified directory
    or lib/yt_dlp by default, or empty string.
    """
    if pkg_dir is None:
        ver_file = os.path.join(LIB_DIR, "yt_dlp", "version.py")
    elif pkg_dir.endswith(".py"):
        ver_file = pkg_dir
    else:
        ver_file = os.path.join(pkg_dir, "version.py")
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



class _SilentLogger:
    """Routes yt-dlp log output into the add-on logger at debug level."""

    def debug(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        logger.debug("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        logger.warning("yt-dlp error: %s", msg)


# ---------------------------------------------------------------------------
# URL classification helpers
# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"^(?:https?://|ftp://|rtmps?://|rtsp://|mms(?:h|t)?://|srt://|www\.)",
    re.IGNORECASE
)

_EXTRACT_URL_RE = re.compile(
    r"(?:https?://|ftp://|rtmps?://|rtsp://|mms(?:h|t)?://|srt://|www\.)[^\s<>'\"`]+",
    re.IGNORECASE
)

_YOUTUBE_HOST_RE = re.compile(
    r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)(/|$)",
    re.IGNORECASE,
)


def normalize_url(text: str) -> str:
    """Ensures the URL has an explicit scheme."""
    t = text.strip()
    if t.lower().startswith("www."):
        return "https://" + t
    return t


def extract_url(text: str) -> Optional[str]:
    """
    Intelligently extracts the first valid web/media URL embedded inside any surrounding
    text, message, chat snippet, or formatted string.
    
    Examples:
        - "Check this out https://youtu.be/abc123xyz it is great!" -> "https://youtu.be/abc123xyz"
        - "listen to www.youtube.com/watch?v=123 now" -> "https://www.youtube.com/watch?v=123"
        - "https://soundcloud.com/artist/track" -> "https://soundcloud.com/artist/track"
    """
    if not text or not isinstance(text, str):
        return None
    m = _EXTRACT_URL_RE.search(text.strip())
    if m:
        raw_url = m.group(0).rstrip(".,;:!?)>]}'\"\u060C\u061F\u061B\u066B\u066C«»“”’‘")
        return normalize_url(raw_url)
    return None


def is_url(text: str) -> bool:
    """True if the given text is a direct URL or contains an embedded media URL."""
    if not text or not isinstance(text, str):
        return False
    return bool(extract_url(text))


def is_youtube_url(url: str) -> bool:
    return bool(_YOUTUBE_HOST_RE.match(url.strip()))


ITEM_VIDEO = "video"
ITEM_SHORTS = "shorts"
ITEM_PLAYLIST = "playlist"
ITEM_CHANNEL = "channel"
ITEM_LISTING = "listing"  # synthetic channel sub-listing (Videos / Shorts / Playlists / Live)


def classify_flat_entry(entry: Dict[str, Any]) -> str:
    """Classifies a flat-extracted yt-dlp entry as video, shorts, playlist, or channel."""
    url = str(entry.get("url") or entry.get("webpage_url") or "")
    ie_key = str(entry.get("ie_key") or "")
    etype = str(entry.get("_type") or "")
    dur = entry.get("duration")
    title = str(entry.get("title") or entry.get("headline") or entry.get("fulltitle") or "")

    low = url.lower()
    title_low = title.lower()
    if "/shorts/" in low or "#short" in title_low or "#shorts" in title_low:
        return ITEM_SHORTS
    if dur is not None:
        try:
            if 0 < float(dur) <= 60 and ("youtube" in low or ie_key.lower().startswith("youtube")):
                return ITEM_SHORTS
        except (TypeError, ValueError):
            pass
    if "playlist?list=" in low or ie_key in ("YoutubePlaylist", "SoundcloudSet"):
        return ITEM_PLAYLIST
    if ie_key in ("YoutubeTab", "TikTokUser", "SoundcloudUser") or etype in ("playlist", "multi_video"):
        if "/@" in low or "/channel/" in low or "/c/" in low or "/user/" in low:
            return ITEM_CHANNEL
        return ITEM_PLAYLIST
    return ITEM_VIDEO


class StreamItem:
    """A single browsable result: video, playlist, channel, or sub-listing."""

    def __init__(
        self,
        kind: str,
        url: str,
        title: str,
        duration: Optional[float] = None,
        uploader: str = "",
        is_live: bool = False,
        requires_login: bool = False,
    ) -> None:
        self.kind = kind
        self.url = url
        self.title = title or url
        self.duration = duration
        self.uploader = uploader
        self.is_live = is_live
        self.requires_login = requires_login

    @classmethod
    def from_flat_entry(cls, entry: Dict[str, Any]) -> Optional["StreamItem"]:
        url = entry.get("url") or entry.get("webpage_url") or entry.get("id")
        if not url:
            return None
        kind = classify_flat_entry(entry)
        dur = entry.get("duration")
        try:
            dur = float(dur) if dur is not None else None
        except (TypeError, ValueError):
            dur = None
        live_status = entry.get("live_status")

        # Multi-tiered title resolution across various YouTube/site flat representations
        raw_title = (
            entry.get("title")
            or entry.get("fulltitle")
            or entry.get("headline")
            or entry.get("alt_title")
            or entry.get("description")
            or entry.get("track")
            or ""
        )
        if isinstance(raw_title, list):
            raw_title = " ".join(str(t) for t in raw_title if t)
        title_str = str(raw_title).strip()

        uploader_str = str(
            entry.get("channel")
            or entry.get("uploader")
            or entry.get("channel_name")
            or entry.get("artist")
            or ""
        ).strip()

        # Clean fallback if title is absent or is an unformatted URL
        if not title_str or title_str.startswith("http://") or title_str.startswith("https://") or title_str == str(url):
            vid_id = str(entry.get("id") or "").strip()
            if uploader_str:
                title_str = f"{uploader_str} - Short ({vid_id})" if kind == ITEM_SHORTS else f"{uploader_str} ({vid_id})"
            elif vid_id:
                title_str = f"Short ({vid_id})" if kind == ITEM_SHORTS else f"Video ({vid_id})"
            else:
                title_str = str(url)

        url_str = str(url or "").strip()
        if len(url_str) == 11 and "/" not in url_str and not url_str.startswith("http"):
            url_str = f"https://www.youtube.com/watch?v={url_str}"

        return cls(
            kind=kind,
            url=url_str,
            title=title_str,
            duration=dur,
            uploader=uploader_str,
            is_live=(live_status == "is_live" or bool(entry.get("is_live"))),
        )


SUPPORTED_COOKIE_BROWSERS: Sequence[str] = ("none", "firefox")


def get_manual_cookies_file() -> str:
    """Returns the configured manual cookies.txt path if it exists, else ''."""
    cfg = _get_config()
    path = str(cfg.get("ytdlpCookiesFile", "") or "").strip().strip('"')
    if path:
        path = os.path.expandvars(os.path.expanduser(path))
        if os.path.isfile(path):
            return path
    return ""


def login_cookies_enabled() -> bool:
    """
    True when sign-in cookies are configured: either a manual cookies.txt
    file, or a supported browser (Firefox) selected for automatic cookie extraction.
    """
    if get_manual_cookies_file():
        return True
    cfg = _get_config()
    browser = str(cfg.get("ytdlpCookiesBrowser", "") or "").strip().lower()
    return bool(browser in SUPPORTED_COOKIE_BROWSERS and browser != "none")


def is_cookie_error(error_text: str) -> bool:
    """
    Detects browser-cookie extraction failures (e.g. Chrome's app-bound
    encryption blocking DPAPI decryption) or invalid/bot cookies so the user gets accurate advice.
    """
    low = str(error_text).lower()
    return (
        "cookie" in low
        or "dpapi" in low
        or "decrypt" in low
        or "sign in to confirm" in low
        or "confirm you're not a bot" in low
        or "confirm you?re not a bot" in low
        or "only available to registered users" in low
        or "sign in to view" in low
        or "private video" in low
        or "members-only" in low
        or "app-bound" in low
        or "elevation" in low
    )


def check_youtube_cookies_validity(cookie_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Validates whether the configured or specified cookies.txt file contains
    the essential YouTube authentication tokens (specifically LOGIN_INFO / SAPISID).
    Returns (is_valid, reason_str).
    Possible reasons:
        'ok': Cookies appear complete and valid.
        'not_configured': No cookies file configured.
        'file_not_found': File path does not exist.
        'missing_auth_tokens': Missing SID/SAPISID/3PSID/LOGIN_INFO tokens.
        'expired': Session tokens (LOGIN_INFO) have expired timestamp.
        'empty': File is empty or has no YouTube cookies.
    """
    if cookie_path is None:
        cookie_path = get_manual_cookies_file()
    if not cookie_path:
        return False, "not_configured"
    if not os.path.isfile(cookie_path):
        return False, "file_not_found"

    has_yt = False
    has_login_info = False
    has_sid_or_sapisid = False
    is_expired = False
    current_time = time.time()

    try:
        with open(cookie_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    domain = parts[0].lower()
                    expiry_str = parts[4].strip()
                    name = parts[5].strip()
                    if "youtube.com" in domain or "google.com" in domain:
                        has_yt = True
                        try:
                            expiry = int(expiry_str)
                            if expiry > 0 and expiry < current_time:
                                if name in ("LOGIN_INFO", "SAPISID", "__Secure-3PAPISID", "SID"):
                                    is_expired = True
                        except (ValueError, TypeError):
                            pass

                        if name == "LOGIN_INFO":
                            has_login_info = True
                        if name in ("SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID", "SID", "__Secure-3PSID"):
                            has_sid_or_sapisid = True
    except Exception as e:
        return False, f"read_error: {e}"

    if not has_yt:
        return False, "empty"
    if is_expired:
        return False, "expired"
    if not has_login_info and not has_sid_or_sapisid:
        return False, "missing_auth_tokens"
    return True, "ok"


def get_account_sections() -> List["StreamItem"]:
    """
    Builds the YouTube account & feeds menu (P key): personalized sections
    (requiring sign-in cookies) plus Trending which works without an account.
    Each section opens in the standard interactive results list.
    """
    return [
        StreamItem(
            ITEM_LISTING,
            "https://www.youtube.com/feed/channels",
            _("Subscribed channels"),
            requires_login=True,
        ),
        StreamItem(
            ITEM_LISTING,
            "https://www.youtube.com/feed/subscriptions",
            _("Latest videos from your subscriptions"),
            requires_login=True,
        ),
        StreamItem(
            ITEM_LISTING,
            "https://www.youtube.com/feed/subscriptions/shorts",
            _("Shorts from your subscriptions"),
            requires_login=True,
        ),
        StreamItem(
            ITEM_LISTING,
            "https://www.youtube.com/feed/recommended",
            _("Recommended for you (home feed)"),
            requires_login=True,
        ),
        StreamItem(
            ITEM_LISTING,
            "https://www.youtube.com/playlist?list=WL",
            _("Watch Later playlist"),
            requires_login=True,
        ),
        StreamItem(
            ITEM_LISTING,
            "https://www.youtube.com/playlist?list=LL",
            _("Liked videos"),
            requires_login=True,
        ),
        StreamItem(
            ITEM_LISTING,
            "https://www.youtube.com/feed/history",
            _("Watch history"),
            requires_login=True,
        ),
        # Direct global top 100 music chart (works for everyone without login)
        StreamItem(
            ITEM_LISTING,
            "https://www.youtube.com/playlist?list=PL4fGSI1pDJn6puJdseH2Rt9sMvt9E2M4i",
            _("Trending music (Top 100 songs worldwide)"),
            requires_login=False,
        ),
    ]


# ---------------------------------------------------------------------------
# yt-dlp option building
# ---------------------------------------------------------------------------

def _get_config() -> Dict[str, Any]:
    try:
        return getConfig()
    except Exception:
        return {}


def _get_js_runtimes() -> Dict[str, Dict[str, Any]]:
    bundled_qjs = os.path.join(LIB_DIR, "bin", "qjs.exe")
    if os.path.isfile(bundled_qjs):
        return {"quickjs": {"path": bundled_qjs}}
    return {}


_STANDARD_HTTP_HEADERS: Dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}


def _is_youtube_target(url: Optional[str]) -> bool:
    """
    Returns True if target URL/query is for YouTube.
    YouTube requests should never be overridden with generic browser headers
    because YouTube extractors manage their own native headers and clashing
    User-Agents trigger cookie invalidation and bot challenges.
    """
    if not url:
        return True
    u = str(url).lower().strip()
    return (
        "youtube.com" in u
        or "youtu.be" in u
        or u.startswith("ytsearch")
        or "youtubei" in u
    )


def _base_ydl_opts(use_cookies: bool = True, target_url: Optional[str] = None) -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _SilentLogger(),
        "skip_download": True,
        "socket_timeout": 15,
        "retries": 2,
        "ignoreerrors": True,
        "no_color": True,
        "js_runtimes": _get_js_runtimes(),
    }

    # Only apply standard browser headers to non-YouTube domains (such as TikTok, SoundCloud, or generic WAF sites).
    # Overriding http_headers for YouTube overrides native extractor clients and clashes with account cookies.
    if target_url and not _is_youtube_target(target_url):
        opts["http_headers"] = _STANDARD_HTTP_HEADERS

    if not use_cookies:
        opts["extractor_args"] = {
            "youtube": {
                "player_client": ["tv_embedded"]
            }
        }
        return opts

    opts["extractor_args"] = {
        "youtube": {
            "player_client": ["web"]
        }
    }

    # Sign-in cookies: a manual cookies.txt file takes priority (works even
    # when the browser blocks automatic extraction, e.g. Chrome's app-bound
    # encryption); otherwise fall back to supported browser automatic extraction.
    cookie_file = get_manual_cookies_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file
    else:
        cfg = _get_config()
        browser = str(cfg.get("ytdlpCookiesBrowser", "") or "").strip().lower()
        if browser in SUPPORTED_COOKIE_BROWSERS and browser != "none":
            opts["cookiesfrombrowser"] = (browser,)
    return opts


# ---------------------------------------------------------------------------
# Extraction API (all functions are blocking; call from worker threads)
# ---------------------------------------------------------------------------

def search_youtube(
    query: str,
    limit: Optional[int] = None,
    start_index: int = 1
) -> List[StreamItem]:
    """
    Searches YouTube and returns mixed results (videos, playlists, channels)
    supporting incremental offset pagination.
    """
    ytdlp = _get_ytdlp()

    cfg = _get_config()
    if limit is None:
        try:
            limit = int(cfg.get("searchResultsCount", 20))
        except (ValueError, TypeError):
            limit = 20
    limit = max(1, int(limit))
    start_index = max(1, int(start_index))
    end_index = start_index + limit - 1

    log_debug("YTDLP", "search_youtube start: query='%s', limit=%d, start_index=%d, end_index=%d", query, limit, start_index, end_index)
    t0 = time.time()

    url = f"ytsearch{end_index}:{query}"
    opts = _base_ydl_opts(target_url=url)
    opts.update({
        "extract_flat": True,
        "playlist_items": f"{start_index}-{end_index}",
    })
    try:
        with ytdlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        log_exception("YTDLP", f"search_youtube failed for {url}", e)
        if login_cookies_enabled():
            logger.warning("Search with cookies failed (%s); retrying without cookies", e)
            opts_no_cookies = _base_ydl_opts(use_cookies=False, target_url=url)
            opts_no_cookies.update({
                "extract_flat": True,
                "playlist_items": f"{start_index}-{end_index}",
            })
            with ytdlp.YoutubeDL(opts_no_cookies) as ydl:
                info = ydl.extract_info(url, download=False)
        else:
            raise

    items: List[StreamItem] = []
    for entry in (info or {}).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        item = StreamItem.from_flat_entry(entry)
        if item:
            items.append(item)
    t1 = time.time()
    log_debug("YTDLP", "search_youtube completed in %.2fs: returned %d items", t1 - t0, len(items))
    return items


_MIX_LIST_RE = re.compile(r"[?&]list=(RD[0-9A-Za-z_-]+)")
_VIDEO_ID_RE = re.compile(r"^[0-9A-Za-z_-]{11}$")
_MIX_PREFIXES = ("RDAMVM", "RDGMEM", "RDMM", "RDEM", "RDCM", "RD")


def _prepare_listing_url(url: str) -> str:
    """
    YouTube Mix (radio) playlists - including the account's personal
    'My Mix' - are 'unviewable' as bare playlist pages; they only
    materialize on a watch page. Rewrites playlist?list=RD... URLs into
    watch?v=<seed>&list=RD... using the seed video id embedded in the mix id.
    """
    m = _MIX_LIST_RE.search(url)
    if not m or "watch?" in url:
        return url
    list_id = m.group(1)
    # RDCLAK ids are real auto-generated chart playlists and browse normally
    if list_id.startswith("RDCLAK"):
        return url

    video_id = None
    vm = re.search(r"[?&]v=([0-9A-Za-z_-]{11})", url)
    if vm:
        video_id = vm.group(1)
    else:
        for prefix in _MIX_PREFIXES:
            if list_id.startswith(prefix):
                candidate = list_id[len(prefix):]
                if _VIDEO_ID_RE.match(candidate):
                    video_id = candidate
                break
    if not video_id:
        return url
    return f"https://www.youtube.com/watch?v={video_id}&list={list_id}"


def fetch_listing(
    url: str,
    limit: Optional[int] = None,
    start_index: int = 1
) -> Tuple[str, List[StreamItem]]:
    """
    Expands a playlist / channel / channel-tab / multi-video page into its entries
    using fast flat extraction with pagination support.

    Returns:
        (listing_title, items)
    """
    cfg = _get_config()
    if limit is None:
        try:
            limit = int(cfg.get("maxStreamPlaylistItems", 50))
        except (ValueError, TypeError):
            limit = 50
    limit = max(1, int(limit))
    start_index = max(1, int(start_index))
    end_index = start_index + limit - 1

    # Special handling for subscriptions shorts
    if url.rstrip("/") == "https://www.youtube.com/feed/subscriptions/shorts":
        scan_limit = max(start_index + limit + 100, limit * 3)
        _t, sub_items = fetch_listing("https://www.youtube.com/feed/subscriptions", limit=scan_limit, start_index=1)
        shorts = [
            it for it in sub_items
            if it.kind == ITEM_SHORTS
            or "/shorts/" in str(it.url).lower()
            or (it.duration is not None and 0 < it.duration <= 60)
            or "#short" in str(it.title).lower()
            or "#shorts" in str(it.title).lower()
        ]
        # If flat subscription feed has few shorts, aggregate latest shorts from top subscribed channels in parallel
        if len(shorts) < (start_index + limit):
            try:
                _ch_title, channels = fetch_listing("https://www.youtube.com/feed/channels", limit=20, start_index=1)
                seen_urls = {s.url for s in shorts}
                top_channels = channels[:8]

                def _fetch_single_channel_shorts(ch_item):
                    try:
                        ch_shorts_url = ch_item.url.rstrip("/") + "/shorts"
                        return fetch_listing(ch_shorts_url, limit=10, start_index=1)
                    except Exception:
                        return "", []

                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = [executor.submit(_fetch_single_channel_shorts, ch) for ch in top_channels]
                    for fut in as_completed(futures, timeout=5.0):
                        try:
                            _sub_t, ch_items = fut.result()
                            for item in ch_items:
                                if item.url not in seen_urls:
                                    seen_urls.add(item.url)
                                    shorts.append(item)
                        except Exception:
                            pass
            except Exception as ex:
                logger.debug("Failed to aggregate channel shorts: %s", ex)

        sliced_shorts = shorts[start_index - 1 : end_index]
        return _("Shorts from your subscriptions"), sliced_shorts

    ytdlp = _get_ytdlp()

    url = _prepare_listing_url(url)
    opts = _base_ydl_opts(target_url=url)
    opts.update({
        "extract_flat": True,
        "playlist_items": f"{start_index}-{end_index}",
    })
    try:
        with ytdlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        is_private = any(p in url for p in [
            "/feed/subscriptions",
            "/feed/channels",
            "/feed/recommended",
            "/feed/history",
            "/feed/library",
            "playlist?list=WL",
            "playlist?list=LL",
        ])
        if not is_private and login_cookies_enabled():
            logger.warning("Listing fetch with cookies failed (%s); retrying without cookies", e)
            opts_no_cookies = _base_ydl_opts(use_cookies=False, target_url=url)
            opts_no_cookies.update({
                "extract_flat": True,
                "playlist_items": f"{start_index}-{end_index}",
            })
            with ytdlp.YoutubeDL(opts_no_cookies) as ydl:
                info = ydl.extract_info(url, download=False)
        else:
            raise

    if not info:
        return "", []

    title = str(info.get("title") or "")
    entries = info.get("entries")
    items: List[StreamItem] = []
    if entries is None:
        item = StreamItem.from_flat_entry(info)
        if item:
            items.append(item)
    else:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item = StreamItem.from_flat_entry(entry)
            if item:
                items.append(item)
    return title, items


def probe_url(url: str, limit: int = 300) -> Tuple[str, List[StreamItem], bool]:
    """
    Probes an arbitrary URL (YouTube or any other supported site).

    Returns:
        (title, items, is_multi):
        is_multi is True when the URL expanded to a multi-entry listing
        (playlist / channel / site section); items then holds the entries.
        When False, items holds a single playable StreamItem for the URL.
    """
    title, items = fetch_listing(url, limit=limit)
    if len(items) > 1:
        return title, items, True
    if len(items) == 1 and items[0].kind != ITEM_VIDEO:
        # Single non-video entry (e.g. a playlist wrapped once) - expand again
        sub_title, sub_items = fetch_listing(items[0].url, limit=limit)
        if sub_items:
            return sub_title or items[0].title, sub_items, len(sub_items) > 1
    if items:
        return title, items, False
    # Nothing extracted flat; treat the raw URL as a single playable item
    return title, [StreamItem(kind=ITEM_VIDEO, url=url, title=title or url)], False


# ---------------------------------------------------------------------------
# Direct stream resolution (audio-first) with a short-lived cache
# ---------------------------------------------------------------------------

_resolve_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_resolve_cache_lock = threading.Lock()
_RESOLVE_CACHE_TTL = 20 * 60  # 20 minutes; googlevideo URLs expire in ~6h but stay safe


def resolve_stream(url: str, prefer_audio: bool = True) -> Dict[str, Any]:
    """
    Resolves a media page URL into a direct playable stream URL.
    Prefers audio-only streams; falls back to combined audio+video streams
    (played invisibly by the headless mpv, exactly like local video files).

    Returns dict with keys:
        stream_url, http_headers, title, duration, is_live, webpage_url
    Raises RuntimeError on failure.
    """
    ytdlp = _get_ytdlp()

    try:
        cfg = getConfig()
        quality = str(cfg.get("streamAudioQuality", "high")).lower()
    except Exception:
        quality = "high"

    cache_key = f"{url}::audio={prefer_audio}::quality={quality}"
    now = time.time()
    with _resolve_cache_lock:
        cached = _resolve_cache.get(cache_key)
        if cached and (now - cached[0]) < _RESOLVE_CACHE_TTL:
            return dict(cached[1])

    def _extract(use_cookies: bool):
        opts = _base_ydl_opts(use_cookies=use_cookies, target_url=url)
        if quality == "low":
            # Low: 64k data saver (prioritizes low bitrate ~64 kbps Opus/AAC streams)
            format_selector = (
                "bestaudio[abr<=70]/"
                "bestaudio[ext=webm][abr<=70]/"
                "bestaudio[abr<=96]/"
                "bestaudio/"
                "best[height<=360][acodec!=none]/"
                "best[acodec!=none]/"
                "best"
            )
        elif quality == "medium":
            # Medium: AAC 128k (standard fidelity, format 140 m4a / 128 kbps)
            format_selector = (
                "bestaudio[acodec^=mp4a][abr<=140]/"
                "bestaudio[ext=m4a]/"
                "bestaudio[abr<=140]/"
                "bestaudio/"
                "best[height<=480][acodec!=none]/"
                "best[acodec!=none]/"
                "best"
            )
        else:
            # High: Opus 160k (highest audio fidelity, format 251 Opus / 160 kbps)
            format_selector = (
                "bestaudio[acodec=opus][abr>=150]/"
                "bestaudio[abr>=150]/"
                "bestaudio/"
                "best[height<=480][acodec!=none]/"
                "best[acodec!=none]/"
                "best"
            )
        opts.update({
            "noplaylist": True,
            "format": format_selector if prefer_audio else "best",
            "ignoreerrors": False,
        })
        with ytdlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    # Playback extraction runs WITHOUT sign-in cookies first: logged-in
    # sessions produce googlevideo URLs that are PO-token-bound and return
    # 403 to external players like mpv, while anonymous URLs stream fine.
    # Cookies are still used for browsing (search / feeds / playlists), and
    # as a fallback here for age-restricted or members-only content.
    info = None
    first_error: Optional[Exception] = None
    try:
        info = _extract(use_cookies=False)
    except Exception as e:
        first_error = e

    if not info and login_cookies_enabled():
        logger.info("Anonymous extraction failed for %s; retrying with sign-in cookies", url)
        try:
            info = _extract(use_cookies=True)
        except Exception as e:
            raise first_error or e

    if not info:
        if first_error:
            raise first_error
        raise RuntimeError("Extraction returned no result")
    # If a playlist sneaked through, take the first entry
    if info.get("_type") == "playlist" and info.get("entries"):
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise RuntimeError("Empty playlist result")
        info = entries[0]

    stream_url = info.get("url")
    if not stream_url and info.get("requested_formats"):
        # Split A/V formats: pick the audio one if present
        fmts = info["requested_formats"]
        audio = next((f for f in fmts if f.get("acodec") not in (None, "none")), None)
        chosen = audio or fmts[0]
        stream_url = chosen.get("url")
        info = {**info, "http_headers": chosen.get("http_headers") or info.get("http_headers")}
    if not stream_url:
        raise RuntimeError("No playable stream URL found")

    dur = info.get("duration")
    try:
        dur = float(dur) if dur is not None else 0.0
    except (TypeError, ValueError):
        dur = 0.0

    raw_chapters = info.get("chapters") or []
    parsed_chapters = []
    for i, ch in enumerate(raw_chapters):
        if isinstance(ch, dict) and ch.get("start_time") is not None:
            try:
                st = float(ch["start_time"])
                et = float(ch["end_time"]) if ch.get("end_time") is not None else None
                title = str(ch.get("title") or f"Chapter {i+1}")
                parsed_chapters.append({
                    "title": title,
                    "start_time": st,
                    "end_time": et,
                })
            except (TypeError, ValueError):
                pass

    if not parsed_chapters:
        desc = str(info.get("description") or "")
        lines = desc.splitlines()
        ts_re = re.compile(r"(?:^|\s)(?:(?:(\d{1,2}):)?(\d{1,2}):(\d{2}))\s*[-–—:]?\s*(.+)$")
        for line in lines:
            m = ts_re.search(line.strip())
            if m:
                h_str, m_str, s_str, t_str = m.groups()
                hrs = int(h_str) if h_str else 0
                mins = int(m_str)
                secs = int(s_str)
                total_sec = float(hrs * 3600 + mins * 60 + secs)
                t_clean = t_str.strip().strip("-–—:[]()")
                if t_clean:
                    parsed_chapters.append({
                        "title": t_clean,
                        "start_time": total_sec,
                        "end_time": None,
                    })

    if parsed_chapters:
        parsed_chapters.sort(key=lambda c: c.get("start_time", 0.0))
        for idx in range(len(parsed_chapters)):
            if idx + 1 < len(parsed_chapters):
                parsed_chapters[idx]["end_time"] = parsed_chapters[idx + 1]["start_time"]
            elif dur > 0:
                parsed_chapters[idx]["end_time"] = dur

    # Extract all distinct multi-language audio tracks (e.g. YouTube multi-language audio)
    available_audio_tracks = []
    seen_langs = {}
    for f in info.get("formats", []):
        if not isinstance(f, dict):
            continue
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none"):
            lang = f.get("language") or f.get("language_preference") or "default"
            abr = f.get("abr") or f.get("tbr") or 0
            if lang not in seen_langs or abr > (seen_langs[lang].get("abr") or 0):
                seen_langs[lang] = f

    if len(seen_langs) > 1:
        for lang, f in seen_langs.items():
            f_url = f.get("url")
            if f_url:
                note = f.get("format_note") or ""
                title = note if note else str(lang)
                available_audio_tracks.append({
                    "url": f_url,
                    "lang": str(lang),
                    "title": title,
                    "http_headers": dict(f.get("http_headers") or info.get("http_headers") or {}),
                })
        # Keep currently resolved audio stream at index 0 if present
        for i, t in enumerate(available_audio_tracks):
            if t.get("url") == stream_url:
                if i > 0:
                    available_audio_tracks.insert(0, available_audio_tracks.pop(i))
                break

    # Extract distinct video formats and quality options (1080p, 720p, etc.)
    video_options: List[Tuple[str, str, int, bool]] = []
    seen_vqs = set()
    v_fmts = [
        f for f in info.get("formats", [])
        if isinstance(f, dict) and f.get("vcodec") not in (None, "none") and f.get("url") and (f.get("height") or 0) > 0
    ]
    v_fmts.sort(
        key=lambda f: (
            int(f.get("height") or 0),
            1 if "avc" in str(f.get("vcodec") or "").lower() or f.get("ext") == "mp4" else 0,
            int(f.get("tbr") or f.get("vbr") or 0)
        ),
        reverse=True
    )
    for f in v_fmts:
        h = int(f.get("height") or 0)
        note = str(f.get("format_note") or f"{h}p")
        label = note if ("p" in note or "k" in note.lower()) else f"{h}p"
        has_audio = f.get("acodec") not in (None, "none")
        if has_audio:
            label = f"{label} (video with audio)"
        if label not in seen_vqs:
            seen_vqs.add(label)
            video_options.append((label, str(f["url"]), h, has_audio))

    has_video = bool(video_options)

    headers = dict(info.get("http_headers") or {})
    low_url = url.lower()
    low_stream = str(stream_url).lower()
    if "tiktok.com" in low_url or "byteoversea" in low_stream or "ibyteimg" in low_stream or "tiktokcdn" in low_stream:
        if "Referer" not in headers:
            headers["Referer"] = "https://www.tiktok.com/"
        if "User-Agent" not in headers:
            headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

    result = {
        "stream_url": str(stream_url),
        "http_headers": headers,
        "title": str(info.get("title") or ""),
        "duration": dur,
        "is_live": bool(info.get("is_live")),
        "webpage_url": str(info.get("webpage_url") or url),
        "chapters": parsed_chapters,
        "audio_tracks": available_audio_tracks,
        "has_video": has_video,
        "video_options": video_options,
    }

    with _resolve_cache_lock:
        # Live stream manifests should not be cached for long
        ttl_entry = (now if not result["is_live"] else now - _RESOLVE_CACHE_TTL + 60, result)
        _resolve_cache[url] = ttl_entry
        if len(_resolve_cache) > 64:
            oldest = sorted(_resolve_cache.items(), key=lambda kv: kv[1][0])
            for k, _v in oldest[: len(_resolve_cache) - 64]:
                _resolve_cache.pop(k, None)

    return dict(result)


def clear_resolve_cache() -> None:
    with _resolve_cache_lock:
        _resolve_cache.clear()


# ---------------------------------------------------------------------------
# yt-dlp self-update and multi-channel management (Stable / Nightly / Master)
# ---------------------------------------------------------------------------

_PYPI_JSON_URL = "https://pypi.org/pypi/yt-dlp/json"
_GITHUB_NIGHTLY_API_URL = "https://api.github.com/repos/yt-dlp/yt-dlp-nightly-builds/releases/latest"
_GITHUB_MASTER_API_URL = "https://api.github.com/repos/yt-dlp/yt-dlp-master-builds/releases/latest"

YTDLP_CHANNELS = {
    "stable": "Stable (PyPI)",
    "nightly": "Nightly (Daily YouTube Fixes)",
    "master": "Master (Development)",
}

BUNDLED_BACKUP_DIR = os.path.join(LIB_DIR, "yt_dlp_bundled")
PREVIOUS_BACKUP_DIR = os.path.join(LIB_DIR, "yt_dlp_previous")
META_FILE = os.path.join(LIB_DIR, "yt_dlp_meta.json")

_update_lock = threading.Lock()


def _version_tuple(ver: str) -> Tuple[int, ...]:
    parts = []
    for p in str(ver).split("."):
        digits = re.sub(r"\D", "", p)
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _load_meta() -> Dict[str, Any]:
    if os.path.isfile(META_FILE):
        try:
            with open(META_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {
        "installed_version": get_bundled_version(),
        "installed_channel": "stable",
        "previous_version": "",
        "previous_channel": "",
        "updated_at": "",
    }


def _save_meta(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(LIB_DIR, exist_ok=True)
        with open(META_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("Failed to save yt-dlp metadata: %s", e)


def ensure_bundled_snapshot() -> None:
    """
    Ensures that a pristine factory backup copy of yt_dlp exists in LIB_DIR/yt_dlp_bundled.
    This creates an immutable snapshot of the version originally shipped with the addon.
    """
    target_pkg = os.path.join(LIB_DIR, "yt_dlp")
    if os.path.isdir(target_pkg) and not os.path.isdir(BUNDLED_BACKUP_DIR):
        try:
            shutil.copytree(target_pkg, BUNDLED_BACKUP_DIR, dirs_exist_ok=True)
            logger.info("Created pristine factory snapshot of yt-dlp in %s", BUNDLED_BACKUP_DIR)
        except Exception as e:
            logger.warning("Could not create bundled snapshot: %s", e)


def can_rollback() -> bool:
    """Returns True if a valid previous version backup exists."""
    prev_ver_file = os.path.join(PREVIOUS_BACKUP_DIR, "version.py")
    return os.path.isfile(prev_ver_file)


def can_reset_bundled() -> bool:
    """Returns True if factory bundled backup exists."""
    bundled_ver_file = os.path.join(BUNDLED_BACKUP_DIR, "version.py")
    return os.path.isfile(bundled_ver_file)


def get_channel_info() -> Dict[str, Any]:
    """Returns metadata about current, previous, and bundled versions."""
    meta = _load_meta()
    installed_ver = get_bundled_version()
    prev_ver = get_installed_version(PREVIOUS_BACKUP_DIR) if can_rollback() else ""
    bundled_ver = get_installed_version(BUNDLED_BACKUP_DIR) if can_reset_bundled() else ""
    return {
        "installed_version": installed_ver or meta.get("installed_version", ""),
        "installed_channel": meta.get("installed_channel", "stable"),
        "previous_version": prev_ver or meta.get("previous_version", ""),
        "previous_channel": meta.get("previous_channel", ""),
        "bundled_version": bundled_ver,
        "can_rollback": can_rollback(),
        "can_reset_bundled": can_reset_bundled(),
    }


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
        # 1. Prefer .whl
        for asset in assets:
            name = str(asset.get("name", ""))
            if name.endswith("py3-none-any.whl") or (name.endswith(".whl") and "yt_dlp" in name):
                archive_url = str(asset.get("browser_download_url", ""))
                break
        # 2. Prefer yt-dlp.tar.gz or any .tar.gz archive
        if not archive_url:
            for asset in assets:
                name = str(asset.get("name", ""))
                if name == "yt-dlp.tar.gz" or name.endswith(".tar.gz") or name.endswith(".tgz"):
                    archive_url = str(asset.get("browser_download_url", ""))
                    break
        # 3. Prefer any .zip archive
        if not archive_url:
            for asset in assets:
                name = str(asset.get("name", ""))
                if name.endswith(".zip") and not name.endswith(".exe"):
                    archive_url = str(asset.get("browser_download_url", ""))
                    break
        # 4. Fallback to GitHub tarball or zipball
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
            latest, download_url = check_latest_version(channel=channel)
        except Exception as e:
            return False, f"error:network:{e}"

        if not download_url:
            return False, "error:no-download-url"

        # If staying on the same channel and version <= current, it is already up to date
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
            # 1. Try zipfile (for .whl or .zip)
            if zipfile.is_zipfile(archive_path):
                try:
                    with zipfile.ZipFile(archive_path) as zf:
                        zf.extractall(extract_dir)
                    extracted = True
                except Exception as e:
                    logger.debug("Zipfile extraction failed: %s", e)

            # 2. Try tarfile (for .tar.gz, .tgz, .tar, etc.)
            if not extracted:
                try:
                    with tarfile.open(archive_path, "r:*") as tf:
                        tf.extractall(extract_dir)
                    extracted = True
                except Exception as e:
                    logger.debug("Tarfile extraction failed: %s", e)

            if not extracted:
                return False, "error:bad-archive"

            # Locate the package directory named 'yt_dlp' inside extracted contents
            new_pkg = None
            for root, dirs, files in os.walk(extract_dir):
                if os.path.basename(root) == "yt_dlp" and ("version.py" in files or "__init__.py" in files):
                    new_pkg = root
                    break

            if not new_pkg or not os.path.isdir(new_pkg):
                return False, "error:bad-package-contents"

            target_pkg = os.path.join(LIB_DIR, "yt_dlp")
            os.makedirs(LIB_DIR, exist_ok=True)

            # Move current package to PREVIOUS_BACKUP_DIR
            if os.path.isdir(target_pkg):
                if os.path.isdir(PREVIOUS_BACKUP_DIR):
                    shutil.rmtree(PREVIOUS_BACKUP_DIR, ignore_errors=True)
                try:
                    os.rename(target_pkg, PREVIOUS_BACKUP_DIR)
                except OSError:
                    shutil.copytree(target_pkg, PREVIOUS_BACKUP_DIR, dirs_exist_ok=True)
                    shutil.rmtree(target_pkg, ignore_errors=True)

            try:
                if not os.path.isdir(target_pkg):
                    shutil.move(new_pkg, target_pkg)
                else:
                    for root, _dirs, files in os.walk(new_pkg):
                        rel = os.path.relpath(root, new_pkg)
                        dest_root = os.path.join(target_pkg, rel) if rel != "." else target_pkg
                        os.makedirs(dest_root, exist_ok=True)
                        for f in files:
                            shutil.copy2(os.path.join(root, f), os.path.join(dest_root, f))
            except Exception as e:
                # Attempt rollback on install failure
                if os.path.isdir(PREVIOUS_BACKUP_DIR) and not os.path.isdir(target_pkg):
                    try:
                        os.rename(PREVIOUS_BACKUP_DIR, target_pkg)
                    except OSError:
                        pass
                return False, f"error:install:{e}"

            # Remove stale pycache
            for root, dirs, _files in os.walk(target_pkg):
                for d in list(dirs):
                    if d == "__pycache__":
                        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                        dirs.remove(d)

            new_installed_ver = get_installed_version(target_pkg) or latest
            meta["previous_version"] = current
            meta["previous_channel"] = current_channel
            meta["installed_version"] = new_installed_ver
            meta["installed_channel"] = channel
            meta["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save_meta(meta)

            logger.info("yt-dlp updated from %s (%s) to %s (%s)", current or "?", current_channel, new_installed_ver, channel)

            try:
                _update_ejs_package(tmp_dir)
            except Exception as e:
                logger.warning("yt-dlp-ejs update failed (non-fatal): %s", e)

            return True, f"updated:{new_installed_ver}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def rollback_ytdlp() -> Tuple[bool, str]:
    """
    Rolls back the current yt-dlp installation to the previous version in lib/yt_dlp_previous.
    Returns (success, message).
    """
    with _update_lock:
        if not can_rollback():
            return False, "error:no_backup"

        target_pkg = os.path.join(LIB_DIR, "yt_dlp")
        meta = _load_meta()
        prev_ver = get_installed_version(PREVIOUS_BACKUP_DIR) or meta.get("previous_version", "")
        prev_channel = meta.get("previous_channel", "stable")
        cur_ver = get_bundled_version()
        cur_channel = meta.get("installed_channel", "stable")

        tmp_swap = os.path.join(LIB_DIR, f"yt_dlp_swap_{int(time.time())}")
        try:
            if os.path.isdir(target_pkg):
                os.rename(target_pkg, tmp_swap)
            os.rename(PREVIOUS_BACKUP_DIR, target_pkg)
            if os.path.isdir(tmp_swap):
                os.rename(tmp_swap, PREVIOUS_BACKUP_DIR)
        except Exception:
            try:
                shutil.rmtree(target_pkg, ignore_errors=True)
                shutil.copytree(PREVIOUS_BACKUP_DIR, target_pkg, dirs_exist_ok=True)
            except Exception as e:
                return False, f"error:rollback_failed:{e}"
            finally:
                if os.path.isdir(tmp_swap):
                    shutil.rmtree(tmp_swap, ignore_errors=True)

        meta["installed_version"] = prev_ver
        meta["installed_channel"] = prev_channel
        meta["previous_version"] = cur_ver
        meta["previous_channel"] = cur_channel
        meta["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_meta(meta)

        logger.info("yt-dlp rolled back to %s (%s)", prev_ver, prev_channel)
        return True, f"rolled_back:{prev_ver}"


def reset_to_bundled_ytdlp() -> Tuple[bool, str]:
    """
    Restores the factory bundled baseline version of yt-dlp from lib/yt_dlp_bundled.
    Returns (success, message).
    """
    with _update_lock:
        if not can_reset_bundled():
            return False, "error:no_bundled"

        target_pkg = os.path.join(LIB_DIR, "yt_dlp")
        meta = _load_meta()
        bundled_ver = get_installed_version(BUNDLED_BACKUP_DIR)
        cur_ver = get_bundled_version()
        cur_channel = meta.get("installed_channel", "stable")

        if os.path.isdir(target_pkg):
            shutil.rmtree(PREVIOUS_BACKUP_DIR, ignore_errors=True)
            try:
                shutil.copytree(target_pkg, PREVIOUS_BACKUP_DIR, dirs_exist_ok=True)
            except Exception:
                pass

        try:
            shutil.rmtree(target_pkg, ignore_errors=True)
            shutil.copytree(BUNDLED_BACKUP_DIR, target_pkg, dirs_exist_ok=True)
        except Exception as e:
            return False, f"error:reset_failed:{e}"

        meta["installed_version"] = bundled_ver
        meta["installed_channel"] = "stable"
        meta["previous_version"] = cur_ver
        meta["previous_channel"] = cur_channel
        meta["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_meta(meta)

        logger.info("yt-dlp reset to bundled baseline version %s", bundled_ver)
        return True, f"reset_bundled:{bundled_ver}"


def _update_ejs_package(tmp_dir: str) -> None:
    """Downloads the latest yt-dlp-ejs solver package into the lib directory."""
    req = urllib.request.Request(
        "https://pypi.org/pypi/yt-dlp-ejs/json",
        headers={"User-Agent": "HeadlessPlayer-NVDA-Addon"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    latest = str(data.get("info", {}).get("version", ""))
    wheel_url = ""
    for f in data.get("releases", {}).get(latest, []):
        if str(f.get("filename", "")).endswith(".whl"):
            wheel_url = str(f.get("url", ""))
            break
    if not wheel_url:
        return

    wheel_path = os.path.join(tmp_dir, "yt_dlp_ejs.whl")
    req = urllib.request.Request(wheel_url, headers={"User-Agent": "HeadlessPlayer-NVDA-Addon"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(wheel_path, "wb") as fh:
        shutil.copyfileobj(resp, fh)

    extract_dir = os.path.join(tmp_dir, "ejs_extracted")
    with zipfile.ZipFile(wheel_path) as zf:
        members = [m for m in zf.namelist() if m.startswith("yt_dlp_ejs/")]
        if not members:
            return
        zf.extractall(extract_dir, members=members)

    new_pkg = os.path.join(extract_dir, "yt_dlp_ejs")
    target_pkg = os.path.join(LIB_DIR, "yt_dlp_ejs")
    old_pkg = os.path.join(LIB_DIR, f"yt_dlp_ejs_old_{int(time.time())}")
    if os.path.isdir(target_pkg):
        try:
            os.rename(target_pkg, old_pkg)
        except OSError:
            old_pkg = ""
    shutil.move(new_pkg, target_pkg)
    if old_pkg and os.path.isdir(old_pkg):
        shutil.rmtree(old_pkg, ignore_errors=True)
    logger.info("yt-dlp-ejs updated to %s", latest)

