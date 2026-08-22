"""
HeadlessPlayer NVDA Add-on - Tones & Audio Cue Helper
Provides acoustic feedback via NVDA's tones.beep subsystem for mode changes,
A-B repeat markers, boundary hits, and unmapped key swallowing.
"""

from __future__ import annotations
import logging
import threading
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

_NVDA_TONES_AVAILABLE = False


class ToneCueManager:
    """
    Manages audio cues.
    All acoustic beeps and earcons are completely silenced to provide
    clean screen reader speech output without audio distractions.
    Records history for testing without making any audio hardware calls.
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._lock = threading.Lock()
        self._history: List[Tuple[int, int]] = []
        self._test_mode = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @is_enabled.setter
    def is_enabled(self, val: bool) -> None:
        self._enabled = bool(val)

    @property
    def test_mode(self) -> bool:
        return self._test_mode

    @test_mode.setter
    def test_mode(self, val: bool) -> None:
        self._test_mode = bool(val)

    def beep(self, pitch: int, duration: int, left: int = 50, right: int = 50) -> None:
        """
        Silently records tone history in memory without any sound output.
        """
        if not self._enabled:
            return
        with self._lock:
            self._history.append((pitch, duration))

    def play_mode_enter(self) -> None:
        """Ascending arpeggio cue: 440 Hz (40 ms) -> 880 Hz (50 ms)."""
        self.beep(440, 40)
        self.beep(880, 50)

    def play_mode_exit(self) -> None:
        """Descending arpeggio cue: 880 Hz (40 ms) -> 440 Hz (50 ms)."""
        self.beep(880, 40)
        self.beep(440, 50)

    def play_point_a(self) -> None:
        """Point A set confirmation tone: 523 Hz (C5, 50 ms)."""
        self.beep(523, 50)

    def play_point_b(self) -> None:
        """Point B set confirmation tone: 659 Hz (E5, 50 ms)."""
        self.beep(659, 50)

    def play_loop_active(self) -> None:
        """Two-tone chirp when A-B loop engages: 523 Hz (30 ms) -> 659 Hz (30 ms)."""
        self.beep(523, 30)
        self.beep(659, 30)

    def play_boundary_hit(self) -> None:
        """Low warning tone when file start/end boundary is reached: 220 Hz (A3, 60 ms)."""
        self.beep(220, 60)

    def play_unmapped_key(self) -> None:
        """Subtle tactile click indicating unmapped key swallowed: 150 Hz (15 ms)."""
        self.beep(150, 15)

    def play_seek_click(self) -> None:
        """Subtle instantaneous click for seek stepping: 400 Hz (10 ms)."""
        self.beep(400, 10)

    def get_history(self) -> List[Tuple[int, int]]:
        """Returns a copy of the tone history (for verification and unit tests)."""
        with self._lock:
            return list(self._history)

    def clear_history(self) -> None:
        """Clears recorded tone history."""
        with self._lock:
            self._history.clear()

    @property
    def last_beep(self) -> Optional[Tuple[int, int]]:
        """Returns the most recently played (pitch, duration) tuple or None."""
        with self._lock:
            return self._history[-1] if self._history else None


# Module-level singleton instance
tone_manager = ToneCueManager()

# Direct convenience functions
play_mode_enter = tone_manager.play_mode_enter
play_mode_exit = tone_manager.play_mode_exit
play_point_a = tone_manager.play_point_a
play_point_b = tone_manager.play_point_b
play_loop_active = tone_manager.play_loop_active
play_boundary_hit = tone_manager.play_boundary_hit
play_unmapped_key = tone_manager.play_unmapped_key
play_seek_click = tone_manager.play_seek_click
beep = tone_manager.beep
