"""
HeadlessPlayer NVDA Add-on - Modal Keyboard Interception Layer
Implements exclusive modal keyboard capture via inputCore.decide_executeGesture.
Captures, routes, and swallows all keystrokes during Player Mode to prevent
leakage to active background applications.
"""

from __future__ import annotations
import logging
from typing import Any, Callable, Dict, List, Optional, Set

# Attempt importing NVDA modules
try:
    import inputCore  # type: ignore
    _NVDA_INPUTCORE_AVAILABLE = True
except ImportError:
    inputCore = None  # type: ignore
    _NVDA_INPUTCORE_AVAILABLE = False

try:
    import ui  # type: ignore
    _NVDA_UI_AVAILABLE = True
except ImportError:
    ui = None  # type: ignore
    _NVDA_UI_AVAILABLE = False

try:
    import speech  # type: ignore
    _NVDA_SPEECH_AVAILABLE = True
except ImportError:
    speech = None  # type: ignore
    _NVDA_SPEECH_AVAILABLE = False

try:
    from . import _  # type: ignore
except (ImportError, ValueError):
    try:
        _ = _  # type: ignore
    except NameError:
        _ = lambda text: text

from .tones_helper import tone_manager, ToneCueManager

try:
    from .config_spec import getConfig
except ImportError:
    try:
        from config_spec import getConfig
    except ImportError:
        def getConfig() -> Dict[str, Any]:
            return {}

logger = logging.getLogger(__name__)

# Virtual Key Codes (Win32)
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21  # Page Up
VK_NEXT = 0x22   # Page Down
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28

# Digits 0-9
VK_0 = 0x30
VK_1 = 0x31
VK_2 = 0x32
VK_3 = 0x33
VK_4 = 0x34
VK_5 = 0x35
VK_6 = 0x36
VK_7 = 0x37
VK_8 = 0x38
VK_9 = 0x39

# Numpad 0-9
VK_NUMPAD0 = 0x60
VK_NUMPAD1 = 0x61
VK_NUMPAD2 = 0x62
VK_NUMPAD3 = 0x63
VK_NUMPAD4 = 0x64
VK_NUMPAD5 = 0x65
VK_NUMPAD6 = 0x66
VK_NUMPAD7 = 0x67
VK_NUMPAD8 = 0x68
VK_NUMPAD9 = 0x69

# Letters
VK_A = 0x41
VK_B = 0x42
VK_C = 0x43
VK_E = 0x45
VK_F = 0x46
VK_H = 0x48
VK_I = 0x49
VK_M = 0x4D
VK_N = 0x4E
VK_O = 0x4F
VK_P = 0x50
VK_R = 0x52
VK_S = 0x53
VK_U = 0x55
VK_V = 0x56
VK_Z = 0x5A
VK_TAB = 0x09

# OEM Bracket keys (English [ and ] / Arabic ج and د)
VK_OEM_4 = 0xDB  # 219 - English '[' / Arabic 'ج'
VK_OEM_6 = 0xDD  # 221 - English ']' / Arabic 'د'

# Key name alias sets for layout invariance
POINT_A_KEYS: Set[str] = {
    "[",
    "ج",
    "bracketleft",
    "leftbracket",
    "left bracket",
    "openbracket",
    "opening bracket",
}

POINT_B_KEYS: Set[str] = {
    "]",
    "د",
    "bracketright",
    "rightbracket",
    "right bracket",
    "closebracket",
    "closing bracket",
}

HELP_KEYS: Set[str] = {
    "h",
    "ا",
    "alef",
    "arabic_alef",
}

DIGIT_MAP: Dict[str, int] = {
    "1": 10, "numpad1": 10, "numpad_1": 10,
    "2": 20, "numpad2": 20, "numpad_2": 20,
    "3": 30, "numpad3": 30, "numpad_3": 30,
    "4": 40, "numpad4": 40, "numpad_4": 40,
    "5": 50, "numpad5": 50, "numpad_5": 50,
    "6": 60, "numpad6": 60, "numpad_6": 60,
    "7": 70, "numpad7": 70, "numpad_7": 70,
    "8": 80, "numpad8": 80, "numpad_8": 80,
    "9": 90, "numpad9": 90, "numpad_9": 90,
    "0": 0,  "numpad0": 0,  "numpad_0": 0,
}

