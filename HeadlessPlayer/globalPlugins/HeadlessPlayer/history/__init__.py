# -*- coding: utf-8 -*-
"""
HeadlessPlayer History Subpackage.
Manages persistent database storage, playback resume positions, and recents browsing.
"""
from __future__ import annotations

from . import database, state_store, recents

for _mod in (database, state_store, recents):
    for _k, _v in list(_mod.__dict__.items()):
        if not _k.startswith("__"):
            globals()[_k] = _v
