"""Short human labels for what a control does, for the main window: "Hot cue B", "FX1 slot 2 level",
"Tempo ±0.5%". Built from the behaviour and the Rekordbox functions it resolves to in the control's context.

describe() returns (label, detail): detail adds what doesn't fit (the deck when it isn't the half's own, a hold
action, why something is unavailable).
"""
import re

from rekordtrakt.engine import behaviours as b

FUNCTION_LABELS = {
    "PlayPause": "Play / pause", "Cue": "Cue", "Sync": "Sync", "MasterTempo": "Key lock", "Slip": "Slip",
    "JumpToTrackStart": "Back to start", "DirectionSlipRev": "Reverse (slip)", "Reverse": "Reverse",
    "PitchBendDown": "Nudge −", "PitchBendUp": "Nudge +", "TapBpm": "Tap BPM", "TempoReset": "Tempo reset",
    "LoopHalfDouble": "Loop size", "AutoLoop": "Loop on/off", "ActiveLoop": "Reloop / exit",
    "ReloopExit": "Reloop / exit", "LoopMove": "Move loop", "ForwardAndLoad": "Load", "InstDoubles": "Instant doubles",
    "Browse": "Browse", "Forward": "Open", "Back": "Back", "AddToTagList": "Add to tag list",
    "EQHigh": "EQ high", "EQMid": "EQ mid", "EQLow": "EQ low", "ChannelFader": "Volume", "Gain": "Gain",
    "HeadphoneCue": "Headphone cue", "CFXSubParameter": "Colour FX param", "Quantize": "Quantize",
    "SemitoneUp": "Key +", "SemitoneDown": "Key −", "VinylAdjustBrake": "Vinyl brake",
}
PATTERNS = [
    (r"PAD(\d)_HotCue\+Shift", lambda m: f"Delete hot cue {chr(64 + int(m[1]))}"),
    (r"PAD(\d)_HotCue", lambda m: f"Hot cue {chr(64 + int(m[1]))}"),
    (r"PAD(\d)_BeatJump", lambda m: f"Beat-jump pad {m[1]}"),
    (r"FX(\d)Assign(\d)", lambda m: f"FX{m[1]} on deck {m[2]}"),
    (r"FX(\d)-(\d)On", lambda m: f"FX{m[1]} slot {m[2]} on"),
    (r"FX(\d)-(\d)Select", lambda m: f"FX{m[1]} slot {m[2]} next effect"),
    (r"FX(\d)-(\d)", lambda m: f"FX{m[1]} slot {m[2]} level"),
    (r"FX(\d)BeatUpDown", lambda m: f"FX{m[1]} beat"),
    (r"SFX(\d)-(\d)On", lambda m: f"SFX{m[1]} slot {m[2]} on"),
    (r"SFX(\d)-(\d)Select", lambda m: f"SFX{m[1]} slot {m[2]} next"),
    (r"SFX(\d)-Slider", lambda m: f"SFX{m[1]} amount"),
    (r"SFX(\d)-Touch", lambda m: f"SFX{m[1]} engage"),
    (r"PartIsolator(\w+)", lambda m: f"{m[1]} level"),
    (r"ActivePart(\w+)", lambda m: f"{m[1]} on/off"),
    (r"FXPartSelect(\w+)", lambda m: f"Part FX {m[1]}"),
    (r"CFXParameterCH(\d)Center", lambda m: f"Colour FX ch{m[1]} centre"),
    (r"CFXParameterCH(\d)", lambda m: f"Colour FX ch{m[1]}"),
    (r"CFX(\d)On", lambda m: f"Colour FX type {m[1]}"),
    (r"Jump(\d+)Fwd", lambda m: f"Jump +{m[1]} beats"),
    (r"Jump(\d+)Prev", lambda m: f"Jump −{m[1]} beats"),
]