VK_DIGIT_MAP: Dict[int, int] = {
    VK_1: 10, VK_NUMPAD1: 10,
    VK_2: 20, VK_NUMPAD2: 20,
    VK_3: 30, VK_NUMPAD3: 30,
    VK_4: 40, VK_NUMPAD4: 40,
    VK_5: 50, VK_NUMPAD5: 50,
    VK_6: 60, VK_NUMPAD6: 60,
    VK_7: 70, VK_NUMPAD7: 70,
    VK_8: 80, VK_NUMPAD8: 80,
    VK_9: 90, VK_NUMPAD9: 90,
    VK_0: 0,  VK_NUMPAD0: 0,
}


class ModalInputLayer:
    """
    Modal keyboard capture layer for HeadlessPlayer.
    Registers with inputCore.decide_executeGesture to trap and route all keystrokes.
    """

    def __init__(
        self,
        controller: Optional[Any] = None,
        tone_mgr: Optional[ToneCueManager] = None
    ) -> None:
        self.controller = controller
        self.tone_manager = tone_mgr or tone_manager
        self._is_active: bool = False
        self._is_suspended: bool = False
        self._registered: bool = False

        # Configurable seek/speed/volume steps (dynamically resolved from config)
        self._seek_normal: Optional[float] = None
        self._seek_slow: Optional[float] = None
        self._seek_fast: Optional[float] = None
        self._seek_ultrafast: Optional[float] = None
        self.speed_step: float = 0.1
        self.volume_step: float = 5.0

        # State callback listeners
        self._mode_change_callbacks: List[Callable[[bool], None]] = []

    @property
    def seek_normal(self) -> float:
        if self._seek_normal is not None:
            return self._seek_normal
        return float(getConfig().get("seekStepNormal", 5))

    @seek_normal.setter
    def seek_normal(self, val: Optional[float]) -> None:
        self._seek_normal = float(val) if val is not None else None

    @property
    def seek_slow(self) -> float:
        if self._seek_slow is not None:
            return self._seek_slow
        return float(getConfig().get("seekStepSlow", 1))

    @seek_slow.setter
    def seek_slow(self, val: Optional[float]) -> None:
        self._seek_slow = float(val) if val is not None else None

    @property
    def seek_fast(self) -> float:
        if self._seek_fast is not None:
            return self._seek_fast
        return float(getConfig().get("seekStepFast", 30))

    @seek_fast.setter
    def seek_fast(self, val: Optional[float]) -> None:
        self._seek_fast = float(val) if val is not None else None

    @property
    def seek_ultrafast(self) -> float:
        if self._seek_ultrafast is not None:
            return self._seek_ultrafast
        return float(getConfig().get("seekStepUltrafast", 300))

    @seek_ultrafast.setter
    def seek_ultrafast(self, val: Optional[float]) -> None:
        self._seek_ultrafast = float(val) if val is not None else None

    @property
    def is_active(self) -> bool:
        """Returns True if Player Mode is currently active."""
        return self._is_active

    @property
    def is_player_mode_active(self) -> bool:
        """Alias for is_active."""
        return self._is_active

    def activate_player_mode(self, announce: bool = True) -> None:
        """Activates Player Mode."""
        self.set_player_mode(True, announce=announce)

    def deactivate_player_mode(self, announce: bool = True) -> None:
        """Deactivates Player Mode."""
        self.set_player_mode(False, announce=announce)

    @property
    def is_suspended(self) -> bool:
        """Returns True if modal interception is temporarily suspended (e.g. for dialogs)."""
        return self._is_suspended

    @is_suspended.setter
    def is_suspended(self, val: bool) -> None:
        self._is_suspended = bool(val)

    def suspend(self) -> None:
        """Temporarily suspends modal interception so normal keyboard input reaches dialogs."""
        self._is_suspended = True

    def suspend_interception(self) -> None:
        """Alias for suspend()."""
        self.suspend()

    def resume(self) -> None:
        """Resumes modal interception after dialog closure."""
        self._is_suspended = False

    def resume_interception(self) -> None:
        """Alias for resume()."""
        self.resume()

    def add_mode_change_callback(self, cb: Callable[[bool], None]) -> None:
        """Registers a callback function to be called when mode changes: cb(active: bool)."""
        if cb not in self._mode_change_callbacks:
            self._mode_change_callbacks.append(cb)

    def remove_mode_change_callback(self, cb: Callable[[bool], None]) -> None:
        """Removes a registered mode change callback."""
        if cb in self._mode_change_callbacks:
            self._mode_change_callbacks.remove(cb)

    def set_player_mode(self, active: bool, announce: bool = True) -> None:
        """
        Activates or deactivates Player Mode.
        Plays acoustic feedback and announces mode status via NVDA.
        """
        if self._is_active == active:
            return

        self._is_active = active

        if active:
            self.tone_manager.play_mode_enter()
            if announce:
                self._speak(_("Player Mode active"))
            # Pre-warm mpv engine in background thread so it is instantly ready
            if self.controller and hasattr(self.controller, "start"):
                import threading
                threading.Thread(
                    target=self.controller.start,
                    daemon=True,
                    name="HeadlessPlayer-PrewarmEngine"
                ).start()
        else:
            self.tone_manager.play_mode_exit()
            if announce:
                self._speak(_("Player Mode exited"))

        # Notify callbacks
        for cb in list(self._mode_change_callbacks):
            try:
                cb(active)
            except Exception as e:
                logger.error("Error in mode change callback: %s", e)

    def toggle_player_mode(self, announce: bool = True) -> bool:
        """Toggles Player Mode and returns new state."""
        self.set_player_mode(not self._is_active, announce=announce)
        return self._is_active

    def register(self) -> bool:
        """Registers the gesture decider with NVDA's inputCore."""
        if self._registered:
            return True
        if _NVDA_INPUTCORE_AVAILABLE and inputCore:
            try:
                inputCore.decide_executeGesture.register(self.on_decide_execute_gesture)
                self._registered = True
                logger.info("Registered ModalInputLayer with inputCore.decide_executeGesture")
                return True
            except Exception as e:
                logger.error("Failed to register decide_executeGesture: %s", e)
                return False
        return False

    def unregister(self) -> None:
        """Unregisters the gesture decider from NVDA's inputCore."""
        if not self._registered:
            return
        if _NVDA_INPUTCORE_AVAILABLE and inputCore:
            try:
                inputCore.decide_executeGesture.unregister(self.on_decide_execute_gesture)
            except Exception as e:
                logger.debug("Error unregistering decide_executeGesture: %s", e)
        self._registered = False

    def _speak(self, text: str) -> None:
        """Speaks a message using NVDA ui.message if available."""
        if _NVDA_UI_AVAILABLE and ui:
            try:
                ui.message(text)
            except Exception as e:
                logger.debug("ui.message error: %s", e)

    def _safe_call(self, method_name: str, *args, **kwargs) -> Any:
        """
        Safely invokes a method on the controller (or fallback method aliases) asynchronously
        to ensure NVDA's inputCore decider never blocks or stutters.
        """
        if not self.controller:
            return None

        # Primary and alias method names
        aliases = {
            "toggle_pause": ["toggle_pause", "play_pause", "pause_toggle"],
            "stop": ["stop", "stop_playback"],
            "toggle_mute": ["toggle_mute", "mute_toggle"],
            "seek": ["seek", "seek_relative"],
            "seek_percent": ["seek_percent", "seek_percentage", "seek_to_percent"],
            "adjust_volume": ["adjust_volume", "change_volume", "set_volume_delta"],
            "adjust_bass": ["adjust_bass", "bass_adjust", "change_bass"],
            "adjust_speed": ["adjust_speed", "change_speed", "set_speed_delta"],
            "cycle_speed_preset": ["cycle_speed_preset", "cycle_speed", "next_speed_preset"],
            "set_ab_point_a": ["set_ab_point_a", "set_point_a", "mark_ab_a", "set_ab_a"],
            "set_ab_point_b": ["set_ab_point_b", "set_point_b", "mark_ab_b", "set_ab_b"],
            "toggle_repeat": ["toggle_repeat", "cycle_repeat", "toggle_loop", "toggle_ab_repeat"],
            "clear_ab_points": ["clear_ab_points", "clear_ab", "clear_loop", "clear_ab_loop"],
            "prev_chapter": ["prev_chapter", "previous_chapter", "chapter_prev"],
            "next_chapter": ["next_chapter", "chapter_next"],
            "cycle_audio_track": ["cycle_audio_track", "cycle_audio", "next_audio_track"],
            "open_file_dialog": ["open_file_dialog", "prompt_open_file", "load_file_dialog"],
            "open_url_dialog": ["open_url_dialog", "prompt_open_url", "open_url"],
            "copy_current_url": ["copy_current_url", "copy_url", "copy_link"],
            "open_account_feed": ["open_account_feed", "account_feed", "open_account"],
            "open_folder_dialog": ["open_folder_dialog", "prompt_open_folder", "load_folder_dialog"],
            "load_from_explorer": ["load_from_explorer", "load_explorer_selection", "play_explorer_selection"],
            "prev_track": ["prev_track", "previous_track", "playlist_prev", "prev"],
            "next_track": ["next_track", "playlist_next", "next"],
            "jump_to_first_track": ["jump_to_first_track", "first_track", "first_playlist_track"],
            "jump_to_last_track": ["jump_to_last_track", "last_track", "last_playlist_track"],
            "jump_to_track_start": ["jump_to_track_start", "track_start", "seek_track_start"],
            "jump_to_track_end": ["jump_to_track_end", "track_end", "seek_track_end"],
            "toggle_auto_next": ["toggle_auto_next", "toggle_autonext", "set_auto_next"],
            "toggle_shuffle": ["toggle_shuffle", "shuffle_toggle", "set_shuffle"],
            "speak_media_info": ["speak_media_info", "announce_media_info", "get_media_info"],
            "speak_remaining_time": ["speak_remaining_time", "announce_remaining_time", "get_remaining_time"],
            "speak_elapsed_time": ["speak_elapsed_time", "announce_elapsed_time", "get_elapsed_time"],
            "show_shortcuts_help": ["show_shortcuts_help", "show_help", "help", "shortcuts_help"],
        }

        candidate_names = aliases.get(method_name, [method_name])
        for name in candidate_names:
            method = getattr(self.controller, name, None)
            if callable(method):
                try:
                    return method(*args, **kwargs)
                except Exception as e:
                    logger.error("Error invoking controller.%s: %s", name, e)
                    return None
        return None

    def on_decide_execute_gesture(self, gesture: Any) -> bool:
        """
        NVDA inputCore.decide_executeGesture decider callback.
        
        Returns:
            False: Gesture consumed / swallowed by Player Mode (ZERO leak to OS apps).
            True:  Gesture passed through to NVDA / Windows OS.
        """
        # Pass-through when Player Mode is inactive or suspended
        if not self._is_active or self._is_suspended:
            return True

        # Whitelist NVDA modifier keys (Insert, CapsLock) to preserve NVDA modifier state tracking
        if getattr(gesture, "isNVDAModifier", False):
            return True

        main_key = (getattr(gesture, "mainKeyName", "") or "").lower()
        raw_mods = getattr(gesture, "modifierNames", None) or getattr(gesture, "modifiers", None) or []
        mods = {str(m).lower() for m in raw_mods}
        has_ctrl = "control" in mods or "ctrl" in mods
        has_shift = "shift" in mods
        has_alt = "alt" in mods

        # If user taps bare NVDA modifier key (Insert / CapsLock), allow pass-through
        if main_key in ("insert", "capslock", "caps_lock", "extendedinsert") and not (has_ctrl or has_shift or has_alt):
            return True

        # Silence speech immediately when bare Control key is pressed (standard NVDA behavior)
        vk = getattr(gesture, "vkCode", 0)
        if main_key in ("control", "ctrl", "leftcontrol", "rightcontrol", "left_control", "right_control") or vk in (0x11, 0xA2, 0xA3):
            if not (has_shift or has_alt):
                if _NVDA_SPEECH_AVAILABLE and speech:
                    try:
                        speech.cancelSpeech()
                    except Exception:
                        pass
                if self.controller and hasattr(self.controller, "speech"):
                    try:
                        self.controller.speech.cancel_speech()
                    except Exception:
                        pass
                return False

        # Check for toggle gesture to exit Player Mode
        if self._is_toggle_gesture(gesture):
            self.set_player_mode(False)
            return False

        # Dispatch player command
        handled = self.dispatch_gesture(gesture)
        if handled:
            return False  # Handled and consumed

        # Unmapped key: swallow completely and play subtle feedback click
        self.tone_manager.play_unmapped_key()
        return False

    def _is_toggle_gesture(self, gesture: Any) -> bool:
        """Detects if gesture is the toggle shortcut NVDA+Ctrl+Shift+P / Insert+Ctrl+Shift+P."""
        identifiers = getattr(gesture, "identifiers", []) or []
        for ident in identifiers:
            ident_lower = str(ident).lower()
            if ("control" in ident_lower or "ctrl" in ident_lower) and "shift" in ident_lower and "p" in ident_lower and (
                "nvda" in ident_lower or "insert" in ident_lower or "capslock" in ident_lower
            ):
                return True

        # Fallback check on modifier names and main key / vk
        raw_mods = getattr(gesture, "modifierNames", None) or getattr(gesture, "modifiers", None) or []
        mods = {str(m).lower() for m in raw_mods}
        main_key = (getattr(gesture, "mainKeyName", "") or "").lower()
        vk = getattr(gesture, "vkCode", 0)

        has_ctrl = "control" in mods or "ctrl" in mods
        has_shift = "shift" in mods
        has_nvda = "nvda" in mods or "insert" in mods or "capslock" in mods

        if has_ctrl and has_shift and has_nvda and (main_key == "p" or vk == VK_P):
            return True

        return False

    def _matches_action(self, gesture: Any, action_name: str, default_cond: bool) -> bool:
        """
        Checks if gesture matches the custom configured key for action_name,
        falling back to default_cond if no custom key is configured.
        """
        try:
            from .config_spec import getKeymap, parseKeymapKeys
            keymap = getKeymap()
            custom_keys = parseKeymapKeys(keymap.get(action_name, ""))
        except Exception:
            return default_cond

        if not custom_keys:
            return default_cond

        raw_mods = getattr(gesture, "modifierNames", None) or getattr(gesture, "modifiers", None) or []
        mods = sorted(list({str(m).lower().replace("ctrl", "control") for m in raw_mods}))
        main_key = (getattr(gesture, "mainKeyName", "") or "").lower()
        vk = getattr(gesture, "vkCode", 0)

        # Normalize key aliases
        if main_key in ("leftarrow", "left"):
            main_key = "leftarrow"
        elif main_key in ("rightarrow", "right"):
            main_key = "rightarrow"
        elif main_key in ("uparrow", "up"):
            main_key = "uparrow"
        elif main_key in ("downarrow", "down"):
            main_key = "downarrow"
        elif main_key in ("pageup", "page_up", "prior"):
            main_key = "pageup"
        elif main_key in ("pagedown", "page_down", "next"):
            main_key = "pagedown"
        elif main_key in ("escape", "esc"):
            main_key = "escape"
        elif main_key in ("space", "spacebar"):
            main_key = "space"
        elif main_key in ("home", "extendedhome"):
            main_key = "home"
        elif main_key in ("end", "extendedend"):
            main_key = "end"

        mod_prefix = "+".join(mods)
        current_rep = f"{mod_prefix}+{main_key}" if mod_prefix else main_key

        for custom_key in custom_keys:
            if current_rep == custom_key:
                return True

            if custom_key == "space" and (main_key == "space" or vk == VK_SPACE) and not mods:
                return True
            if custom_key in ("escape", "esc") and (main_key in ("escape", "esc") or vk == VK_ESCAPE) and not mods:
                return True
            if custom_key == "tab" and (main_key == "tab" or vk == VK_TAB) and not mods:
                return True
            if custom_key == "shift+tab" and (main_key == "tab" or vk == VK_TAB) and mods == ["shift"]:
                return True
            if custom_key == "home" and (main_key == "home" or vk == VK_HOME) and not mods:
                return True
            if custom_key == "end" and (main_key == "end" or vk == VK_END) and not mods:
                return True
            if custom_key == "control+home" and (main_key == "home" or vk == VK_HOME) and mods == ["control"]:
                return True
            if custom_key == "control+end" and (main_key == "end" or vk == VK_END) and mods == ["control"]:
                return True
            if custom_key in ("control", "ctrl") and (main_key in ("control", "ctrl") or vk in (0x11, 0xA2, 0xA3)):
                return True

        return default_cond

    def dispatch_gesture(self, gesture: Any) -> bool:
        """
        Maps normalized gesture properties and virtual key codes to player engine actions.
        Supports full customization from NVDA Settings.
        
        Returns:
            True if key was recognized and dispatched, False if unmapped.
        """
        main_key = (getattr(gesture, "mainKeyName", "") or "").lower()
        vk = getattr(gesture, "vkCode", 0)
        raw_mods = getattr(gesture, "modifierNames", None) or getattr(gesture, "modifiers", None) or []
        mods = {str(m).lower() for m in raw_mods}

        has_ctrl = "control" in mods or "ctrl" in mods
        has_shift = "shift" in mods
        has_alt = "alt" in mods

        # -------------------------------------------------------------
        # 1. Escape: Exit Player Mode
        # -------------------------------------------------------------
        if self._matches_action(gesture, "exit_mode", (main_key in ("escape", "esc") or vk == VK_ESCAPE)):
            self.set_player_mode(False)
            return True

        # -------------------------------------------------------------
        # 2. Playback & Core Controls
        # -------------------------------------------------------------
        # Play/Pause toggle
        if self._matches_action(gesture, "play_pause", ((main_key == "space" or vk == VK_SPACE) and not (has_ctrl or has_alt or has_shift))):
            self._safe_call("toggle_pause")
            return True

        # Stop and rewind
        if self._matches_action(gesture, "stop", ((main_key == "s" or vk == VK_S) and not (has_ctrl or has_alt))):
            self._safe_call("stop")
            return True

        # Mute / Unmute
        if self._matches_action(gesture, "mute", ((main_key == "m" or vk == VK_M) and not (has_ctrl or has_alt))):
            self._safe_call("toggle_mute")
            return True

        # -------------------------------------------------------------
        # 3. Seeking & Chapter Navigation
        # -------------------------------------------------------------
        is_left = main_key in ("leftarrow", "left") or vk == VK_LEFT
        is_right = main_key in ("rightarrow", "right") or vk == VK_RIGHT

        if is_left and has_ctrl and has_shift:
            self._safe_call("prev_chapter")
            return True
        if is_right and has_ctrl and has_shift:
            self._safe_call("next_chapter")
            return True

        if self._matches_action(gesture, "seek_ultrafast_backward", (is_left and has_shift and not (has_ctrl or has_alt))):
            self._safe_call("seek", -self.seek_ultrafast)
            return True
        if self._matches_action(gesture, "seek_ultrafast_forward", (is_right and has_shift and not (has_ctrl or has_alt))):
            self._safe_call("seek", self.seek_ultrafast)
            return True

        if self._matches_action(gesture, "seek_fast_backward", (is_left and has_ctrl and not (has_alt or has_shift))):
            self._safe_call("seek", -self.seek_fast)
            return True
        if self._matches_action(gesture, "seek_fast_forward", (is_right and has_ctrl and not (has_alt or has_shift))):
            self._safe_call("seek", self.seek_fast)
            return True

        if self._matches_action(gesture, "seek_slow_backward", (is_left and has_alt and not (has_ctrl or has_shift))):
            self._safe_call("seek", -self.seek_slow)
            return True
        if self._matches_action(gesture, "seek_slow_forward", (is_right and has_alt and not (has_ctrl or has_shift))):
            self._safe_call("seek", self.seek_slow)
            return True

        if self._matches_action(gesture, "seek_backward", (is_left and not (has_ctrl or has_alt or has_shift))):
            self._safe_call("seek", -self.seek_normal)
            return True
        if self._matches_action(gesture, "seek_forward", (is_right and not (has_ctrl or has_alt or has_shift))):
            self._safe_call("seek", self.seek_normal)
            return True

        # Number Keys 1-9 (10% to 90%) and 0 (0%)
        if not (has_ctrl or has_alt or has_shift):
            if main_key in DIGIT_MAP:
                percent = DIGIT_MAP[main_key]
                self._safe_call("seek_percent", percent)
                return True
            elif vk in VK_DIGIT_MAP:
                percent = VK_DIGIT_MAP[vk]
                self._safe_call("seek_percent", percent)
                return True

        # -------------------------------------------------------------
        # 4. Volume & Pitch-Preserved Speed
        # -------------------------------------------------------------
        is_up = main_key in ("uparrow", "up") or vk == VK_UP
        is_down = main_key in ("downarrow", "down") or vk == VK_DOWN

        if self._matches_action(gesture, "speed_up", (is_up and has_ctrl and not has_shift)):
            self._safe_call("adjust_speed", self.speed_step)
            return True
        if self._matches_action(gesture, "speed_down", (is_down and has_ctrl and not has_shift)):
            self._safe_call("adjust_speed", -self.speed_step)
            return True

        if self._matches_action(gesture, "speed_preset_up", (is_up and has_shift and not has_ctrl)):
            self._safe_call("cycle_speed_preset", forward=True)
            return True
        if self._matches_action(gesture, "speed_preset_down", (is_down and has_shift and not has_ctrl)):
            self._safe_call("cycle_speed_preset", forward=False)
            return True

        if self._matches_action(gesture, "vol_up", (is_up and not (has_ctrl or has_shift or has_alt))):
            self._safe_call("adjust_volume", self.volume_step)
            return True
        if self._matches_action(gesture, "vol_down", (is_down and not (has_ctrl or has_shift or has_alt))):
            self._safe_call("adjust_volume", -self.volume_step)
            return True

        # Bass boost / reduce (b / shift+b, +/- 3 dB)
        if self._matches_action(gesture, "bass_down", ((main_key == "b" or vk == VK_B) and has_shift and not (has_ctrl or has_alt))):
            self._safe_call("adjust_bass", -3.0)
            return True
        if self._matches_action(gesture, "bass_up", ((main_key == "b" or vk == VK_B) and not (has_ctrl or has_alt or has_shift))):
            self._safe_call("adjust_bass", 3.0)
            return True

        # -------------------------------------------------------------
        # 5. A-B Segment Repeat & Track Repeat (Layout Invariance)
        # -------------------------------------------------------------
        if self._matches_action(gesture, "point_a", (main_key in POINT_A_KEYS or vk == VK_OEM_4)):
            self._safe_call("set_ab_point_a")
            return True

        if self._matches_action(gesture, "point_b", (main_key in POINT_B_KEYS or vk == VK_OEM_6)):
            self._safe_call("set_ab_point_b")
            return True

        if self._matches_action(gesture, "toggle_repeat", ((main_key == "r" or vk == VK_R) and not (has_ctrl or has_alt))):
            self._safe_call("toggle_repeat")
            return True

        if self._matches_action(gesture, "clear_loop", ((main_key == "c" or vk == VK_C) and not (has_ctrl or has_alt))):
            self._safe_call("clear_ab_points")
            return True

        # -------------------------------------------------------------
        # 6. Audio Tracks Switching
        # -------------------------------------------------------------
        if (main_key == "a" or vk == VK_A) and not (has_ctrl or has_alt):
            self._safe_call("cycle_audio_track")
            return True

        # -------------------------------------------------------------
        # 7. Playlist, Explorer & Dialogs
        # -------------------------------------------------------------
        if self._matches_action(gesture, "open_file", ((main_key == "o" or vk == VK_O) and not (has_ctrl or has_alt))):
            self._safe_call("open_file_dialog")
            return True

        if self._matches_action(gesture, "open_folder", ((main_key == "f" or vk == VK_F) and not (has_ctrl or has_alt))):
            self._safe_call("open_folder_dialog")
            return True

        if self._matches_action(gesture, "open_url", ((main_key == "u" or vk == VK_U) and not (has_ctrl or has_alt))):
            self._safe_call("open_url_dialog")
            return True

        if self._matches_action(gesture, "copy_url", ((main_key == "v" or vk == VK_V) and not (has_ctrl or has_alt))):
            self._safe_call("copy_current_url")
            return True

        if self._matches_action(gesture, "account_feed", ((main_key == "p" or vk == VK_P) and not (has_ctrl or has_alt or has_shift))):
            self._safe_call("open_account_feed")
            return True

        if self._matches_action(gesture, "load_explorer", ((main_key == "e" or vk == VK_E) and not (has_ctrl or has_alt))):
            self._safe_call("load_from_explorer")
            return True

        if self._matches_action(gesture, "prev_track", (main_key in ("pageup", "page_up", "prior") or vk == VK_PRIOR)):
            self._safe_call("prev_track")
            return True

        if self._matches_action(gesture, "next_track", (main_key in ("pagedown", "page_down", "next") or vk == VK_NEXT)):
            self._safe_call("next_track")
            return True

        # Home & End: Start/End of current track vs First/Last in playlist
        is_home = main_key in ("home", "extendedhome") or vk == VK_HOME
        is_end = main_key in ("end", "extendedend") or vk == VK_END

        if self._matches_action(gesture, "first_track", (is_home and has_ctrl and not has_shift)):
            self._safe_call("jump_to_first_track")
            return True

        if self._matches_action(gesture, "last_track", (is_end and has_ctrl and not has_shift)):
            self._safe_call("jump_to_last_track")
            return True

        if self._matches_action(gesture, "track_start", (is_home and not (has_ctrl or has_alt or has_shift))):
            self._safe_call("jump_to_track_start")
            return True

        if self._matches_action(gesture, "track_end", (is_end and not (has_ctrl or has_alt or has_shift))):
            self._safe_call("jump_to_track_end")
            return True

        if self._matches_action(gesture, "toggle_auto_next", ((main_key == "n" or vk == VK_N) and not (has_ctrl or has_alt))):
            self._safe_call("toggle_auto_next")
            return True

        if self._matches_action(gesture, "toggle_shuffle", ((main_key == "z" or vk == VK_Z) and not (has_ctrl or has_alt))):
            self._safe_call("toggle_shuffle")
            return True

        # -------------------------------------------------------------
        # 8. Speech Information Queries & Help Dialog
        # -------------------------------------------------------------
        if self._matches_action(gesture, "remaining_time", ((main_key == "i" or vk == VK_I) and has_ctrl)):
            self._safe_call("speak_remaining_time")
            return True

        if self._matches_action(gesture, "elapsed_time", ((main_key == "i" or vk == VK_I) and has_shift)):
            self._safe_call("speak_elapsed_time")
            return True

        if self._matches_action(gesture, "media_info", ((main_key == "i" or vk == VK_I) and not (has_ctrl or has_shift or has_alt))):
            self._safe_call("speak_media_info")
            return True

        if self._matches_action(gesture, "show_help", ((main_key in HELP_KEYS or vk == VK_H) and not (has_ctrl or has_alt))):
            self._safe_call("show_shortcuts_help")
            return True

        # Unmapped key
        return False
