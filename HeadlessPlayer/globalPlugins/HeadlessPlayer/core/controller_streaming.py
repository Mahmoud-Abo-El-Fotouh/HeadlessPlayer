# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Controller Streaming Mixin.
Handles YouTube & web stream extraction, search, auto-paging, chapter parsing, and SponsorBlock skipping.
"""

from __future__ import annotations
import logging
import os
import sys
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from .. import _  # type: ignore
except (ImportError, ValueError):
    try:
        from . import _  # type: ignore
    except (ImportError, ValueError):
        try:
            _ = _  # type: ignore
        except NameError:
            def _(s: str) -> str:
                return s

from ..playlist import Track
from ..utils.config_spec import getConfig, getConfigValue
from ..utils import copy_to_clipboard, log_debug, log_exception
from ..history.database import get_db_manager
from ..streaming import engine as stream_engine
from ..streaming.dialogs import prompt_url_input, show_results_dialog
from ..streaming.sponsorblock import extract_youtube_id, fetch_sponsor_segments

logger = logging.getLogger("HeadlessPlayer.ControllerStreaming")


class ControllerStreamingMixin:
    """
    Mixin providing online stream resolution, YouTube search, URL opening, and stream management.
    """

    def _check_streaming_available(self) -> bool:
        """Verifies the yt-dlp engine is usable, speaking an accurate reason if not."""
        if stream_engine.is_available():
            return True
        if sys.version_info < (3, 10):
            self.speech.speak(_(
                "Online streaming is unavailable. It requires NVDA 2024.1 or later."
            ))
        else:
            self.speech.speak(_(
                "The streaming engine failed to load. "
                "Try updating it from HeadlessPlayer settings."
            ))
        return False

    def open_url_dialog(self) -> None:
        """
        Opens the URL / YouTube search entry box (U key in Player Mode).
        Accepts a YouTube URL, any supported website URL, or free text to search YouTube interactively.
        """
        if not self._check_streaming_available():
            return

        self._exit_player_mode_for_dialog()

        def _on_sub(url: str) -> None:
            self._restore_player_mode_after_dialog()
            self._on_url_or_search_submitted(url)

        def _on_cancel() -> None:
            self._restore_player_mode_after_dialog()

        prompt_url_input(
            on_submit=_on_sub,
            on_cancelled=_on_cancel,
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
        )

    def _canonical_current_track_path(self) -> Optional[str]:
        """Returns the stable, canonical URL or file path for the active track."""
        cur_track = self.playlist.get_current_track()
        cand = (cur_track.path if (cur_track and cur_track.path) else None) or self._last_loaded_path
        if cand and not ("127.0.0.1" in str(cand) or "localhost" in str(cand)):
            return str(cand).strip()
        eng_path = getattr(self.engine, "path", None)
        if eng_path and not ("127.0.0.1" in str(eng_path) or "localhost" in str(eng_path)):
            return str(eng_path).strip()
        if cur_track and hasattr(cur_track, "metadata"):
            meta_id = cur_track.metadata.get("id")
            if meta_id:
                return f"https://www.youtube.com/watch?v={meta_id}"
        return None

    def _copy_to_clipboard(self, target: str) -> bool:
        """Copies file (CF_HDROP + CF_UNICODETEXT) or URL to the Windows clipboard."""
        return copy_to_clipboard(target)

    def copy_current_url(self) -> None:
        """
        Copies the current track's source URL (for online streams) or its
        file path (for local files) to the Windows clipboard (V key).
        """
        cur = self.playlist.get_current_track()
        target_path = self._canonical_current_track_path()
        if not target_path:
            self.speech.speak(_("Nothing is currently loaded."))
            return

        if target_path.startswith("youtube:"):
            vid = target_path.split(":", 1)[1]
            target_path = f"https://www.youtube.com/watch?v={vid}"

        copied = self._copy_to_clipboard(target_path)
        if copied:
            is_stream = bool(
                (cur and getattr(cur, "is_stream", False))
                or target_path.startswith(("http://", "https://", "ytdl://", "custom://"))
            )
            if is_stream:
                self.speech.speak(_("Link copied to clipboard."))
            else:
                self.speech.speak(_("File and path copied to clipboard."))
        else:
            self.speech.speak(_("Could not copy to clipboard."))

    def copy_direct_url(self) -> None:
        """Shift+V: copies the direct audio media link of the playing online item."""
        cur = self.playlist.get_current_track()
        if not cur or not getattr(cur, "is_stream", False):
            self.speech.speak(_("No online stream is playing."))
            return
        info = self._current_stream_info or {}
        url = str(info.get("stream_url") or info.get("direct_url") or info.get("audio_url") or "")
        if url.startswith("http://127.0.0.1") or url.startswith("http://localhost"):
            url = str(info.get("direct_url") or info.get("audio_url") or "")
            if url.startswith("http://127.0.0.1") or url.startswith("http://localhost"):
                url = ""

        if not url or (info.get("webpage_url") and info.get("id") and info.get("id") not in cur.path):
            try:
                resolved = stream_engine.resolve_stream(cur.path)
                url = str(resolved.get("stream_url") or resolved.get("direct_url") or resolved.get("audio_url") or "")
                if url.startswith("http://127.0.0.1") or url.startswith("http://localhost"):
                    url = str(resolved.get("direct_url") or resolved.get("audio_url") or "")
                    if url.startswith("http://127.0.0.1") or url.startswith("http://localhost"):
                        url = ""
            except Exception as e:
                logger.error("copy_direct_url resolve failed: %s", e)
                url = ""
        if not url:
            self.speech.speak(_("The direct audio link is not available yet."))
            return
        if self._copy_to_clipboard(url):
            self.speech.speak(_("Direct audio link copied to clipboard."))
        else:
            self.speech.speak(_("Could not copy to clipboard."))

    # -------------------------------------------------------------------------
    # Clip Exporter & Encoding Delegation
    # -------------------------------------------------------------------------

    def _export_range(self) -> Tuple[Optional[float], Optional[float], str]:
        """Returns (start, end, scenario): both points, A + current position as B, or nothing selected."""
        return self.export_coordinator.export_range()

    def _export_source(self, cur: Any) -> Any:
        return self.export_coordinator.export_source(cur)

    def export_clip(self) -> None:
        """D key: opens the Clip Exporter for the A-B selection or full item."""
        self.export_coordinator.export_clip()

    def quick_export(self) -> None:
        """Shift+D: exports the A-B selection immediately with remembered settings."""
        self.export_coordinator.quick_export()

    def _run_export(self, source: Any, settings: Dict[str, Any], start: Optional[float], end: Optional[float], filename: str, folder: str) -> None:
        self.export_coordinator.run_export(source, settings, start, end, filename, folder)

    def open_account_feed(self) -> None:
        """Opens the YouTube account browser (P key)."""
        if not self._check_streaming_available():
            return

        self._exit_player_mode_for_dialog()

        items = stream_engine.get_account_sections()
        show_results_dialog(
            _("YouTube Account & Feeds"),
            items,
            self,
            suspend_capture=self._suspend_input,
            resume_capture=self._resume_input,
            is_playlist_context=False,
        )

    def _on_url_or_search_submitted(self, text: str) -> None:
        threading.Thread(
            target=self._handle_url_or_search,
            args=(text,),
            daemon=True,
            name="HeadlessPlayer-UrlSearch"
        ).start()

    def _handle_url_or_search(self, text: str) -> None:
        """Background worker: classifies the U-box input and acts on it."""
        cfg = getConfig()
        try:
            extracted_url = stream_engine.extract_url(text)
            if extracted_url:
                url = extracted_url
                self.speech.speak(_("Loading URL, please wait..."))
                limit = int(cfg.get("maxStreamPlaylistItems", 50))
                title, items, is_multi = stream_engine.probe_url(url, limit=limit)

                if is_multi:
                    videos = [
                        it for it in items
                        if getattr(it, "kind", "") in (stream_engine.ITEM_VIDEO, stream_engine.ITEM_SHORTS)
                    ]
                    if videos and len(videos) == len(items):
                        self.play_stream_items(videos, start_index=0, listing_title=title, source_target=url, source_type="listing", batch_size=limit)
                    else:
                        show_results_dialog(
                            title or url,
                            items,
                            self,
                            suspend_capture=self._suspend_input,
                            resume_capture=self._resume_input,
                            is_playlist_context=bool(videos),
                            source_type="listing",
                            source_target=url,
                            batch_size=limit,
                        )
                else:
                    self.play_stream_items(items, start_index=0, listing_title=title)
            else:
                self.speech.speak(_("Searching YouTube, please wait..."))
                limit = int(cfg.get("searchResultsCount", 20))
                log_debug("CONTROLLER", "Interactive YouTube search started: text='%s', limit=%d", text, limit)
                results = stream_engine.search_youtube(text, limit=limit)
                log_debug("CONTROLLER", "Interactive YouTube search finished: %d results found", len(results) if results else 0)
                if not results:
                    self.speech.speak(_("No results found."))
                    return
                show_results_dialog(
                    _("YouTube results for: %s") % text,
                    results,
                    self,
                    suspend_capture=self._suspend_input,
                    resume_capture=self._resume_input,
                    is_playlist_context=False,
                    source_type="search",
                    source_target=text,
                    batch_size=limit,
                )
        except Exception as e:
            logger.error("URL/search handling failed: %s", e, exc_info=True)
            log_exception("CONTROLLER", f"URL/search handling failed for text='{text}'", e)
            self.speech.speak(self._stream_error_message(e))

    def _stream_error_message(self, exc: Exception) -> str:
        """Builds an accurate spoken error message for a streaming failure."""
        err_str = str(exc)
        if getattr(stream_engine, "is_bot_error", lambda s: False)(err_str) or "bot" in err_str.lower():
            return _(
                "YouTube requires sign-in verification for this content. "
                "Please configure valid sign-in cookies in HeadlessPlayer settings."
            )
        if stream_engine.is_cookie_error(err_str):
            return _(
                "Could not read sign-in cookies from your browser. "
                "Set a manual cookies.txt file in HeadlessPlayer settings instead."
            )
        return _(
            "Operation failed. Check your internet connection, "
            "or update yt-dlp from HeadlessPlayer settings."
        )

    def play_stream_items(
        self,
        items: Sequence[Any],
        start_index: int = 0,
        listing_title: str = "",
        source_target: Optional[str] = None,
        source_url: Optional[str] = None,
        source_type: str = "listing",
        batch_size: Optional[int] = None,
    ) -> bool:
        """
        Queues a sequence of online StreamItems as the active playlist and starts playback.
        """
        target = source_target or source_url

        playable_items = [
            it for it in items
            if getattr(it, "kind", "") in (stream_engine.ITEM_VIDEO, stream_engine.ITEM_SHORTS)
            or getattr(it, "is_stream", False)
            or (not getattr(it, "kind", "") and (hasattr(it, "url") or hasattr(it, "path")))
        ]
        if not playable_items:
            self.speech.speak(_("No playable items found."))
            return False

        if 0 <= start_index < len(items) and items[start_index] in playable_items:
            start_index = playable_items.index(items[start_index])
        else:
            start_index = max(0, min(start_index, len(playable_items) - 1))

        tracks = []
        for it in playable_items:
            meta = dict(getattr(it, "metadata", {}) or {})
            is_vid = bool(getattr(it, "kind", "") in (stream_engine.ITEM_VIDEO, stream_engine.ITEM_SHORTS) or (getattr(it, "extra", None) and getattr(it, "extra", {}).get("has_video")))
            meta.update({
                "is_live": bool(getattr(it, "is_live", False)),
                "listing": listing_title,
                "kind": getattr(it, "kind", "video"),
                "is_video": is_vid,
            })
            t = Track(
                path=getattr(it, "url", None) or getattr(it, "path", ""),
                title=getattr(it, "title", ""),
                duration=getattr(it, "duration", None),
                metadata=meta,
            )
            if is_vid:
                t.is_video = True
            tracks.append(t)

        with self._lock:
            first = self.playlist.load_stream_tracks(tracks, start_index=start_index, append=False)
            if target:
                self._active_stream_source_target = target
                self._active_stream_source_url = target
                self._active_stream_source_type = source_type
                self._active_stream_next_idx = len(items) + 1
                self._active_stream_batch_size = batch_size or len(items) or 50
                self._active_stream_has_more = True
                self._active_stream_fetching = False
            else:
                self._active_stream_source_target = None
                self._active_stream_source_url = None
                self._active_stream_source_type = "listing"
                self._active_stream_has_more = False

        if not first:
            self.speech.speak(_("No playable items found."))
            return False

        if target and len(tracks) > 1:
            try:
                db = get_db_manager()
                db.save_recent_container(
                    path=target,
                    title=listing_title or target,
                    container_type="search" if source_type == "search" else "playlist"
                )
            except Exception as e:
                logger.debug("Error saving recent playlist container: %s", e)

        if len(tracks) > 1:
            self.speech.announce_loaded_files(len(tracks), total_duration=self.playlist.total_duration)
        res = self.play_track(first)

        self._check_auto_enter_player_mode()
        return res

    def play_search_as_playlist(self, query: str) -> None:
        """Searches YouTube in background and plays results directly as continuous stream."""
        if not query:
            return
        self.speech.speak(_("Searching YouTube, please wait..."))

        def worker() -> None:
            try:
                cfg = getConfig()
                limit = int(cfg.get("searchResultsCount", 20))
                results = stream_engine.search_youtube(query, limit=limit)
                if not results:
                    self.speech.speak(_("No results found."))
                    return
                lvl_items = [
                    it for it in results
                    if getattr(it, "kind", "") in (stream_engine.ITEM_VIDEO, stream_engine.ITEM_SHORTS)
                ]
                if not lvl_items:
                    lvl_items = results
                self.play_stream_items(
                    lvl_items,
                    start_index=0,
                    listing_title=_("YouTube results for: %s") % query,
                    source_target=query,
                    source_type="search",
                    batch_size=limit,
                )
            except Exception as e:
                logger.error("Error playing search playlist for '%s': %s", query, e, exc_info=True)
                self.speech.speak(self._stream_error_message(e))

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-PlaySearchPlaylist").start()

    def open_search_dialog(self, query: str) -> None:
        """Asynchronously searches YouTube in background thread and opens results dialog."""
        if not query:
            return
        threading.Thread(
            target=self._handle_url_or_search,
            args=(query,),
            daemon=True,
            name="HeadlessPlayer-OpenSearchDialog"
        ).start()

    def play_stream_listing(self, url: str, listing_title: str = "") -> None:
        """Loads an online playlist or channel stream URL in background."""
        self.speech.speak(_("Loading playlist, please wait..."))

        def worker() -> None:
            try:
                cfg = getConfig()
                limit = int(cfg.get("maxStreamPlaylistItems", 50))
                title, items = stream_engine.fetch_listing(url, limit=limit, start_index=1)
                self.play_stream_items(
                    items,
                    start_index=0,
                    listing_title=title or listing_title,
                    source_target=url,
                    source_type="listing",
                    batch_size=limit,
                )
            except Exception as e:
                logger.error("Playlist expansion failed: %s", e, exc_info=True)
                self.speech.speak(self._stream_error_message(e))

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-PlayListing").start()

    def _check_stream_queue_auto_extend(self) -> None:
        """Asynchronously loads next batch of tracks for active online playlist/listing or search query."""
        with self._lock:
            target = getattr(self, "_active_stream_source_target", None) or getattr(self, "_active_stream_source_url", None)
            stype = getattr(self, "_active_stream_source_type", "listing")
            has_more = getattr(self, "_active_stream_has_more", False)
            fetching = getattr(self, "_active_stream_fetching", False)
            if not target or not has_more or fetching:
                return
            if not any(getattr(t, "is_stream", False) for t in self.playlist._tracks):
                self._active_stream_source_target = None
                self._active_stream_source_url = None
                self._active_stream_has_more = False
                return
            count = self.playlist.count
            if count >= 500:
                self._active_stream_has_more = False
                return
            cur_orig = self.playlist.original_index
            if count == 0 or cur_orig < max(0, count - 10):
                return
            self._active_stream_fetching = True
            start_idx = self._active_stream_next_idx
            bsize = self._active_stream_batch_size

        def worker() -> None:
            try:
                if stype == "search":
                    new_items = stream_engine.search_youtube(target, limit=bsize, start_index=start_idx)
                else:
                    _title, new_items = stream_engine.fetch_listing(target, limit=bsize, start_index=start_idx)

                playable = [
                    it for it in new_items
                    if getattr(it, "kind", "") in (stream_engine.ITEM_VIDEO, stream_engine.ITEM_SHORTS)
                    or getattr(it, "is_stream", False)
                    or (not getattr(it, "kind", "") and (hasattr(it, "url") or hasattr(it, "path")))
                ]
                with self._lock:
                    current_target = getattr(self, "_active_stream_source_target", None) or getattr(self, "_active_stream_source_url", None)
                    if current_target == target:
                        if not playable:
                            self._active_stream_has_more = False
                        else:
                            existing_paths = {t.path for t in self.playlist.tracks if t and t.path}
                            existing_ids = set()
                            for p in existing_paths:
                                vid = extract_youtube_id(p)
                                if vid:
                                    existing_ids.add(vid)

                            new_tracks = []
                            for it in playable:
                                p = getattr(it, "url", None) or getattr(it, "path", "")
                                if not p or p in existing_paths:
                                    continue
                                vid = extract_youtube_id(p)
                                if vid and vid in existing_ids:
                                    continue
                                existing_paths.add(p)
                                if vid:
                                    existing_ids.add(vid)

                                meta = dict(getattr(it, "metadata", {}) or {})
                                meta.update({"is_live": bool(getattr(it, "is_live", False))})
                                new_tracks.append(
                                    Track(
                                        path=p,
                                        title=getattr(it, "title", ""),
                                        duration=getattr(it, "duration", None),
                                        metadata=meta,
                                    )
                                )
                            if new_tracks:
                                self.playlist.load_stream_tracks(new_tracks, append=True)
                            self._active_stream_next_idx = start_idx + len(new_items)
                            tolerance = 5 if bsize >= 20 else 1
                            self._active_stream_has_more = len(new_items) >= max(1, bsize - tolerance)
            except Exception as ex:
                logger.debug("Stream queue auto-extend failed (%s, target=%s): %s", stype, target, ex)
            finally:
                with self._lock:
                    self._active_stream_fetching = False

        threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-QueueExtend").start()

    def _play_stream_track(self, track: Track, resume_pos: Optional[float] = None) -> bool:
        """Starts asynchronous resolution and playback of an online stream track."""
        with self._lock:
            if getattr(self, "_is_resolving_stream", False) and getattr(self, "_resolving_track_path", None) == track.path:
                self.speech.speak(_("Loading stream, please wait..."))
                return True

            self._is_resolving_stream = True
            self._resolving_track_path = track.path

            if self._last_loaded_path and self._last_loaded_path != track.path:
                self.save_current_position(target_path=self._last_loaded_path)

            self._stream_play_generation += 1
            generation = self._stream_play_generation
            self._current_stream_chapters = list(getattr(track, "chapters", [])) if getattr(track, "chapters", None) else []

            if resume_pos is not None:
                self._pending_resume_pos = resume_pos if resume_pos >= 0.5 else None
            else:
                cfg = getConfig()
                if cfg.get("resumePosition", True) and not track.metadata.get("is_live"):
                    saved_pos = self.state_store.get_position(
                        track.path,
                        current_duration=getattr(track, "duration", None)
                    )
                    self._pending_resume_pos = saved_pos if (saved_pos and saved_pos >= 1.0) else None
                else:
                    self._pending_resume_pos = None

            orig_idx = self.playlist.current_index + 1
            total = self.playlist.count

        if not getattr(self, "_silence_resume_announcement", False):
            self.speech.speak(_("Loading: %s") % track.display_name)
        threading.Thread(
            target=self._resolve_and_play_stream,
            args=(track, generation, orig_idx, total),
            daemon=True,
            name="HeadlessPlayer-StreamResolve"
        ).start()
        return True

    def _resolve_and_play_stream(self, track: Track, generation: int, orig_idx: int, total: int) -> None:
        """Background worker: resolves stream URL and loads into mpv engine."""
        with self._lock:
            if generation != self._stream_play_generation or self._is_terminating:
                return

        try:
            info = stream_engine.resolve_stream(track.path)
        except Exception as e:
            logger.error("Stream resolution failed for %s: %s", track.path, e)
            with self._lock:
                stale = generation != self._stream_play_generation
                if not stale:
                    self._is_resolving_stream = False
                    self._resolving_track_path = None
            if not stale:
                self.engine.stop()
                err_str = str(e)
                if getattr(stream_engine, "is_bot_error", lambda s: False)(err_str) or stream_engine.is_cookie_error(err_str) or "bot" in err_str.lower():
                    self.speech.speak(self._stream_error_message(e))
                else:
                    self.speech.speak(_(
                        "Could not play this stream. Check your internet connection, "
                        "or update yt-dlp from HeadlessPlayer settings."
                    ))
            return

        with self._lock:
            if generation != self._stream_play_generation or self._is_terminating:
                return

            self._is_resolving_stream = False
            self._resolving_track_path = None

            if info.get("title") and (not track.title or track.title == track.path):
                track.title = info["title"]
            if info.get("duration"):
                track.duration = float(info["duration"])
            if info.get("is_live"):
                track.metadata["is_live"] = True
                self._pending_resume_pos = None

            if info.get("chapters"):
                track.chapters = list(info["chapters"])
                track.metadata["chapters"] = list(info["chapters"])
                self._current_stream_chapters = list(info["chapters"])
            else:
                self._current_stream_chapters = []

            success = self.engine.load_stream(info["stream_url"], info.get("http_headers"))
            if success:
                self._last_loaded_path = track.path
                self.state_store.save_recent_file(track.path)
                self._load_sponsor_segments_for_url(track.path or info.get("webpage_url") or info.get("id"))

                self._current_stream_info = dict(info)
                self._stream_audio_tracks = list(info.get("audio_tracks", []))
                self._stream_audio_track_idx = 0
                self.speech.announce_track(orig_idx, total, track.display_name)
                self._check_stream_queue_auto_extend()
                self._prefetch_next_stream_track()
            else:
                auto_retries = getattr(self, "_stream_auto_retries", 0)
                if auto_retries < 3:
                    self._stream_auto_retries = auto_retries + 1
                    try:
                        stream_engine.clear_resolve_cache()
                    except Exception:
                        pass
                    self._silence_resume_announcement = True
                    self.speech.speak(_("Reconnecting..."))
                    self.play_track(track)
                    return
                self.speech.speak(_("Playback engine failed to start."))

    def _prefetch_next_stream_track(self) -> Optional[threading.Thread]:
        """Asynchronously pre-resolves the next online stream track in background."""
        with self._lock:
            if not self.playlist or self.playlist.is_empty():
                return None
            cur_idx = self.playlist.current_index
            total = self.playlist.count
            if cur_idx + 1 >= total:
                return None
            next_t = self.playlist.get_track_at(cur_idx + 1)
            if not next_t or not getattr(next_t, "is_stream", False) or not next_t.path:
                return None
            target_path = next_t.path

        def worker(path: str) -> None:
            try:
                stream_engine.resolve_stream(path)
            except Exception as e:
                logger.debug("Background stream pre-fetch ignored error for %s: %s", path, e)

        t = threading.Thread(
            target=worker,
            args=(target_path,),
            daemon=True,
            name="HeadlessPlayer-StreamPrefetch"
        )
        t.start()
        if "unittest" in sys.modules:
            t.join(timeout=0.2)
        return t

    def _current_track_is_live_stream(self, path: Optional[str] = None) -> bool:
        if path:
            for t in getattr(self.playlist, "_tracks", []):
                if getattr(t, "path", None) == path:
                    return bool(getattr(t, "is_stream", False) and getattr(t, "metadata", {}).get("is_live"))
        cur = self.playlist.get_current_track()
        return bool(cur and getattr(cur, "is_stream", False) and cur.metadata.get("is_live"))

    def _on_sponsor_skipped(self, category: str, start: float, end: float) -> None:
        """Invoked when engine automatically skips a SponsorBlock segment."""
        logger.info("Controller: SponsorBlock skipped %s segment [%.2f -> %.2f]", category, start, end)
        self.speech.announce_sponsor_skipped(category)

    def _load_sponsor_segments_for_url(self, url: str) -> None:
        """Fetches SponsorBlock skip segments asynchronously for YouTube URLs/IDs."""
        if not self.engine:
            return
        self.engine.clear_sponsor_segments()
        if not getConfigValue("sponsorBlockEnabled", True):
            return

        video_id = extract_youtube_id(url)
        if not video_id:
            return

        current_gen = self._stream_play_generation

        def worker(vid: str, gen: int) -> None:
            try:
                cats_str = str(getConfigValue("sponsorBlockCategories", "sponsor,selfpromo,interaction,intro,outro"))
                cats = [c.strip() for c in cats_str.split(",") if c.strip()]
                segs = fetch_sponsor_segments(vid, categories=cats)
                with self._lock:
                    if gen != self._stream_play_generation:
                        return
                    if segs and self.engine:
                        self.engine.set_sponsor_segments(segs)
            except Exception as e:
                logger.debug("Error in SponsorBlock worker for %s: %s", vid, e)

        threading.Thread(target=worker, args=(video_id, current_gen), daemon=True, name="HeadlessPlayer-SponsorBlock").start()
