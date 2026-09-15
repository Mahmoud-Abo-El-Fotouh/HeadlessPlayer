# -*- coding: utf-8 -*-
from __future__ import annotations
"""
HeadlessPlayer Configuration Specification and Persistence Layer.
Manages all add-on settings, user preferences, and keyboard mappings
with high-performance, crash-safe HPDB database storage.
"""

from typing import Any, Dict
from .database import get_db_manager

CONFIG_SECTION = "headlessPlayer"

DEFAULT_CONFIG: Dict[str, Any] = {
    "announceVolume": True,
    "announceSeek": True,
    "announceSpeed": True,
    "announceTrack": True,
    "announceLoop": True,
    "announceChapter": True,
    "announceChapterAuto": True,
    "announcePlaylistTotalDuration": False,
    "remainingTimeAccountsForSpeed": True,
    "elapsedTimeAccountsForSpeed": True,
    "seekStepNormal": 5,

    "seekStepSlow": 1,
    "seekStepFast": 30,
    "seekStepUltrafast": 300,
    "defaultSpeed": 1.0,
    "defaultRepeatMode": "off",
    "defaultAutoNext": True,
    "resumePosition": True,
    "rememberPlaybackState": False,
    "autoEnterPlayerMode": True,
    "mpvExecutablePath": "",
    "namedPipeName": r"\\.\pipe\nvda_headless_player",
    "volume": 100,
    "lastPlaybackPath": "",
    "ytdlpCookiesBrowser": "none",
    "ytdlpCookiesFile": "",
    "searchResultsCount": 20,
    "maxStreamPlaylistItems": 300,
    "sponsorBlockEnabled": True,
    "announceSponsorSkip": True,
    "sponsorBlockCategories": "sponsor,selfpromo,interaction,intro,outro",
    "bassGain": 0.0,
    "streamAudioFormat": "best",
    "streamAudioQuality": "high",
    "exportFolder": "",
    "exportFormat": "mp3",
    "exportQuality": "high",
    "exportAudioToVideo": False,
    "exportVideoQuality": "",
    "exportAutoCopy": True,
    "recentsEnabled": True,
    "recentsMaxEntries": 30,
    "recentsKeepFiles": True,
    "recentsKeepFolders": True,
    "recentsKeepPlaylists": True,
    "recentsKeepStreams": True,
}

DEFAULT_KEYMAP: Dict[str, str] = {
    "play_pause": "space",
    "stop": "s",
    "mute": "m",
    "vol_up": "uparrow",
    "vol_down": "downarrow",
    "bass_up": "b",
    "bass_down": "shift+b",
    "seek_forward": "rightarrow",
    "seek_backward": "leftarrow",
    "seek_slow_forward": "alt+rightarrow",
    "seek_slow_backward": "alt+leftarrow",
    "seek_fast_forward": "control+rightarrow",
    "seek_fast_backward": "control+leftarrow",
    "seek_ultrafast_forward": "shift+rightarrow",
    "seek_ultrafast_backward": "shift+leftarrow",
    "speed_up": "control+uparrow",
    "speed_down": "control+downarrow",
    "speed_preset_up": "shift+uparrow",
    "speed_preset_down": "shift+downarrow",
    "next_track": "pagedown",
    "prev_track": "pageup",
    "track_start": "home",
    "track_end": "end",
    "first_track": "control+home",
    "last_track": "control+end",
    "next_chapter": "control+shift+rightarrow",
    "prev_chapter": "control+shift+leftarrow",
    "cycle_audio_track": "a",
    "point_a": "[",
    "point_b": "]",
    "toggle_repeat": "r",
    "clear_loop": "c",
    "open_file": "o",
    "open_folder": "f",
    "load_explorer": "e",
    "toggle_auto_next": "n",
    "toggle_shuffle": "z",
    "media_info": "i",
    "remaining_time": "control+i",
    "elapsed_time": "shift+i",
    "show_help": "h",
    "open_url": "u",
    "copy_url": "v",
    "copy_direct_url": "shift+v",
    "export_clip": "d",
    "quick_export": "shift+d",
    "account_feed": "p",
    "recent_playlist_next": "control+.",
    "recent_playlist_prev": "control+,",
    "recent_playlist_first": "control+shift+,",
    "recent_playlist_last": "control+shift+.",
    "recent_track_next": ".",
    "recent_track_prev": ",",
    "recent_track_first": "shift+,",
    "recent_track_last": "shift+.",
    "recent_delete": "delete",
    "open_settings": "control+shift+s",
    "close_player": "x",
    "exit_mode": "escape",
}


