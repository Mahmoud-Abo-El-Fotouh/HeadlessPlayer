# -*- coding: utf-8 -*-
"""
HeadlessPlayer Debug Log Manager.
Provides dedicated high-performance file-based logging to HeadlessPlayer_debug.log in %TEMP%,
and an in-memory Ring Buffer for instant self-diagnostics and telemetry dumps.
"""

from __future__ import annotations
import collections
import datetime
import logging
import os
import threading
import traceback
from typing import Any, List, Optional

_TEMP = os.environ.get("TEMP", "") or os.environ.get("TMP", "") or "."
_LOG_FILE = os.path.join(_TEMP, "HeadlessPlayer_debug.log")
_FLAG_FILE = os.path.join(_TEMP, "HeadlessPlayer_debug.enabled")
_LOCK = threading.Lock()
_ENABLED = True


class RingBuffer:
    """Thread-safe generic circular ring buffer with bounded capacity."""

    def __init__(self, capacity: int = 100) -> None:
        self.capacity = max(1, capacity)
        self._deque: collections.deque = collections.deque(maxlen=self.capacity)
        self._lock = threading.Lock()

    def append(self, item: Any) -> None:
        with self._lock:
            self._deque.append(item)

    def to_list(self) -> List[Any]:
        with self._lock:
            return list(self._deque)

    def clear(self) -> None:
        with self._lock:
            self._deque.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._deque)

    def __iter__(self):
        with self._lock:
            return iter(list(self._deque))


# In-memory circular Ring Buffer holding the most recent 100 log events
_RING_BUFFER = RingBuffer(capacity=100)


def is_enabled() -> bool:
    """Returns True if debug logging is currently enabled."""
    global _ENABLED
    return _ENABLED or os.path.exists(_FLAG_FILE)


def set_enabled(enabled: bool) -> None:
    """Enables or disables debug file logging and updates flag file."""
    global _ENABLED
    _ENABLED = bool(enabled)
    try:
        if _ENABLED:
            if not os.path.exists(_FLAG_FILE):
                with open(_FLAG_FILE, "w", encoding="utf-8") as f:
                    f.write("1\n")
        else:
            if os.path.exists(_FLAG_FILE):
                os.remove(_FLAG_FILE)
    except Exception:
        pass


def get_log_filepath() -> str:
    """Returns the absolute path to HeadlessPlayer_debug.log."""
    return _LOG_FILE


def clear_log() -> None:
    """Clears the log file and in-memory ring buffer."""
    _RING_BUFFER.clear()
    with _LOCK:
        try:
            with open(_LOG_FILE, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass


clear_logs = clear_log


def get_recent_logs(limit: int = 100) -> List[str]:
    """Retrieves recent log entries from the in-memory ring buffer."""
    entries = _RING_BUFFER.to_list()
    return entries[-limit:] if limit > 0 else entries


def log_debug(tag: str, message: str, *args: Any) -> None:
    """Logs a formatted debug message with timestamp, thread ID, tag, and saves to ring buffer."""
    try:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        thread_name = threading.current_thread().name
        thread_id = threading.get_ident()

        if args:
            try:
                formatted = message % args
            except Exception:
                formatted = f"{message} {args}"
        else:
            formatted = str(message)

        line = f"[{now_str}] [T:{thread_name}:{thread_id}] [{tag}] {formatted}\n"

        with _LOCK:
            _RING_BUFFER.append(line)
            if is_enabled():
                with open(_LOG_FILE, "a", encoding="utf-8", errors="replace") as fh:
                    fh.write(line)
                    fh.flush()
    except Exception:
        pass


def log_event(tag: str, message: str, *args: Any, level: str = "DEBUG") -> None:
    """Convenience alias for structured telemetry logging."""
    log_debug(tag, message, *args)


def log_exception(tag: str, message: str, exc: Optional[BaseException] = None) -> None:
    """Logs an exception with traceback."""
    try:
        if exc is None:
            tb = traceback.format_exc()
        else:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log_debug(tag, f"EXCEPTION: {message}\n{tb}")
    except Exception:
        pass


class HeadlessPlayerLogHandler(logging.Handler):
    """
    Logging handler that bridges standard Python logging calls
    (logger.info, logger.debug, logger.error, logger.warning, logger.exception)
    from all HeadlessPlayer modules into HeadlessPlayer_debug.log and Ring Buffer.
    """
    def emit(self, record: logging.LogRecord) -> None:
        try:
            raw_msg = record.getMessage()
            # Avoid duplicate writes for calls that already passed through utils.log_*
            if raw_msg.startswith("[HeadlessPlayer:"):
                return

            tag = record.name
            if tag.startswith("HeadlessPlayer."):
                tag = tag[len("HeadlessPlayer."):]
            elif tag == "HeadlessPlayer":
                tag = "CORE"

            lvl = record.levelname
            prefix = f"[{lvl}] " if lvl != "DEBUG" else ""

            if record.exc_info:
                exc_text = self.format(record)
                log_debug(tag, f"{prefix}{raw_msg}\n{exc_text}")
            else:
                log_debug(tag, f"{prefix}{raw_msg}")
        except Exception:
            pass


_HANDLER_ATTACHED = False


def attach_logging_handler() -> None:
    """
    Attaches the HeadlessPlayerLogHandler to the 'HeadlessPlayer' parent logger.
    Configures DEBUG level on the logger hierarchy so all debug logs are captured.
    """
    global _HANDLER_ATTACHED
    if _HANDLER_ATTACHED:
        return
    try:
        hp_logger = logging.getLogger("HeadlessPlayer")
        hp_logger.setLevel(logging.DEBUG)
        handler = HeadlessPlayerLogHandler()
        hp_logger.addHandler(handler)
        _HANDLER_ATTACHED = True
    except Exception:
        pass