# Device options the settings window offers: title, value labels, help.
OPTION_INFO = {
    "encoders": ("Encoder style", {"legacy": "Stock X1", "mod": "Performance Mod"},
                 "Stock: Browse scrolls the track list (Shift: the folder tree). Performance Mod: Browse jumps by "
                 "the beat-jump size (Shift: 1 beat) and Shift + Loop changes key."),
    "shift_loop": ("Shift + Loop", {"jump": "Beat jump / move loop", "key": "Key change"}, None),
    "vinyl_brake": ("Vinyl brake on PLAY hold", {False: "Off", True: "On"}, None),
    "beatjump_size": ("Beat jump size", {1: "1 beat", 4: "4 beats", 8: "8 beats", 16: "16 beats"},
                      "1 beat uses Rekordbox's beat-jump pads."),
    "tempo_fine_steps": ("Fine tempo step (Sync + Loop)", {1: "0.5%", 2: "1%"}, None),
    "tempo_coarse_steps": ("Large tempo step (Sync + Loop held)", {2: "1%", 4: "2%", 10: "5%"}, None),
    "knob_pickup": ("Knob pickup (soft takeover)", {False: "Off", True: "On"},
                    "On: after a page or deck change, a knob only takes over once it reaches Rekordbox's value "
                    "(arrows show which way to turn). Off: knobs always send at once."),
}
# Options that only mean something alongside another one's value: the settings window shows them only then.
OPTION_WHEN = {"shift_loop": ("encoders", "legacy")}      # Performance Mod encoders: Shift + Loop is always key

# Short labels for controls that sit in a titled row ("Slot 1": On, Level) or speak for themselves ("Cue A").
SHORT_PATTERNS = [
    (r"FX\d-\dOn|SFX\d-\dOn", lambda m: "On"), (r"FX\d-\dSelect", lambda m: "Next FX"),
    (r"FX\d-\d", lambda m: "Level"), (r"FX\dBeatUpDown", lambda m: "Beat"),
    (r"SFX\d-\dSelect", lambda m: "Next"), (r"SFX\d-Slider", lambda m: "Amount"), (r"SFX\d-Touch", lambda m: "Engage"),
    (r"PartIsolator\w+", lambda m: "Level"), (r"ActivePart\w+", lambda m: "On/off"), (r"FXPartSelect\w+", lambda m: "Part FX"),
    (r"CFXParameterCH\d", lambda m: "Colour FX"), (r"CFXSubParameter", lambda m: "Param"),
    (r"EQ(High|Mid|Low)", lambda m: "EQ"), (r"ChannelFader", lambda m: "Volume"), (r"HeadphoneCue", lambda m: "Phones"),
    (r"FX(\d)Assign\d", lambda m: f"FX{m[1]}"),
    (r"Jump(\d+)Fwd", lambda m: f"Jump +{m[1]}"), (r"Jump(\d+)Prev", lambda m: f"Jump −{m[1]}"),
    (r"PAD(\d)_HotCue\+Shift", lambda m: f"Delete {chr(64 + int(m[1]))}"),
    (r"PAD(\d)_HotCue", lambda m: f"Cue {chr(64 + int(m[1]))}"),
]


# Where double-clicking a knob in the window puts it back to: only for knobs with an obvious neutral position
# (centre = no change). Others (volume, FX levels, stem levels) have none, so double-click does nothing there.
KNOB_DEFAULTS = [(r"EQ(High|Mid|Low)", 64), (r"Gain", 64), (r"CFXParameterCH\d", 64), (r"CFXSubParameter", 64),
                 (r"FilterKnob", 64)]


def knob_default(function):
    return next((v for pattern, v in KNOB_DEFAULTS if re.fullmatch(pattern, function)), None)


