# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - SponsorBlock Integration Module.
Provides automatic skipping of sponsored segments, self-promotions, interaction reminders,
and intros/outros for YouTube audio and video playback using the open SponsorBlock API.
"""

from __future__ import annotations
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("HeadlessPlayer.SponsorBlock")

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

# Default categories enabled for auto-skipping
DEFAULT_CATEGORIES = [
    "sponsor",       # Paid sponsors / advertisements
    "selfpromo",     # Unpaid / self-promotion
    "interaction",   # "Like and subscribe" reminders
    "intro",         # Intermission / Intro animation
    "outro",         # End credits / Outro
]

# Localized category names
def get_category_display_name(category: str) -> str:
    """Returns a clean localized display/speech name for a SponsorBlock category."""
    mapping = {
        "sponsor": _("sponsor segment"),
        "selfpromo": _("self-promotion"),
        "interaction": _("subscribe reminder"),
        "intro": _("intro animation"),
        "outro": _("outro credits"),
        "music_offtopic": _("non-music section"),
        "preview": _("preview recap"),
        "filler": _("filler segment"),
    }
    return mapping.get(category.lower(), _("sponsor segment"))


# Regex patterns to extract standard YouTube 11-char video IDs from YouTube URLs or raw ID string
YOUTUBE_ID_PATTERNS = [
    re.compile(r'(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/|v\/)|youtu\.be\/)([0-9A-Za-z_-]{11})', re.IGNORECASE),
    re.compile(r'^([0-9A-Za-z_-]{11})$'),
]


def extract_youtube_id(url_or_id: Optional[str]) -> Optional[str]:
    """Extracts the 11-character YouTube video ID from a URL or raw ID string."""
    if not url_or_id:
        return None
    s = str(url_or_id).strip()
    for pattern in YOUTUBE_ID_PATTERNS:
        match = pattern.search(s)
        if match:
            return match.group(1)
    return None


# Thread-safe in-memory cache for fetched segments: {video_id: (timestamp, segments)}
_SEGMENT_CACHE: Dict[str, Tuple[float, List[Tuple[float, float, str]]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 3600.0  # 1 hour


def fetch_sponsor_segments(
    video_id: str,
    categories: Optional[List[str]] = None,
    timeout: int = 4
) -> List[Tuple[float, float, str]]:
    """
    Fetches skip segments for a given YouTube video ID from the SponsorBlock API.

    Returns:
        List of (start_seconds, end_seconds, category_name) tuples sorted by start time.
    """
    vid = extract_youtube_id(video_id)
    if not vid:
        return []

    # 1. Check in-memory cache
    now = time.time()
    with _CACHE_LOCK:
        if vid in _SEGMENT_CACHE:
            ts, cached_segs = _SEGMENT_CACHE[vid]
            if now - ts < _CACHE_TTL:
                return cached_segs

    if categories is None:
        categories = DEFAULT_CATEGORIES

    # 2. Query SponsorBlock API
    cat_param = json.dumps(categories)
    encoded_cats = urllib.parse.quote(cat_param)
    api_url = f"https://sponsor.ajay.app/api/skipSegments?videoID={vid}&categories={encoded_cats}"

    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "HeadlessPlayer-NVDA-Addon/1.2.2 (https://github.com/Mahmoud-Abo-El-Fotouh/HeadlessPlayer)",
            "Accept": "application/json",
        }
    )

    segments: List[Tuple[float, float, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_data = json.loads(resp.read().decode("utf-8"))
                if isinstance(raw_data, list):
                    for item in raw_data:
                        seg_range = item.get("segment")
                        cat = str(item.get("category", "sponsor"))
                        if isinstance(seg_range, (list, tuple)) and len(seg_range) == 2:
                            try:
                                start_s = float(seg_range[0])
                                end_s = float(seg_range[1])
                                if end_s > start_s:
                                    segments.append((start_s, end_s, cat))
                            except (ValueError, TypeError):
                                continue
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # 404 is standard from SponsorBlock API when no segments are reported
            segments = []
        else:
            logger.debug("SponsorBlock API HTTP error %d for %s: %s", e.code, vid, e)
            return []
    except Exception as e:
        logger.debug("SponsorBlock API request failed for %s: %s", vid, e)
        return []

    # Sort segments chronologically and merge overlapping intervals
    segments.sort(key=lambda x: x[0])
    merged_segments: List[Tuple[float, float, str]] = []
    for seg in segments:
        if not merged_segments:
            merged_segments.append(seg)
        else:
            prev_start, prev_end, prev_cat = merged_segments[-1]
            if seg[0] <= prev_end:
                # Overlap: extend previous segment end
                merged_segments[-1] = (prev_start, max(prev_end, seg[1]), prev_cat)
            else:
                merged_segments.append(seg)
    segments = merged_segments

    # Cache results with maximum size bound (100 items)
    with _CACHE_LOCK:
        _SEGMENT_CACHE[vid] = (now, segments)
        if len(_SEGMENT_CACHE) > 100:
            oldest = sorted(_SEGMENT_CACHE.items(), key=lambda kv: kv[1][0])
            for k, _ in oldest[: len(_SEGMENT_CACHE) - 100]:
                _SEGMENT_CACHE.pop(k, None)

    if segments:
        logger.info("SponsorBlock: Loaded %d segments for YouTube video %s", len(segments), vid)

    return segments
