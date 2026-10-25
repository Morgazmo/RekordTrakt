"""Start at login: a per-user value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run (no admin needed).

`reg` is the winreg module; tests pass a fake.
"""
import sys
import winreg
from pathlib import Path

from rekordtrakt import paths

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "RekordTrakt"


def command():
    """What Windows runs at login: the installed RekordTrakt.exe, or pythonw with a source checkout's launcher."""
    if paths.INSTALLED:
        return f'"{sys.executable}" --login'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else sys.executable}" "{paths.PROGRAM_DIR / "RekordTrakt.pyw"}" --login'


def is_enabled(reg=winreg):
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
            reg.QueryValueEx(key, VALUE)
            return True
    except OSError:
        return False


def enable(reg=winreg):
    with reg.CreateKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
        reg.SetValueEx(key, VALUE, 0, reg.REG_SZ, command())


def disable(reg=winreg):
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
            reg.DeleteValue(key, VALUE)
    except FileNotFoundError:
        pass


def set_enabled(on, reg=winreg):
    (enable if on else disable)(reg)