SHORT_FUNCTIONS = {
    "PlayPause": "Play", "Cue": "Cue", "Sync": "Sync", "MasterTempo": "Key lock", "Slip": "Slip",
    "JumpToTrackStart": "To start", "DirectionSlipRev": "Reverse", "Reverse": "Reverse", "PitchBendDown": "Nudge −",
    "PitchBendUp": "Nudge +", "TapBpm": "Tap BPM", "TempoReset": "Tempo reset", "LoopHalfDouble": "Loop size",
    "AutoLoop": "On/off", "ActiveLoop": "Reloop", "ReloopExit": "Reloop", "ForwardAndLoad": "Load",
    "InstDoubles": "Doubles", "Browse": "Browse", "Forward": "Open", "Back": "Back", "AddToTagList": "Tag list",
    "Quantize": "Quantize", "SemitoneUp": "Key +", "SemitoneDown": "Key −",
}


def short_function_label(function):
    if function in SHORT_FUNCTIONS:
        return SHORT_FUNCTIONS[function]
    for pattern, make in SHORT_PATTERNS:
        m = re.fullmatch(pattern, function)
        if m:
            return make(m)
    return None


def short(behaviour, eng, ctx):
    """A one- or two-word label for the control's tile, or None to use the full label."""
    if isinstance(behaviour, b.Disabled):
        return "—"
    if isinstance(behaviour, (b.Button, b.Knob, b.Rotary, b.Latch)):
        return short_function_label(behaviour.ref.resolve(ctx)[0]) or (
            "Engage" if isinstance(behaviour, b.Latch) else None)
    if isinstance(behaviour, b.ModifierTap) and behaviour.tap_ref:
        return short_function_label(behaviour.tap_ref.resolve(ctx)[0])
    if isinstance(behaviour, b.Split):
        p, m = short_function_label(behaviour.plus.resolve(ctx)[0]), short_function_label(behaviour.minus.resolve(ctx)[0])
        if p and m and p.startswith("Jump +") and m.startswith("Jump −"):
            return f"Jump ±{p[6:]}"
        return "Key ±" if (p, m) == ("Key +", "Key −") else None
    if isinstance(behaviour, b.BeatJump):
        return f"Jump ±{behaviour.size or (eng.devices[ctx['_pos']].options.get('beatjump_size', 4) if ctx.get('_pos') else 4)}"
    if isinstance(behaviour, b.Tempo):
        return describe(behaviour, eng, ctx)[0]
    if isinstance(behaviour, b.PlayBrake):
        return "Play"
    if isinstance(behaviour, b.BrowseList):
        return "Browse" + (f" ×{behaviour.page}" if behaviour.page > 1 else "")
    if isinstance(behaviour, b.BrowseTree):
        return "Folders" + (f" ×{behaviour.page}" if behaviour.page > 1 else "")
    if isinstance(behaviour, b.TreeOpen):
        return "Open"
    if isinstance(behaviour, b.TreeBack):
        return "Back"
    if isinstance(behaviour, b.HoldOrTap):
        return short_function_label(behaviour.tap_ref.resolve(ctx)[0])
    if isinstance(behaviour, b.ToggleMode):
        return {"page": "Prev page" if behaviour.step < 0 else "Next page", "browser": "Browser mode",
                "bank": "Cue bank"}.get(behaviour.key)
    if isinstance(behaviour, b.CfxKnob):
        return "Colour FX"
    if isinstance(behaviour, b.CfxToggle):
        return "On/off"
    if isinstance(behaviour, b.CfxTypeKnob):
        return "Type"
    if isinstance(behaviour, b.CfxNextType):
        return "Next type"
    if isinstance(behaviour, b.PartFxHold):
        return "Part FX"
    if isinstance(behaviour, b.SetValue):
        return f"{short_function_label(behaviour.ref.resolve(ctx)[0]) or function_label(behaviour.ref.function)} {behaviour.value}"
    if isinstance(behaviour, (b.Group, b.MultiKnob, b.Sequence)):
        parts = _parts(behaviour)
        first = short(parts[0], eng, ctx) if parts and isinstance(parts[0], b.Behaviour) else None
        first = first or (short_function_label(parts[0].resolve(ctx)[0]) if parts and isinstance(parts[0], b.Ref) else None)
        if isinstance(behaviour, b.Sequence):
            return f"{first} then +{len(parts) - 1}" if first and len(parts) > 1 else first or "Sequence"
        return f"{first} +{len(parts) - 1}" if first and len(parts) > 1 else first
    return None


