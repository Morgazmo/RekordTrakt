"""A controller described by a data file, rekordtrakt/devices/definitions/<type>.json: what it is, every control
with its MIDI message and LED, and its physical layout for the window. Supporting a new MIDI controller means a
new file, not new code.

Definition format (schema 1):
  type, name, maker, midi_mode, port_hints      what it is and how to put it in MIDI mode
  halves                                         ["L", "R"] for a two-deck unit (control ids "L.x" / "R.x"), else []
                                                 (each half drives one deck and one FX unit, chosen in the window)
  deck_slots, fx_slots                           a unit without halves: the decks and FX units it drives, each
                                                 {key, label, default?}; bindings name one by its key ("a"), and the
                                                 window lets you move each. Default: decks "a" and "b" (first and
                                                 second) and FX unit "fx"; [] for none
  shift                                          {"style": "channel_offset", "offset": n} when shifted controls arrive
                                                 n channels up; {"style": "none"} when Shift sends nothing
  led_interval                                   seconds between LED messages (some units drop bursts)
  led_values                                     "velocity" (values passed through, e.g. colours) or "on_off"
  controls[]                                     {id, kind: button|knob|fader|encoder, name,
                                                  in: {msg: note|cc, ch: 1-16, num, relative?: offset64|twos_complement},
                                                  led?: true (same message as the input) or {msg, ch, num}}
  layout                                         {columns: [css widths], items: [{control | role, c, r, w?, h?,
                                                  shape?, glyph?, push?, half?, ...}]}

Buttons press on note-on > 0 (note-off or velocity 0 releases) or CC > 0 (CC 0 releases).
"""
import functools
import json
from pathlib import Path

import re

from rekordtrakt import paths
from rekordtrakt.devices.base import (DEFAULT_DECK_SLOTS, DEFAULT_FX_SLOTS, PRESS, RELEASE, RESERVED_KEYS, TURN,
                                      VALUE, Decoded, relative_offset64, relative_twos_complement)

DEFINITIONS_DIR = Path(__file__).resolve().parent / "definitions"
# Your own controllers (imported from a mapping file): with your settings, never inside the program.
USER_DEFINITIONS_DIR = paths.DATA_DIR / "devices"
KINDS = {"button": PRESS, "knob": VALUE, "fader": VALUE, "encoder": TURN}
RELATIVE = {"offset64": relative_offset64, "twos_complement": relative_twos_complement}
STATUS = {"note": 0x90, "cc": 0xB0}


class DefinitionError(ValueError):
    pass


