# -*- coding: utf-8 -*-
"""
Win32 Named Pipe Client for mpv JSON-IPC.
Pure ctypes calling kernel32.dll using FILE_FLAG_OVERLAPPED for robust, non-blocking
full-duplex asynchronous JSON-IPC communication with mpv.
Zero external dependencies (no pywin32 required).
"""

from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("HeadlessPlayer.IPC")

# Win32 Constants
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

# Win32 Error & Wait Codes
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_HANDLE = 6
ERROR_BROKEN_PIPE = 109
ERROR_PIPE_BUSY = 231
ERROR_NO_DATA = 232
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_IO_PENDING = 997

WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258

# Load kernel32
try:
    kernel32 = ctypes.windll.kernel32
except (AttributeError, OSError):
    kernel32 = None


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


if kernel32 is not None:
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE

    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(OVERLAPPED)
    ]
    kernel32.ReadFile.restype = wintypes.BOOL

    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(OVERLAPPED)
    ]
    kernel32.WriteFile.restype = wintypes.BOOL

    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateEventW.restype = wintypes.HANDLE

    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    kernel32.GetOverlappedResult.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(OVERLAPPED),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL
    ]
    kernel32.GetOverlappedResult.restype = wintypes.BOOL

    kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
    kernel32.ResetEvent.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel32.WaitNamedPipeW.restype = wintypes.BOOL

    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD


