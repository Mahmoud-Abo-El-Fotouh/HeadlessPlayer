# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Stream Item Models & URL Classification.
"""

from __future__ import annotations
import logging
import re
from typing import Any, Dict, List, Optional
from ..utils import format_time

logger = logging.getLogger("HeadlessPlayer.StreamEngine")

try:
    from .. import _  # type: ignore
except (ImportError, ValueError):
    try:
        _
    except NameError:
        def _(s: str) -> str:
            return s

# Item Types
ITEM_VIDEO = "video"
ITEM_SHORTS = "shorts"
ITEM_PLAYLIST = "playlist"
ITEM_CHANNEL = "channel"
ITEM_LISTING = "listing"  # synthetic channel sub-listing (Videos / Shorts / Playlists / Live)

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
        if "playlist" in low or "list=" in low:
            return ITEM_PLAYLIST
    if "channel" in low or "/@" in low or "/user/" in low or "/c/" in low:
        return ITEM_CHANNEL
    return ITEM_VIDEO


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


class StreamItem:
    """
    Unified representation of a search result, channel entry, or playlist item.
    Supports both legacy and modern property access patterns.
    """

    def __init__(
        self,
        kind: str = ITEM_VIDEO,
        url: str = "",
        title: str = "",
        duration: Optional[float] = None,
        uploader: Optional[str] = None,
        views: Optional[int] = None,
        count: Optional[int] = None,
        requires_login: bool = False,
        extra: Optional[Dict[str, Any]] = None,
        is_live: bool = False,
        **kwargs: Any,
    ) -> None:
        self.kind = kwargs.get("item_type", kind)
        self.url = str(kwargs.get("url", url) or "").strip()

        raw_title = kwargs.get("title", title)
        if raw_title is not None and str(raw_title).strip():
            self.title = str(raw_title).strip()
        elif self.url:
            self.title = self.url
        else:
            self.title = "Untitled"

        self.duration = kwargs.get("duration", duration)

        channel_val = kwargs.get("channel", kwargs.get("uploader", uploader))
        self.uploader = channel_val if channel_val is not None else None

        self.views = kwargs.get("view_count", kwargs.get("views", views))
        self.count = kwargs.get("item_count", kwargs.get("count", count))
        self.requires_login = bool(kwargs.get("requires_login", requires_login))
        self.extra = extra or kwargs.get("extra") or {}
        self.is_live = bool(
            is_live
            or kwargs.get("is_live")
            or self.extra.get("is_live")
            or self.extra.get("live_status") == "is_live"
        )

    @property
    def item_type(self) -> str:
        return self.kind

    @item_type.setter
    def item_type(self, val: str) -> None:
        self.kind = val

    @property
    def channel(self) -> Optional[str]:
        return self.uploader

    @channel.setter
    def channel(self, val: Optional[str]) -> None:
        self.uploader = val

    @property
    def view_count(self) -> Optional[int]:
        return self.views

    @view_count.setter
    def view_count(self, val: Optional[int]) -> None:
        self.views = val

    @property
    def item_count(self) -> Optional[int]:
        return self.count

    @item_count.setter
    def item_count(self, val: Optional[int]) -> None:
        self.count = val

    @classmethod
    def from_flat_entry(cls, entry: Dict[str, Any]) -> "StreamItem":
        """Builds a StreamItem from a flat-extracted yt-dlp entry dictionary."""
        kind = classify_flat_entry(entry)
        raw_url = str(entry.get("url") or entry.get("webpage_url") or "")
        if raw_url and not raw_url.startswith(("http://", "https://")):
            # YouTube flat extraction gives just the video ID as the URL for videos
            if kind in (ITEM_VIDEO, ITEM_SHORTS):
                raw_url = f"https://www.youtube.com/watch?v={raw_url}"

        title = str(
            entry.get("title")
            or entry.get("headline")
            or entry.get("fulltitle")
            or raw_url
            or "Untitled"
        )
        channel = (
            entry.get("channel")
            or entry.get("uploader")
            or entry.get("uploader_id")
            or entry.get("channel_id")
        )
        dur = entry.get("duration")
        duration_float: Optional[float] = None
        if dur is not None:
            try:
                duration_float = float(dur)
            except (TypeError, ValueError):
                duration_float = None

        is_live = bool(entry.get("is_live") or entry.get("live_status") == "is_live")
        item_count = entry.get("playlist_count") or entry.get("item_count")

        return cls(
            kind=kind,
            url=raw_url,
            title=title,
            duration=duration_float,
            uploader=str(channel) if channel else None,
            views=entry.get("view_count"),
            count=int(item_count) if item_count is not None else None,
            extra=entry,
            is_live=is_live,
        )

    def format_display_text(self, show_type_prefix: bool = True) -> str:
        """
        Formats the item into accessible text for NVDA list items.
        """
        parts: List[str] = []

        if show_type_prefix:
            if self.kind == ITEM_PLAYLIST:
                if self.count and self.count > 0:
                    parts.append(f"[{_('Playlist')}: {self.count}]")
                else:
                    parts.append(f"[{_('Playlist')}]")
            elif self.kind == ITEM_CHANNEL:
                parts.append(f"[{_('Channel')}]")
            elif self.kind == ITEM_SHORTS:
                parts.append(f"[{_('Shorts')}]")
            elif self.is_live:
                parts.append(f"[{_('Live')}]")

        body = self.title
        if self.uploader and self.kind != ITEM_CHANNEL:
            body = f"{body} - {self.uploader}"

        if self.duration and self.duration > 0 and self.kind in (ITEM_VIDEO, ITEM_SHORTS):
            body = f"{body} [{format_time(self.duration)}]"

        parts.append(body)
        return " ".join(parts)

    def __str__(self) -> str:
        return self.format_display_text(show_type_prefix=True)

    def __repr__(self) -> str:
        return f"<StreamItem kind={self.kind!r} title={self.title!r} url={self.url!r}>"
