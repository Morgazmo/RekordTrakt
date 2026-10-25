"""Starts the RekordTrakt tray app without a console window (double-click, or what start-at-login runs)."""
import sys

from rekordtrakt.shell.app import main

sys.exit(main())
