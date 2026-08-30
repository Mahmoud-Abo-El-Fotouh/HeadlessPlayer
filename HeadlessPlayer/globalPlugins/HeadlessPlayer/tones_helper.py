"""
HeadlessPlayer NVDA Add-on - Tones & Audio Cue Helper (No-op Silent Stub)
All acoustic beeps have been completely disabled as media players rely on speech feedback.
"""

from __future__ import annotations
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class ToneCueManager:
    """
    Silent no-op manager for tone cues.
    All acoustic beeps are completely disabled.
    """

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = False
        self._test_mode = False

    @property
    def is_enabled(self) -> bool:
        return False

    @is_enabled.setter
    def is_enabled(self, val: bool) -> None:
        self._enabled = False

    @property
    def test_mode(self) -> bool:
        return self._test_mode

    @test_mode.setter
    def test_mode(self, val: bool) -> None:
        self._test_mode = bool(val)

    def beep(self, pitch: int, duration: int, left: int = 50, right: int = 50) -> None:
        """Completely silent no-op."""
        pass

    def play_mode_enter(self) -> None:
        pass

    def play_mode_exit(self) -> None:
        pass

    def play_point_a(self) -> None:
        pass

    def play_point_b(self) -> None:
        pass

    def play_loop_active(self) -> None:
        pass

    def play_boundary_hit(self) -> None:
        pass

    def play_unmapped_key(self) -> None:
        pass

    def play_seek_click(self) -> None:
        pass

    def get_history(self) -> List[Tuple[int, int]]:
        return []

    def clear_history(self) -> None:
        pass

    @property
    def last_beep(self) -> Optional[Tuple[int, int]]:
        return None


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
