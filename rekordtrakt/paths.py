"""Where RekordTrakt's files live: the program's own, and each user's settings, logs and window profile."""
import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
INSTALLED = bool(getattr(sys, "frozen", False))         # set by RekordTrakt.exe, the installed app
PROGRAM_DIR = Path(sys.executable).resolve().parent if INSTALLED else PACKAGE_DIR.parent
DATA_DIR = Path(os.environ.get("REKORDTRAKT_HOME")
                or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "RekordTrakt")
