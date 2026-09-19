# -*- coding: utf-8 -*-
from __future__ import annotations

from .process import (
    MpvProcess,
    find_mpv_binary,
    get_default_mpv_args,
    is_64bit_os,
    get_system_architecture,
    DEFAULT_PIPE_NAME,
    HEADLESS_FLAGS,
)
from .ipc import (
    WinNamedPipeClient,
    OVERLAPPED,
)
from .diagnostics import (
    check_mpv_binary,
    check_stream_engine,
    check_database,
    check_translations,
    run_full_diagnostics,
    generate_diagnostic_report_text,
    copy_diagnostic_report_to_clipboard,
    HealthStatus,
)
from .speech import (
    SpeechFeedback,
    get_speech_feedback,
    set_speech_feedback,
    SEEK_DEBOUNCE_INTERVAL,
    LANGUAGE_NAMES,
)
from .engine import (
    HeadlessEngine,
    is_supported_media_file,
    SPEED_PRESETS,
    ALL_SUPPORTED_EXTENSIONS,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    SUPPORTED_PLAYLIST_EXTENSIONS,
)
from .controller import PlayerController, get_controller, set_controller

__all__ = [
    "MpvProcess",
    "find_mpv_binary",
    "get_default_mpv_args",
    "is_64bit_os",
    "get_system_architecture",
    "DEFAULT_PIPE_NAME",
    "HEADLESS_FLAGS",
    "WinNamedPipeClient",
    "OVERLAPPED",
    "check_mpv_binary",
    "check_stream_engine",
    "check_database",
    "check_translations",
    "run_full_diagnostics",
    "generate_diagnostic_report_text",
    "copy_diagnostic_report_to_clipboard",
    "HealthStatus",
    "SpeechFeedback",
    "get_speech_feedback",
    "set_speech_feedback",
    "SEEK_DEBOUNCE_INTERVAL",
    "LANGUAGE_NAMES",
    "HeadlessEngine",
    "is_supported_media_file",
    "SPEED_PRESETS",
    "ALL_SUPPORTED_EXTENSIONS",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "SUPPORTED_VIDEO_EXTENSIONS",
    "SUPPORTED_PLAYLIST_EXTENSIONS",
    "PlayerController",
    "get_controller",
    "set_controller",
]
