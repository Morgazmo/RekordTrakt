"""The bridge port pair (app side <-> Rekordbox side): find it, or create it through the bridge helper.

The helper (tools/bridge-helper) makes a Windows MIDI Services loopback pair, so no MIDI Settings or loopMIDI install
is needed. A pair made by MIDI Settings or loopMIDI with the same names is used as it is. Never make a second pair
with names that already exist: WinMM would list each name twice, and a pair with duplicated names is refused,
never used. verify_pair() proves the two names really are one pair before any
controller is enabled.
"""
import json
import os
import queue
import random
import subprocess
import time
from pathlib import Path

from rekordtrakt import paths

EXE = "rekordtrakt-bridge.exe"
UNIQUE_IDS = ("rekordtraktapp", "rekordtraktbridge")    # fixed, so a repeat create fails instead of duplicating
LOOPMIDI_HINT = ("Windows MIDI Services isn't available on this PC (it needs Windows 11 25H2 or later). Install "
                 "loopMIDI and create a port named '{name}', then set both bridge ports in RekordTrakt's rig.json "
                 "(in %LOCALAPPDATA%\\RekordTrakt) to it.")
# Test messages: note-off on channel 16, which Rekordbox ignores (it never acts on note-off) and the bridge never uses.
PROBE_STATUS = 0x8F
PROBE_NOTES = (0x7E, 0x7F)          # app side -> Rekordbox side, Rekordbox side -> app side


def helper_path():
    """The installed helper, else a build in a source checkout."""
    bin_dir = paths.PROGRAM_DIR / "tools" / "bridge-helper" / "bin"
    candidates = [Path(os.environ["REKORDTRAKT_BRIDGE_HELPER"])] if os.environ.get("REKORDTRAKT_BRIDGE_HELPER") else []
    candidates += [paths.PROGRAM_DIR / "bridge" / EXE, bin_dir / "publish" / "win-x64" / EXE,
                   bin_dir / "x64" / "Release" / "net10.0-windows10.0.26100.0" / EXE]
    return next((p for p in candidates if p.exists()), None)


def run_helper(*args, timeout=15):
    """Runs the helper and returns its JSON result; failures come back as {"success": False, "error": ...}."""
    path = helper_path()
    if path is None:
        return {"success": False, "usable": False, "error": "bridge helper not found (build tools/bridge-helper)"}
    try:
        out = subprocess.run([str(path), *args], capture_output=True, text=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"success": False, "usable": False, "error": f"bridge helper failed: {e}"}
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"success": False, "usable": False,
                "error": f"bridge helper gave no result (exit {out.returncode}): {out.stderr.strip()[:200]}"}


def port_units(helper=run_helper):
    """{MIDI input name: the physical unit it belongs to} (the USB device's instance id, with its serial number when
    it has one), from Windows MIDI Services through the helper; {} without them, and names are all there is."""
    result = helper("ports")
    if not result.get("success"):
        return {}
    return {p["name"]: p["unit"] for p in result.get("ports", [])
            if p.get("name") and p.get("unit") and not p["unit"].upper().startswith("SWD\\")}   # SWD: virtual ports


def _present(midi, names):
    ins, outs = midi.input_names(), midi.output_names()
    return {n: min(ins.count(n), outs.count(n)) for n in names}


