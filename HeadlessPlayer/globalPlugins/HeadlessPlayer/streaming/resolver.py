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


def is_bot_error(err_str: str) -> bool:
    """Detects whether an extractor failure is due to YouTube bot verification challenge."""
    e = (err_str or "").lower()
    return any(p in e for p in [
        "sign in to confirm you’re not a bot",
        "sign in to confirm you're not a bot",
        "confirm you?re not a bot",
        "confirm you're not a bot",
        "bot verification",
    ])


def is_cookie_error(err_str: str) -> bool:
    """Detects whether an extractor failure is due to expired or missing login cookies."""
    e = (err_str or "").lower()
    if is_bot_error(err_str):
        return False
    return any(p in e for p in [
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
        "socket_timeout": 5,
        "retries": 1,
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
        if "/feed/subscriptions" in target_url:
            opts["extractor_args"] = {
                "youtube": {"player_client": ["ios", "web"]},
                "youtubetab": {"skip": ["authcheck"]},
            }
        elif "/feed/channels" in target_url:
            # Subscribed channels feed works with default client; skip:authcheck breaks YoutubeTabIE
            opts["extractor_args"] = {}
        elif any(p in target_url for p in ("/feed/recommended", "/feed/history")):
            opts["extractor_args"] = {
                "youtube": {"player_client": ["web"]},
            }
        elif not use_cookies:
            client = cfg.get("youtubeExtractorClient", "tv_embedded")
            client_list = [c.strip() for c in client.split(",") if c.strip()] if isinstance(client, str) else []
            opts["extractor_args"] = {
                "youtube": {
                    "player_client": client_list or ["tv_embedded"],
                    "skip": ["hls"],
                }
            }
        else:
            client = cfg.get("youtubeExtractorClientAuth", "android,ios")
            client_list = [c.strip() for c in client.split(",") if c.strip()] if isinstance(client, str) else []
            opts["extractor_args"] = {
                "youtube": {
                    "player_client": client_list or ["android", "ios"],
                    "skip": ["hls"],
                }
            }

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


def _resolve_tiktok(url: str, prefer_audio: bool = True) -> Optional[Dict[str, Any]]:
    """
    Directly resolves TikTok video and audio streams via TikWM API.
    Bypasses yt-dlp anti-bot challenges and solves unexpected response errors.
    """
    import urllib.request
    import urllib.parse
    import json

    try:
        clean_url = url.strip()
        # Follow redirects for short TikTok links (vm.tiktok.com, vt.tiktok.com, /t/)
        if any(p in clean_url for p in ("vm.tiktok.com", "vt.tiktok.com", "/t/")):
            try:
                redir_req = urllib.request.Request(
                    clean_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )
                with urllib.request.urlopen(redir_req, timeout=10) as redir_resp:
                    clean_url = redir_resp.geturl()
            except Exception as e_redir:
                logger.debug("TikTok redirect resolution failed: %s", e_redir)

        encoded = urllib.parse.quote(clean_url, safe="")
        api_url = f"https://www.tikwm.com/api/?url={encoded}"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        if data.get("code") != 0 or not data.get("data"):
            return None

        d = data["data"]
        play_url = d.get("play") or d.get("wmplay") or ""
        music_url = d.get("music") or (d.get("music_info") or {}).get("play") or ""
        title = d.get("title") or "TikTok Video"
        author_info = d.get("author") or {}
        author = author_info.get("nickname") or author_info.get("unique_id") or ""
        dur = float(d.get("duration") or 0.0)

        # play_url has the full audiovisual track; music_url is often just a short 15s sample
        chosen_url = play_url or music_url
        if not chosen_url:
            return None

        video_options = []
        if play_url:
            video_options.append(("HD (No Watermark)", play_url, 1080, True))

        audio_tracks = []
        if music_url:
            audio_tracks.append({
                "id": "music",
                "title": _("TikTok Audio"),
                "url": music_url,
                "http_headers": {},
            })

        return {
            "stream_url": chosen_url,
            "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            "title": title,
            "uploader": author,
            "duration": dur,
            "is_live": False,
            "webpage_url": clean_url,
            "chapters": [],
            "audio_tracks": audio_tracks,
            "has_video": bool(play_url),
            "video_options": video_options,
        }
    except Exception as e:
        logger.debug("TikWM resolution failed for %s: %s", url, e)
        return None


def resolve_stream(url: str, prefer_audio: bool = True) -> Dict[str, Any]:
    """
    Resolves a media page URL into a direct playable stream URL.
    Prefers audio-only streams; falls back to combined audio+video streams.
    Result dictionary keys:
        stream_url, http_headers, title, duration, is_live, webpage_url, chapters, audio_tracks, has_video, video_options
    """
    cfg = getConfig()
    quality = str(cfg.get("streamAudioQuality") or cfg.get("streamQuality") or "high").lower()

    cache_key = f"{url}::audio={prefer_audio}::quality={quality}"
    now = time.time()
    with _resolve_cache_lock:
        cached = _resolve_cache.get(cache_key)
        if cached and (now - cached[0]) < _RESOLVE_CACHE_TTL:
            return dict(cached[1])

    if "tiktok.com" in url.lower():
        tt_res = _resolve_tiktok(url, prefer_audio=prefer_audio)
        if tt_res:
            with _resolve_cache_lock:
                _resolve_cache[cache_key] = (now, tt_res)
            return dict(tt_res)

    ytdlp = _get_ytdlp()

    if quality == "low":
        format_selector = (
            "bestaudio[abr<=70]/"
            "bestaudio[ext=webm][abr<=70]/"
            "bestaudio[ext=m4a][abr<=70]/"
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

    is_yt_target = bool(is_youtube_url(url) or "youtube" in url or "youtu.be" in url)

    def _build_strategies() -> List[Tuple[str, bool, Dict[str, Any], str]]:
        st: List[Tuple[str, bool, Dict[str, Any], str]] = []
        if not is_yt_target:
            st.append(("generic_anon", False, {}, format_selector if prefer_audio else "best"))
            if login_cookies_enabled():
                st.append(("generic_auth", True, {}, format_selector if prefer_audio else "best"))
            return st

        # Video mode strategies
        if not prefer_audio:
            st.append(("tv_embedded_video", False, {"youtube": {"player_client": ["tv_embedded"]}}, "bestvideo+bestaudio/best"))
            st.append(("android_video", False, {"youtube": {"player_client": ["android"]}}, "bestvideo+bestaudio/best"))
            st.append(("web_video", False, {"youtube": {"player_client": ["web"]}}, "bestvideo+bestaudio/best"))
            if login_cookies_enabled():
                st.append(("cookies_video", True, {"youtube": {"player_client": ["web", "android"]}}, "bestvideo+bestaudio/best"))
            return st

        # Audio mode strategies
        primary_client = cfg.get("youtubeExtractorClient", "tv_embedded")
        primary_list = [c.strip() for c in primary_client.split(",") if c.strip()] if isinstance(primary_client, str) else []
        st.append(("primary", False, {"youtube": {"player_client": primary_list or ["tv_embedded"], "skip": ["hls"]}}, format_selector))
        st.append(("android_fast", False, {"youtube": {"player_client": ["android"], "player_skip": ["webpage", "configs"], "skip": ["hls"]}}, format_selector))
        st.append(("ios", False, {"youtube": {"player_client": ["ios"], "skip": ["hls"]}}, format_selector))
        st.append(("web", False, {"youtube": {"player_client": ["web"]}}, format_selector))
        st.append(("mweb", False, {"youtube": {"player_client": ["mweb"]}}, format_selector))
        st.append(("tv", False, {"youtube": {"player_client": ["tv"]}}, format_selector))

        if login_cookies_enabled():
            cookie_client = cfg.get("youtubeExtractorClientAuth", "android,ios")
            c_list = [c.strip() for c in cookie_client.split(",") if c.strip()] if isinstance(cookie_client, str) else []
            st.append(("cookies_auth", True, {"youtube": {"player_client": c_list or ["android", "ios"], "skip": ["hls"]}}, format_selector))
            st.append(("cookies_web", True, {"youtube": {"player_client": ["web"]}, "youtubetab": {"skip": ["authcheck"]}}, format_selector))

        return st

    strategies = _build_strategies()
    info = None
    first_error: Optional[Exception] = None
    last_error: Optional[Exception] = None

    for name, use_cookies, extractor_args, fmt in strategies:
        try:
            opts = _base_ydl_opts(use_cookies=use_cookies, target_url=url)
            if not use_cookies:
                opts.pop("cookiefile", None)
                opts.pop("cookiesfrombrowser", None)
            if extractor_args:
                opts["extractor_args"] = extractor_args
            opts.update({
                "noplaylist": True,
                "format": fmt,
                "ignoreerrors": False,
            })
            with ytdlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info:
                logger.debug("Successfully resolved stream for %s using strategy: %s", url, name)
                break
        except Exception as e:
            if not first_error:
                first_error = e
            last_error = e
            logger.debug("Resolution strategy '%s' failed for %s: %s", name, url, e)

    if not info:
        if first_error:
            raise first_error
        if last_error:
            raise last_error
        raise RuntimeError("Extraction returned no result")

    if info.get("_type") == "playlist" and info.get("entries"):
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise RuntimeError("Empty playlist result")
        info = entries[0]

    stream_url = info.get("url")
    best_audio_url = ""
    for f in (info.get("formats") or []):
        f_url = f.get("url") or f.get("manifest_url")
        if f_url and f.get("acodec") not in (None, "none") and str(f.get("acodec")).lower() != "none":
            if f.get("vcodec") in (None, "none") or str(f.get("vcodec")).lower() == "none":
                best_audio_url = f_url
                break
            elif not best_audio_url:
                best_audio_url = f_url

    if not stream_url and info.get("requested_formats"):
        fmts = info["requested_formats"]
        if prefer_audio:
            audio = next((f for f in fmts if f.get("acodec") not in (None, "none")), None)
            chosen = audio or fmts[0]
        else:
            video = next((f for f in fmts if f.get("vcodec") not in (None, "none")), None)
            chosen = video or fmts[0]
            if not best_audio_url:
                audio = next((f for f in fmts if f.get("acodec") not in (None, "none")), None)
                if audio:
                    best_audio_url = audio.get("url") or ""
        stream_url = chosen.get("url")
        info = {**info, "http_headers": chosen.get("http_headers") or info.get("http_headers")}
    if not stream_url and best_audio_url:
        stream_url = best_audio_url
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
    seen_track_ids = set()
    requested = info.get("requested_formats") or []
    if requested:
        for fmt in requested:
            if fmt.get("acodec") not in (None, "none") and str(fmt.get("acodec")).lower() != "none":
                fid = fmt.get("format_id", "")
                if fid and fid not in seen_track_ids:
                    seen_track_ids.add(fid)
                    f_url = fmt.get("url") or fmt.get("manifest_url") or stream_url or ""
                    audio_tracks.append({
                        "id": fid,
                        "title": fmt.get("format_note") or fmt.get("ext", "audio"),
                        "lang": fmt.get("language") or "",
                        "url": f_url,
                        "http_headers": fmt.get("http_headers") or info.get("http_headers") or {},
                    })
    for fmt in (info.get("formats") or []):
        f_url = fmt.get("url") or fmt.get("manifest_url")
        if f_url and fmt.get("vcodec") in (None, "none") and fmt.get("acodec") not in (None, "none") and str(fmt.get("acodec")).lower() != "none":
            fid = fmt.get("format_id", "")
            if fid and fid not in seen_track_ids:
                seen_track_ids.add(fid)
                audio_tracks.append({
                    "id": fid,
                    "title": fmt.get("format_note") or fmt.get("ext", "audio"),
                    "lang": fmt.get("language") or "",
                    "url": f_url,
                    "http_headers": fmt.get("http_headers") or info.get("http_headers") or {},
                })

    # Video options for video streams / quality switcher
    formats = info.get("formats") or []
    video_options: List[Tuple[str, str, int, bool]] = []
    seen_labels = set()
    for f in formats:
        h = f.get("height")
        f_url = f.get("url") or f.get("manifest_url") or stream_url or ""
        if h and f_url and f.get("vcodec") not in (None, "none") and str(f.get("vcodec")).lower() != "none":
            lbl = f"{h}p"
            fps = f.get("fps")
            if fps and fps > 30:
                lbl += f"{int(fps)}"
            if lbl not in seen_labels:
                seen_labels.add(lbl)
                has_audio = bool(f.get("acodec") not in (None, "none") and str(f.get("acodec")).lower() != "none")
                video_options.append((lbl, f_url, int(h), has_audio))

    if video_options:
        video_options.sort(key=lambda opt: opt[2], reverse=True)

    has_video = bool(
        video_options
        or (info.get("vcodec") not in (None, "none") and str(info.get("vcodec")).lower() != "none")
        or info.get("requested_formats") and any(fmt.get("vcodec") not in (None, "none") for fmt in info["requested_formats"])
    )

    res = {
        "id": str(info.get("id") or ""),
        "stream_url": stream_url,
        "audio_url": best_audio_url or (stream_url if prefer_audio else ""),
        "http_headers": info.get("http_headers") or {},
        "title": str(info.get("title") or "Online Stream"),
        "uploader": str(info.get("uploader") or info.get("channel") or ""),
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
