"""Compiles Rekordbox actions into a bridge mapping (.midi.csv) plus a machine-readable manifest, and reads an
installed bridge mapping back.

Every function's address comes from the permanent address table (rekordtrakt/rekordbox/addresses.json, plan in
addresses.py): per-deck inputs on channels 1-4, global on 5, feedback on 9-12 and 13, overflow on 6-8 and 14-16.
Rekordbox's echo of its own feedback therefore lands on channels it has no input rows for, and the translator never
treats its own commands as feedback.

A per-deck row uses Rekordbox's compact "base message + channel per deck" form when the four decks share a number on
consecutive channels, and explicit per-deck messages otherwise (as Pioneer's own files do, e.g. "Load,,,9646,9647").
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

NOTE, CC = 0x90, 0xB0
OUTPUT_ONLY_TYPES = {"Indicator", "IndicatorHiRes", "JogIndicator", "JogIndicatorHiRes", "Value"}

CATALOGUE = Path(__file__).resolve().parents[1] / "rekordbox" / "catalogues" / "rekordbox-6.8.7.txt"
CATALOGUES = {6: CATALOGUE, 7: CATALOGUE.with_name("rekordbox-7.2.19.txt")}


@dataclass(frozen=True)
class Action:
    function: str               # Rekordbox function name, e.g. "PlayPause"
    rb_type: str                # Rekordbox control type, e.g. "Button", "Rotary", "KnobSliderHiRes", "Indicator"
    semantics: str              # toggle | momentary | relative | absolute7 | absolute14 | feedback
    decks: tuple = ()           # () = global function
    feedback: str = ""          # "" = no output; "note" or "cc" = how Rekordbox reports it back
    options: str = ""           # Rekordbox options column, e.g. "Fast" or "RO;Priority=100"
    comment: str = ""


class BridgeError(ValueError):
    pass


def load_catalogue(path=CATALOGUE):
    pairs = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "|" in line:
            name, rb_type = line.split("|", 1)
            pairs.add((name, rb_type))
    return pairs


def _columns(address, decks):
    """The five CSV columns (base, deck 1-4) for one side of a row; address is {"kind", "at": [[ch, num], ...]}."""
    if not address:
        return ["", "", "", "", ""]
    status = NOTE if address["kind"] == "note" else CC
    at = address["at"]
    if not decks:
        ch, num = at[0]
        return [f"{status | ch:02X}{num:02X}", "", "", "", ""]
    channels, numbers = [c for c, _ in at], {n for _, n in at}
    if len(numbers) == 1 and channels == list(range(channels[0], channels[0] + 4)):
        num = at[0][1]
        return [f"{status >> 4:X}0{num:02X}", *(str(at[d - 1][0]) if d in decks else "" for d in (1, 2, 3, 4))]
    return ["", *(f"{status | at[d - 1][0]:02X}{at[d - 1][1]:02X}" if d in decks else "" for d in (1, 2, 3, 4))]


def compile_bridge(port_name, actions, catalogue=None, table=None, rekordbox=6):
    """Returns (csv_text, manifest_dict) for Rekordbox major version `rekordbox` (6 or 7). Raises BridgeError on
    functions that version doesn't have, functions without an address, or address clashes."""
    catalogue = load_catalogue(CATALOGUES[int(rekordbox)]) if catalogue is None else catalogue
    if table is None:
        from rekordtrakt.rekordbox.addresses import load_table
        table = load_table()
    rows, entries = [], []
    used_in, used_out = {}, {}

    def claim(used, key, owner):
        if key in used:
            raise BridgeError(f"address {key} used by both {used[key]} and {owner}")
        used[key] = owner

    for a in actions:
        if (a.function, a.rb_type) not in catalogue:
            raise BridgeError(f"{a.function}|{a.rb_type} is not in the Rekordbox function catalogue")
        t = table.get(a.function)
        has_input = a.rb_type not in OUTPUT_ONLY_TYPES
        if not t or (has_input and not t.get("in")) or (a.feedback and not t.get("out")):
            raise BridgeError(f"{a.function} has no address: run 'python -m rekordtrakt.rekordbox.addresses'")
        address_in, address_out = (t["in"] if has_input else None), (t["out"] if a.feedback else None)
        for deck in a.decks or (None,):
            i = deck - 1 if deck else 0
            entry = {"function": a.function, "deck": deck, "type": a.rb_type, "semantics": a.semantics,
                     "input": None, "output": None}
            if address_in:
                ch, num = address_in["at"][i]
                status = (NOTE if address_in["kind"] == "note" else CC) | ch
                entry["input"] = {"status": status, "data1": num}
                claim(used_in, (status, num), f"{a.function}/{deck}")
                if address_in["kind"] == "cc14":
                    entry["input"]["lsb"] = num + 32
                    claim(used_in, (status, num + 32), f"{a.function}/{deck} LSB")
            if address_out:
                ch, num = address_out["at"][i]
                status = (NOTE if address_out["kind"] == "note" else CC) | ch
                entry["output"] = {"status": status, "data1": num}
                claim(used_out, (status, num), f"{a.function}/{deck}")
            entries.append(entry)
        rows.append(",".join([a.function, "", a.rb_type, *_columns(address_in, a.decks),
                              *_columns(address_out, a.decks), a.options, a.comment]))

    csv_text = "\r\n".join([f"@file,1,{port_name}", *rows]) + "\r\n"
    manifest = {
        "port": port_name,
        "rekordbox_catalogue": CATALOGUES[int(rekordbox)].name,
        "csv_sha256": hashlib.sha256(csv_text.encode("ascii")).hexdigest(),
        "address_plan": "rekordtrakt/rekordbox/addresses.json",
        "entries": entries,
    }
    return csv_text, manifest


