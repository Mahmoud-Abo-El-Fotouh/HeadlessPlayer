# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Clip exporter (D / Shift+D).

Cuts the A-B selection (or the whole item) of the playing media - a local
file, a YouTube item or any online stream - and saves it as MP3, M4A or an
MP4 video ready for stories / chats. Everything is done by the bundled mpv
encoder in a background thread; no ffmpeg is used.

Sources:
  local   - the file mpv is playing
  youtube - the InnerTube renditions (audio track + every video quality),
            read through the local chunking proxy
  stream  - any other direct URL (radio, mp3 link)
"""

from __future__ import annotations
import logging
import os
import re
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .utils import log_debug, log_exception

logger = logging.getLogger("HeadlessPlayer.ClipExporter")

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

FORMATS = ("mp3", "m4a", "mp4")
QUALITIES = ("high", "story")
STORY_MAX_HEIGHT = 720
WAVEFORM_SIZE = "720x1280"
WAVEFORM_GRAPH = f"--lavfi-complex=[aid1]asplit[ao][a2];[a2]showwaves=s={WAVEFORM_SIZE}:mode=cline:colors=white:rate=30,format=yuv420p[vo]"


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _cfg() -> Dict[str, Any]:
    try:
        from .config_spec import getConfig
        return getConfig()
    except Exception:
        return {}


def _set(key: str, value: Any) -> None:
    try:
        from .config_spec import setConfigValue
        setConfigValue(key, value)
    except Exception:
        pass


def get_export_folder() -> str:
    folder = str(_cfg().get("exportFolder", "") or "").strip().strip('"')
    if folder:
        folder = os.path.expandvars(os.path.expanduser(folder))
    else:
        folder = os.path.join(os.path.expanduser("~"), "Downloads", "HeadlessPlayer")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        logger.error("Cannot create export folder %s: %s", folder, e)
    return folder


def get_default_settings() -> Dict[str, Any]:
    c = _cfg()
    fmt = str(c.get("exportFormat", "mp3") or "mp3").lower()
    if fmt not in FORMATS:
        fmt = "mp3"
    q = str(c.get("exportQuality", "high") or "high").lower()
    if q not in QUALITIES:
        q = "high"
    return {
        "format": fmt,
        "quality": q,
        "audio_to_video": bool(c.get("exportAudioToVideo", False)),
        "video_quality": str(c.get("exportVideoQuality", "") or ""),
        "folder": get_export_folder(),
        "auto_copy": bool(c.get("exportAutoCopy", True)),
    }


def remember_settings(settings: Dict[str, Any]) -> None:
    _set("exportFormat", settings.get("format", "mp3"))
    _set("exportQuality", settings.get("quality", "high"))
    _set("exportAudioToVideo", bool(settings.get("audio_to_video", False)))
    _set("exportVideoQuality", str(settings.get("video_quality", "") or ""))
    if settings.get("folder"):
        _set("exportFolder", settings["folder"])


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str, max_len: int = 100) -> str:
    name = _INVALID_CHARS.sub(" ", name or "").strip().rstrip(".")
    name = re.sub(r"\s+", " ", name)
    return (name or "clip")[:max_len].strip()


def fmt_clock(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}-{m:02d}-{s:02d}" if h else f"{m:02d}-{s:02d}"


def suggest_filename(title: str, start: Optional[float], end: Optional[float], ext: str) -> str:
    base = safe_filename(title).replace(" ", "_")
    if start is not None and end is not None:
        base = f"{base}_{fmt_clock(start)}_to_{fmt_clock(end)}"
    return f"{base}.{ext}"


def unique_path(folder: str, filename: str) -> str:
    root, ext = os.path.splitext(filename)
    path = os.path.join(folder, filename)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{root} ({n}){ext}")
        n += 1
    return path


# ---------------------------------------------------------------------------
# Source description
# ---------------------------------------------------------------------------

class ExportSource:
    """
    What is being exported.
      kind: "local" | "youtube" | "stream"
      path: local file path or page/stream URL
      title: display title
      has_video: whether the source carries a video track
      audio_url: playable audio input for mpv (proxied for YouTube)
      video_options: [(label, video_url_proxied, height)] for YouTube
      duration: seconds (0 if unknown)
    """

    def __init__(self, kind: str, path: str, title: str, has_video: bool, audio_url: str = "",
                 video_options: Optional[List[Tuple[str, str, int]]] = None, duration: float = 0.0) -> None:
        self.kind = kind
        self.path = path
        self.title = title
        self.has_video = has_video
        self.audio_url = audio_url
        self.video_options = list(video_options or [])
        self.duration = float(duration or 0.0)


_VIDEO_EXT = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".vob", ".ogv", ".3gp", ".mpg", ".mpeg", ".m4v"}


def describe_source(path: str, title: str = "", stream_info: Optional[Dict[str, Any]] = None) -> ExportSource:
    """Builds an ExportSource for a local file, a YouTube page URL or a direct stream URL."""
    low = (path or "").lower()
    if not low.startswith(("http://", "https://")):
        ext = os.path.splitext(low)[1]
        return ExportSource("local", path, title or os.path.splitext(os.path.basename(path))[0], ext in _VIDEO_EXT)

    # Try InnerTube backend if bundled (Plus Edition)
    has_it = False
    try:
        from . import innertube_backend as it
        from . import stream_proxy
        has_it = it.is_youtube_url(path)
    except (ImportError, AttributeError):
        has_it = False

    if has_it:
        video_id = it.extract_video_id(path)
        if not video_id:
            raise RuntimeError("not a YouTube video URL")
        data, client = it._player_response(video_id)
        vd = data.get("videoDetails") or {}
        sd = data.get("streamingData") or {}
        if vd.get("isLive"):
            raise RuntimeError("LIVE")
        ua = client.user_agent
        adaptive = [f for f in (sd.get("adaptiveFormats") or []) if isinstance(f, dict) and f.get("url")]
        combined = [f for f in (sd.get("formats") or []) if isinstance(f, dict) and f.get("url")]

        def length(f: Dict[str, Any]) -> int:
            try:
                return int(f.get("contentLength") or 0)
            except (TypeError, ValueError):
                return 0

        def bitrate(f: Dict[str, Any]) -> int:
            try:
                return int(f.get("averageBitrate") or f.get("bitrate") or 0)
            except (TypeError, ValueError):
                return 0

        auds = [f for f in adaptive if str(f.get("mimeType", "")).startswith("audio/")]
        default_lang = ""
        for f in auds:
            if (f.get("audioTrack") or {}).get("audioIsDefault"):
                default_lang = str((f.get("audioTrack") or {}).get("id") or "")
        if default_lang:
            auds = [f for f in auds if str((f.get("audioTrack") or {}).get("id") or "") == default_lang]
        # prefer AAC (m4a) for widest compatibility, highest bitrate
        auds.sort(key=lambda f: (1 if "mp4" in str(f.get("mimeType", "")) else 0, bitrate(f)), reverse=True)
        audio_url = ""
        if stream_info and stream_info.get("direct_url"):
            # the audio that is playing right now (already proxied by the player)
            audio_url = str(stream_info.get("stream_url") or "")
        if not audio_url and auds:
            a = auds[0]
            audio_url = stream_proxy.register(str(a["url"]), ua, length(a), str(a.get("mimeType") or ""), video_id)

        video_options: List[Tuple[str, str, int]] = []
        seen = set()
        vids = [f for f in adaptive if str(f.get("mimeType", "")).startswith("video/")]
        vids.sort(key=lambda f: (int(f.get("height") or 0), 1 if "avc1" in str(f.get("mimeType", "")) else 0, bitrate(f)), reverse=True)
        for f in vids:
            h = int(f.get("height") or 0)
            q = str(f.get("qualityLabel") or f"{h}p")
            if h <= 0 or q in seen:
                continue
            seen.add(q)
            codec = "H.264" if "avc1" in str(f.get("mimeType", "")) else ("VP9" if "vp" in str(f.get("mimeType", "")) else ("AV1" if "av01" in str(f.get("mimeType", "")) else ""))
            label = f"{q} ({codec})" if codec else q
            purl = stream_proxy.register(str(f["url"]), ua, length(f), str(f.get("mimeType") or ""), video_id)
            video_options.append((label, purl, h))
        for f in combined:
            h = int(f.get("height") or 0)
            q = str(f.get("qualityLabel") or f"{h}p")
            label = _("%s (video with audio)") % q
            if label in seen:
                continue
            seen.add(label)
            purl = stream_proxy.register(str(f["url"]), ua, length(f), str(f.get("mimeType") or ""), video_id)
            video_options.append((label, purl, h))
        try:
            dur = float(vd.get("lengthSeconds") or 0)
        except (TypeError, ValueError):
            dur = 0.0
        return ExportSource("youtube", path, title or str(vd.get("title") or video_id), bool(video_options), audio_url, video_options, dur)

    # Standard online stream resolution (Store Edition or non-YouTube stream URLs)
    audio_url = ""
    dur = 0.0
    if stream_info and stream_info.get("stream_url"):
        audio_url = str(stream_info["stream_url"])
        dur = float(stream_info.get("duration") or 0.0)
    else:
        try:
            from . import stream_engine
            res = stream_engine.resolve_stream(path)
            audio_url = str(res.get("stream_url") or "")
            dur = float(res.get("duration") or 0.0)
            if not title and res.get("title"):
                title = str(res["title"])
        except Exception:
            audio_url = path

    name = title or os.path.basename(path.split("?")[0]) or "stream"
    return ExportSource("stream", path, name, os.path.splitext(low.split("?")[0])[1] in _VIDEO_EXT, audio_url, [], dur)


# ---------------------------------------------------------------------------
# mpv command construction
# ---------------------------------------------------------------------------

def find_mpv() -> str:
    try:
        from .mpv_process import find_mpv_binary
        addon_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        return find_mpv_binary(str(_cfg().get("mpvExecutablePath", "") or ""), addon_root) or ""
    except Exception as e:
        logger.debug("find_mpv failed: %s", e)
        return ""


def _no_window() -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs["startupinfo"] = si
    return kwargs


def build_command(source: ExportSource, settings: Dict[str, Any], start: Optional[float], end: Optional[float], dest: str) -> List[str]:
    """
    settings: format (mp3|m4a|mp4), quality (high|story), audio_to_video (bool),
              video_quality (label from source.video_options or "")
    """
    mpv = find_mpv()
    if not mpv:
        raise RuntimeError("mpv not found")
    fmt = settings.get("format", "mp3")
    story = settings.get("quality", "high") == "story"
    # NOTE: never pass --ao/--vo here: they disable mpv's encoding outputs
    cmd: List[str] = [mpv, "--no-config", "--ytdl=no", "--really-quiet", "--no-terminal"]
    if start is not None:
        cmd.append(f"--start={float(start):.3f}")
    if end is not None:
        cmd.append(f"--end={float(end):.3f}")

    if fmt == "mp3":
        cmd += ["--no-video", "--oac=libmp3lame", "--oacopts=b=128k" if story else "--oacopts=b=192k"]
        inputs = [source.audio_url or source.path]
    elif fmt == "m4a":
        cmd += ["--no-video", "--oac=aac", "--oacopts=b=96k" if story else "--oacopts=b=160k"]
        inputs = [source.audio_url or source.path]
    else:  # mp4 video
        cmd += ["--ovc=libx264", "--oac=aac", "--oacopts=b=96k" if story else "--oacopts=b=160k"]
        cmd.append("--ovcopts=preset=veryfast,crf=28" if story else "--ovcopts=preset=veryfast,crf=21")
        cmd.append("--ofopts=movflags=+faststart")
        want_waveform = bool(settings.get("audio_to_video")) or not source.has_video
        if not want_waveform and source.kind == "youtube":
            label = str(settings.get("video_quality") or "")
            chosen = next((v for v in source.video_options if v[0] == label), None)
            if chosen is None:
                # default: best quality, capped at 720p for story exports
                cands = sorted(source.video_options, key=lambda v: v[2], reverse=True)
                if story:
                    cands = [v for v in cands if v[2] <= STORY_MAX_HEIGHT] or cands
                chosen = cands[0]
            combined = "with audio" in chosen[0] or "مع الصوت" in chosen[0]
            inputs = [chosen[1]]
            if not combined and source.audio_url:
                cmd.append(f"--audio-file={source.audio_url}")
            vf = [f"scale=-2:{STORY_MAX_HEIGHT}"] if (story and chosen[2] > STORY_MAX_HEIGHT) else []
            vf.append("format=yuv420p")  # H.264 players need 4:2:0
            cmd.append("--vf=lavfi=[" + ",".join(vf) + "]")
        elif not want_waveform:
            inputs = [source.path]
            vf = [f"scale=-2:'min({STORY_MAX_HEIGHT},ih)'"] if story else []
            vf.append("format=yuv420p")
            cmd.append("--vf=lavfi=[" + ",".join(vf) + "]")
        else:
            # audio-only source (or user choice): draw an animated waveform so
            # the clip can be posted as a story
            cmd.append(WAVEFORM_GRAPH)
            inputs = [source.audio_url or source.path]
    cmd.append(f"--o={dest}")
    cmd += inputs
    return cmd


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def export(source: ExportSource, settings: Dict[str, Any], start: Optional[float], end: Optional[float], filename: str, folder: str = "") -> str:
    """Runs the export synchronously (call from a worker thread). Returns the saved path."""
    folder = folder or get_export_folder()
    os.makedirs(folder, exist_ok=True)
    fmt = settings.get("format", "mp3")
    if not filename.lower().endswith("." + fmt):
        filename = os.path.splitext(filename)[0] + "." + fmt
    dest = unique_path(folder, safe_filename(filename, 150))
    cmd = build_command(source, settings, start, end, dest)
    log_debug("EXPORT", "mpv export: %s", " ".join(c if len(c) < 90 else c[:90] + "..." for c in cmd))
    t0 = time.time()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=6 * 3600, **_no_window())
    ok = proc.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0
    if not ok:
        err = proc.stderr.decode("utf-8", "replace").strip()[-300:]
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        raise RuntimeError(err or f"mpv exited with code {proc.returncode}")
    log_debug("EXPORT", "saved %s (%d bytes) in %.1fs", dest, os.path.getsize(dest), time.time() - t0)
    return dest


def export_async(source: ExportSource, settings: Dict[str, Any], start: Optional[float], end: Optional[float],
                 filename: str, folder: str, on_done: Callable[[Optional[str], Optional[Exception]], None]) -> threading.Thread:
    def worker() -> None:
        try:
            path = export(source, settings, start, end, filename, folder)
            on_done(path, None)
        except Exception as e:
            log_exception("EXPORT", "export failed", e)
            on_done(None, e)

    t = threading.Thread(target=worker, daemon=True, name="HeadlessPlayer-Export")
    t.start()
    return t
