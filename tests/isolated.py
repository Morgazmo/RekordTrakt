"""Imported first by every test module: RekordTrakt's per-user files (rig, logs, imported controllers) go to a
temporary folder, never the real ones. EXAMPLE is a rig with two X1 MK3s and two F1s to test with."""
import json
import os
import tempfile
from pathlib import Path

os.environ["REKORDTRAKT_HOME"] = tempfile.mkdtemp(prefix="rekordtrakt-test-")
EXAMPLE_FILE = Path(__file__).resolve().parent / "fixtures" / "rig.json"
EXAMPLE = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
