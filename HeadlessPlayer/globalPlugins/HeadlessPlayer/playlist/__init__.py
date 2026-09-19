# -*- coding: utf-8 -*-
"""
HeadlessPlayer Playlist Subpackage.
Manages playlist queues, tracks, repeat modes, and ordering.
"""
from __future__ import annotations

from . import models, manager

for _mod in (models, manager):
    for _k, _v in list(_mod.__dict__.items()):
        if not _k.startswith("__"):
            globals()[_k] = _v
