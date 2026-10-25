"""Installs the bridge mapping into Rekordbox 6 and moves the controllers' direct mappings aside, safely.

- **Baseline:** the first time RekordTrakt touches a mapping file, an exact copy is kept and never overwritten, so
  uninstall restores what the user had before RekordTrakt, however many times it was installed or upgraded.
- **Snapshots:** each install also keeps a copy of what it replaced (the last few), for rolling back one upgrade.
- **One step:** apply() installs the bridge and disables the direct mappings as a transaction. Every file is checked
  first, every change is staged, and if anything fails, every file is put back as it was.
- **User edits:** a bridge file edited since RekordTrakt installed it (not just reformatted by Rekordbox, which
  rewrites mapping files on exit) is never overwritten without an explicit choice.

Rekordbox must be closed: it reads mapping files at start and rewrites them when it quits.
"""
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from rekordtrakt.bridge.compiler import canonical_mappings

RB_DIR = Path(os.environ["APPDATA"]) / "Pioneer" / "rekordbox6"
MAPPINGS_DIR = RB_DIR / "MidiMappings"
STATE_DIR = RB_DIR / "RekordTrakt"            # outside MidiMappings so Rekordbox never reads our backups
SNAPSHOTS_KEPT = 5


class InstallConflict(RuntimeError):
    """The bridge file was edited by hand since RekordTrakt installed it."""


class RekordboxRunning(RuntimeError):
    pass


def _paths():
    # Read at call time so tests can point the module at a temporary folder.
    return MAPPINGS_DIR, STATE_DIR, STATE_DIR / "installed.json"


def rekordbox_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq rekordbox.exe", "/NH"], capture_output=True, text=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout   # no console flash
    return "rekordbox.exe" in out


def wait_for_rekordbox_closed(poll=1.0, announce=print):
    if rekordbox_running():
        announce("Waiting for Rekordbox to close (it may rewrite mapping files on exit)")
        while rekordbox_running():
            time.sleep(poll)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_state():
    _, state_dir, state_file = _paths()
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    for name, entry in state.items():
        if "baseline" not in entry:          # written before baselines existed: the earliest backup is the original
            backups = sorted((state_dir / "backups").glob(f"{name}.*"))
            entry["baseline"] = str(backups[0]) if backups else None
            entry["baseline_absent"] = not backups
    return state


def _write_state(state):
    _, state_dir, state_file = _paths()
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, state_file)


def verify(name):
    """For a file RekordTrakt installed: 'unchanged', 'reformatted by Rekordbox' (same mappings), 'changed' or 'missing'."""
    mappings_dir, _, _ = _paths()
    target = mappings_dir / name
    entry = _load_state().get(name)
    if not target.exists():
        return "missing"
    if not entry:
        return "not installed by RekordTrakt"
    if entry["sha256"] == _sha256(target):
        return "unchanged"
    reference = Path(entry.get("reference", ""))
    if reference.is_file():
        same = canonical_mappings(reference.read_text(encoding="ascii")) == canonical_mappings(target.read_text(encoding="ascii"))
        return "reformatted by Rekordbox" if same else "changed"
    return "changed"


def has_mappings(path):
    path = Path(path)
    return path.exists() and bool(canonical_mappings(path.read_text(encoding="ascii", errors="replace")))


class _Transaction:
    """Remembers each file's contents before it is first changed; rollback() puts them all back."""

    def __init__(self):
        self.before = {}

    def touch(self, path):
        path = Path(path)
        if path not in self.before:
            self.before[path] = path.read_bytes() if path.exists() else None

    def rollback(self):
        for path, data in self.before.items():
            try:
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
            except OSError:
                pass


def _write_atomic(target, data, txn):
    txn.touch(target)
    staging = target.with_name(f".{target.name}.rekordtrakt-tmp")
    staging.write_bytes(data)
    os.replace(staging, target)                 # atomic on the same volume


