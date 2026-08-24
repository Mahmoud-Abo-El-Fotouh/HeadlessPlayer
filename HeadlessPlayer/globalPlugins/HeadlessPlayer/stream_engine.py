# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Online Streaming Engine (yt-dlp backend).
Provides YouTube search, playlist/channel listing expansion, direct audio
stream URL resolution for YouTube and 1800+ other sites via the bundled
yt-dlp library, plus a self-update mechanism from PyPI.
"""

from __future__ import annotations
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Callable, Dict, List, Optional, Tuple

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


def get_bundled_version() -> str:
    """
    Returns the version string of the bundled yt-dlp without importing it
    (reads lib/yt_dlp/version.py textually), or empty string.
    """
    ver_file = os.path.join(LIB_DIR, "yt_dlp", "version.py")
    try:
        with open(ver_file, "r", encoding="utf-8") as fh:
            content = fh.read()
        m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", content)
        if m:
            return m.group(1)
    except OSError:
        pass
    return ""


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

_URL_RE = re.compile(r"^(https?://|www\.)", re.IGNORECASE)

_YOUTUBE_HOST_RE = re.compile(
    r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)(/|$)",
    re.IGNORECASE,
)


def is_url(text: str) -> bool:
    """True if the given text looks like a web URL rather than a search query."""
    if not text or not isinstance(text, str):
        return False
    return bool(_URL_RE.match(text.strip()))


def normalize_url(text: str) -> str:
    """Ensures the URL has an explicit scheme."""
    t = text.strip()
    if t.lower().startswith("www."):
        return "https://" + t
    return t


def is_youtube_url(url: str) -> bool:
    return bool(_YOUTUBE_HOST_RE.match(url.strip()))


ITEM_VIDEO = "video"
ITEM_PLAYLIST = "playlist"
ITEM_CHANNEL = "channel"
ITEM_LISTING = "listing"  # synthetic channel sub-listing (Videos / Playlists / Live)


def classify_flat_entry(entry: Dict[str, Any]) -> str:
    """Classifies a flat-extracted yt-dlp entry as video, playlist, or channel."""
    url = str(entry.get("url") or entry.get("webpage_url") or "")
    ie_key = str(entry.get("ie_key") or "")
    etype = str(entry.get("_type") or "")

    low = url.lower()
    if "playlist?list=" in low or ie_key in ("YoutubePlaylist",):
        return ITEM_PLAYLIST
    if ie_key == "YoutubeTab" or etype in ("playlist", "multi_video"):
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
        url = entry.get("url") or entry.get("webpage_url")
        if not url:
            return None
        kind = classify_flat_entry(entry)
        dur = entry.get("duration")
        try:
            dur = float(dur) if dur is not None else None
        except (TypeError, ValueError):
            dur = None
        live_status = entry.get("live_status")
        return cls(
            kind=kind,
            url=str(url),
            title=str(entry.get("title") or ""),
            duration=dur,
            uploader=str(entry.get("channel") or entry.get("uploader") or ""),
            is_live=(live_status == "is_live" or bool(entry.get("is_live"))),
        )


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
    file, or a browser selected for automatic cookie extraction.
    """
    if get_manual_cookies_file():
        return True
    cfg = _get_config()
    browser = str(cfg.get("ytdlpCookiesBrowser", "") or "").strip().lower()
    return bool(browser and browser != "none")


def is_cookie_error(error_text: str) -> bool:
    """
    Detects browser-cookie extraction failures (e.g. Chrome's app-bound
    encryption blocking DPAPI decryption) so the user gets accurate advice.
    """
    low = str(error_text).lower()
    return "cookie" in low or "dpapi" in low or "decrypt" in low


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
        from .config_spec import getConfig
        return getConfig()
    except Exception:
        return {}


def _get_js_runtimes() -> Dict[str, Dict[str, Any]]:
    """
    Enables every JavaScript runtime yt-dlp can use for YouTube's JS
    challenges (required for logged-in cookies and many formats):
    Deno / Node / Bun when installed on the system, plus the tiny QuickJS
    binary bundled with the add-on as a guaranteed fallback.
    """
    runtimes: Dict[str, Dict[str, Any]] = {"deno": {}, "node": {}, "bun": {}}
    bundled_qjs = os.path.join(LIB_DIR, "bin", "qjs.exe")
    if os.path.isfile(bundled_qjs):
        runtimes["quickjs"] = {"path": bundled_qjs}
    else:
        runtimes["quickjs"] = {}
    return runtimes


