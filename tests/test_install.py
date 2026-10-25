"""Installing into Rekordbox's mapping folder: baseline kept across upgrades, user edits protected, and an
all-or-nothing install. Uses a temporary folder in place of Rekordbox's.

Run from the repo root:  python -m unittest discover -s tests
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import isolated                                                          # noqa: E402,F401  (first)
from rekordtrakt.bridge import install as rb                             # noqa: E402
from rekordtrakt.bridge.compiler import compile_bridge                    # noqa: E402
from rekordtrakt.rekordbox.registry import bridge_actions                  # noqa: E402

NAME = "RekordTrakt Bridge.midi.csv"
DIRECT = ("X1.midi.csv", "F1.midi.csv")


def bridge_csv(functions):
    return compile_bridge("RekordTrakt Bridge", bridge_actions([(f, 1) for f in functions]))[0]


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.mappings, self.state = self.tmp / "MidiMappings", self.tmp / "RekordTrakt"
        self.mappings.mkdir()
        self.patches = [mock.patch.object(rb, "MAPPINGS_DIR", self.mappings),
                        mock.patch.object(rb, "STATE_DIR", self.state),
                        mock.patch.object(rb, "rekordbox_running", lambda: False)]
        for p in self.patches:
            p.start()
        self.build = self.tmp / "build"
        self.build.mkdir()
        self.say = []

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def version(self, *functions):
        path = self.build / NAME
        path.write_text(bridge_csv(functions), encoding="ascii")
        return path

    def apply(self, path, direct=(), **kw):
        return rb.apply(path, direct, announce=self.say.append, **kw)

    def direct(self, name, functions=("PlayPause",)):
        (self.mappings / name).write_text(bridge_csv(functions), encoding="ascii")

    def test_install_upgrade_upgrade_uninstall_restores_the_original(self):
        original = b"@file,1,RekordTrakt Bridge\n"            # what Rekordbox had before (an empty stub)
        (self.mappings / NAME).write_bytes(original)
        self.apply(self.version("PlayPause"))
        self.apply(self.version("PlayPause", "Cue"))
        self.apply(self.version("PlayPause", "Cue", "Sync"))
        state = json.loads((self.state / "installed.json").read_text())[NAME]
        self.assertEqual(len(state["snapshots"]), 3)
        rb.restore(NAME, announce=self.say.append)
        self.assertEqual((self.mappings / NAME).read_bytes(), original)
        self.assertNotIn(NAME, json.loads((self.state / "installed.json").read_text()))

    def test_uninstall_removes_a_file_that_was_not_there_before(self):
        self.apply(self.version("PlayPause"))
        self.apply(self.version("Cue"))
        rb.restore(NAME, announce=self.say.append)
        self.assertFalse((self.mappings / NAME).exists())

    def test_reformatting_by_rekordbox_is_not_a_user_edit(self):
        target = self.apply(self.version("PlayPause"))
        target.write_text(target.read_text().replace("\n", "\r\n"), encoding="ascii")    # same mappings, rewritten
        self.apply(self.version("Cue"))                                                  # no conflict

    def test_a_user_edit_is_not_overwritten_without_a_choice(self):
        target = self.apply(self.version("PlayPause"))
        target.write_text(bridge_csv(["Sync"]), encoding="ascii")                         # edited by hand
        with self.assertRaises(rb.InstallConflict):
            self.apply(self.version("Cue"))
        self.assertIn("Sync", target.read_text())
        self.apply(self.version("Cue"), overwrite_user_edit=True)
        self.assertIn("Cue", target.read_text())

    def test_bridge_and_direct_mappings_change_together(self):
        for name in DIRECT:
            self.direct(name)
        self.apply(self.version("PlayPause"), DIRECT)
        for name in DIRECT:
            self.assertFalse((self.mappings / name).exists())
            self.assertTrue((self.state / "disabled" / name).exists())

    def test_an_interrupted_install_puts_everything_back(self):
        original = b"@file,1,RekordTrakt Bridge\n"
        (self.mappings / NAME).write_bytes(original)
        for name in DIRECT:
            self.direct(name)
        before = {p.name: p.read_bytes() for p in self.mappings.iterdir()}
        real_disable = rb._disable

        def fail_on_second(name, txn, announce):
            if name == DIRECT[1]:
                raise OSError("disk full")
            real_disable(name, txn, announce)
        with mock.patch.object(rb, "_disable", fail_on_second):
            with self.assertRaises(OSError):
                self.apply(self.version("PlayPause"), DIRECT)
        after = {p.name: p.read_bytes() for p in self.mappings.iterdir() if not p.name.startswith(".")}
        self.assertEqual(after, before)
        self.assertFalse((self.state / "installed.json").exists())

    def test_refuses_while_rekordbox_runs_when_not_waiting(self):
        with mock.patch.object(rb, "rekordbox_running", lambda: True):
            with self.assertRaises(rb.RekordboxRunning):
                self.apply(self.version("PlayPause"), wait=False)
        self.assertFalse((self.mappings / NAME).exists())

    def test_old_state_files_get_their_earliest_backup_as_baseline(self):
        (self.state / "backups").mkdir(parents=True)
        (self.state / "backups" / f"{NAME}.20261023-120000").write_bytes(b"original")
        (self.state / "backups" / f"{NAME}.20261024-090000").write_bytes(b"rekordtrakt v1")
        (self.mappings / NAME).write_text(bridge_csv(["PlayPause"]), encoding="ascii")
        (self.state / "installed.json").write_text(json.dumps({NAME: {
            "sha256": rb._sha256(self.mappings / NAME), "installed": "2026-10-24T09:00:00", "reference": "",
            "backup": str(self.state / "backups" / f"{NAME}.20261024-090000")}}))
        self.apply(self.version("Cue"))
        rb.restore(NAME, announce=self.say.append)
        self.assertEqual((self.mappings / NAME).read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
