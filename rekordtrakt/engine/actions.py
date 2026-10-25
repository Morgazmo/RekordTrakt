"""Your own mappings: what the mapping editor saves, and the behaviours built from it.

A device's mapping is data (kept in the rig file next to its decks and options), layered over its preset profile:

  {"bindings": [{"layer": "base", "page": "fx", "control": "L.fx_button_1", "action": {...}}, ...],
   "pages": [{"id": "u1", "name": "Loops", "short": "Loops"}, ...]}

- layer: "base", "shift", or a modifier layer the preset offers ("sync", "sync/shift"); page: an FX-section page
  ("fx", "mixer", a custom page id) or null for every page; control: the device's control id.
- A binding replaces the preset's for that layer/page/control. Removing it brings the preset's back.
- Custom pages start blank: the FX-section controls do nothing there until bound.

Actions (what a control does), checked against the action registry and the control's kind:

  {"do": "function", "function": "PlayPause", "deck": "deck"}     one function. deck: "deck" (this half's deck),
        a deck slot's key on a unit without halves ("a"/"b": an F1's first/second deck), "d1".."d4" (a fixed
        deck), or absent for global functions. An encoder
        bound to a button function also needs "minus" (the function for anticlockwise, e.g. Jump4Fwd / Jump4Prev).
  {"do": "functions", "items": [{"function": ..., "deck": ..., "from": 0, "to": 127}, ...]}
        several at once: buttons press them together; a knob drives each over its own range (to < from inverts).
  {"do": "sequence", "steps": [{"function": ..., "deck": ..., "wait": 0.5}, ...]}
        a button runs the steps in order, each after its wait in seconds.
  {"do": "value", "function": "EQLow", "deck": "deck", "value": 0, "release": 64}
        a button sets a knob function (release: the value when let go; absent = stays).
  {"do": "nothing"}       bound on purpose to nothing.
"""
import re

from rekordtrakt.engine import behaviours as b
from rekordtrakt.rekordbox import registry

DECK_KEYS = ("deck", "a", "b", "d1", "d2", "d3", "d4")       # the default: an X1 half's or an F1's
BUTTON_TYPES = {"Button", "Pad"}
VALUE_TYPES = {"KnobSlider", "KnobSliderHiRes"}
TURN_TYPES = {"Rotary"}
MAX_ITEMS, MAX_STEPS, MAX_WAIT = 8, 16, 30.0


class MappingError(ValueError):
    pass


def _function(spec, decks=DECK_KEYS, scope_check=True):
    name = spec.get("function")
    f = registry.BY_NAME.get(name)
    if f is None:
        raise MappingError(f"'{name}' isn't a function RekordTrakt can send")
    if f.semantics == "feedback":
        raise MappingError(f"{f.label} is a light Rekordbox reports, not something to send")
    deck = spec.get("deck")
    if f.scope == "deck":
        if deck not in decks:
            raise MappingError(f"{f.label} needs a deck")
    elif deck is not None and scope_check:
        raise MappingError(f"{f.label} isn't per deck")
    return f, (deck if f.scope == "deck" else None)


def _single(spec, kind, decks=DECK_KEYS):
    """One function as a behaviour for a control of `kind` (button, knob, fader, encoder)."""
    f, deck = _function(spec, decks)
    if kind == "button":
        if f.rb_type in BUTTON_TYPES:
            return b.Button(f.name, deck)
        if f.rb_type in VALUE_TYPES:
            return b.SetValue(f.name, deck, value=_value(spec.get("value", 127)),
                              release=None if spec.get("release") is None else _value(spec["release"]),
                              hires=f.rb_type == "KnobSliderHiRes")
        raise MappingError(f"{f.label} can't go on a button")
    if kind in ("knob", "fader"):
        if f.rb_type in VALUE_TYPES:
            return b.Knob(f.name, deck, hires=f.rb_type == "KnobSliderHiRes")
        raise MappingError(f"{f.label} can't follow a {kind}")
    if kind == "encoder":
        if f.rb_type in TURN_TYPES:
            return b.Rotary(f.name, deck)
        if f.rb_type in BUTTON_TYPES:
            minus = spec.get("minus")
            if not minus:
                raise MappingError(f"{f.label} on an encoder also needs a function for turning the other way")
            g, _ = _function({"function": minus, "deck": spec.get("deck")}, decks)
            if g.rb_type not in BUTTON_TYPES:
                raise MappingError(f"{g.label} can't be a turn step")
            return b.Split(f.name, g.name, deck)
        raise MappingError(f"{f.label} can't go on an encoder")
    raise MappingError(f"unknown control kind '{kind}'")


