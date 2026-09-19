# -*- coding: utf-8 -*-
"""
HeadlessPlayer Debug Log Manager.
Provides dedicated high-performance file-based logging to HeadlessPlayer_debug.log in %TEMP%,
and an in-memory Ring Buffer for instant self-diagnostics and telemetry dumps.
"""

from __future__ import annotations
import argparse
import collections
import datetime
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
from typing import Any, List, Optional

_TEMP = os.environ.get("TEMP", "") or os.environ.get("TMP", "") or "."
_LOG_FILE = os.path.join(_TEMP, "HeadlessPlayer_debug.log")
_FLAG_FILE = os.path.join(_TEMP, "HeadlessPlayer_debug.enabled")
_LOCK = threading.Lock()
_ENABLED = False
_DEV_BUILD = False


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
    """Returns True if debug logging is explicitly enabled in dev mode or dev builds."""
    global _ENABLED, _DEV_BUILD
    return _DEV_BUILD or _ENABLED or os.path.exists(_FLAG_FILE) or os.environ.get("HEADLESSPLAYER_DEV") == "1"


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


def _tail_log(initial_lines: int = 15) -> None:
    log_file = get_log_filepath()
    if not is_enabled():
        print("\n[!] NOTICE: Debug logging is currently DISABLED.")
        print("    Enable it first (Option 1 or 'on' command) to capture incoming NVDA events.")

    if not os.path.exists(log_file):
        print(f"\n[*] Waiting for log file to be created: {log_file}")
        print("    (Press Ctrl+C to stop)")
        while not os.path.exists(log_file):
            time.sleep(0.5)

    print(f"\n[*] Live-tailing log file: {log_file}")
    print("    (Showing last lines, then waiting for new events in real time. Press Ctrl+C to stop)")
    print("-" * 70)

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            if all_lines:
                recent = all_lines[-initial_lines:]
                for l in recent:
                    sys.stdout.write(l)
                sys.stdout.flush()

            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n[*] Stopped live log monitoring.")


def _run_diagnostics() -> None:
    try:
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.abspath(os.path.join(cur_dir, "..", "..", ".."))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        diag_mod = sys.modules.get("globalPlugins.HeadlessPlayer.core.diagnostics")
        if not diag_mod:
            try:
                diag_mod = __import__("globalPlugins.HeadlessPlayer.core.diagnostics", fromlist=["generate_diagnostic_report_text"])
            except Exception:
                try:
                    from ..core import diagnostics as diag_mod
                except Exception:
                    try:
                        from core import diagnostics as diag_mod
                    except Exception:
                        import diagnostics as diag_mod
        print("\n[*] Running Full System Health Diagnostics...\n")
        report = getattr(diag_mod, "generate_diagnostic_report_text")()
        print(report)
    except Exception as e:
        print(f"[-] Failed to run diagnostics: {e}")


def _print_status() -> None:
    status_str = "ENABLED" if is_enabled() else "DISABLED"
    log_file = get_log_filepath()
    print("\n==================================================")
    print(f" HeadlessPlayer Debug Logging Status: [{status_str}]")
    print("==================================================")
    print(f" - Flag File: {_FLAG_FILE} ({'EXISTS' if os.path.exists(_FLAG_FILE) else 'NOT FOUND'})")
    print(f" - Log File : {log_file}")
    if os.path.exists(log_file):
        size_kb = os.path.getsize(log_file) / 1024.0
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                line_count = sum(1 for _ in f)
        except Exception:
            line_count = 0
        mtime = time.ctime(os.path.getmtime(log_file))
        print(f" - File Size: {size_kb:.2f} KB ({line_count} lines)")
        print(f" - Last Modified: {mtime}")
    else:
        print(" - File Size: Log file does not exist yet.")
    print("==================================================\n")


def _interactive_menu() -> None:
    while True:
        status_str = "ENABLED" if is_enabled() else "DISABLED"
        print(f"\n=== HeadlessPlayer Debug Log Manager [Status: {status_str}] ===")
        print("1. Enable Debug Logging")
        print("2. Disable Debug Logging")
        print("3. Check Status & Log File Info")
        print("4. Open Log File in Notepad")
        print("5. Live Monitor Logs (Tail)")
        print("6. Clear Log File & Memory Buffer")
        print("7. Run System Diagnostics")
        print("0. Exit")
        print("==================================================")
        try:
            choice = input("Enter your choice (0-7): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if choice == "1":
            set_enabled(True)
            print(f"\n[+] Debug logging ENABLED -> {get_log_filepath()}")
        elif choice == "2":
            set_enabled(False)
            print("\n[-] Debug logging DISABLED")
        elif choice == "3":
            _print_status()
        elif choice == "4":
            log_file = get_log_filepath()
            if not os.path.exists(log_file):
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write("")
            subprocess.Popen(["notepad.exe", log_file])
            print(f"\n[*] Opened {log_file} in Notepad.")
        elif choice == "5":
            _tail_log()
        elif choice == "6":
            clear_log()
            print("\n[+] Log file and memory buffer cleared.")
        elif choice == "7":
            _run_diagnostics()
        elif choice == "0":
            print("Goodbye!")
            break
        else:
            print("[-] Invalid choice. Please select 0 to 7.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HeadlessPlayer Developer Debug Log Manager")
    parser.add_argument(
        "action",
        nargs="?",
        choices=["on", "off", "status", "open", "view", "clear", "tail", "diag"],
        help="Action: on, off, status, open, view, clear, tail, diag (or omit for interactive menu)"
    )
    args = parser.parse_args()

    if not args.action:
        _interactive_menu()
    elif args.action == "on":
        set_enabled(True)
        print(f"[+] Debug logging ENABLED -> {get_log_filepath()}")
    elif args.action == "off":
        set_enabled(False)
        print("[-] Debug logging DISABLED")
    elif args.action == "status":
        _print_status()
    elif args.action in ("open", "view"):
        log_file = get_log_filepath()
        if not os.path.exists(log_file):
            with open(log_file, "w", encoding="utf-8") as f:
                f.write("")
        subprocess.Popen(["notepad.exe", log_file])
        print(f"[*] Opened {log_file} in Notepad.")
    elif args.action == "clear":
        clear_log()
        print("[+] Log file and memory buffer cleared.")
    elif args.action == "tail":
        _tail_log()
    elif args.action == "diag":
        _run_diagnostics()
