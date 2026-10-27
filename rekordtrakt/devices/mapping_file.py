"""Controllers from a mapping file: turn a .midi.xml controller mapping into a RekordTrakt device definition and a
starting mapping, so a controller someone has already mapped elsewhere works here without writing anything.

A .midi.xml mapping lists each control's MIDI message, what it does (a [Group] and a key, e.g. [Channel1] play),
and the LEDs it lights. From that:

- the definition: every distinct input message becomes a control (note = button, CC = knob, or encoder when the
  file reads it relatively), with an LED where the file sends one back on the same message, laid out on a plain
  grid (drag it into shape later; physical layouts aren't in these files);
- the mapping: controls whose key has a Rekordbox equivalent are bound to it on the right deck ([ChannelN] ->
  deck N). Controls the file drives through its own scripts are left unbound: there's nothing to translate, so
  they're listed for the mapping editor.

Nothing from the file is ever run. It's read as data.
"""
import hashlib
import json
import re
import xml.etree.ElementTree as ET

ROOT_TAGS = {"MixxxControllerPreset", "MixxxMIDIPreset"}  # the format's root element: current and older files

# key (per [ChannelN]) -> Rekordbox function
DECK_KEYS = {
    "play": "PlayPause", "cue_default": "Cue", "cue_gotoandplay": "Cue", "sync_enabled": "Sync", "beatsync": "Sync",
    "keylock": "MasterTempo", "pfl": "HeadphoneCue", "slip_enabled": "Slip", "quantize": "Quantize",
    "reverse": "Reverse", "reverseroll": "DirectionSlipRev", "bpm_tap": "TapBpm", "start": "JumpToTrackStart",
    "start_play": "JumpToTrackStart", "LoadSelectedTrack": "Load", "rate_temp_up": "PitchBendUp",
    "rate_temp_down": "PitchBendDown", "rate_perm_up": "TempoIncMedium", "rate_perm_down": "TempoDecMedium",
    "reloop_toggle": "ReloopExit", "reloop_exit": "ReloopExit", "loop_in": "LoopIn", "loop_out": "LoopOut",
    "loop_halve": "LoopHalf", "loop_double": "LoopDouble", "beatloop_activate": "AutoLoop", "sync_key": "KeySync",
    "reset_key": "KeyReset", "pitch_up": "SemitoneUp", "pitch_down": "SemitoneDown",
    "volume": "ChannelFader", "pregain": "Gain", "rate": "TempoSlider", "beatjump_forward": "Jump4Fwd",
    "beatjump_backward": "Jump4Prev",
}
BEATLOOP_SIZES = {"0.0625": "1_16", "0.125": "1_8", "0.25": "1_4", "0.5": "1_2", "1": "1", "2": "2", "4": "4", "8": "8"}
EQ_PARAMETERS = {"parameter3": "EQHigh", "parameter2": "EQMid", "parameter1": "EQLow"}
RELATIVE_OPTIONS = {"selectknob", "diff", "spread64", "relative"}
ORDINALS = ("First", "Second", "Third", "Fourth")


class MappingFileError(ValueError):
    pass


def _int(text):
    text = (text or "").strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def _slug(text, n=40):
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:n] or "control"