class DefinedDevice:
    def __init__(self, definition):
        self.definition = definition
        self.type_name = definition["type"]
        self.display_name = definition["name"]
        self.led_interval = definition.get("led_interval", 0.01)
        self.has_halves = bool(definition.get("halves"))
        if self.has_halves:                     # each half has its own deck and FX unit instead
            self.deck_slots, self.fx_slots = (), ()
        else:
            self.deck_slots = tuple(definition.get("deck_slots", DEFAULT_DECK_SLOTS))
            self.fx_slots = tuple(definition.get("fx_slots", DEFAULT_FX_SLOTS))
            keys = [s.get("key") for s in self.deck_slots + self.fx_slots]
            if len(self.deck_slots) > 4 or len(self.fx_slots) > 2 or len(set(keys)) != len(keys):
                raise DefinitionError(f"{self.type_name}: up to 4 deck slots and 2 FX slots, each with its own key")
            for slot in self.deck_slots + self.fx_slots:
                key = slot.get("key")
                if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,15}", key) or (
                        key in RESERVED_KEYS and not (key == "fx" and slot in self.fx_slots)):
                    raise DefinitionError(f"{self.type_name}: '{key}' can't be a slot key")
        shift = definition.get("shift") or {}
        self.has_shift = shift.get("style") == "channel_offset"
        self._velocity = definition.get("led_values") == "velocity"
        self._in = {}           # (msg, channel 0-15, number) -> (control id, kind, shifted, relative decoder)
        self._led = {}          # control id -> (status, number)
        self._controls = []
        for c in definition["controls"]:
            spec = c["in"]
            if c["kind"] not in KINDS or spec["msg"] not in STATUS or not 1 <= spec["ch"] <= 16:
                raise DefinitionError(f"{self.type_name}: bad control {c.get('id')}")
            relative = RELATIVE.get(spec.get("relative"))
            if c["kind"] == "encoder" and relative is None:
                raise DefinitionError(f"{self.type_name}: encoder {c['id']} needs a relative style")
            self._controls.append((c["id"], KINDS[c["kind"]]))
            self._claim((spec["msg"], spec["ch"] - 1, spec["num"]), (c["id"], c["kind"], False, relative))
            if self.has_shift:
                self._claim((spec["msg"], spec["ch"] - 1 + shift["offset"], spec["num"]),
                            (c["id"], c["kind"], True, relative))
            led = c.get("led")
            if led:
                out = spec if led is True else led
                self._led[c["id"]] = (STATUS[out["msg"]] | (out["ch"] - 1), out["num"])

    def _claim(self, key, value):
        if key in self._in:
            raise DefinitionError(f"{self.type_name}: {value[0]} and {self._in[key][0]} share a MIDI message")
        self._in[key] = value

    def decode(self, status, d1, d2):
        kind, ch = status & 0xF0, status & 0x0F
        msg = "note" if kind in (0x80, 0x90) else "cc" if kind == 0xB0 else None
        hit = self._in.get((msg, ch, d1)) if msg else None
        if not hit:
            return None
        control, ckind, shifted, relative = hit
        if ckind == "button":
            pressed = (kind == 0x90 and d2 > 0) if msg == "note" else d2 > 0
            return Decoded(control, PRESS if pressed else RELEASE, shift=shifted)
        if ckind == "encoder":
            return Decoded(control, TURN, relative(d2), shifted)
        return Decoded(control, VALUE, d2, shifted)

    def led(self, control, value):
        """MIDI message that sets the LED of `control`, or None if it has none. True/127 = on, 0 = off; with
        led_values "velocity" other values pass through (e.g. colours)."""
        spec = self._led.get(control)
        if spec is None:
            return None
        if self._velocity:
            v = 127 if value is True else (max(0, min(127, int(value))) if value else 0)
        else:
            v = 127 if value else 0
        return spec[0], spec[1], v

    def led_controls(self):
        return list(self._led)

    def controls(self):
        """Every control as (id, kind), for the engine and the window."""
        return list(self._controls)

    def control_kinds(self):
        """Every control's physical kind: button, knob, fader or encoder (what the mapping editor offers)."""
        return {c["id"]: c["kind"] for c in self.definition["controls"]}

    def public(self):
        """What the window needs: names, kinds, layout (no MIDI details)."""
        d = self.definition
        return {"type": d["type"], "name": d["name"], "maker": d.get("maker"), "halves": d.get("halves", []),
                "deck_slots": list(self.deck_slots), "fx_slots": list(self.fx_slots),
                "has_shift": self.has_shift, "midi_mode": d.get("midi_mode"),
                "controls": {c["id"]: {"kind": c["kind"], "name": c.get("name", c["id"]), "led": bool(c.get("led"))}
                             for c in d["controls"]},
                "layout": d.get("layout", {})}


def load_definitions(folder=DEFINITIONS_DIR):
    defs = {}
    for path in sorted(Path(folder).glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("schema") != 1:
            raise DefinitionError(f"{path.name}: unknown schema {d.get('schema')}")
        defs[d["type"]] = d
    return defs


def device_types(folder=DEFINITIONS_DIR, user_folder=USER_DEFINITIONS_DIR):
    """type -> factory making a DefinedDevice: the built-in controllers, then your own (which can't replace one)."""
    out = {t: functools.partial(DefinedDevice, d) for t, d in load_definitions(folder).items()}
    if user_folder and Path(user_folder).is_dir():
        for path in sorted(Path(user_folder).glob("*.json")):
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                if d.get("schema") == 1 and d.get("type") not in out:
                    DefinedDevice(d)                      # checked before it's offered
                    out[d["type"]] = functools.partial(DefinedDevice, d)
            except (OSError, ValueError, KeyError, TypeError):
                continue                                  # a broken file of your own never stops the app
    return out


def save_user_definition(definition, folder=USER_DEFINITIONS_DIR):
    """Checks a definition and keeps it with your own controllers; returns its type. A file that's already there
    is kept as it is (the same type means the same controls); a new one whose name is taken gets "(2)" and so on."""
    DefinedDevice(definition)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{definition['type']}.json"
    if path.exists():
        return definition["type"]
    names = set()
    for other in folder.glob("*.json"):
        try:
            names.add(json.loads(other.read_text(encoding="utf-8")).get("name"))
        except (OSError, ValueError):
            continue
    base, n = definition["name"], 2
    while definition["name"] in names:
        definition["name"], n = f"{base} ({n})", n + 1
    path.write_text(json.dumps(definition, indent=2), encoding="utf-8")
    return definition["type"]
