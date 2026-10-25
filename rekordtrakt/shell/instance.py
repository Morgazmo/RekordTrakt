"""One tray app at a time, and how a second launch (or the command line) finds the running one."""
import ctypes
import json
import os
from ctypes import wintypes

from rekordtrakt.shell.events import APP_DIR

MUTEX_NAME = "Local\\RekordTrakt.App"
INFO_FILE = APP_DIR / "app.json"        # port and token of the running app's local web server
ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.OpenMutexW.restype = wintypes.HANDLE
_kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


class SingleInstance:
    def __init__(self, name=MUTEX_NAME):
        self.handle = _kernel32.CreateMutexW(None, False, name)
        self.first = bool(self.handle) and ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def release(self):
        if self.handle:
            _kernel32.CloseHandle(self.handle)
            self.handle = None


def is_running(name=MUTEX_NAME):
    handle = _kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if handle:
        _kernel32.CloseHandle(handle)
    return bool(handle)


def write_info(port, token):
    INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
    INFO_FILE.write_text(json.dumps({"pid": os.getpid(), "port": port, "token": token}), encoding="utf-8")


def read_info():
    try:
        return json.loads(INFO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear_info():
    INFO_FILE.unlink(missing_ok=True)