def ensure_pair(app_port, rekordbox_port, midi, helper=run_helper, wait=3.0, sleep=time.sleep):
    """Makes sure the bridge ports exist. Returns {"ok", "state", "message", ...}, where state is one of
    existing, created, duplicate (exists, but a name is listed twice), unavailable, failed."""
    names = {app_port, rekordbox_port}
    counts = _present(midi, names)
    if any(c > 1 for c in counts.values()):
        names_twice = " and ".join(f"'{n}'" for n, c in counts.items() if c > 1)
        return {"ok": False, "state": "duplicate",
                "message": f"There's more than one MIDI port called {names_twice}, so Rekordbox could be talking to "
                           "the wrong one. Remove the extra one in Windows MIDI Settings (or restart Windows if "
                           "RekordTrakt made it), then start again."}
    if all(counts.values()):
        result = {"ok": True, "state": "existing", "message": f"using '{app_port}' <-> '{rekordbox_port}'"}
        if len(names) == 2:
            result.update(_mute_state(app_port, rekordbox_port, helper))
        return result
    if len(names) == 1:
        return {"ok": False, "state": "unavailable", "message": f"MIDI port '{app_port}' not found (loopMIDI running?)"}

    check = helper("check")
    if not check.get("usable"):
        reason = check.get("error") or ("Windows is too old" if check.get("windows_supported") is False
                                        else "the MIDI service or its loopback transport isn't available")
        return {"ok": False, "state": "unavailable", "message": f"can't create the bridge: {reason}. "
                + LOOPMIDI_HINT.format(name=rekordbox_port)}
    created = helper("create", "--name-a", app_port, "--name-b", rekordbox_port,
                     "--id-a", UNIQUE_IDS[0], "--id-b", UNIQUE_IDS[1])
    if not created.get("success"):
        return {"ok": False, "state": "failed", "message": f"couldn't create the bridge: {created.get('error')}"}
    end = time.monotonic() + wait
    while not all(_present(midi, names).values()):
        if time.monotonic() > end:
            return {"ok": False, "state": "failed", "association_id": created.get("association_id"),
                    "message": "created the bridge, but its ports didn't appear"}
        sleep(0.1)
    return {"ok": True, "state": "created", "association_id": created.get("association_id"),
            "message": f"created '{app_port}' <-> '{rekordbox_port}' (lasts until restart; recreated at start-up)"}


def verify_pair(app_port, rekordbox_port, midi, timeout=0.5):
    """Sends a test message each way through the pair and checks it arrives on the other side. Returns None when
    the ports are one working pair, else what's wrong. (Windows MIDI Services and loopMIDI ports accept more than one
    client, so this works while Rekordbox has them open.)"""
    q = queue.Queue()
    opened = []
    try:
        for name in {app_port, rekordbox_port}:
            opened.append(midi.MidiIn(name, q))
        outs = {name: midi.MidiOut(name) for name in {app_port, rekordbox_port}}
        opened += outs.values()
        nonce = random.randint(1, 126)
        expected = {(rekordbox_port, PROBE_NOTES[0]), (app_port, PROBE_NOTES[1])}
        outs[app_port].send(PROBE_STATUS, PROBE_NOTES[0], nonce)
        outs[rekordbox_port].send(PROBE_STATUS, PROBE_NOTES[1], nonce)
        end = time.monotonic() + timeout
        while expected and time.monotonic() < end:
            try:
                port, status, d1, d2, _ = q.get(timeout=max(0.0, end - time.monotonic()))
            except queue.Empty:
                break
            if status == PROBE_STATUS and d2 == nonce:
                expected.discard((port, d1))
    except (LookupError, OSError) as e:
        return f"couldn't open the MIDI bridge ports: {e}"
    finally:
        for p in opened:
            try:
                p.close()
            except Exception:
                pass
    if expected:
        return ("the MIDI bridge ports aren't connected to each other (a test message didn't arrive). Remove any "
                "extra ports with these names in Windows MIDI Settings, then start again.")
    return None


def _mute_state(app_port, rekordbox_port, helper):
    """Windows mutes a loopback if it detects a feedback loop; the translator would then look dead."""
    listing = helper("list")
    for entry in listing.get("active", []):
        if entry["endpoint_a"]["name"] == app_port and entry["endpoint_b"]["name"] == rekordbox_port:
            if entry.get("muted_for_feedback") or entry.get("muted"):
                return {"muted": True, "message": "the bridge exists but Windows has muted it"
                        + (" after detecting a feedback loop" if entry.get("muted_for_feedback") else "")
                        + "; unmute it in MIDI Settings"}
            return {"association_id": entry["association_id"]}
    return {}


def remove_pair(app_port, rekordbox_port, helper=run_helper):
    """Removes a pair this app created. Pairs saved by MIDI Settings are left alone (they're the user's)."""
    listing = helper("list")
    if not listing.get("success"):
        return {"ok": False, "message": listing.get("error")}
    saved = {e["association_id"] for e in listing.get("saved", [])}
    removed = []
    for entry in listing.get("active", []):
        if (entry["endpoint_a"]["name"], entry["endpoint_b"]["name"]) == (app_port, rekordbox_port):
            if entry["association_id"] in saved:
                return {"ok": False, "message": "this pair was made in MIDI Settings; remove it there"}
            if helper("remove", "--association", entry["association_id"]).get("success"):
                removed.append(entry["association_id"])
    return {"ok": bool(removed), "removed": removed,
            "message": f"removed {len(removed)} pair(s)" if removed else "no app-made pair found"}