def _parts(behaviour):
    if isinstance(behaviour, b.Group):
        return behaviour.parts
    if isinstance(behaviour, b.MultiKnob):
        return [t[0] for t in behaviour.targets]
    if isinstance(behaviour, b.Sequence):
        return [step for _, step in behaviour.steps]
    return []


def function_label(function):
    if function in FUNCTION_LABELS:
        return FUNCTION_LABELS[function]
    for pattern, make in PATTERNS:
        m = re.fullmatch(pattern, function)
        if m:
            return make(m)
    from rekordtrakt.rekordbox import registry               # the registry's label for everything else
    known = registry.BY_NAME.get(function)
    if known and known.label != function:
        return known.label
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", function)


def _ref(ref, eng, ctx):
    """Label for a Ref, plus "deck N" when it drives a deck other than the half's own."""
    function, deck = ref.resolve(ctx)
    label = function_label(function)
    if function == "ForwardAndLoad" and deck:
        return f"Load to deck {deck}", None
    other = deck and ref.deck != "deck"
    return label, (f"deck {deck}" if other else None)


def _pair(plus, minus, eng, ctx):
    p, _ = _ref(plus, eng, ctx)
    m, _ = _ref(minus, eng, ctx)
    for a, z in (("+", "−"),):
        if p.endswith(a) and m.endswith(z) and p[:-1] == m[:-1]:
            return f"{p[:-1].rstrip()} ±"
    jp, jm = re.fullmatch(r"Jump \+(\d+) beats", p), re.fullmatch(r"Jump −(\d+) beats", m)
    if jp and jm and jp[1] == jm[1]:
        return f"Jump ±{jp[1]} beats"
    return f"{p} / {m}"


