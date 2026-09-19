# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Stream Resolver & Cookie Manager.
Resolves web media links into direct playable stream URLs using yt-dlp with audio-first format selection.
"""

from __future__ import annotations
import logging
import os
import re
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from ..utils import log_debug, log_exception
from ..utils.config_spec import getConfig, getConfigValue
from .models import _SilentLogger, is_youtube_url

logger = logging.getLogger("HeadlessPlayer.StreamResolver")

try:
    from .. import _  # type: ignore
except (ImportError, ValueError):
    try:
        _
    except NameError:
        def _(s: str) -> str:
            return s

SUPPORTED_COOKIE_BROWSERS = ("none", "firefox", "librewolf", "waterfox", "floorp")


def _get_ytdlp() -> Any:
    for mod_name in (
        "globalPlugins.HeadlessPlayer.stream_engine",
        "globalPlugins.HeadlessPlayer.streaming.engine",
        "globalPlugins.HeadlessPlayer.streaming",
        "globalPlugins.HeadlessPlayer.streaming.updater",
    ):
        mod = sys.modules.get(mod_name)
        if mod and "_get_ytdlp" in mod.__dict__:
            fn = mod.__dict__["_get_ytdlp"]
            if fn is not _get_ytdlp:
                return fn()
    from . import updater
    return updater._get_ytdlp()


def get_manual_cookies_file() -> Optional[str]:
    """Returns absolute path to user-configured cookies.txt file if configured and valid."""
    cfg = getConfig()
    p = cfg.get("ytdlpCookiesFile") or cfg.get("youtubeCookiesFile")
    if p and isinstance(p, str) and os.path.isfile(p):
        return p
    return None


def login_cookies_enabled() -> bool:
    """True if custom cookies file or supported browser cookies are configured."""
    cfg = getConfig()
    c_browser = str(cfg.get("ytdlpCookiesBrowser", "none")).lower().strip()
    browser_valid = c_browser in SUPPORTED_COOKIE_BROWSERS and c_browser != "none"
    return bool(get_manual_cookies_file() or browser_valid)


def is_cookie_error(err_str: str) -> bool:
    """Detects whether an extractor failure is due to expired or missing login cookies."""
    e = (err_str or "").lower()
    return any(p in e for p in [
        "sign in to confirm you’re not a bot",
        "sign in to confirm you're not a bot",
        "confirm you?re not a bot",
        "confirm you're not a bot",
        "could not decrypt cookies",
        "dpapi decryption failed",
        "app-bound encryption prevented cookie access",
        "this video is only available to registered users",
        "sign in to view your subscriptions",
        "sign in if you've been granted access",
        "this video is private",
        "members-only content",
        "login required",
        "cookies",
    ])


def check_youtube_cookies_validity(cookies_file: Optional[str] = None) -> Tuple[bool, str]:
    """
    Checks if cookies.txt exists and contains valid authentication cookies.
    Returns: (is_valid: bool, reason: str)
    """
    cfg = getConfig()
    path = cookies_file if cookies_file is not None else (cfg.get("ytdlpCookiesFile") or cfg.get("youtubeCookiesFile"))
    if not path or not isinstance(path, str) or not path.strip():
        return False, "not_configured"
    if not os.path.isfile(path):
        return False, "file_not_found"
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
        lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
        if not lines:
            return False, "empty"

        yt_lines = [l for l in lines if ".youtube.com" in l or ".google.com" in l or "youtube.com" in l]
        if not yt_lines:
            return False, "empty"

        has_auth = any(k in content for k in ["__Secure-3PAPISID", "SID", "LOGIN_INFO", "SAPISID", "HSID", "SSID", "APISID"])
        if not has_auth:
            return False, "missing_auth_tokens"

        now = int(time.time())
        for line in yt_lines:
            parts = line.split("\t")
            if len(parts) >= 7:
                c_name = parts[5]
                try:
                    c_exp = int(parts[4])
                    if 0 < c_exp < now:
                        if c_name in ("LOGIN_INFO", "SAPISID", "__Secure-3PAPISID", "SID"):
                            return False, "expired"
                except (ValueError, TypeError):
                    pass

        return True, "ok"
    except Exception as e:
        return False, str(e)


def _base_ydl_opts(use_cookies: bool = True, target_url: str = "") -> Dict[str, Any]:
    """Builds standard baseline options for yt-dlp invocations."""
    cfg = getConfig()
    opts: Dict[str, Any] = {
        "logger": _SilentLogger(),
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "simulate": True,
    }

    if use_cookies:
        c_file = get_manual_cookies_file()
        if c_file:
            opts["cookiefile"] = c_file
        else:
            c_browser = str(cfg.get("ytdlpCookiesBrowser", "none")).lower().strip()
            if c_browser in SUPPORTED_COOKIE_BROWSERS and c_browser != "none":
                opts["cookiesfrombrowser"] = (c_browser,)

    is_yt = bool(not target_url or is_youtube_url(target_url) or "youtube" in target_url or "ytsearch" in target_url)
    if is_yt:
        if not use_cookies:
            opts["extractor_args"] = {"youtube": {"player_client": ["tv_embedded"]}}
        else:
            client = cfg.get("youtubeExtractorClient", "web")
            if client:
                client_list = [c.strip() for c in client.split(",") if c.strip()]
                opts["extractor_args"] = {"youtube": {"player_client": client_list or ["web"]}}

    return opts


# ---------------------------------------------------------------------------
# Direct stream resolution (audio-first) with a short-lived cache
# ---------------------------------------------------------------------------

_resolve_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_resolve_cache_lock = threading.Lock()
_RESOLVE_CACHE_TTL = 20 * 60  # 20 minutes


def clear_resolve_cache() -> None:
    """Flushes cached stream resolution entries."""
    with _resolve_cache_lock:
        _resolve_cache.clear()


def resolve_stream(url: str, prefer_audio: bool = True) -> Dict[str, Any]:
    """
    Resolves a media page URL into a direct playable stream URL.
    Prefers audio-only streams; falls back to combined audio+video streams.

    Returns dict with keys:
        stream_url, http_headers, title, duration, is_live, webpage_url, chapters, audio_tracks, has_video, video_options
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

    if info.get("_type") == "playlist" and info.get("entries"):
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise RuntimeError("Empty playlist result")
        info = entries[0]

    stream_url = info.get("url")
    if not stream_url and info.get("requested_formats"):
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
        parsed_chapters.sort(key=lambda c: c["start_time"])
        for i in range(len(parsed_chapters) - 1):
            if parsed_chapters[i]["end_time"] is None:
                parsed_chapters[i]["end_time"] = parsed_chapters[i + 1]["start_time"]
        if dur > 0 and parsed_chapters[-1]["end_time"] is None:
            parsed_chapters[-1]["end_time"] = dur

    audio_tracks: List[Dict[str, Any]] = []
    requested = info.get("requested_formats") or []
    if requested:
        for fmt in requested:
            if fmt.get("acodec") not in (None, "none"):
                audio_tracks.append({
                    "id": fmt.get("format_id", ""),
                    "title": fmt.get("format_note") or fmt.get("ext", "audio"),
                    "lang": fmt.get("language") or "",
                })

    # Video options for video streams / quality switcher
    formats = info.get("formats") or []
    video_options: List[Tuple[str, str]] = []
    for f in formats:
        h = f.get("height")
        f_url = f.get("url")
        if h and f_url and f.get("vcodec") not in (None, "none"):
            lbl = f"{h}p"
            fps = f.get("fps")
            if fps and fps > 30:
                lbl += f"{fps}"
            video_options.append((lbl, f_url))

    if video_options:
        def _get_h(opt_tuple):
            digits = "".join(c for c in opt_tuple[0] if c.isdigit())
            return int(digits) if digits else 0
        video_options.sort(key=_get_h, reverse=True)

    has_video = bool(
        video_options
        or (info.get("vcodec") not in (None, "none") and str(info.get("vcodec")).lower() != "none")
        or info.get("requested_formats") and any(fmt.get("vcodec") not in (None, "none") for fmt in info["requested_formats"])
    )

    res = {
        "stream_url": stream_url,
        "http_headers": info.get("http_headers") or {},
        "title": str(info.get("title") or "Online Stream"),
        "duration": dur,
        "is_live": bool(info.get("is_live") or info.get("live_status") == "is_live"),
        "webpage_url": str(info.get("webpage_url") or url),
        "chapters": parsed_chapters,
        "audio_tracks": audio_tracks,
        "has_video": has_video,
        "video_options": video_options,
    }

    with _resolve_cache_lock:
        _resolve_cache[cache_key] = (now, res)

    return res
