# -*- coding: utf-8 -*-
"""
HeadlessPlayer NVDA Add-on - Virtual Key Codes, Arabic Keyboard Map & Gesture Normalization.
"""

from __future__ import annotations
import ctypes
import logging
from typing import Dict, List, Optional, Set

logger = logging.getLogger("HeadlessPlayer.InputGestures")

# Virtual Key Codes (Win32)
VK_TAB = 0x09
VK_RETURN = 0x0D
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

# Modifier Virtual Key Codes (Win32)
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt key
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_LWIN = 0x5B
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_RWIN = 0x5C

ALL_MODIFIER_VKS = (
    VK_SHIFT, VK_LSHIFT, VK_RSHIFT,
    VK_CONTROL, VK_LCONTROL, VK_RCONTROL,
    VK_MENU, VK_LMENU, VK_RMENU,
    VK_LWIN, VK_RWIN,
)

EXTENDED_MODIFIER_VKS = (VK_RCONTROL, VK_RMENU, VK_LWIN, VK_RWIN)
EXTENDED_VKS = (
    VK_RCONTROL, VK_RMENU, VK_LWIN, VK_RWIN,
    VK_PRIOR, VK_NEXT, VK_END, VK_HOME,
    VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN,
    VK_INSERT, VK_DELETE,
)


def _send_key_up(vk: int) -> None:
    """Sends a Win32 synthetic key-up event for a given virtual key code with hardware scan code."""
    try:
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "user32"):
            flags = KEYEVENTF_KEYUP
            if vk in EXTENDED_VKS or vk in EXTENDED_MODIFIER_VKS:
                flags |= KEYEVENTF_EXTENDEDKEY
            scan = 0
            try:
                scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0) & 0xFF
            except Exception:
                scan = 0
            ctypes.windll.user32.keybd_event(vk, scan, flags, 0)
    except Exception as e:
        logger.debug("keybd_event error for vk=0x%02X: %s", vk, e)


def release_all_modifiers() -> None:
    """
    Pulses synthetic key-up events for all modifier keys (Shift, Ctrl, Alt, Win)
    to eliminate sticky modifier keys after exiting modal capture or opening dialogs.
    """
    for vk in ALL_MODIFIER_VKS:
        _send_key_up(vk)


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
VK_D = 0x44
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
VK_X = 0x58
VK_Z = 0x5A

# OEM Bracket keys (English [ and ] / Arabic ج and د)
VK_OEM_3 = 0xC0  # 192 - English '`' / Arabic 'ذ'
VK_OEM_4 = 0xDB  # 219 - English '[' / Arabic 'ج'
VK_OEM_6 = 0xDD  # 221 - English ']' / Arabic 'د'
VK_DELETE = 0x2E # 46 - Delete key
VK_OEM_COMMA = 0xBC  # 188 - ',' / Arabic 'و'
VK_OEM_PERIOD = 0xBE # 190 - '.' / Arabic 'ز'

# Arabic Keyboard to Canonical English Key Map for layout invariance
ARABIC_TO_ENGLISH_KEY_MAP: Dict[str, str] = {
    "ض": "q", "ص": "w", "ث": "e", "ق": "r", "ف": "t", "غ": "y", "ع": "u",
    "ه": "i", "خ": "o", "ح": "p", "ج": "[", "د": "]", "ش": "a", "س": "s",
    "ي": "d", "ب": "f", "ل": "g", "ا": "h", "أ": "h", "إ": "h", "آ": "h",
    "ت": "j", "ن": "k", "م": "l", "ك": ";", "ط": "'", "ئ": "z", "ء": "x",
    "ؤ": "c", "ر": "v", "ى": "n", "ة": "m", "و": ",", "ز": ".", "ظ": "/",
    "لا": "b", "لأ": "b", "لإ": "b", "لآ": "b",
    "ذ": "`", "؛": ";", "،": ",", "؟": "/", "ـ": "-", "«": "[", "»": "]",
}

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

COMMA_KEYS: Set[str] = {
    ",",
    "comma",
    "و",
    "<",
    "less",
    "،",
}

PERIOD_KEYS: Set[str] = {
    ".",
    "period",
    "fullstop",
    "dot",
    "ز",
    ">",
    "greater",
}

DELETE_KEYS: Set[str] = {
    "delete",
    "del",
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