def describe(behaviour, eng, ctx, modifier_names=None):
    """(label, detail) for a bound behaviour in context ctx."""
    names = modifier_names or {}
    dev = eng.devices.get(ctx.get("_pos")) if ctx.get("_pos") else None
    opts = dev.options if dev else {}
    if isinstance(behaviour, b.Disabled):
        return "—", behaviour.reason
    if isinstance(behaviour, b.ModifierTap):
        hold = names.get(behaviour.name, behaviour.name)
        if behaviour.tap_ref:
            tap, _ = _ref(behaviour.tap_ref, eng, ctx)
        elif behaviour.tap_behaviour:
            tap, _ = describe(behaviour.tap_behaviour, eng, ctx, names)
        else:
            tap = None
        detail = f"hold: {hold}"
        if behaviour.long_ref:
            detail += f"; hold {behaviour.long_after:g} s alone: {_ref(behaviour.long_ref, eng, ctx)[0]}"
        return (tap or f"Hold: {hold}"), (detail if tap else None)
    if isinstance(behaviour, (b.Button, b.Rotary, b.Knob)):
        label, detail = _ref(behaviour.ref, eng, ctx)
        if isinstance(behaviour, b.Knob) and behaviour.ref.function == "ChannelFader":
            label = "Volume"
        return label, detail
    if isinstance(behaviour, b.Latch):
        label, detail = _ref(behaviour.ref, eng, ctx)
        return f"{label} (toggle)", detail
    if isinstance(behaviour, b.Macro):
        return " + ".join(_ref(r, eng, ctx)[0] for r in behaviour.refs), None
    if isinstance(behaviour, b.SetValue):
        label, detail = _ref(behaviour.ref, eng, ctx)
        after = f"; back to {behaviour.release_value} when let go" if behaviour.release_value is not None else ""
        return f"{label} = {behaviour.value}", (detail or "") + after or None
    if isinstance(behaviour, b.Group):
        return " + ".join(describe(p, eng, ctx, names)[0] for p in behaviour.parts), "all at once"
    if isinstance(behaviour, b.MultiKnob):
        parts = []
        for ref, low, high, _ in behaviour.targets:
            label = _ref(ref, eng, ctx)[0]
            parts.append(label if (low, high) == (0, 127) else f"{label} ({low}–{high})")
        return " + ".join(parts), "one knob, several functions"
    if isinstance(behaviour, b.Sequence):
        steps = []
        for wait, step in behaviour.steps:
            steps.append((f"wait {wait:g} s, " if wait else "") + describe(step, eng, ctx, names)[0])
        return " → ".join(steps), "in order, on one press"
    if isinstance(behaviour, b.Split):
        return _pair(behaviour.plus, behaviour.minus, eng, ctx), None
    if isinstance(behaviour, b.HoldOrTap):
        return _ref(behaviour.tap_ref, eng, ctx)[0], f"hold {behaviour.seconds:g} s: {_ref(behaviour.hold_ref, eng, ctx)[0]}"
    if isinstance(behaviour, b.BeatJump):
        size = behaviour.size or opts.get("beatjump_size", 4)
        return f"Beat jump ±{size}", "moves the loop when one is active"
    if isinstance(behaviour, b.Tempo):
        steps = opts.get("tempo_fine_steps", 1) if behaviour.fine else opts.get("tempo_coarse_steps", 4)
        return f"Tempo ±{steps * 0.5:g}%", None
    if isinstance(behaviour, b.PlayBrake):
        return "Play / pause", "hold while playing: vinyl brake"
    if isinstance(behaviour, b.BrowseList):
        return "Browse tracks" + (f" ×{behaviour.page}" if behaviour.page > 1 else ""), None
    if isinstance(behaviour, b.BrowseTree):
        return "Browse folders" + (f" ×{behaviour.page}" if behaviour.page > 1 else ""), None
    if isinstance(behaviour, b.TreeOpen):
        return "Open folder", None
    if isinstance(behaviour, b.TreeBack):
        return "Back to folders", None
    if isinstance(behaviour, b.ToggleMode):
        if behaviour.key == "page":
            return ("Next page" if behaviour.step > 0 else "Previous page"), None
        if behaviour.key == "browser":
            return "Browser Mode on/off", None
        if behaviour.key == "bank":
            return "Hot cue bank 1-4 / 5-8", None
        return f"{behaviour.key} on/off", None
    if isinstance(behaviour, b.SetupDeck):
        return f"Deck {behaviour.deck}", "this half controls it"
    if isinstance(behaviour, b.SetupFx):
        return f"FX unit {behaviour.unit}", "this half uses it"
    if isinstance(behaviour, b.SetupOption):
        title, values, _ = OPTION_INFO.get(behaviour.option, (behaviour.option, {}, None))
        value = opts.get(behaviour.option)
        return title, f"now: {values.get(value, value)}"
    if isinstance(behaviour, b.PartFxHold):
        on = b.part_fx(eng).current(eng)[behaviour.stem]
        return f"Part FX {behaviour.stem}", f"tap: on/off (now {'on' if on else 'off'}); hold: this stem only"
    if isinstance(behaviour, b.CfxKnob):
        ch = ctx.get(behaviour.key)
        on = b.cfx(eng).on.get(ch, True)
        return f"Colour FX ch{ch}", None if on else "off: turns are remembered"
    if isinstance(behaviour, b.CfxToggle):
        return f"Colour FX ch{ctx.get(behaviour.key)} on/off", None
    if isinstance(behaviour, b.CfxTypeKnob):
        return "Colour FX type", "6 zones: type 1-6"
    if isinstance(behaviour, b.CfxNextType):
        return "Next Colour FX type", None
    return type(behaviour).__name__, None
