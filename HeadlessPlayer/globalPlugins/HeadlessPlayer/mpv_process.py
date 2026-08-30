# -*- coding: utf-8 -*-
"""
mpv Process Lifecycle & Discovery Manager.
Launches headless, detached mpv daemon process with zero UI, console, or taskbar footprint.
Implements 4-tier mpv binary discovery cascade across bundled resources, user settings,
system PATH, and standard Windows package manager locations.
"""

import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import List, Optional

logger = logging.getLogger("HeadlessPlayer.MpvProcess")

# Default pipe endpoint
DEFAULT_PIPE_NAME = r"\\.\pipe\nvda_headless_player"

# Windows Process Creation Flags
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

# Win32 Job Object Constants
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    try:
        kernel32 = ctypes.windll.kernel32
    except (AttributeError, OSError):
        kernel32 = None
else:
    kernel32 = None

if kernel32 is not None:
    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryLimit", ctypes.c_size_t),
            ("PeakJobMemoryLimit", ctypes.c_size_t),
        ]

    try:
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE

        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL

        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
    except Exception:
        pass



def get_system_architecture() -> str:
    """
    Detect machine CPU architecture normalized to 'x64', 'arm64', or 'x86'.
    """
    arch = platform.machine().lower()
    if arch in ("amd64", "x86_64", "em64t"):
        return "x64"
    elif arch in ("arm64", "aarch64"):
        return "arm64"
    elif arch in ("i386", "i686", "x86"):
        return "x86"
    return "x64"  # Default fallback


def find_mpv_binary(
    custom_path: Optional[str] = None,
    addon_root: Optional[str] = None
) -> Optional[str]:
    """
    4-Tier Discovery Cascade for mpv binary:
    Tier 1: User-configured custom path (NVDA settings)
    Tier 2: Bundled add-on resources (resources/bin/<arch>/mpv.exe)
    Tier 3: System PATH (shutil.which)
    Tier 4: Standard Windows install locations (Scoop, Chocolatey, Program Files, LocalAppData)
    """
    # --- Tier 1: User-Configured Custom Path ---
    if custom_path and isinstance(custom_path, str) and custom_path.strip():
        expanded = os.path.expandvars(custom_path.strip().strip('"'))
        if os.path.isfile(expanded):
            logger.info("Found user-configured mpv binary: %s", expanded)
            return os.path.abspath(expanded)
        else:
            logger.warning("Configured custom mpv path does not exist: %s", custom_path)

    # --- Tier 2: Bundled Add-on Resources ---
    if not addon_root:
        # Resolve add-on root directory relative to this module:
        # HeadlessPlayer/globalPlugins/HeadlessPlayer/mpv_process.py -> HeadlessPlayer
        module_dir = os.path.dirname(os.path.abspath(__file__))
        addon_root = os.path.abspath(os.path.join(module_dir, "..", ".."))

    arch = get_system_architecture()
    candidate_bundled = [
        os.path.join(addon_root, "resources", "bin", arch, "mpv.exe"),
    ]
    if arch == "x64":
        candidate_bundled.append(os.path.join(addon_root, "resources", "bin", "x64", "mpv.exe"))
    candidate_bundled.append(os.path.join(addon_root, "resources", "bin", "mpv.exe"))
    for path in candidate_bundled:
        if os.path.isfile(path):
            logger.info("Found bundled mpv binary: %s", path)
            return os.path.abspath(path)

    # --- Tier 3: System PATH ---
    path_which = shutil.which("mpv") or shutil.which("mpv.exe")
    if path_which and os.path.isfile(path_which):
        logger.info("Found mpv on system PATH: %s", path_which)
        return os.path.abspath(path_which)

    # --- Tier 4: Standard Windows Installation Locations ---
    standard_locations = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "mpv", "mpv.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "mpv", "mpv.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\mpv\mpv.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\apps\mpv\current\mpv.exe"),
        r"C:\ProgramData\chocolatey\bin\mpv.exe",
        os.path.expandvars(r"%APPDATA%\mpv\mpv.exe"),
        os.path.expandvars(r"%USERPROFILE%\mpv\mpv.exe"),
    ]

    for loc in standard_locations:
        if os.path.isfile(loc):
            logger.info("Found mpv in standard installation path: %s", loc)
            return os.path.abspath(loc)

    logger.debug("mpv executable could not be discovered in any cascade tier.")
    return None


def get_default_mpv_args(pipe_name: str = DEFAULT_PIPE_NAME) -> List[str]:
    """
    Construct the baseline headless arguments for mpv.
    Guarantees no window, no console, no OSD, pitch preservation, and IPC server initialization.
    """
    return [
        "--idle=yes",
        "--keep-open=no",
        "--vo=null",
        "--no-video",
        "--no-terminal",
        "--force-window=no",
        f"--input-ipc-server={pipe_name}",
        "--audio-pitch-correction=yes",
        "--volume-max=150",
        "--hr-seek=yes",
        "--hr-seek-framedrop=no",
        "--ytdl=no",
        "--config=no",
        "--load-scripts=no",
        "--no-sub",
        "--no-osc",
        "--no-osd-bar",
        "--msg-level=all=no",
    ]


# Module-level constant for headless arguments
HEADLESS_FLAGS = get_default_mpv_args()


