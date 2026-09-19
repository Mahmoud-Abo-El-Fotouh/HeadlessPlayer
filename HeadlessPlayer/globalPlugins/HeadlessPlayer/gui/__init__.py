# -*- coding: utf-8 -*-
from __future__ import annotations

from .dialogs import (
    prompt_open_file_dialog,
    prompt_open_files_dialog,
    prompt_open_folder_dialog,
    generate_help_text,
    prompt_help_dialog,
    set_dialog_test_handler,
)
from .key_capture import (
    KeyCaptureDialog,
    ACTION_DISPLAY_NAMES,
    ACTION_CATEGORIES,
    ACTION_CATEGORY_MAP,
    get_all_key_suggestions,
    ARABIC_TO_ENGLISH_KEY_MAP,
)
from .shortcuts_dialog import (
    HeadlessPlayerShortcutsDialog,
)
from .updater_dialog import (
    YtdlpUpdateDialog,
)
from .settings_panel import (
    HeadlessPlayerSettingsPanel,
    SPEED_CHOICES,
    REPEAT_CHOICES,
    STREAM_QUALITY_CHOICES,
    YTDLP_CHANNEL_CHOICES,
)

__all__ = [
    "prompt_open_file_dialog",
    "prompt_open_files_dialog",
    "prompt_open_folder_dialog",
    "generate_help_text",
    "prompt_help_dialog",
    "set_dialog_test_handler",
    "KeyCaptureDialog",
    "ACTION_DISPLAY_NAMES",
    "ACTION_CATEGORIES",
    "ACTION_CATEGORY_MAP",
    "get_all_key_suggestions",
    "ARABIC_TO_ENGLISH_KEY_MAP",
    "HeadlessPlayerShortcutsDialog",
    "YtdlpUpdateDialog",
    "HeadlessPlayerSettingsPanel",
    "SPEED_CHOICES",
    "REPEAT_CHOICES",
    "STREAM_QUALITY_CHOICES",
    "YTDLP_CHANNEL_CHOICES",
]