def _base_ydl_opts(use_cookies: bool = True) -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _SilentLogger(),
        "skip_download": True,
        "socket_timeout": 20,
        "retries": 2,
        "ignoreerrors": True,
        "no_color": True,
        "js_runtimes": _get_js_runtimes(),
    }
    if not use_cookies:
        return opts
    # Sign-in cookies: a manual cookies.txt file takes priority (works even
    # when the browser blocks automatic extraction, e.g. Chrome's app-bound
    # encryption); otherwise fall back to automatic browser extraction.
    cookie_file = get_manual_cookies_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file
    else:
        cfg = _get_config()
        browser = str(cfg.get("ytdlpCookiesBrowser", "") or "").strip().lower()
        if browser and browser != "none":
            opts["cookiesfrombrowser"] = (browser,)
    return opts


# ---------------------------------------------------------------------------
# Extraction API (all functions are blocking; call from worker threads)
# ---------------------------------------------------------------------------

def search_youtube(query: str, limit: int = 20) -> List[StreamItem]:
    """
    Searches YouTube and returns mixed results (videos, playlists, channels).
    """
    ytdlp = _get_ytdlp()

    limit = max(1, min(50, int(limit)))
    opts = _base_ydl_opts()
    opts.update({
        "extract_flat": True,
        "playlist_items": f"1-{limit}",
    })
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    try:
        with ytdlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        if login_cookies_enabled():
            logger.warning("Search with cookies failed (%s); retrying without cookies", e)
            opts_no_cookies = _base_ydl_opts(use_cookies=False)
            opts_no_cookies.update({
                "extract_flat": True,
                "playlist_items": f"1-{limit}",
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


def fetch_listing(url: str, limit: int = 300) -> Tuple[str, List[StreamItem]]:
    """
    Expands a playlist / channel / channel-tab / multi-video page into its entries
    using fast flat extraction.

    Returns:
        (listing_title, items)
    """
    ytdlp = _get_ytdlp()

    url = _prepare_listing_url(url)
    limit = max(1, int(limit))
    opts = _base_ydl_opts()
    opts.update({
        "extract_flat": True,
        "playlist_items": f"1-{limit}",
    })
    try:
        with ytdlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        is_private = any(p in url for p in ["/feed/subscriptions", "/feed/channels", "playlist?list=WL", "playlist?list=LL", "/feed/history"])
        if not is_private and login_cookies_enabled():
            logger.warning("Listing fetch with cookies failed (%s); retrying without cookies", e)
            opts_no_cookies = _base_ydl_opts(use_cookies=False)
            opts_no_cookies.update({
                "extract_flat": True,
                "playlist_items": f"1-{limit}",
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
        # Single item page
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

    now = time.time()
    with _resolve_cache_lock:
        cached = _resolve_cache.get(url)
        if cached and (now - cached[0]) < _RESOLVE_CACHE_TTL:
            return dict(cached[1])

    def _extract(use_cookies: bool):
        opts = _base_ydl_opts(use_cookies=use_cookies)
        opts.update({
            "noplaylist": True,
            "format": "bestaudio/best" if prefer_audio else "best",
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

    # Extract all distinct multi-language audio tracks (e.g. YouTube multi-language audio)
    available_audio_tracks = []
    seen_langs = {}
    for f in info.get("formats", []):
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none"):
            lang = f.get("language") or f.get("language_preference") or "default"
            abr = f.get("abr") or f.get("tbr") or 0
            if lang not in seen_langs or abr > (seen_langs[lang].get("abr") or 0):
                seen_langs[lang] = f

    if len(seen_langs) > 1:
        for lang, f in seen_langs.items():
            f_url = f.get("url")
            if f_url:
                available_audio_tracks.append({
                    "url": f_url,
                    "lang": str(lang),
                    "title": str(f.get("format_note") or f.get("language") or lang),
                    "http_headers": dict(f.get("http_headers") or info.get("http_headers") or {}),
                })

    result = {
        "stream_url": str(stream_url),
        "http_headers": dict(info.get("http_headers") or {}),
        "title": str(info.get("title") or ""),
        "duration": dur,
        "is_live": bool(info.get("is_live")),
        "webpage_url": str(info.get("webpage_url") or url),
        "chapters": parsed_chapters,
        "audio_tracks": available_audio_tracks,
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
# yt-dlp self-update from PyPI
# ---------------------------------------------------------------------------

_PYPI_JSON_URL = "https://pypi.org/pypi/yt-dlp/json"
_update_lock = threading.Lock()


def _version_tuple(ver: str) -> Tuple[int, ...]:
    parts = []
    for p in str(ver).split("."):
        digits = re.sub(r"\D", "", p)
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_latest_version(timeout: float = 15.0) -> Tuple[str, str]:
    """
    Queries PyPI for the newest yt-dlp release.

    Returns:
        (latest_version, wheel_download_url)
    """
    req = urllib.request.Request(
        _PYPI_JSON_URL,
        headers={"User-Agent": "HeadlessPlayer-NVDA-Addon"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    latest = str(data["info"]["version"])
    wheel_url = ""
    for f in data["releases"].get(latest, []):
        if str(f.get("filename", "")).endswith("py3-none-any.whl"):
            wheel_url = str(f["url"])
            break
    if not wheel_url:
        for f in data.get("urls", []):
            if str(f.get("filename", "")).endswith(".whl"):
                wheel_url = str(f["url"])
                break
    return latest, wheel_url


def update_ytdlp(progress_cb: Optional[Callable[[str], None]] = None) -> Tuple[bool, str]:
    """
    Checks PyPI and, if a newer yt-dlp exists, downloads and installs it into
    the add-on's lib directory. NVDA must be restarted to load the new version.

    Returns:
        (updated, message)
    """
    def report(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    with _update_lock:
        current = get_bundled_version()
        report("checking")
        try:
            latest, wheel_url = check_latest_version()
        except Exception as e:
            return False, f"error:network:{e}"

        if not wheel_url:
            return False, "error:no-wheel"

        if current and _version_tuple(latest) <= _version_tuple(current):
            return False, f"up-to-date:{current}"

        report("downloading")
        tmp_dir = tempfile.mkdtemp(prefix="hp_ytdlp_")
        try:
            wheel_path = os.path.join(tmp_dir, "yt_dlp.whl")
            req = urllib.request.Request(
                wheel_url,
                headers={"User-Agent": "HeadlessPlayer-NVDA-Addon"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp, open(wheel_path, "wb") as fh:
                shutil.copyfileobj(resp, fh)

            report("installing")
            extract_dir = os.path.join(tmp_dir, "extracted")
            with zipfile.ZipFile(wheel_path) as zf:
                members = [m for m in zf.namelist() if m.startswith("yt_dlp/")]
                if not members:
                    return False, "error:bad-wheel"
                zf.extractall(extract_dir, members=members)

            new_pkg = os.path.join(extract_dir, "yt_dlp")
            target_pkg = os.path.join(LIB_DIR, "yt_dlp")
            backup_pkg = os.path.join(LIB_DIR, f"yt_dlp_old_{int(time.time())}")

            os.makedirs(LIB_DIR, exist_ok=True)

            # Clean any stale backups from previous updates
            for name in os.listdir(LIB_DIR):
                if name.startswith("yt_dlp_old_"):
                    shutil.rmtree(os.path.join(LIB_DIR, name), ignore_errors=True)

            moved_old = False
            if os.path.isdir(target_pkg):
                try:
                    os.rename(target_pkg, backup_pkg)
                    moved_old = True
                except OSError:
                    # Directory busy: fall back to overwrite-in-place
                    pass

            try:
                if moved_old or not os.path.isdir(target_pkg):
                    shutil.move(new_pkg, target_pkg)
                else:
                    # Overwrite files in place
                    for root, _dirs, files in os.walk(new_pkg):
                        rel = os.path.relpath(root, new_pkg)
                        dest_root = os.path.join(target_pkg, rel) if rel != "." else target_pkg
                        os.makedirs(dest_root, exist_ok=True)
                        for f in files:
                            shutil.copy2(os.path.join(root, f), os.path.join(dest_root, f))
            except Exception as e:
                # Attempt rollback
                if moved_old and not os.path.isdir(target_pkg):
                    try:
                        os.rename(backup_pkg, target_pkg)
                    except OSError:
                        pass
                return False, f"error:install:{e}"

            if moved_old:
                shutil.rmtree(backup_pkg, ignore_errors=True)

            # Remove stale compiled caches so the new version loads cleanly
            for root, dirs, _files in os.walk(target_pkg):
                for d in list(dirs):
                    if d == "__pycache__":
                        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                        dirs.remove(d)

            logger.info("yt-dlp updated from %s to %s", current or "?", latest)

            # Also refresh the companion JS challenge solver package
            # (yt-dlp-ejs); new yt-dlp releases expect matching solver scripts.
            try:
                _update_ejs_package(tmp_dir)
            except Exception as e:
                logger.warning("yt-dlp-ejs update failed (non-fatal): %s", e)

            return True, f"updated:{latest}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _update_ejs_package(tmp_dir: str) -> None:
    """Downloads the latest yt-dlp-ejs solver package into the lib directory."""
    req = urllib.request.Request(
        "https://pypi.org/pypi/yt-dlp-ejs/json",
        headers={"User-Agent": "HeadlessPlayer-NVDA-Addon"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    latest = str(data["info"]["version"])
    wheel_url = ""
    for f in data["releases"].get(latest, []):
        if str(f.get("filename", "")).endswith(".whl"):
            wheel_url = str(f["url"])
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