class MpvProcess:
    """
    Manages the lifecycle of the detached headless mpv subprocess.
    """

    def __init__(
        self,
        mpv_executable: Optional[str] = None,
        pipe_name: str = DEFAULT_PIPE_NAME,
        extra_args: Optional[List[str]] = None,
        addon_root: Optional[str] = None
    ):
        self.pipe_name: str = pipe_name
        self.extra_args: List[str] = extra_args or []
        self.addon_root: Optional[str] = addon_root
        self._custom_executable: Optional[str] = mpv_executable
        self._discovered_executable: Optional[str] = None
        self.process: Optional[subprocess.Popen] = None
        self._job_handle: Optional[Any] = None

    def _assign_process_to_job(self) -> bool:
        """
        Assigns the spawned mpv subprocess to a Win32 Job Object with
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000). Guarantees the OS will
        automatically terminate mpv if NVDA crashes or terminates unexpectedly.
        """
        if os.name != "nt" or kernel32 is None or not self.process:
            return False

        try:
            if not self._job_handle:
                h_job = kernel32.CreateJobObjectW(None, None)
                if not h_job:
                    logger.debug("CreateJobObjectW failed with error %d", kernel32.GetLastError())
                    return False
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                success = kernel32.SetInformationJobObject(
                    h_job,
                    JobObjectExtendedLimitInformation,
                    ctypes.byref(info),
                    ctypes.sizeof(info)
                )
                if not success:
                    logger.debug("SetInformationJobObject failed with error %d", kernel32.GetLastError())
                    kernel32.CloseHandle(h_job)
                    return False
                self._job_handle = h_job

            proc_handle = getattr(self.process, "_handle", None)
            if proc_handle is not None:
                assign_ok = kernel32.AssignProcessToJobObject(self._job_handle, int(proc_handle))
                if assign_ok:
                    logger.info("Successfully bound mpv process (PID %d) to Win32 Job Object.", self.process.pid)
                    return True
                else:
                    logger.debug("AssignProcessToJobObject failed with error %d", kernel32.GetLastError())
        except Exception as e:
            logger.debug("Exception assigning mpv process to Job Object: %s", e)
        return False

    @property
    def executable_path(self) -> Optional[str]:
        """Resolved path to mpv executable."""
        if self._discovered_executable and os.path.isfile(self._discovered_executable):
            return self._discovered_executable
        self._discovered_executable = find_mpv_binary(
            custom_path=self._custom_executable,
            addon_root=self.addon_root
        )
        return self._discovered_executable

    @property
    def pid(self) -> Optional[int]:
        """PID of running mpv process if active."""
        if self.process and self.process.poll() is None:
            return self.process.pid
        return None

    def is_running(self) -> bool:
        """Check if the mpv subprocess is actively running."""
        return bool(self.process and self.process.poll() is None)

    def start(self) -> bool:
        """
        Launch the detached, windowless mpv process.
        Returns True on successful launch, False otherwise.
        """
        if self.is_running():
            logger.debug("mpv process is already running (PID: %d).", self.process.pid)
            return True

        binary = self.executable_path
        if not binary:
            logger.error("Cannot launch mpv: No executable found in discovery cascade.")
            return False

        args = [binary] + get_default_mpv_args(self.pipe_name) + self.extra_args

        startupinfo = None
        creationflags = 0

        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            creationflags = CREATE_NO_WINDOW

        try:
            logger.info("Launching headless mpv daemon: %s (Pipe: %s)", binary, self.pipe_name)
            self.process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
                creationflags=creationflags,
                close_fds=True
            )
            # Short sleep to allow process initialization
            time.sleep(0.05)
            if self.process.poll() is not None:
                logger.error("mpv process terminated immediately with exit code %d", self.process.poll())
                return False

            # Assign to Win32 Job Object for crash daemon protection
            self._assign_process_to_job()
            return True
        except Exception as e:
            logger.error("Failed to launch mpv subprocess: %s", e, exc_info=True)
            self.process = None
            return False

    def stop(self, timeout_sec: float = 2.0) -> bool:
        """
        Gracefully terminate the mpv subprocess, falling back to force-kill if needed.
        """
        try:
            if self.process and self.process.poll() is None:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=timeout_sec)
                    logger.info("mpv process terminated gracefully.")
                except subprocess.TimeoutExpired:
                    logger.warning("mpv process did not terminate within timeout; killing forcefully.")
                    try:
                        self.process.kill()
                        self.process.wait(timeout=1.0)
                    except Exception as e:
                        logger.debug("Error force-killing mpv process: %s", e)
                except Exception as e:
                    logger.error("Error stopping mpv process: %s", e)
        finally:
            self.process = None
            if self._job_handle and kernel32 is not None:
                try:
                    kernel32.CloseHandle(self._job_handle)
                except Exception:
                    pass
                self._job_handle = None

        return True

    def build_mpv_arguments(self, binary: Optional[str] = None) -> List[str]:
        """Constructs full argument list for launching mpv subprocess."""
        bin_path = binary or self.executable_path or "mpv.exe"
        return [bin_path] + get_default_mpv_args(self.pipe_name) + self.extra_args

    def terminate(self, timeout_sec: float = 2.0) -> bool:
        """Alias for stop() to terminate subprocess."""
        return self.stop(timeout_sec=timeout_sec)

    def kill(self) -> None:
        """Forcefully kill mpv subprocess immediately."""
        if self.process and self.process.poll() is None:
            try:
                self.process.kill()
            except Exception as e:
                logger.debug("Error killing mpv process: %s", e)
            self.process = None