def initializeConfig() -> None:
    """
    Initializes the database manager and populates default settings if needed.
    """
    db = get_db_manager()
    # Populate any missing default settings
    for key, default_val in DEFAULT_CONFIG.items():
        if db.get_setting(key) is None:
            db.set_setting(key, default_val)
    # Populate any missing default keymap shortcuts
    for action, default_key in DEFAULT_KEYMAP.items():
        config_key = f"key_{action}"
        if db.get_setting(config_key) is None:
            db.set_setting(config_key, default_key)


def getConfig() -> Dict[str, Any]:
    """
    Returns the active HeadlessPlayer configuration dictionary from database,
    merged on top of DEFAULT_CONFIG defaults.
    """
    cfg = dict(DEFAULT_CONFIG)
    try:
        db = get_db_manager()
        stored = db.get_all_settings()
        cfg.update(stored)
    except Exception:
        pass
    return cfg


def setConfigValue(key: str, value: Any) -> None:
    """
    Sets a specific configuration key in the database.
    """
    try:
        db = get_db_manager()
        db.set_setting(key, value)
    except Exception:
        pass


def getConfigValue(key: str, default: Any = None) -> Any:
    """
    Gets a specific configuration key with fallback to DEFAULT_CONFIG or provided default.
    """
    try:
        db = get_db_manager()
        val = db.get_setting(key)
        if val is not None:
            return val
    except Exception:
        pass
    if default is not None:
        return default
    return DEFAULT_CONFIG.get(key)


def saveConfig() -> None:
    """
    Commits any pending configuration changes (database manager handles atomic persistence automatically).
    """
    pass


def parseKeymapKeys(value: str) -> list:
    """
    Parses a keymap entry into its list of key gestures.
    Each action may have multiple shortcuts separated by commas,
    e.g. 'pagedown,tab' assigns both Page Down and Tab to Next Track.
    Properly handles the comma key (',') and modifier combinations like 'control+,' or 'shift+,'.
    """
    if not value or not isinstance(value, str):
        return []
    val = value.strip().lower()
    if val == ",":
        return [","]
    if val.replace(" ", "").replace(",", "") == "":
        return []
    tokens = []
    current = []
    for char in val:
        if char == ",":
            if current and current[-1] == "+":
                current.append(char)
            elif not current:
                current.append(char)
            else:
                token = "".join(current).strip()
                if token:
                    tokens.append(token)
                current = []
        else:
            current.append(char)
    if current:
        token = "".join(current).strip()
        if token:
            tokens.append(token)
    return tokens


def getKeymap() -> Dict[str, str]:
    """
    Returns the active keymap for Player Mode, merging user customizations from database over DEFAULT_KEYMAP.
    Explicitly saved empty strings represent unassigned actions.
    """
    keymap = dict(DEFAULT_KEYMAP)
    try:
        db = get_db_manager()
        for action in DEFAULT_KEYMAP:
            config_key = f"key_{action}"
            val = db.get_setting(config_key)
            if val is None and action.startswith("recent_playlist_"):
                legacy_key = config_key.replace("recent_playlist_", "recent_container_")
                val = db.get_setting(legacy_key)
            if val is not None and isinstance(val, str):
                keymap[action] = val.strip().lower()
    except Exception:
        pass
    return keymap


def setKeymap(keymap: Dict[str, str]) -> None:
    """
    Saves customized keymap entries to database.
    """
    try:
        db = get_db_manager()
        mapping = {}
        for action, key_id in keymap.items():
            config_key = f"key_{action}"
            val = key_id.strip().lower() if isinstance(key_id, str) else ""
            mapping[config_key] = val
        db.set_settings_bulk(mapping)
    except Exception:
        pass


def resetKeymap() -> None:
    """
    Resets customized keymap entries in database to factory defaults.
    """
    try:
        db = get_db_manager()
        mapping = {}
        for action, default_val in DEFAULT_KEYMAP.items():
            config_key = f"key_{action}"
            mapping[config_key] = default_val
        db.set_settings_bulk(mapping)
    except Exception:
        pass
