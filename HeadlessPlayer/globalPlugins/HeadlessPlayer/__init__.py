# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Global Plugin.
Headless, privacy-oriented media player add-on for NVDA operated via modal keyboard capture.
Coordinates lifecycle, translation, configuration registration, settings panel category,
and global toggle gesture bindings.
"""

from __future__ import annotations
import logging
import os
import sys
from typing import Any, Dict, Optional

# 1. Initialize Translations
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

# 2. NVDA Base Handlers & Decorators
try:
    import globalPluginHandler
    _BaseGlobalPlugin = globalPluginHandler.GlobalPlugin
except Exception:
    class _BaseGlobalPlugin:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass
        def terminate(self) -> None:
            pass

try:
    import scriptHandler
    script = scriptHandler.script
except Exception:
    def script(*args: Any, **kwargs: Any) -> Any:  # type: ignore
        def decorator(fn: Any) -> Any:
            return fn
        return decorator

try:
    import gui
    _NVDA_GUI_AVAILABLE = True
except Exception:
    gui = None
    _NVDA_GUI_AVAILABLE = False

# 3. Import HeadlessPlayer Subsystems
from .config_spec import initializeConfig, getConfig, setConfigValue
from .engine import HeadlessEngine, ALL_SUPPORTED_EXTENSIONS, SPEED_PRESETS, is_supported_media_file
from .ipc_client import WinNamedPipeClient
from .mpv_process import MpvProcess, find_mpv_binary, DEFAULT_PIPE_NAME
from .playlist import Playlist, Track, RepeatMode
from .state_store import StateStore, get_state_store
from .tones_helper import ToneCueManager, tone_manager
from .speech_feedback import SpeechFeedback, get_speech_feedback, set_speech_feedback
from .input_layer import ModalInputLayer
from .controller import PlayerController, get_controller, set_controller
from .settings_panel import HeadlessPlayerSettingsPanel

logger = logging.getLogger("HeadlessPlayer")


class GlobalPlugin(_BaseGlobalPlugin):
    """
    Headless Media Player NVDA Global Plugin.
    Manages add-on lifecycle, modal keyboard capture registration, and settings panel integration.
    """

    scriptCategory = _("Headless Media Player")

    __gestures__ = {
        "kb:NVDA+control+shift+p": "togglePlayerMode",
        "kb:insert+control+shift+p": "togglePlayerMode",
        "kb:capslock+control+shift+p": "togglePlayerMode",
        "kb:NVDA+control+windows+e": "addFromExplorer",
        "kb:insert+control+windows+e": "addFromExplorer",
        "kb:capslock+control+windows+e": "addFromExplorer",
        "kb:mediaplaypause": "mediaPlayPause",
        "kb:medianexttrack": "mediaNextTrack",
        "kb:mediaprevtrack": "mediaPrevTrack",
        "kb:mediastop": "mediaStop",
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        logger.info("Initializing HeadlessPlayer GlobalPlugin...")

        # 1. Initialize Configuration Specification
        try:
            initializeConfig()
        except Exception as e:
            logger.warning("Failed to initialize config spec: %s", e)

        # 2. Instantiate Components
        self.state_store: StateStore = get_state_store()
        self.tone_manager: ToneCueManager = tone_manager
        self.speech: SpeechFeedback = get_speech_feedback()
        self.playlist: Playlist = Playlist()
        self.engine: HeadlessEngine = HeadlessEngine()
        self.input_layer: ModalInputLayer = ModalInputLayer(tone_mgr=self.tone_manager)

        # 3. Instantiate Central Controller
        self.controller: PlayerController = PlayerController(
            engine=self.engine,
            playlist=self.playlist,
            state_store=self.state_store,
            tone_mgr=self.tone_manager,
            speech_feedback=self.speech,
            input_layer=self.input_layer
        )
        set_controller(self.controller)

        # 4. Register Modal Keyboard Capture Decider
        try:
            self.input_layer.register()
        except Exception as e:
            logger.error("Failed to register ModalInputLayer: %s", e)

        # 5. Register Settings Panel Category in NVDA Settings Dialog
        self._register_settings_panel()

        logger.info("HeadlessPlayer GlobalPlugin initialized successfully.")

    def _register_settings_panel(self) -> None:
        """Registers HeadlessPlayerSettingsPanel with NVDA Settings dialog."""
        gui_mod = sys.modules.get("gui") or gui
        if gui_mod and hasattr(gui_mod, "NVDASettingsDialog"):
            categoryClasses = getattr(gui_mod.NVDASettingsDialog, "categoryClasses", None)
            if isinstance(categoryClasses, list) and HeadlessPlayerSettingsPanel not in categoryClasses:
                categoryClasses.append(HeadlessPlayerSettingsPanel)
                logger.info("Registered HeadlessPlayerSettingsPanel category in NVDA Settings.")

    def _unregister_settings_panel(self) -> None:
        """Removes HeadlessPlayerSettingsPanel from NVDA Settings dialog."""
        gui_mod = sys.modules.get("gui") or gui
        if gui_mod and hasattr(gui_mod, "NVDASettingsDialog"):
            categoryClasses = getattr(gui_mod.NVDASettingsDialog, "categoryClasses", None)
            if isinstance(categoryClasses, list) and HeadlessPlayerSettingsPanel in categoryClasses:
                categoryClasses.remove(HeadlessPlayerSettingsPanel)
                logger.info("Unregistered HeadlessPlayerSettingsPanel from NVDA Settings.")

    @script(
        description=_("Toggles Headless Media Player keyboard capture mode."),
        category=_("Headless Media Player"),
        gesture="kb:NVDA+control+shift+p"
    )
    def script_togglePlayerMode(self, gesture: Any) -> None:
        """Toggles modal Player Mode on and off."""
        if self.input_layer:
            self.input_layer.toggle_player_mode()

    @script(
        description=_("Directly loads and plays selected or focused media files/folders from Windows Explorer."),
        category=_("Headless Media Player"),
        gesture="kb:NVDA+control+windows+e"
    )
    def script_addFromExplorer(self, gesture: Any) -> None:
        """Directly loads and plays active media selection from Windows Explorer."""
        if self.controller:
            self.controller.load_from_explorer()

    @script(
        description=_("Plays or pauses Headless Media Player playback from anywhere."),
        category=_("Headless Media Player"),
        gesture="kb:mediaplaypause"
    )
    def script_mediaPlayPause(self, gesture: Any) -> None:
        """Global Media Play/Pause key handler."""
        if self.controller and (self.controller.engine.is_loaded or not self.controller.playlist.is_empty()):
            self.controller.toggle_play_pause()
        else:
            gesture.send()

    @script(
        description=_("Plays the next track in Headless Media Player playlist from anywhere."),
        category=_("Headless Media Player"),
        gesture="kb:medianexttrack"
    )
    def script_mediaNextTrack(self, gesture: Any) -> None:
        """Global Media Next Track key handler."""
        if self.controller and not self.controller.playlist.is_empty():
            self.controller.next_track(manual=True)
        else:
            gesture.send()

    @script(
        description=_("Plays the previous track in Headless Media Player playlist from anywhere."),
        category=_("Headless Media Player"),
        gesture="kb:mediaprevtrack"
    )
    def script_mediaPrevTrack(self, gesture: Any) -> None:
        """Global Media Previous Track key handler."""
        if self.controller and not self.controller.playlist.is_empty():
            self.controller.prev_track()
        else:
            gesture.send()

    @script(
        description=_("Stops Headless Media Player playback from anywhere."),
        category=_("Headless Media Player"),
        gesture="kb:mediastop"
    )
    def script_mediaStop(self, gesture: Any) -> None:
        """Global Media Stop key handler."""
        if self.controller and (self.controller.engine.is_loaded or not self.controller.playlist.is_empty()):
            self.controller.stop()
        else:
            gesture.send()

    def terminate(self) -> None:
        """
        Clean plugin termination:
        Deactivates Player Mode, unregisters input decider, terminates controller,
        saves state, and removes settings panel category.
        """
        logger.info("Terminating HeadlessPlayer GlobalPlugin...")

        # 1. Deactivate & Unregister Modal Input Interception
        if self.input_layer:
            try:
                if self.input_layer.is_active:
                    self.input_layer.set_player_mode(False, announce=False)
                self.input_layer.unregister()
            except Exception as e:
                logger.debug("Error unregistering input layer: %s", e)

        # 2. Terminate Controller and mpv Subprocess
        if self.controller:
            try:
                self.controller.terminate()
            except Exception as e:
                logger.debug("Error terminating controller: %s", e)

        # 3. Clear singleton references
        set_controller(None)

        # 4. Unregister Settings Panel Category
        self._unregister_settings_panel()

        try:
            super().terminate()
        except Exception:
            pass

        logger.info("HeadlessPlayer GlobalPlugin terminated cleanly.")


__all__ = [
    "GlobalPlugin",
    "PlayerController",
    "HeadlessEngine",
    "ModalInputLayer",
    "SpeechFeedback",
    "Playlist",
    "Track",
    "RepeatMode",
    "StateStore",
    "ToneCueManager",
    "HeadlessPlayerSettingsPanel",
    "WinNamedPipeClient",
    "MpvProcess",
    "find_mpv_binary",
    "DEFAULT_PIPE_NAME",
    "ALL_SUPPORTED_EXTENSIONS",
    "SPEED_PRESETS",
    "is_supported_media_file",
    "get_controller",
    "set_controller",
    "get_speech_feedback",
    "set_speech_feedback",
    "get_state_store",
    "initializeConfig",
    "getConfig",
    "setConfigValue",
    "_",
]
