# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - SponsorBlock Integration Module.
Provides automatic skipping of sponsored segments, self-promotions, interaction reminders,
and intros/outros for YouTube audio and video playback using the open SponsorBlock API.
"""

from __future__ import annotations
import hashlib
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

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

try:
    from .addon_updater import get_current_addon_version
except Exception:
    def get_current_addon_version() -> str:
        return "1.3.0"

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
    re.compile(
        r'(?:https?:\/\/)?(?:[a-zA-Z0-9_-]+\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/|v\/|live\/)|youtu\.be\/)([0-9A-Za-z_-]{11})',
        re.IGNORECASE
    ),
    re.compile(r'^([0-9A-Za-z_-]{11})$'),
]


def extract_youtube_id(url_or_id: Optional[str]) -> Optional[str]:
    """
    Extracts the 11-character YouTube video ID from a URL or raw ID string.
    Strictly validates domain to avoid false matches on non-YouTube URLs (e.g. SoundCloud).
    """
    if not url_or_id:
        return None
    s = str(url_or_id).strip()
    if s.startswith(("http://", "https://")):
        try:
            parsed = urllib.parse.urlparse(s)
            domain = (parsed.netloc or "").lower()
            if ":" in domain:
                domain = domain.split(":")[0]
            if not (domain.endswith("youtube.com") or domain.endswith("youtu.be")):
                return None
        except Exception:
            return None

    for pattern in YOUTUBE_ID_PATTERNS:
        match = pattern.search(s)
        if match:
            return match.group(1)
    return None


def merge_overlapping_segments(
    segments: List[Tuple[float, float, str]],
    gap_threshold: float = 0.5
) -> List[Tuple[float, float, str]]:
    """
    Merges overlapping and adjacent segments (within gap_threshold) so playback does
    not suffer from double-seeking, audio clicks, or multiple skip stutter.
    """
    if not segments or len(segments) <= 1:
        return segments

    # Sort primarily by start time
    sorted_segs = sorted(segments, key=lambda s: (s[0], s[1]))
    merged: List[Tuple[float, float, str]] = []

    curr_start, curr_end, curr_cat = sorted_segs[0]

    for next_start, next_end, next_cat in sorted_segs[1:]:
        if next_start <= (curr_end + gap_threshold):
            curr_end = max(curr_end, next_end)
            if next_cat not in curr_cat:
                curr_cat = f"{curr_cat}, {next_cat}"
        else:
            merged.append((curr_start, curr_end, curr_cat))
            curr_start, curr_end, curr_cat = next_start, next_end, next_cat

    merged.append((curr_start, curr_end, curr_cat))
    return merged


# Thread-safe in-memory cache for fetched segments: {video_id: (timestamp, segments)}
_SEGMENT_CACHE: Dict[str, Tuple[float, List[Tuple[float, float, str]]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 3600.0  # 1 hour


def fetch_sponsor_segments(
    video_id: str,
    categories: Optional[List[str]] = None,
    timeout: int = 4,
    use_hash_prefix: bool = True
) -> List[Tuple[float, float, str]]:
    """
    Fetches skip segments for a given YouTube video ID from the SponsorBlock API.
    Supports privacy-preserving Hash Prefix API (k-anonymity via sha256 hash prefix)
    with graceful fallback to direct query and robust overlapping interval merging.

    Returns:
        List of (start_seconds, end_seconds, category_name) tuples sorted and merged.
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
    if not categories:
        return []

    cat_param = json.dumps(categories)
    encoded_cats = urllib.parse.quote(cat_param)

    segments: List[Tuple[float, float, str]] = []
    ver_str = get_current_addon_version()
    headers = {
        "User-Agent": f"HeadlessPlayer-NVDA-Addon/{ver_str} (https://github.com/Mahmoud-Abo-El-Fotouh/HeadlessPlayer)",
        "Accept": "application/json",
    }

    # 2. Privacy-preserving Hash Prefix API (k-anonymity)
    if use_hash_prefix:
        try:
            hash_prefix = hashlib.sha256(vid.encode("utf-8")).hexdigest()[:4]
            api_url = f"https://sponsor.ajay.app/api/skipSegments/{hash_prefix}?categories={encoded_cats}"
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, list):
                        for item in data:
                            if item.get("videoID") == vid:
                                for seg in item.get("segments", []):
                                    seg_range = seg.get("segment")
                                    cat = str(seg.get("category", "sponsor"))
                                    if isinstance(seg_range, (list, tuple)) and len(seg_range) == 2:
                                        try:
                                            s_start = float(seg_range[0])
                                            s_end = float(seg_range[1])
                                            if s_end > s_start:
                                                segments.append((s_start, s_end, cat))
                                        except (ValueError, TypeError):
                                            continue
                                break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # 404 in Hash Prefix API means no videos matching prefix have segments
                segments = []
            else:
                logger.debug("SponsorBlock Hash Prefix HTTP %d for %s: %s", e.code, vid, e)
        except Exception as e:
            logger.debug("SponsorBlock Hash Prefix request failed for %s: %s, falling back to direct", vid, e)

    # 3. Direct query fallback (if hash prefix failed or returned nothing)
    if not segments and not use_hash_prefix:
        try:
            api_url = f"https://sponsor.ajay.app/api/skipSegments?videoID={vid}&categories={encoded_cats}"
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    raw_data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(raw_data, list):
                        for item in raw_data:
                            seg_range = item.get("segment")
                            cat = str(item.get("category", "sponsor"))
                            if isinstance(seg_range, (list, tuple)) and len(seg_range) == 2:
                                try:
                                    s_start = float(seg_range[0])
                                    s_end = float(seg_range[1])
                                    if s_end > s_start:
                                        segments.append((s_start, s_end, cat))
                                except (ValueError, TypeError):
                                    continue
        except urllib.error.HTTPError as e:
            if e.code != 404:
                logger.debug("SponsorBlock direct HTTP %d for %s: %s", e.code, vid, e)
        except Exception as e:
            logger.debug("SponsorBlock direct request failed for %s: %s", vid, e)

    # 4. Merge overlapping and adjacent segments to eliminate double-jumps
    segments = merge_overlapping_segments(segments)

    # 5. Cache results with bounded LRU size
    with _CACHE_LOCK:
        _SEGMENT_CACHE[vid] = (now, segments)
        if len(_SEGMENT_CACHE) > 100:
            oldest = sorted(_SEGMENT_CACHE.items(), key=lambda kv: kv[1][0])
            for k, _ in oldest[: len(_SEGMENT_CACHE) - 100]:
                _SEGMENT_CACHE.pop(k, None)

    if segments:
        logger.info("SponsorBlock: Loaded %d merged segments for YouTube video %s", len(segments), vid)

    return segments