def apply(csv_path, direct_names=(), overwrite_user_edit=False, announce=print, wait=True):
    """Installs the bridge mapping `csv_path` and disables the direct mappings `direct_names`, as one step.
    Raises RekordboxRunning (wait=False), InstallConflict, or the error that stopped it, after putting
    every file back."""
    mappings_dir, state_dir, state_file = _paths()
    if wait:
        wait_for_rekordbox_closed(announce=announce)
    elif rekordbox_running():
        raise RekordboxRunning("close Rekordbox first: it rewrites its mapping files when it quits")
    csv_path = Path(csv_path)
    data = csv_path.read_bytes()
    target = mappings_dir / csv_path.name
    state = _load_state()
    entry = state.get(target.name)

    # --- checks, before anything changes -----------------------------------------------------------------------
    if entry and target.exists() and verify(target.name) == "changed" and not overwrite_user_edit:
        raise InstallConflict(f"{target.name} was edited since RekordTrakt installed it; installing would replace "
                              "those edits")
    to_disable = [n for n in direct_names if has_mappings(mappings_dir / n)]

    txn = _Transaction()
    now = datetime.now()
    try:
        txn.touch(state_file)
        # Baseline: the user's file before RekordTrakt ever touched it (kept forever).
        if entry is None:
            entry = {"baseline_absent": not target.exists(), "baseline": None}
            if target.exists():
                baseline = state_dir / "baseline" / target.name
                if not baseline.exists():
                    txn.touch(baseline)
                    baseline.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(target, baseline)
                entry["baseline"] = str(baseline)
        # Snapshot: what this install replaces (for rolling back one upgrade).
        snapshots = list(entry.get("snapshots", []))
        if target.exists():
            snap = state_dir / "snapshots" / f"{target.name}.{now:%Y%m%d-%H%M%S-%f}"
            txn.touch(snap)
            snap.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, snap)
            snapshots.append(str(snap))
        mappings_dir.mkdir(parents=True, exist_ok=True)
        _write_atomic(target, data, txn)
        reference = state_dir / "installed" / target.name     # what we installed, for semantic comparison later
        reference.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(reference, data, txn)
        for name in to_disable:
            _disable(name, txn, announce)
        entry.update({"sha256": hashlib.sha256(data).hexdigest(), "installed": now.isoformat(timespec="seconds"),
                      "reference": str(reference), "snapshots": snapshots[-SNAPSHOTS_KEPT:]})
        state[target.name] = entry
        _write_state(state)
    except BaseException:
        txn.rollback()
        raise
    for old in snapshots[:-SNAPSHOTS_KEPT]:
        Path(old).unlink(missing_ok=True)
    announce(f"Installed {target.name}" + (f"; disabled {', '.join(to_disable)}" if to_disable else ""))
    return target


def install(csv_path, announce=print):
    """The bridge mapping alone (kept for scripts); apply() is the full install."""
    return apply(csv_path, (), announce=announce)


def _disable(name, txn, announce):
    mappings_dir, state_dir, _ = _paths()
    source = mappings_dir / name
    target = state_dir / "disabled" / name
    txn.touch(source)
    txn.touch(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():                     # an older disabled copy: keep it beside, with a date
        older = target.with_name(f"{name}.{datetime.now():%Y%m%d-%H%M%S-%f}")
        txn.touch(older)
        shutil.copyfile(target, older)
    shutil.copyfile(source, target)
    source.unlink()
    announce(f"Disabled direct mapping {name} (kept in {target.parent})")


def disable(name, announce=print):
    """Moves a controller's direct mapping out of Rekordbox's folder (so the translator doesn't double-fire)."""
    wait_for_rekordbox_closed(announce=announce)
    mappings_dir, _, _ = _paths()
    if not has_mappings(mappings_dir / name):
        return False
    txn = _Transaction()
    try:
        _disable(name, txn, announce)
    except BaseException:
        txn.rollback()
        raise
    return True


def enable(name, announce=print):
    """Puts a disabled direct mapping back (the manual fallback). Rekordbox may have left an empty file
    with the same name; that is replaced, but a file with mappings in it is not."""
    wait_for_rekordbox_closed(announce=announce)
    mappings_dir, state_dir, _ = _paths()
    source = state_dir / "disabled" / name
    if not source.exists():
        return False
    target = mappings_dir / name
    if has_mappings(target):
        raise FileExistsError(f"{target} already has mappings; not overwriting it")
    shutil.move(str(source), str(target))
    announce(f"Re-enabled direct mapping {name}")
    return True


def restore(name, announce=print):
    """Uninstall: puts back the baseline (the file as it was before RekordTrakt first touched it), or removes the
    file if there was none."""
    wait_for_rekordbox_closed(announce=announce)
    mappings_dir, _, _ = _paths()
    state = _load_state()
    entry = state.get(name)
    if not entry:
        raise LookupError(f"{name} was not installed by RekordTrakt")
    target = mappings_dir / name
    if entry.get("baseline"):
        shutil.copyfile(entry["baseline"], target)
        announce(f"Restored {name} as it was before RekordTrakt")
    elif target.exists():
        target.unlink()
        announce(f"Removed {name} (there was none before RekordTrakt)")
    del state[name]
    _write_state(state)