def _function(group, key):
    """(Rekordbox function, deck key or None) for a [group] key, or None if there's no equivalent."""
    m = re.fullmatch(r"\[Channel(\d)\]", group)
    if m:
        deck = f"d{m[1]}" if m[1] in "1234" else None
        if not deck:
            return None
        if key in DECK_KEYS:
            return DECK_KEYS[key], deck
        hc = re.fullmatch(r"hotcue_(\d+)_(activate|clear|gotoandplay)", key)
        if hc and 1 <= int(hc[1]) <= 8:
            return f"PAD{hc[1]}_HotCue" + ("+Shift" if hc[2] == "clear" else ""), deck
        bl = re.fullmatch(r"beatloop_([\d.]+)_(toggle|activate)", key)
        if bl and bl[1] in BEATLOOP_SIZES:
            return f"BeatLoop{BEATLOOP_SIZES[bl[1]]}", deck
        bj = re.fullmatch(r"beatjump_(\d+)_(forward|backward)", key)
        if bj and bj[1] in ("4", "8", "16"):
            return f"Jump{bj[1]}{'Fwd' if bj[2] == 'forward' else 'Prev'}", deck
        return None
    m = re.fullmatch(r"\[EqualizerRack1_\[Channel(\d)\]_Effect1\]", group)
    if m and key in EQ_PARAMETERS and m[1] in "1234":
        return EQ_PARAMETERS[key], f"d{m[1]}"
    m = re.fullmatch(r"\[QuickEffectRack1_\[Channel(\d)\]\]", group)
    if m and key == "super1" and m[1] in "1234":
        return f"CFXParameterCH{m[1]}", None
    if group == "[Master]" and key == "crossfader":
        return "CrossFader", None
    if group in ("[Library]", "[Playlist]"):
        return {"MoveVertical": "Browse", "SelectTrackKnob": "Browse", "MoveUp": "BrowseUp", "MoveDown": "BrowseDown",
                "SelectNextTrack": "BrowseDown", "SelectPrevTrack": "BrowseUp", "GoToItem": "Forward",
                "MoveFocusBackward": "Back"}.get(key), None
    return None


