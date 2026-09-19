# -*- coding: utf-8 -*-
"""
HeadlessPlayer Utilities Subpackage.
"""
from __future__ import annotations

from . import common, logger, explorer, updater, config_spec

for _mod in (common, logger, explorer, updater, config_spec):
    for _k, _v in list(_mod.__dict__.items()):
        if not _k.startswith("__") and _k not in ("logger", "common", "explorer", "updater", "config_spec", "logging", "log_manager"):
            globals()[_k] = _v

logging = logger
log_manager = logger
