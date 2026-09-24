# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - YouTube & Online Media Search & Listing Explorer.
"""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
import re
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..utils import log_debug, log_exception
from ..utils.config_spec import getConfig, getConfigValue
from .models import (
    StreamItem,
    ITEM_VIDEO,
    ITEM_SHORTS,
    ITEM_PLAYLIST,
    ITEM_CHANNEL,
    ITEM_LISTING,
)
from .resolver import _base_ydl_opts, login_cookies_enabled

logger = logging.getLogger("HeadlessPlayer.StreamSearch")

try:
    from .. import _  # type: ignore
except (ImportError, ValueError):
    try:
        _
    except NameError:
        def _(s: str) -> str:
            return s


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


def get_account_sections() -> List[StreamItem]:
    """
    Builds the YouTube account & feeds menu (P key): personalized sections
    (requiring sign-in cookies) plus Trending which works without an account.
    """
    return [
        StreamItem(
            kind=ITEM_LISTING,
            url="https://www.youtube.com/feed/channels",
            title=_("Subscribed channels"),
            extra={"requires_login": True},
        ),
        StreamItem(
            kind=ITEM_LISTING,
            url="https://www.youtube.com/feed/subscriptions",
            title=_("Latest videos from your subscriptions"),
            extra={"requires_login": True},
        ),
        StreamItem(
            kind=ITEM_LISTING,
            url="https://www.youtube.com/feed/subscriptions/shorts",
            title=_("Shorts from your subscriptions"),
            extra={"requires_login": True},
        ),
        StreamItem(
            kind=ITEM_LISTING,
            url="https://www.youtube.com/feed/recommended",
            title=_("Recommended for you (home feed)"),
            extra={"requires_login": True},
        ),
        StreamItem(
            kind=ITEM_LISTING,
            url="https://www.youtube.com/playlist?list=WL",
            title=_("Watch Later playlist"),
            extra={"requires_login": True},
        ),
        StreamItem(
            kind=ITEM_LISTING,
            url="https://www.youtube.com/playlist?list=LL",
            title=_("Liked videos"),
            extra={"requires_login": True},
        ),
        StreamItem(
            kind=ITEM_LISTING,
            url="https://www.youtube.com/feed/history",
            title=_("Watch history"),
            extra={"requires_login": True},
        ),
        StreamItem(
            kind=ITEM_LISTING,
            url="https://www.youtube.com/playlist?list=PL4fGSI1pDJn6puJdseH2Rt9sMvt9E2M4i",
            title=_("Trending music (Top 100 songs worldwide)"),
            extra={"requires_login": False},
        ),
    ]


def _prepare_listing_url(url: str) -> str:
    """Normalizes channel and mix URLs for flat listing extraction."""
    u = url.strip()
    m_mix = re.search(r"list=(RD(?:AMVM|MM)([a-zA-Z0-9_-]+))", u)
    if m_mix:
        list_id = m_mix.group(1)
        video_id = m_mix.group(2)
        return f"https://www.youtube.com/watch?v={video_id}&list={list_id}"

    if u.startswith(("http://", "https://")):
        if "/@" in u or "/channel/" in u or "/c/" in u or "/user/" in u:
            low = u.lower().rstrip("/")
            if not any(low.endswith(s) for s in ("/videos", "/shorts", "/playlists", "/streams", "/featured", "/community")):
                return u.rstrip("/") + "/videos"
    return u


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

    cfg = getConfig()
    if limit is None:
        try:
            limit = int(cfg.get("searchResultsCount", 20))
        except (ValueError, TypeError):
            limit = 20
    limit = max(1, int(limit))
    start_index = max(1, int(start_index))
    end_index = start_index + limit - 1

    log_debug("YTDLP", "search_youtube start: query='%s', limit=%d, start_index=%d, end_index=%d", query, limit, start_index, end_index)

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
        if isinstance(entry, dict):
            item = StreamItem.from_flat_entry(entry)
            if item:
                items.append(item)
    return items


_listing_cache: Dict[str, Tuple[float, str, List[StreamItem]]] = {}
_listing_cache_lock = threading.Lock()
_LISTING_CACHE_TTL = 15 * 60  # 15 minutes


def clear_listing_cache() -> None:
    """Clears the in-memory continuation tokens and listings cache."""
    with _listing_cache_lock:
        _listing_cache.clear()


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
    cfg = getConfig()
    if limit is None:
        try:
            limit = int(cfg.get("maxStreamPlaylistItems", 50))
        except (ValueError, TypeError):
            limit = 50
    limit = max(1, int(limit))
    start_index = max(1, int(start_index))
    end_index = start_index + limit - 1

    cache_key = f"{url.strip()}::{start_index}::{limit}"
    now = time.time()
    with _listing_cache_lock:
        cached = _listing_cache.get(cache_key)
        if cached and (now - cached[0]) < _LISTING_CACHE_TTL:
            return cached[1], list(cached[2])

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
        if len(shorts) < (start_index + limit):
            try:
                _ch_title, channels = fetch_listing("https://www.youtube.com/feed/channels", limit=20, start_index=1)
                seen_urls = {s.url for s in shorts}
                top_channels = channels[:8]

                def _fetch_single_channel_shorts(ch_item):
                    try:
                        ch_shorts_url = ch_item.url.rstrip("/") + "/shorts"
                        _sub_t, ch_items = fetch_listing(ch_shorts_url, limit=10, start_index=1)
                        for it in ch_items:
                            if not it.uploader:
                                it.uploader = ch_item.title
                        return _sub_t, ch_items
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
        res_title = _("Shorts from your subscriptions")
        with _listing_cache_lock:
            _listing_cache[cache_key] = (now, res_title, sliced_shorts)
        return res_title, sliced_shorts

    ytdlp = _get_ytdlp()

    url = _prepare_listing_url(url)

    opts = _base_ydl_opts(target_url=url)
    opts["extract_flat"] = True
    opts["playlist_items"] = f"{start_index}-{end_index}"

    try:
        with ytdlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        if "playlist?list=wl" in url.lower() or "playlist?list=ll" in url.lower():
            logger.warning("Personal playlist %s unavailable: %s", url, e)
            raise RuntimeError(
                _("This playlist requires valid sign-in cookies. Please configure or update your cookies.txt file in HeadlessPlayer settings.")
            ) from e
        is_private = any(p in url.lower() for p in (
            "/feed/subscriptions",
            "/feed/channels",
            "/feed/recommended",
            "/feed/history",
            "/feed/library",
            "playlist?list=wl",
            "playlist?list=ll",
        ))
        if is_private:
            logger.warning("Personal feed %s unavailable: %s", url, e)
            raise RuntimeError(
                _("This feed requires valid sign-in cookies. Please configure or update your cookies.txt file in HeadlessPlayer settings.")
            ) from e
        if login_cookies_enabled():
            logger.warning("Listing fetch with cookies failed (%s); retrying without cookies", e)
            opts_no_cookies = _base_ydl_opts(use_cookies=False, target_url=url)
            opts_no_cookies["extract_flat"] = True
            opts_no_cookies["playlist_items"] = f"{start_index}-{end_index}"
            with ytdlp.YoutubeDL(opts_no_cookies) as ydl:
                info = ydl.extract_info(url, download=False)
        else:
            raise

    if not info:
        return "", []

    title = str(info.get("title") or "")
    parent_uploader = info.get("channel") or info.get("uploader") or info.get("title")
    entries = info.get("entries")
    items: List[StreamItem] = []
    if entries is None:
        item = StreamItem.from_flat_entry(info, default_uploader=parent_uploader)
        if item:
            items.append(item)
    else:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item = StreamItem.from_flat_entry(entry, default_uploader=parent_uploader)
            if item:
                items.append(item)

    with _listing_cache_lock:
        _listing_cache[cache_key] = (now, title, items)
    return title, items


def probe_url(url: str, limit: int = 300) -> Tuple[str, List[StreamItem], bool]:
    """
    Probes an arbitrary URL (YouTube, TikTok, or any other supported site).

    Returns:
        (title, items, is_multi):
        is_multi is True when the URL expanded to a multi-entry listing
        (playlist / channel / site section); items then holds the entries.
        When False, items holds a single playable StreamItem for the URL.
    """
    if "tiktok.com" in url.lower():
        try:
            from .resolver import resolve_stream
            res = resolve_stream(url, prefer_audio=False)
            canonical_url = res.get("webpage_url") or url
            item = StreamItem(
                kind=ITEM_VIDEO,
                url=canonical_url,
                title=res.get("title") or url,
                duration=res.get("duration"),
                uploader=res.get("uploader"),
                extra={"has_video": True, "stream_info": res},
            )
            return res.get("title") or "TikTok Video", [item], False
        except Exception as e:
            logger.warning("Direct TikTok probe failed: %s", e)

    title, items = fetch_listing(url, limit=limit)
    if len(items) > 1:
        return title, items, True
    if len(items) == 1 and items[0].kind != ITEM_VIDEO:
        sub_title, sub_items = fetch_listing(items[0].url, limit=limit)
        if sub_items:
            return sub_title or items[0].title, sub_items, len(sub_items) > 1
    if items:
        return title, items, False
    return title, [StreamItem(kind=ITEM_VIDEO, url=url, title=title or url)], False