def _is_valid_handle(handle: Any) -> bool:
    """Helper to verify if a Win32 handle is open and valid."""
    if handle is None:
        return False
    val = handle if isinstance(handle, int) else getattr(handle, "value", handle)
    if val in (None, 0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
        return False
    return True


class WinNamedPipeClient:
    """
    Robust Win32 Named Pipe client for mpv JSON-IPC using Overlapped I/O.
    Eliminates driver locks and deadlocks when reading and writing simultaneously.
    """

    def __init__(
        self,
        pipe_path: Optional[str] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        pipe_name: Optional[str] = None
    ):
        resolved_path = pipe_path or pipe_name or r"\\.\pipe\nvda_headless_player"
        self.pipe_path: str = resolved_path
        self.pipe_name: str = resolved_path
        self.event_callback: Optional[Callable[[Dict[str, Any]], None]] = event_callback
        self.handle: Optional[wintypes.HANDLE] = None
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._running: bool = False
        self._reader_thread: Optional[threading.Thread] = None
        self._req_counter: int = 0
        self._pending_requests: Dict[int, Dict[str, Any]] = {}
        self._event_listeners: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        self._property_listeners: Dict[str, List[Callable[[str, Any], None]]] = {}

    def connect(self, timeout_sec: float = 3.0) -> bool:
        """
        Connect to the mpv Win32 named pipe using FILE_FLAG_OVERLAPPED.
        """
        if kernel32 is None:
            logger.error("kernel32 is unavailable on this platform.")
            return False

        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            handle = kernel32.CreateFileW(
                self.pipe_path,
                GENERIC_READ | GENERIC_WRITE,
                0,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED,
                None
            )

            if _is_valid_handle(handle):
                self.handle = handle
                self._running = True
                self._reader_thread = threading.Thread(
                    target=self._reader_loop,
                    daemon=True,
                    name="HeadlessPlayer-IPCReader"
                )
                self._reader_thread.start()
                logger.info("Connected to mpv named pipe '%s' with Overlapped I/O successfully.", self.pipe_path)
                return True

            err = kernel32.GetLastError()
            if err == ERROR_PIPE_BUSY:
                kernel32.WaitNamedPipeW(self.pipe_path, 200)
            elif err in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
                time.sleep(0.05)
            else:
                logger.debug("CreateFileW failed with error code %d", err)
                time.sleep(0.05)

        logger.warning("Failed to connect to named pipe '%s' within %.1fs timeout.", self.pipe_path, timeout_sec)
        return False

    def is_connected(self) -> bool:
        """Check whether the IPC client is actively connected."""
        return self._running and _is_valid_handle(self.handle)

    def close(self) -> None:
        """Close named pipe connection and terminate background worker thread."""
        self._running = False
        with self._lock:
            if _is_valid_handle(self.handle):
                try:
                    kernel32.CloseHandle(self.handle)
                except Exception as e:
                    logger.debug("Error closing pipe handle: %s", e)
                self.handle = None

            # Wake up and cancel any pending requests
            for req_info in self._pending_requests.values():
                req_info["response"] = {"error": "connection closed"}
                req_info["event"].set()
            self._pending_requests.clear()

        if self._reader_thread and self._reader_thread.is_alive():
            if threading.current_thread() != self._reader_thread:
                self._reader_thread.join(timeout=0.5)
            self._reader_thread = None

        logger.info("Named pipe client closed.")

    def _reader_loop(self) -> None:
        """
        Background reader thread consuming newline-delimited UTF-8 JSON messages via Overlapped I/O.
        """
        buffer_size = 65536
        read_buf = ctypes.create_string_buffer(buffer_size)
        bytes_read = wintypes.DWORD(0)
        accumulator = bytearray()

        h_read_event = kernel32.CreateEventW(None, True, False, None)
        ov = OVERLAPPED()
        ov.hEvent = h_read_event

        try:
            while self._running and _is_valid_handle(self.handle):
                kernel32.ResetEvent(h_read_event)
                bytes_read.value = 0
                success = kernel32.ReadFile(
                    self.handle,
                    read_buf,
                    buffer_size,
                    None,
                    ctypes.byref(ov)
                )

                if not success:
                    err = kernel32.GetLastError()
                    if err == ERROR_IO_PENDING:
                        # Wait in 200ms slices to allow clean shutdown check on self._running
                        while self._running:
                            wait_res = kernel32.WaitForSingleObject(h_read_event, 200)
                            if wait_res == WAIT_OBJECT_0:
                                break
                            elif wait_res == WAIT_TIMEOUT:
                                continue
                            else:
                                break

                        if not self._running or not _is_valid_handle(self.handle):
                            break

                        get_res = kernel32.GetOverlappedResult(
                            self.handle,
                            ctypes.byref(ov),
                            ctypes.byref(bytes_read),
                            False
                        )
                        if not get_res or bytes_read.value == 0:
                            break
                    elif err in (ERROR_BROKEN_PIPE, 109, 233, 6):
                        # Pipe closed by server
                        break
                    else:
                        logger.debug("ReadFile error code: %d", err)
                        break
                else:
                    # Synchronous immediate completion of overlapped read
                    kernel32.GetOverlappedResult(
                        self.handle,
                        ctypes.byref(ov),
                        ctypes.byref(bytes_read),
                        False
                    )

                if bytes_read.value > 0:
                    accumulator.extend(read_buf.raw[:bytes_read.value])

                    if len(accumulator) > 10 * 1024 * 1024:
                        logger.error("IPC reader accumulator exceeded 10MB; clearing buffer.")
                        accumulator.clear()

                    while b"\n" in accumulator:
                        idx = accumulator.index(b"\n")
                        line_bytes = accumulator[:idx].strip()
                        del accumulator[:idx + 1]

                        if not line_bytes:
                            continue

                        try:
                            line_str = line_bytes.decode("utf-8", errors="replace")
                            msg = json.loads(line_str)
                            self._dispatch_message(msg)
                        except Exception as e:
                            logger.error("Failed to parse incoming IPC message: %s", e)

        finally:
            if _is_valid_handle(h_read_event):
                kernel32.CloseHandle(h_read_event)

        self._running = False
        with self._lock:
            self.handle = None
            for req_info in self._pending_requests.values():
                req_info["response"] = {"error": "pipe closed"}
                req_info["event"].set()
            self._pending_requests.clear()

    def _dispatch_message(self, msg: Dict[str, Any]) -> None:
        """Route parsed JSON message based on request_id or event header."""
        if "request_id" in msg:
            req_id = msg["request_id"]
            with self._lock:
                req_info = self._pending_requests.get(req_id)
            if req_info:
                req_info["response"] = msg
                req_info["event"].set()
        elif "event" in msg:
            evt_name = msg.get("event", "")

            # Dispatch to generic event callback
            if self.event_callback:
                try:
                    self.event_callback(msg)
                except Exception as e:
                    logger.error("Exception in IPC event callback: %s", e)

            # Dispatch to specific event listeners
            listeners = self._event_listeners.get(evt_name, [])
            for callback in list(listeners):
                try:
                    callback(msg)
                except Exception as e:
                    logger.error("Exception in event listener for '%s': %s", evt_name, e)

            # Dispatch property change notifications
            if evt_name == "property-change":
                prop_name = msg.get("name", "")
                prop_data = msg.get("data")
                prop_listeners = self._property_listeners.get(prop_name, [])
                for prop_cb in list(prop_listeners):
                    try:
                        prop_cb(prop_name, prop_data)
                    except Exception as e:
                        logger.error("Exception in property listener for '%s': %s", prop_name, e)

    def register_event_listener(self, event_name: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for a specific mpv event."""
        with self._lock:
            if event_name not in self._event_listeners:
                self._event_listeners[event_name] = []
            if callback not in self._event_listeners[event_name]:
                self._event_listeners[event_name].append(callback)

    def unregister_event_listener(self, event_name: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Unregister a callback for a specific mpv event."""
        with self._lock:
            if event_name in self._event_listeners and callback in self._event_listeners[event_name]:
                self._event_listeners[event_name].remove(callback)

    def register_property_listener(self, prop_name: str, callback: Callable[[str, Any], None]) -> None:
        """Register a callback for a specific property change."""
        with self._lock:
            if prop_name not in self._property_listeners:
                self._property_listeners[prop_name] = []
            if callback not in self._property_listeners[prop_name]:
                self._property_listeners[prop_name].append(callback)

    def unregister_property_listener(self, prop_name: str, callback: Callable[[str, Any], None]) -> None:
        """Unregister a callback for a specific property change."""
        with self._lock:
            if prop_name in self._property_listeners and callback in self._property_listeners[prop_name]:
                self._property_listeners[prop_name].remove(callback)

    def _write_overlapped_bytes(self, raw_data: bytes, timeout_sec: float = 2.0) -> bool:
        """Writes data using Overlapped I/O."""
        with self._write_lock:
            if not _is_valid_handle(self.handle) or kernel32 is None:
                return False

            h_write_event = kernel32.CreateEventW(None, True, False, None)
            ov = OVERLAPPED()
            ov.hEvent = h_write_event
            bytes_written = wintypes.DWORD(0)

            try:
                success = kernel32.WriteFile(
                    self.handle,
                    raw_data,
                    len(raw_data),
                    None,
                    ctypes.byref(ov)
                )

                if not success:
                    err = kernel32.GetLastError()
                    if err == ERROR_IO_PENDING:
                        wait_ms = int(timeout_sec * 1000)
                        wait_res = kernel32.WaitForSingleObject(h_write_event, wait_ms)
                        if wait_res == WAIT_OBJECT_0:
                            kernel32.GetOverlappedResult(
                                self.handle,
                                ctypes.byref(ov),
                                ctypes.byref(bytes_written),
                                False
                            )
                    else:
                        logger.debug("WriteFile error code %d", err)
                else:
                    kernel32.GetOverlappedResult(
                        self.handle,
                        ctypes.byref(ov),
                        ctypes.byref(bytes_written),
                        False
                    )

                return bool(bytes_written.value == len(raw_data))
            finally:
                if _is_valid_handle(h_write_event):
                    kernel32.CloseHandle(h_write_event)

    def send_command(self, command: List[Any], timeout_sec: float = 2.0) -> Dict[str, Any]:
        """
        Send a command synchronously to mpv and wait for matching response by request_id.
        """
        if not self.is_connected():
            return {"error": "not connected"}

        with self._lock:
            self._req_counter += 1
            req_id = self._req_counter
            evt = threading.Event()
            req_info: Dict[str, Any] = {"event": evt, "response": None}
            self._pending_requests[req_id] = req_info

        payload = {"command": command, "request_id": req_id}
        raw_data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

        written = self._write_overlapped_bytes(raw_data, timeout_sec=timeout_sec)
        if not written:
            with self._lock:
                self._pending_requests.pop(req_id, None)
            return {"error": "write failed"}

        # Wait for reply
        signaled = evt.wait(timeout_sec)
        with self._lock:
            self._pending_requests.pop(req_id, None)

        if signaled:
            return req_info["response"] or {"error": "empty response"}
        else:
            return {"error": "timeout"}

    def send_command_async(self, command: List[Any]) -> bool:
        """
        Fire-and-forget command sent asynchronously without waiting for a reply.
        """
        if not self.is_connected():
            return False

        payload = {"command": command}
        raw_data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        return self._write_overlapped_bytes(raw_data, timeout_sec=1.0)

    def observe_property(self, sub_id: int, prop_name: str) -> bool:
        """Subscribe to automatic push notifications for a property."""
        return self.send_command_async(["observe_property", sub_id, prop_name])

    def unobserve_property(self, sub_id: int) -> bool:
        """Unsubscribe from property change notifications."""
        return self.send_command_async(["unobserve_property", sub_id])

    def get_property(self, prop_name: str, timeout_sec: float = 2.0) -> Any:
        """Synchronously retrieve a property value."""
        res = self.send_command(["get_property", prop_name], timeout_sec=timeout_sec)
        if res.get("error") == "success":
            return res.get("data")
        return None

    def set_property(self, prop_name: str, value: Any, timeout_sec: float = 2.0) -> bool:
        """Synchronously set a property value."""
        res = self.send_command(["set_property", prop_name, value], timeout_sec=timeout_sec)
        return res.get("error") == "success"

    def set_property_async(self, prop_name: str, value: Any) -> bool:
        """Asynchronously set a property value."""
        return self.send_command_async(["set_property", prop_name, value])
