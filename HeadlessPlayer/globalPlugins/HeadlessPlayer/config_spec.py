# -*- coding: utf-8 -*-
"""
HeadlessPlayer Configuration Specification and Persistence Layer.
Registers the [headlessPlayer] configuration schema with NVDA's config manager.
"""

from typing import Any, Dict

CONFIG_SECTION = "headlessPlayer"

# ConfigObj specification definition for NVDA's configObj validator
CONFIG_SPEC_STRING = """
[headlessPlayer]
# Speech Announcements Verbosity
announceVolume = boolean(default=True)
announceSeek = boolean(default=True)
announceSpeed = boolean(default=True)
announceTrack = boolean(default=True)
announceLoop = boolean(default=True)
announceChapter = boolean(default=True)

# Seek Jump Step Sizes (in seconds)
seekStepNormal = integer(default=5, min=1, max=3600)
seekStepSlow = integer(default=1, min=1, max=3600)
seekStepFast = integer(default=30, min=1, max=3600)
seekStepUltrafast = integer(default=300, min=5, max=7200)

# Playback Defaults & Options
defaultSpeed = float(default=1.0, min=0.25, max=5.0)
defaultRepeatMode = string(default="off")
defaultAutoNext = boolean(default=True)
resumePosition = boolean(default=True)
playModalTones = boolean(default=False)
autoEnterPlayerMode = boolean(default=True)

# Audio & Engine Settings
mpvExecutablePath = string(default="")
namedPipeName = string(default="\\\\.\\pipe\\nvda_headless_player")
volume = integer(default=100, min=0, max=150)
lastPlaybackPath = string(default="")

# YouTube & Online Streaming (yt-dlp)
ytdlpCookiesBrowser = string(default="none")
ytdlpCookiesFile = string(default="")
searchResultsCount = integer(default=20, min=5, max=50)
maxStreamPlaylistItems = integer(default=300, min=10, max=1000)
"""

DEFAULT_CONFIG: Dict[str, Any] = {
    "announceVolume": True,
    "announceSeek": True,
    "announceSpeed": True,
    "announceTrack": True,
    "announceLoop": True,
    "announceChapter": True,
    "seekStepNormal": 5,
    "seekStepSlow": 1,
    "seekStepFast": 30,
    "seekStepUltrafast": 300,
    "defaultSpeed": 1.0,
    "defaultRepeatMode": "off",
    "defaultAutoNext": True,
    "resumePosition": True,
    "playModalTones": False,
    "autoEnterPlayerMode": True,
    "mpvExecutablePath": "",
    "namedPipeName": r"\\.\pipe\nvda_headless_player",
    "volume": 100,
    "lastPlaybackPath": "",
    "ytdlpCookiesBrowser": "none",
    "ytdlpCookiesFile": "",
    "searchResultsCount": 20,
    "maxStreamPlaylistItems": 300,
}

# In-memory fallback dictionary for when running outside NVDA (e.g. unit tests)
_fallback_config: Dict[str, Any] = dict(DEFAULT_CONFIG)


def initializeConfig() -> None:
    """
    Registers the HeadlessPlayer configuration specification into NVDA's config engine.
    Safe to invoke both within NVDA runtime and in headless/standalone test environments.
    """
    try:
        import config
        from configobj import ConfigObj
        from validate import Validator
        try:
            from logHandler import log
        except ImportError:
            log = None

        spec = ConfigObj(CONFIG_SPEC_STRING.strip().splitlines(), list_values=False, encoding="utf-8")
        if hasattr(config, "conf") and hasattr(config.conf, "spec"):
            config.conf.spec[CONFIG_SECTION] = spec[CONFIG_SECTION]

            # Validate against current configuration to populate default values
            validator = Validator()
            config.conf.validate(validator, copy=True, section=CONFIG_SECTION)
            if log:
                log.info("HeadlessPlayer: configuration initialized successfully.")
    except Exception:
        # Fallback when NVDA config module is not available
        pass


def getConfig() -> Dict[str, Any]:
    """
    Returns the active HeadlessPlayer configuration dictionary for the active NVDA profile,
    or the in-memory fallback dictionary if NVDA config is not running.
    """
    try:
        import config
        if hasattr(config, "conf"):
            if CONFIG_SECTION not in config.conf:
                config.conf[CONFIG_SECTION] = dict(DEFAULT_CONFIG)
            return config.conf[CONFIG_SECTION]
    except Exception:
        pass
    return _fallback_config


def setConfigValue(key: str, value: Any) -> None:
    """
    Sets a specific configuration key in the active configuration dictionary.
    """
    cfg = getConfig()
    cfg[key] = value


def getConfigValue(key: str, default: Any = None) -> Any:
    """
    Gets a specific configuration key with fallback to DEFAULT_CONFIG or provided default.
    """
    cfg = getConfig()
    if key in cfg:
        return cfg[key]
    if default is not None:
        return default
    return DEFAULT_CONFIG.get(key)


def saveConfig() -> None:
    """
    Saves the global NVDA configuration to disk if running inside NVDA.
    """
    try:
        import config
        if hasattr(config, "conf") and hasattr(config.conf, "save"):
            config.conf.save()
    except Exception:
        pass


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
    "account_feed": "p",
    "exit_mode": "escape",
}


def parseKeymapKeys(value: str) -> list:
    """
    Parses a keymap entry into its list of key gestures.
    Each action may have multiple shortcuts separated by commas,
    e.g. 'pagedown,tab' assigns both Page Down and Tab to Next Track.
    """
    if not value or not isinstance(value, str):
        return []
    return [k.strip().lower() for k in value.split(",") if k.strip()]


def getKeymap() -> Dict[str, str]:
    """
    Returns the active keymap for Player Mode, merging user customizations over DEFAULT_KEYMAP.
    """
    keymap = dict(DEFAULT_KEYMAP)
    cfg = getConfig()
    for action in DEFAULT_KEYMAP:
        config_key = f"key_{action}"
        if config_key in cfg and isinstance(cfg[config_key], str) and cfg[config_key].strip():
            keymap[action] = cfg[config_key].strip().lower()
    return keymap


def setKeymap(custom_map: Dict[str, str]) -> None:
    """
    Updates custom keymap mappings in active configuration.
    """
    cfg = getConfig()
    for action, key in custom_map.items():
        if action in DEFAULT_KEYMAP:
            config_key = f"key_{action}"
            cfg[config_key] = key.strip().lower()


def resetKeymap() -> None:
    """
    Resets all custom player mode shortcut keybindings to factory defaults.
    """
    cfg = getConfig()
    for action in DEFAULT_KEYMAP:
        config_key = f"key_{action}"
        if config_key in cfg:
            del cfg[config_key]