def read_bridge(csv_text, semantics_of=lambda function: ""):
    """The manifest of an installed bridge mapping, read from the file itself (Rekordbox's rewrite included), so the
    translator always sends what Rekordbox actually loaded."""
    by_key = {}
    for side, function, rb_type, deck, msg, _ in sorted(canonical_mappings(csv_text), key=repr):
        e = by_key.setdefault((function, deck), {"function": function, "deck": deck, "type": rb_type,
                                                 "semantics": semantics_of(function), "input": None, "output": None})
        status, data1 = int(msg[:2], 16), int(msg[2:], 16)
        if side == "in":
            e["input"] = {"status": status, "data1": data1}
            if rb_type == "KnobSliderHiRes":
                e["input"]["lsb"] = data1 + 32
        else:
            e["output"] = {"status": status, "data1": data1}
    return {"entries": list(by_key.values())}


# Control types Rekordbox renames when it rewrites a file, mapped back to the name we write.
REWRITTEN_TYPES = {"DdjSxPad": "Pad"}         # Rekordbox 6.8.7 renames these when it rewrites a mapping file


def canonical_mappings(csv_text):
    """The meaning of a .midi.csv as a set, ignoring layout.

    Rekordbox rewrites mapping files on exit: it sorts rows, expands "base + channel per deck"
    into explicit per-deck messages, appends ';' to options and renames the "Pad" type to "DdjSxPad". Comparing
    these sets tells a harmless rewrite apart from a real edit.
    """
    def expand(base, deck_cols):
        if base and not any(deck_cols):
            return {(None, base.upper())}
        out = set()
        for deck, col in enumerate(deck_cols, start=1):
            if not col:
                continue
            if len(col) == 4:                                   # explicit message, e.g. "9200"
                out.add((deck, col.upper()))
            else:                                               # channel index applied to the base message
                out.add((deck, f"{base[0]}{int(col):X}{base[2:]}".upper()))
        return out

    result = set()
    for line in csv_text.splitlines():
        if not line or line.startswith(("@", "#")):
            continue
        f = (line.split(",") + [""] * 15)[:15]
        options = frozenset(o for o in f[13].split(";") if o)
        kind = REWRITTEN_TYPES.get(f[2], f[2])
        for deck, msg in expand(f[3], f[4:8]):
            result.add(("in", f[0], kind, deck, msg, options))
        for deck, msg in expand(f[8], f[9:13]):
            result.add(("out", f[0], kind, deck, msg, options))
    return result


def write_bridge(out_dir, port_name, actions):
    csv_text, manifest = compile_bridge(port_name, actions)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{port_name}.midi.csv"
    csv_path.write_bytes(csv_text.encode("ascii"))
    (out_dir / f"{port_name}.manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return csv_path, manifest
