"""Your rig: which controllers RekordTrakt uses, on which MIDI ports, and which decks each one drives.

Kept per user in rig.json (paths.DATA_DIR). The first run creates it with the bridge ports and no controllers;
they're added in the window (Settings > MIDI devices).
"""
import json
import os
import queue
import re
import shutil
import time
from pathlib import Path

from rekordtrakt import paths
from rekordtrakt.devices import DEVICE_TYPES
from rekordtrakt.engine.engine import DeviceConfig

RIG_FILE = paths.DATA_DIR / "rig.json"
# A source checkout before 1.0 kept the rig next to the code: moved on first run (never under test).
OLD_RIG_FILE = None if os.environ.get("REKORDTRAKT_HOME") else paths.PACKAGE_DIR.parent / "rig.local.json"
BRIDGE_PORTS = {"app_port": "RekordTrakt App", "rekordbox_port": "RekordTrakt Bridge"}
PORT_HINTS = {"x1mk3": "X1 MK3", "f1": "F1"}


def new_rig():
    return {"bridge": dict(BRIDGE_PORTS), "devices": {}}


def load(path=RIG_FILE):
    """The rig, created on first use (or moved from where an older version kept it)."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path == RIG_FILE and OLD_RIG_FILE and OLD_RIG_FILE.exists():
            shutil.copyfile(OLD_RIG_FILE, path)
        else:
            save(new_rig(), path)
    rig = json.loads(path.read_text(encoding="utf-8"))
    for key, port in BRIDGE_PORTS.items():
        rig.setdefault("bridge", {}).setdefault(key, port)
    rig.setdefault("devices", {})
    return rig


def default_name(position):
    """'x1_left' -> 'X1 Left', until the user renames it."""
    return " ".join(w.upper() if len(w) <= 2 else w.capitalize() for w in position.split("_"))


def device_configs(rig):
    return [DeviceConfig(pos, DEVICE_TYPES[d["type"]](), list(d["decks"]), list(d["fx_units"]),
                         options=dict(d.get("options", {})), profile=d.get("profile", ""),
                         name=d.get("name") or default_name(pos), mapping=dict(d.get("mapping") or {}))
            for pos, d in rig["devices"].items()]


PRESETS = {"x1mk3": "performance_mod"}       # the preset a newly added controller of a type starts with


def with_device(rig, port, type_name, mapping=None, unit=None):
    """Adds a controller on `port` (and physical `unit`, when known) to a rig; returns its position. Decks 1 and 2."""
    if type_name not in DEVICE_TYPES:
        raise ValueError(f"no controller type '{type_name}'")
    if any(d["port"] == port for d in rig.get("devices", {}).values()):
        raise ValueError(f"'{port}' is already added")
    device = DEVICE_TYPES[type_name]()
    n, position = 1, f"{type_name}_1"
    while position in rig.setdefault("devices", {}):
        n += 1
        position = f"{type_name}_{n}"
    if device.has_halves:
        decks, fx_units = [1, 2], [1, 2]
    else:
        decks = [s.get("default", i + 1) for i, s in enumerate(getattr(device, "deck_slots", ()))]
        fx_units = [s.get("default", 1) for s in getattr(device, "fx_slots", ())]
    entry = {"type": type_name, "port": port, "decks": decks, "fx_units": fx_units,
             "name": device.display_name + (f" {n}" if n > 1 else ""), "profile": PRESETS.get(type_name, "")}
    if mapping and (mapping.get("bindings") or mapping.get("pages")):
        entry["mapping"] = mapping
    if unit:
        entry["unit"] = unit
    rig["devices"][position] = entry
    return position


WINDOWS_NUMBER = re.compile(r"^\d+ - ")         # "2 - TRAKTOR X1 MK3": Windows numbers identical port names


def follow_units(rig, units):
    """Puts each controller on the port its own unit has now. Windows numbers identical port names in the order
    the units appear, so two X1s can swap names after a replug; the unit (`units`: {port name: unit}, from
    bridge.ports.port_units) can't. A controller without a unit yet gets the one on its port. Changes the rig;
    returns [(position, old port, new port)]."""
    names_of = {}
    for name, unit in units.items():
        names_of.setdefault(unit, []).append(name)
    devices, moves = rig.get("devices", {}), []
    for pos, d in devices.items():
        unit = d.get("unit")
        if not unit:
            if units.get(d["port"]):
                d["unit"] = units[d["port"]]
            continue
        names = names_of.get(unit, [])
        if d["port"] in names:
            continue
        if len(names) > 1:                                  # a unit with several ports: the one with this name
            names = [n for n in names if WINDOWS_NUMBER.sub("", n) == WINDOWS_NUMBER.sub("", d["port"])]
        if len(names) != 1:
            continue                                        # not connected now
        old, new = d["port"], names[0]
        for other_pos, other in devices.items():            # whoever had that name had the other unit: swap
            if other_pos != pos and other["port"] == new:
                other["port"] = old
        d["port"] = new
        moves.append((pos, old, new))
    return moves


def without_device(rig, position):
    if position not in rig.get("devices", {}):
        raise ValueError(f"no controller '{position}'")
    del rig["devices"][position]


def save(rig, path=RIG_FILE):
    """Written whole to a temporary file first, so a crash never leaves half a rig."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rig, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save_device(dev, path=RIG_FILE):
    """Writes a device's deck/FX assignment, options, name and mapping back to the rig."""
    rig = load(path)
    d = rig["devices"][dev.position]
    d["decks"], d["fx_units"], d["options"] = list(dev.decks), list(dev.fx_units), dict(dev.options)
    d["name"] = dev.name
    if dev.mapping.get("bindings") or dev.mapping.get("pages"):
        d["mapping"] = dev.mapping
    else:
        d.pop("mapping", None)
    save(rig, path)


def identify(winmm, path=RIG_FILE, timeout=60):
    """Asks you to press a control on each unit in turn and records which MIDI port it came from."""
    rig = load(path)
    q = queue.Queue()
    candidates = [n for n in winmm.input_names() if any(h.lower() in n.lower() for h in PORT_HINTS.values())]
    ports = [winmm.MidiIn(n, q) for n in candidates]
    try:
        taken = set()
        for pos, d in rig["devices"].items():
            print(f"Press any button on the unit you want as '{pos}' ({d['type']})")
            deadline = time.monotonic() + timeout
            while True:
                try:
                    port, status, *_ = q.get(timeout=max(0.1, deadline - time.monotonic()))
                except queue.Empty:
                    raise TimeoutError(f"nothing pressed for '{pos}'") from None
                hint = PORT_HINTS[d["type"]].lower()
                if hint in port.lower() and port not in taken:
                    d["port"] = port
                    taken.add(port)
                    print(f"   {pos} = '{port}'")
                    time.sleep(0.5)
                    while not q.empty():
                        q.get_nowait()
                    break
    finally:
        for p in ports:
            p.close()
    save(rig, path)
    print(f"Saved {path}")
    return rig
