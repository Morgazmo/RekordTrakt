"""Opens the RekordTrakt window as an app window in Microsoft Edge.

Edge comes with Windows 11, so nothing extra is installed. Its own profile folder keeps these windows apart from
the user's browsing. Without Edge, the default browser is used.
"""
import subprocess
import webbrowser
import winreg
from pathlib import Path

from rekordtrakt.shell.events import APP_DIR

PROFILE_DIR = APP_DIR / "window-profile"
EDGE_FALLBACKS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")


def edge_path():
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") as key:
                path = winreg.QueryValue(key, None)
                if path and Path(path).exists():
                    return path
        except OSError:
            pass
    return next((p for p in EDGE_FALLBACKS if Path(p).exists()), None)


def open_window(url, size=(1460, 960)):          # fits two X1s and two F1s without scrolling
    """Returns "edge" or "browser"."""
    edge = edge_path()
    if edge:
        subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={PROFILE_DIR}", f"--window-size={size[0]},{size[1]}",
                          "--no-first-run", "--no-default-browser-check", "--disable-sync", "--disable-extensions"],
                         close_fds=True)
        return "edge"
    webbrowser.open(url)
    return "browser"
