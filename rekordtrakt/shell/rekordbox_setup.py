"""Updating Rekordbox's MIDI mapping from the window, never from a command line.

The window walks through three steps, each on the user's click:
  1. Close Rekordbox: asks it to close normally (as its own close button does; it may ask first). If a deck is
     playing, it says so and waits for "close anyway". If Rekordbox isn't responding (left running with no
     window, say, so it can't be asked), the window offers to end it.
  2. Install: the whole-registry bridge mapping, with the controllers' direct mappings turned off, as one step with
     backups (bridge/install.py). A bridge file someone edited by hand is only replaced on a second, explicit click.
  3. Start Rekordbox.
After installing, the translator restarts so it reads the new mapping.
"""
import csv
import io
import os
import subprocess
import threading
from pathlib import Path

from rekordtrakt import rig as rig_mod
from rekordtrakt.bridge import install as rb_install
from rekordtrakt.midi import winmm
from rekordtrakt.rekordbox import registry
from rekordtrakt.service import full_bridge, rekordbox_target
from rekordtrakt.shell.events import APP_DIR

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def close_rekordbox():
    """WM_CLOSE to Rekordbox's windows (taskkill without /F): Rekordbox closes normally and saves its state."""
    subprocess.run(["taskkill", "/IM", "rekordbox.exe"], capture_output=True, creationflags=NO_WINDOW)


def end_rekordbox():
    """Ends Rekordbox's process: only for a Rekordbox that isn't responding, and only on the user's click."""
    subprocess.run(["taskkill", "/F", "/IM", "rekordbox.exe"], capture_output=True, creationflags=NO_WINDOW)


def parse_tasklist(text):
    """rekordbox.exe rows of `tasklist /V /FO CSV /NH`: [{"pid", "status", "window"}] ("Not Responding" = hung)."""
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 9 and row[0].lower() == "rekordbox.exe":
            rows.append({"pid": int(row[1]), "status": row[5], "window": row[8]})
    return rows


def rekordbox_processes():
    out = subprocess.run(["tasklist", "/V", "/FI", "IMAGENAME eq rekordbox.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    return parse_tasklist(out)


def installed_versions(program_files=None):
    """{major: [rekordbox.exe paths, oldest first]}: Rekordbox 6 lives in Program Files/Pioneer, 7 in Program Files/rekordbox."""
    roots = [program_files] if program_files else [os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles")]
    out = {6: [], 7: []}
    for root in dict.fromkeys(filter(None, roots)):
        out[6] += sorted(Path(root, "Pioneer").glob("rekordbox 6*/rekordbox.exe"))
        out[7] += sorted(Path(root, "rekordbox").glob("rekordbox 7*/rekordbox.exe"))
    return out


def find_rekordbox(program_files=None, target=6):
    """The Rekordbox program to start: for 6, preferably the version the registry was made for; for 7, the newest."""
    found = installed_versions(program_files)[7 if target == 7 else 6]
    if target != 7:
        exact = [p for p in found if registry.REKORDBOX in p.parent.name]
        if exact:
            return exact[0]
    return found[-1] if found else None


class RekordboxSetup:
    def __init__(self, supervisor, load_rig=rig_mod.load, running=rb_install.rekordbox_running, apply=rb_install.apply,
                 save_rig=None,
                 close=close_rekordbox, find=find_rekordbox, launch=os.startfile, out_dir=APP_DIR / "bridge",
                 processes=rekordbox_processes, end=end_rekordbox, midi_stuck=winmm.service_stuck,
                 later=lambda fn, *args: threading.Thread(target=fn, args=args, daemon=True).start()):
        self.supervisor = supervisor
        self.load_rig = load_rig
        self.save_rig = save_rig or rig_mod.save
        self.running = running
        self.apply = apply
        self.close_rekordbox = close
        self.find = find
        self.launch = launch
        self.out_dir = Path(out_dir)
        self.processes = processes
        self.end_rekordbox = end
        self.midi_stuck = midi_stuck
        self.later = later                      # restarting the translator waits for it: not on the request

    def actions(self):
        return {"rekordbox-check": self.check, "rekordbox-close": self.close, "rekordbox-install": self.install,
                "rekordbox-start": self.start}

    def _target(self):
        try:
            return rekordbox_target(self.load_rig())
        except (OSError, ValueError):
            return 6

    def seen(self, version):
        """Rekordbox `version` ("7.2.19") started: the bridge follows it. When that's a different major version
        from the one it's built for, remember it and restart the translator, so the update for it is offered."""
        try:
            major = int(str(version).split(".")[0])
        except ValueError:
            return
        if major not in (6, 7):
            return
        rig = self.load_rig()
        bridge = rig.setdefault("bridge", {})
        if bridge.get("rekordbox_seen") == major and "rekordbox" not in bridge:
            return
        was = rekordbox_target(rig)
        bridge["rekordbox_seen"] = major
        bridge.pop("rekordbox", None)          # a version picked by hand in an older RekordTrakt: no longer used
        self.save_rig(rig)
        if was != major:
            self.later(self.supervisor.restart, f"Rekordbox {version} is running: the bridge follows it")

    def check(self, body=None):
        procs = self.processes()
        versions = {k: [str(p) for p in v] for k, v in installed_versions().items()} if self.find is find_rekordbox else {}
        return {"running": bool(procs), "responding": all(p["status"] != "Not Responding" for p in procs),
                "found": bool(self._find()), "midi_stuck": self.midi_stuck(), "installed": versions}

    def _find(self):
        try:
            return self.find(target=self._target())
        except TypeError:                      # a find() without a target (tests, the simulator)
            return self.find()

    def _playing(self):
        try:
            return self.supervisor.translator.call(lambda engine: engine.playing_decks())
        except RuntimeError:                    # the translator isn't running: nothing to know
            return []

    def close(self, body=None):
        body = body or {}
        if not self.running():
            return {"closing": False, "running": False}
        if body.get("end"):                     # the user's "End it", offered when it isn't responding
            self.end_rekordbox()
            return {"closing": True, "running": True, "ended": True}
        playing = self._playing()
        if playing and not body.get("anyway"):
            return {"closing": False, "running": True, "playing": playing}
        self.close_rekordbox()
        return {"closing": True, "running": True}

    def install(self, body=None):
        body = body or {}
        if self.running():
            return {"installed": False, "needs": "close"}
        rig = self.load_rig()
        csv_text, manifest = full_bridge(rig)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{rig['bridge']['rekordbox_port']}.midi.csv"
        path.write_bytes(csv_text.encode("ascii"))
        said = []
        try:
            self.apply(path, [f"{d['port']}.midi.csv" for d in rig["devices"].values()],
                       overwrite_user_edit=bool(body.get("overwrite")), announce=said.append, wait=False)
        except rb_install.InstallConflict as e:
            return {"installed": False, "conflict": str(e)}
        except rb_install.RekordboxRunning:
            return {"installed": False, "needs": "close"}
        self.later(self.supervisor.restart, "Rekordbox's MIDI mapping was updated")
        return {"installed": True, "entries": len(manifest["entries"]), "version": registry.VERSION,
                "message": " ".join(said)}

    def start(self, body=None):
        if self.running():
            return {"starting": False, "running": True}
        if self.midi_stuck():
            raise RuntimeError(winmm.STUCK_ADVICE.replace("Close Rekordbox, then restart", "Restart") +
                               " Start Rekordbox after that.")
        exe = self._find()
        if not exe:
            raise RuntimeError(f"Rekordbox {self._target()} wasn't found in Program Files: start it from the Start menu")
        self.launch(str(exe))
        return {"starting": True}