def _value(v):
    if not isinstance(v, int) or not 0 <= v <= 127:
        raise MappingError("values go from 0 to 127")
    return v


def build(action, kind, decks=DECK_KEYS):
    """The behaviour for a saved action on a control of `kind`; raises MappingError if it can't work. `decks`: the
    deck keys the controller has (Device.deck_keys)."""
    if not isinstance(action, dict):
        raise MappingError("an action is an object")
    do = action.get("do")
    if do == "nothing":
        return b.Disabled("nothing assigned")
    if do in ("function", "value"):
        if do == "value" and kind != "button":
            raise MappingError("only a button can set a value")
        return _single(action, kind, decks)
    if do == "functions":
        items = action.get("items") or []
        if not 1 <= len(items) <= MAX_ITEMS:
            raise MappingError(f"choose 1 to {MAX_ITEMS} functions")
        if kind in ("knob", "fader"):
            targets = []
            for item in items:
                f, deck = _function(item, decks)
                if f.rb_type not in VALUE_TYPES:
                    raise MappingError(f"{f.label} can't follow a {kind}")
                targets.append((b.Ref(f.name, deck), _value(item.get("from", 0)), _value(item.get("to", 127)),
                                f.rb_type == "KnobSliderHiRes"))
            return b.MultiKnob(targets)
        return b.Group([_single(item, kind, decks) for item in items])
    if do == "sequence":
        if kind != "button":
            raise MappingError("only a button can run a sequence")
        steps = action.get("steps") or []
        if not 1 <= len(steps) <= MAX_STEPS:
            raise MappingError(f"a sequence has 1 to {MAX_STEPS} steps")
        out = []
        for step in steps:
            wait = step.get("wait", 0)
            if not isinstance(wait, (int, float)) or not 0 <= wait <= MAX_WAIT:
                raise MappingError(f"waits go from 0 to {MAX_WAIT:g} seconds")
            out.append((float(wait), _single(step, "button", decks)))
        return b.Sequence(out)
    raise MappingError(f"unknown action '{do}'")


# --- the mapping as a whole --------------------------------------------------------------------------------------

def empty():
    return {"bindings": [], "pages": []}


def normalise(mapping):
    m = mapping if isinstance(mapping, dict) else {}
    return {"bindings": list(m.get("bindings") or []), "pages": list(m.get("pages") or [])}


def layer_key(layer, page):
    return f"{layer}@p_{page}" if page else layer


def page_ids(mapping):
    return [p["id"] for p in normalise(mapping)["pages"]]


def new_page_id(mapping):
    taken = set(page_ids(mapping))
    n = 1
    while f"u{n}" in taken:
        n += 1
    return f"u{n}"


def check_name(name):
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name or len(name) > 24:
        raise MappingError("page names have 1 to 24 characters")
    return name


def compile_bindings(mapping, kinds, page_controls, layers=("base", "shift"), decks=DECK_KEYS):
    """{(layer key, control): behaviour} for a device's saved mapping. kinds: control id -> kind. Custom pages start
    blank: their page controls do nothing on the base and Shift layers until bound."""
    m = normalise(mapping)
    out = {}
    for page in page_ids(m):
        for control in page_controls:
            for layer in layers:
                out[(layer_key(layer, page), control)] = b.Disabled("nothing on this page")
    for entry in m["bindings"]:
        control = entry.get("control")
        kind = kinds.get(control) or kinds.get(control.split(".", 1)[-1] if control else None)
        if kind is None:
            continue                         # a control this device doesn't have (an import from another model)
        try:
            out[(layer_key(entry.get("layer", "base"), entry.get("page")), control)] = build(entry["action"], kind, decks)
        except (MappingError, KeyError):
            continue                         # unusable after an update: the preset's binding stays
    return out


def feedback_leds(mapping):
    """{led key: Ref} for bound buttons whose function Rekordbox reports back, so their LED shows its state."""
    out = {}
    for entry in normalise(mapping)["bindings"]:
        a = entry.get("action") or {}
        f = registry.BY_NAME.get(a.get("function"))
        if a.get("do") == "function" and f and f.feedback and f.rb_type in BUTTON_TYPES and entry.get("layer", "base") == "base":
            page = entry.get("page")
            out[f"{entry['control']}@p_{page}" if page else entry["control"]] = b.Ref(f.name, a.get("deck") if f.scope == "deck" else None)
    return out