def parse(xml_text):
    """The controls and outputs a mapping file declares."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise MappingFileError(f"that isn't a .midi.xml mapping file ({e})") from None
    if root.tag not in ROOT_TAGS:
        raise MappingFileError("that isn't a .midi.xml controller mapping")
    info = root.find("info")
    name = (info.findtext("name") if info is not None else None) or "Imported controller"
    author = (info.findtext("author") if info is not None else None) or ""
    controls, outputs = [], []
    for c in root.iter("control"):
        try:
            status, midino = _int(c.findtext("status")), _int(c.findtext("midino"))
        except (TypeError, ValueError):
            continue
        found = c.find("options")
        options = {o.tag.lower() for o in found} if found is not None else set()
        controls.append({"group": (c.findtext("group") or "").strip(), "key": (c.findtext("key") or "").strip(),
                         "description": (c.findtext("description") or "").strip(), "status": status,
                         "midino": midino, "options": options})
    for o in root.iter("output"):
        try:
            outputs.append((_int(o.findtext("status")), _int(o.findtext("midino"))))
        except (TypeError, ValueError):
            continue
    return {"name": name.strip(), "author": author.strip(), "controls": controls, "outputs": outputs}


def to_rekordtrakt(xml_text, port_name=""):
    """(definition, mapping, report) for a mapping file."""
    m = parse(xml_text)
    seen, controls, bindings = {}, [], []
    translated, script = 0, []
    outputs = {(s & 0xF0 | 0x90 if s & 0xF0 in (0x80, 0x90) else s, n) for s, n in m["outputs"]}
    for c in m["controls"]:
        kind_byte, ch = c["status"] & 0xF0, (c["status"] & 0x0F) + 1
        if kind_byte not in (0x80, 0x90, 0xB0):
            continue                                   # pitch bend, sysex...: not a control RekordTrakt reads
        msg = "cc" if kind_byte == 0xB0 else "note"
        if "fourteen-bit-lsb" in c["options"]:
            continue                                   # the LSB half of a 14-bit pair: the MSB stands for the control
        key = (msg, ch, c["midino"])
        group_hint = c["group"].strip("[]").lower()
        scripted_button = msg == "cc" and "button" in group_hint
        scripted_encoder = msg == "cc" and "encoder" in group_hint
        relative = msg == "cc" and (bool(c["options"] & RELATIVE_OPTIONS) or scripted_encoder)
        if key not in seen:
            base = c["description"] or f"{c['group'].strip('[]')} {c['key']}".strip()
            cid = _slug(base)
            taken = {x["id"] for x in controls}
            n, unique = 2, cid
            while unique in taken:
                unique, n = f"{cid}_{n}", n + 1
            control = {"id": unique, "kind": "button" if msg == "note" or scripted_button else "encoder" if relative else "knob",
                       "name": base[:40], "in": {"msg": msg, "ch": ch, "num": c["midino"]}}
            if relative:
                control["in"]["relative"] = "twos_complement"
            status = (0x90 if msg == "note" else 0xB0) | (ch - 1)
            if (status, c["midino"]) in outputs:
                control["led"] = True
            controls.append(control)
            seen[key] = unique
        target = _function(c["group"], c["key"])
        if target and target[0]:
            function, deck = target
            action = {"do": "function", "function": function}
            if deck:
                action["deck"] = deck
            if function == "Browse" and not relative and msg == "cc":
                continue                               # an absolute knob can't browse
            if not any(b["control"] == seen[key] for b in bindings):
                bindings.append({"layer": "base", "page": None, "control": seen[key], "action": action})
                translated += 1
        elif (c["key"] and "." in c["key"]) or "script-binding" in c["options"]:
            script.append(c["description"] or c["key"])
    if not controls:
        raise MappingFileError("that mapping has no MIDI controls RekordTrakt can read")
    # Each deck the file drives becomes a deck slot (first, second...) starting on that deck, so moving it in the
    # window moves every control that drove it.
    channels = sorted({int(bnd["action"]["deck"][1:]) for bnd in bindings if bnd["action"].get("deck")})
    slot_keys = {f"d{n}": "abcd"[i] for i, n in enumerate(channels)}
    for bnd in bindings:
        if bnd["action"].get("deck"):
            bnd["action"]["deck"] = slot_keys[bnd["action"]["deck"]]
    deck_slots = [{"key": "abcd"[i], "label": f"{ORDINALS[i]} deck", "default": n} for i, n in enumerate(channels)]
    # The id names the controller and fingerprints its messages: a different file with the same name is a new
    # controller type, never a silent change to one that's in use; the same file again is the same type.
    messages = sorted((c["in"]["msg"], c["in"]["ch"], c["in"]["num"], c["kind"]) for c in controls)
    fingerprint = hashlib.sha1(json.dumps(messages).encode()).hexdigest()[:6]
    type_name = f"imported_{_slug(m['name'], 30)}_{fingerprint}"
    by = f" by {m['author']}" if m["author"] else ""
    definition = {"schema": 1, "type": type_name, "name": m["name"][:40], "maker": m["name"].split()[0],
                  "midi_mode": f"as in its mapping file{by}",
                  "port_hints": [p for p in [port_name, m["name"]] if p], "halves": [], "deck_slots": deck_slots,
                  "fx_slots": [], "shift": {"style": "none"},
                  "led_interval": 0.005, "led_values": "on_off", "controls": controls,
                  "layout": _grid(controls), "source": f"imported from a .midi.xml mapping{by}"}
    report = {"controls": len(controls), "mapped": translated, "scripted": sorted(set(script))[:40]}
    return definition, {"bindings": bindings, "pages": []}, report


def _grid(controls, columns=8):
    """A plain grid: knobs and faders first, then encoders, then buttons, eight to a row."""
    order = {"knob": 0, "fader": 0, "encoder": 1, "button": 2}
    items, row, col, last = [], 1, 1, None
    for c in sorted(controls, key=lambda x: order[x["kind"]]):
        group = order[c["kind"]]
        if last is not None and group != last and col != 1:
            row, col = row + 1, 1
        shape = {"button": "key", "knob": "knob", "fader": "knob", "encoder": "encoder"}[c["kind"]]
        items.append({"control": c["id"], "c": col, "r": row, "shape": shape})
        last = group
        col += 1
        if col > columns:
            row, col = row + 1, 1
    return {"columns": ["1fr"] * columns, "items": items, "source": "automatic grid (from an imported mapping)"}
