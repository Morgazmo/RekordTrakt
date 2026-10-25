"""What a physical control does. Profiles bind controls to these; the engine calls them with a context that says
which deck, FX unit and hot cue bank this control (or X1 half) drives. ctx["_pos"] / ctx["_half"] identify it."""
from dataclasses import dataclass

from rekordtrakt.engine.state import OBSERVED


@dataclass(frozen=True)
class Ref:
    """A Rekordbox function, resolved per context. `function` may contain {deck}, {fx}, {a}, {b}, {hc1}..{hc4};
    `deck` names the context key that gives the deck for per-deck functions."""
    function: str
    deck: str = None

    def resolve(self, ctx):
        return self.function.format(**ctx), (ctx[self.deck] if self.deck else None)


class Behaviour:
    def uses(self):
        """Refs this behaviour may send to or read from (for compiling the bridge mapping)."""
        return []

    def press(self, eng, ctx): pass
    def release(self, eng, ctx): pass
    def turn(self, eng, ctx, steps): pass
    def value(self, eng, ctx, value, physical): pass


# --- plain controls --------------------------------------------------------------------------------------

class Button(Behaviour):
    """Mirrors the physical button: press → press, release → release (velocity 0)."""

    def __init__(self, function, deck=None):
        self.ref = Ref(function, deck)

    def uses(self):
        return [self.ref]

    def press(self, eng, ctx):
        eng.press(self.ref, ctx)

    def release(self, eng, ctx):
        eng.release(self.ref, ctx)


class Macro(Behaviour):
    """One button, several functions pressed and released together."""

    def __init__(self, *refs):
        self.refs = list(refs)

    def uses(self):
        return self.refs

    def press(self, eng, ctx):
        for ref in self.refs:
            eng.press(ref, ctx)

    def release(self, eng, ctx):
        for ref in reversed(self.refs):
            eng.release(ref, ctx)


class Rotary(Behaviour):
    """Relative encoder passed through, one bridge message per step."""

    def __init__(self, function, deck=None):
        self.ref = Ref(function, deck)

    def uses(self):
        return [self.ref]

    def turn(self, eng, ctx, steps):
        eng.step(self.ref, ctx, steps)


class Split(Behaviour):
    """Encoder turned into two buttons: each step clockwise taps `plus`, anticlockwise taps `minus`."""

    def __init__(self, plus, minus, deck=None):
        self.plus, self.minus = Ref(plus, deck), Ref(minus, deck)

    def uses(self):
        return [self.plus, self.minus]

    def turn(self, eng, ctx, steps):
        for _ in range(abs(steps)):
            eng.tap(self.plus if steps > 0 else self.minus, ctx)


class Knob(Behaviour):
    """Absolute knob or fader (0-127), with pickup. `hires` scales it to Rekordbox's 14-bit range."""

    def __init__(self, function, deck=None, hires=False):
        self.ref, self.hires = Ref(function, deck), hires

    def uses(self):
        return [self.ref]

    def value(self, eng, ctx, value, physical):
        eng.knob(self.ref, ctx, value, self.hires, physical)


class HoldOrTap(Behaviour):
    """Short press fires `tap`; holding for `seconds` or longer fires `hold` instead (decided on release)."""

    def __init__(self, tap, hold, seconds=1.0):
        self.tap_ref, self.hold_ref, self.seconds = tap, hold, seconds
        self.since = {}

    def uses(self):
        return [self.tap_ref, self.hold_ref]

    def press(self, eng, ctx):
        self.since[(ctx["_pos"], ctx["_half"])] = eng.clock()

    def release(self, eng, ctx):
        t = self.since.pop((ctx["_pos"], ctx["_half"]), eng.clock())
        eng.tap(self.hold_ref if eng.clock() - t >= self.seconds else self.tap_ref, ctx)


class Disabled(Behaviour):
    """Bound on purpose to nothing (e.g. a feature with no Rekordbox equivalent), so the control doesn't fall
    through to another layer."""

    def __init__(self, reason):
        self.reason = reason

    def press(self, eng, ctx):
        eng.notice(f"   (not available: {self.reason})")

    def turn(self, eng, ctx, steps):
        eng.notice(f"   (not available: {self.reason})")


class ModifierTap(Behaviour):
    """A button that is also a modifier: held, it switches its half to the `name` layer; tapped (released without
    using another control, within `max_tap` seconds if set) it fires `function`, or the behaviour `tap`.
    With `long_function`, an unused hold of `long_after` seconds or more fires that instead (decided on release)."""

    def __init__(self, name, function=None, deck=None, max_tap=None, tap=None, long_function=None, long_after=1.0):
        self.name, self.max_tap, self.tap_behaviour = name, max_tap, tap
        self.tap_ref = Ref(function, deck) if function else None
        self.long_ref, self.long_after = (Ref(long_function, deck) if long_function else None), long_after

    def uses(self):
        refs = [r for r in (self.tap_ref, self.long_ref) if r]
        return refs + (self.tap_behaviour.uses() if self.tap_behaviour else [])


# --- built by the mapping editor (rekordtrakt/engine/actions.py) -----------------------------------------

class SetValue(Behaviour):
    """A button that sets a knob function to `value` (e.g. an EQ kill: low = 0), and to `release` when let go."""

    def __init__(self, function, deck=None, value=127, release=None, hires=False):
        self.ref, self.value, self.release_value, self.hires = Ref(function, deck), value, release, hires

    def uses(self):
        return [self.ref]

    def _set(self, eng, ctx, value):
        if self.hires:
            eng.set14(self.ref, ctx, value * 16383 // 127)
        else:
            eng.set7(self.ref, ctx, value)

    def press(self, eng, ctx):
        self._set(eng, ctx, self.value)

    def release(self, eng, ctx):
        if self.release_value is not None:
            self._set(eng, ctx, self.release_value)


class Group(Behaviour):
    """Several behaviours on one control, all at once: pressed in order, released in reverse, turned together."""

    def __init__(self, parts):
        self.parts = list(parts)

    def uses(self):
        return [r for p in self.parts for r in p.uses()]

    def press(self, eng, ctx):
        for p in self.parts:
            p.press(eng, ctx)

    def release(self, eng, ctx):
        for p in reversed(self.parts):
            p.release(eng, ctx)

    def turn(self, eng, ctx, steps):
        for p in self.parts:
            p.turn(eng, ctx, steps)


class MultiKnob(Behaviour):
    """One knob or fader driving several functions, each over its own range: (Ref, low, high, hires) per target.
    A range from high to low turns that target the other way."""

    def __init__(self, targets):
        self.targets = list(targets)

    def uses(self):
        return [t[0] for t in self.targets]

    def value(self, eng, ctx, value, physical):
        for i, (ref, low, high, hires) in enumerate(self.targets):
            scaled = round(low + (high - low) * value / 127)
            eng.knob(ref, ctx, max(0, min(127, scaled)), hires, (*physical, i))


class Sequence(Behaviour):
    """One press runs several steps in order, each after its own wait (seconds): [(wait, behaviour), ...]. Each
    step is tapped (pressed and released). Letting go doesn't stop it; pressing it again starts it over. Steps still
    waiting are dropped when the engine cancels them (Engine.cancel_waiting)."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.started = {}                     # (position, half) -> the latest press's number

    def uses(self):
        return [r for _, step in self.steps for r in step.uses()]

    def press(self, eng, ctx):
        key = (ctx.get("_pos"), ctx.get("_half"))
        number = self.started[key] = self.started.get(key, 0) + 1
        token = eng.run_token(ctx)
        due = 0.0
        for wait, step in self.steps:
            due += max(0.0, wait)

            def run(step=step):
                if self.started.get(key) == number and eng.still_on(token):
                    step.press(eng, ctx)
                    step.release(eng, ctx)
            if due <= 0:
                run()
            else:
                eng.later(due, run)


# --- loops, jumps and tempo ------------------------------------------------------------------------------

def loop_active(eng, ctx, deck_key="deck"):
    loop = eng.state.field(("GetLoopActive", ctx[deck_key]))
    return bool(loop and loop.status == OBSERVED and loop.value)


JUMP_FUNCTIONS = {4: "Jump4", 8: "Jump8", 16: "Jump16"}           # Rekordbox's MIDI beat jumps
PAD_JUMPS = {1: ("PAD2_BeatJump", "PAD1_BeatJump")}               # (forward, back): beat-jump pads


class BeatJump(Behaviour):
    """Beat jump by `size` beats (or the device's beatjump_size option). With a loop active (observed), it moves
    the loop instead, as the stock X1 does.

    4/8/16 use Rekordbox's beat jumps. 1 uses the beat-jump pad functions (PAD1 back, PAD2 forward per most
    Pioneer mappings; still to be verified live). The earlier "borrow a loop, move it, exit" trick for other sizes
    was dropped: Rekordbox's loop move doesn't carry the playhead, so it never jumped.
    """

    def __init__(self, size=None, deck="deck"):
        self.size, self.deck = size, deck

    def uses(self):
        refs = [Ref("LoopMove", self.deck), Ref("GetLoopActive", self.deck)]
        refs += [Ref(f"{f}{d}", self.deck) for f in JUMP_FUNCTIONS.values() for d in ("Fwd", "Prev")]
        refs += [Ref(f, self.deck) for pair in PAD_JUMPS.values() for f in pair]
        return refs

    def turn(self, eng, ctx, steps):
        if loop_active(eng, ctx, self.deck):
            eng.step(Ref("LoopMove", self.deck), ctx, steps)
            return
        size = self.size or eng.devices[ctx["_pos"]].options.get("beatjump_size", 4)
        if size in PAD_JUMPS:
            function = PAD_JUMPS[size][0 if steps > 0 else 1]
        else:
            function = f"{JUMP_FUNCTIONS.get(size, 'Jump4')}{'Fwd' if steps > 0 else 'Prev'}"
        for _ in range(abs(steps)):
            eng.tap(Ref(function, self.deck), ctx)


def LoopJump(deck="deck"):   # noqa: N802 - the basic X1 preset's Shift + Loop
    return BeatJump(size=4, deck=deck)


class Tempo(Behaviour):
    """Sync hold + Loop: deck tempo up/down using Rekordbox's relative tempo steps (TempoInc/DecMedium), which
    can't jump however the tempo was set before. One step is +/-0.5% in every tempo range. The 14-bit
    fader can't give finer steps: Rekordbox applies soft takeover to it and reports nothing.
    Steps per encoder click: options tempo_fine_steps (default 1 = 0.5%) / tempo_coarse_steps (default 4 = 2%)."""

    def __init__(self, fine, deck="deck"):
        self.fine, self.deck = fine, deck

    def uses(self):
        return [Ref("TempoIncMedium", self.deck), Ref("TempoDecMedium", self.deck)]

    def turn(self, eng, ctx, steps):
        opts = eng.devices[ctx["_pos"]].options
        per_step = opts.get("tempo_fine_steps", 1) if self.fine else opts.get("tempo_coarse_steps", 4)
        ref = Ref("TempoIncMedium" if steps > 0 else "TempoDecMedium", self.deck)
        for _ in range(abs(steps) * per_step):
            eng.tap(ref, ctx)


class PlayBrake(Behaviour):
    """The Performance Mod's vinyl break: holding PLAY for over 0.2 s while playing stops the deck on release,
    slower the longer it was held. Short presses, and presses while paused, behave like PLAY."""

    MIN, MAX = 0.2, 2.0

    def __init__(self, deck="deck"):
        self.deck = deck
        self.pending = {}

    def uses(self):
        return [Ref("PlayPause", self.deck), Ref("VinylAdjustBrake", self.deck), Ref("JogPlayPauseIndicator", self.deck)]

    def press(self, eng, ctx):
        key = (ctx["_pos"], ctx["_half"])
        if eng.state.playing(ctx[self.deck]):
            self.pending[key] = eng.clock()          # decide on release
        else:
            eng.press(Ref("PlayPause", self.deck), ctx)

    def release(self, eng, ctx):
        since = self.pending.pop((ctx["_pos"], ctx["_half"]), None)
        play = Ref("PlayPause", self.deck)
        if since is None:
            eng.release(play, ctx)
            return
        held = eng.clock() - since
        if held >= self.MIN:
            amount = min(1.0, (held - self.MIN) / (self.MAX - self.MIN))
            eng.set7(Ref("VinylAdjustBrake", self.deck), ctx, int(amount * 127))
        eng.tap(play, ctx)


class Latch(Behaviour):
    """Turns a held-type function into an on/off toggle: first press holds it on, the next press lets it go.
    Used for SFX Touch, so the SFX amount applies without holding a button."""

    def __init__(self, function, deck=None):
        self.ref = Ref(function, deck)

    def uses(self):
        return [self.ref]

    def press(self, eng, ctx):
        latched = eng.shared.setdefault("latched", set())
        key = self.ref.resolve(ctx)
        if key in latched:
            latched.discard(key)
            eng.release(self.ref, ctx)
        else:
            latched.add(key)
            eng.press(self.ref, ctx)


def latched_led(function):
    """LED value for a Latch: lit while latched on."""
    def value(eng, dev, half):
        fn = function.format(**dev.context(half))
        return 127 if (fn, None) in eng.shared.get("latched", set()) else 0
    return value


# --- browser ---------------------------------------------------------------------------------------------

def browser(eng):
    """Rekordbox has one browser and moves a single focus between folder tree and track list; the translator
    can't see where it is, so it tracks the focus it last caused (commanded)."""
    return eng.shared.setdefault("browser", {"focus": "list"})


class BrowseList(Behaviour):
    """Track list ±1 per step (× `page`). If the translator last sent focus to the tree, it opens the
    highlighted folder first, which moves Rekordbox's focus to its track list."""

    def __init__(self, page=1):
        self.page = page

    def uses(self):
        return [Ref("Browse"), Ref("Forward")]

    def turn(self, eng, ctx, steps):
        b = browser(eng)
        if b["focus"] == "tree":
            eng.tap(Ref("Forward"), ctx)
            b["focus"] = "list"
        eng.step(Ref("Browse"), ctx, steps * self.page)


class BrowseTree(Behaviour):
    """Folder tree ±1 per step (× `page`): sends Back first if focus was on the list."""

    def __init__(self, page=1):
        self.page = page

    def uses(self):
        return [Ref("Browse"), Ref("Back")]

    def turn(self, eng, ctx, steps):
        b = browser(eng)
        if b["focus"] != "tree":
            eng.tap(Ref("Back"), ctx)
            b["focus"] = "tree"
        eng.step(Ref("Browse"), ctx, steps * self.page)


class TreeOpen(Behaviour):
    """Open the highlighted folder (Rekordbox's Forward); focus moves to its tracks."""

    def uses(self):
        return [Ref("Forward")]

    def press(self, eng, ctx):
        eng.tap(Ref("Forward"), ctx)
        browser(eng)["focus"] = "list"


class TreeBack(Behaviour):
    def uses(self):
        return [Ref("Back")]

    def press(self, eng, ctx):
        eng.tap(Ref("Back"), ctx)
        browser(eng)["focus"] = "tree"


# --- modes and setup -------------------------------------------------------------------------------------

class ToggleMode(Behaviour):
    """Steps a per-half mode through `values` (e.g. Browser Mode on/off, hot cue bank, FX-section page);
    `step` -1 goes backwards. With `values_option`, the device option of that name (if set) picks which of the
    values are used and in what order (the settings window's page list)."""

    def __init__(self, key, values=(False, True), both_halves=False, step=1, values_option=None):
        self.key, self.values, self.both, self.step = key, values, both_halves, step
        self.values_option = values_option

    def press(self, eng, ctx):
        dev = eng.devices[ctx["_pos"]]
        values = list(self.values)
        if self.values_option == "pages":
            values = eng.pages(dev)                  # the enabled pages, custom ones included
        elif self.values_option:
            values = [v for v in dev.options.get(self.values_option, values) if v in self.values] or values
        current = dev.modes[ctx["_half"]].get(self.key, values[0])
        if current in values:
            new = values[(values.index(current) + self.step) % len(values)]
        else:                       # e.g. the current page was turned off: go to the first (or last) one
            new = values[0] if self.step > 0 else values[-1]
        for half in (dev.halves() if self.both else (ctx["_half"],)):
            eng.set_mode(ctx["_pos"], half, self.key, new)


class SetupDeck(Behaviour):
    def __init__(self, deck):
        self.deck = deck

    def press(self, eng, ctx):
        eng.assign(ctx["_pos"], ctx["_half"], deck=self.deck)


class SetupFx(Behaviour):
    def __init__(self, unit):
        self.unit = unit

    def press(self, eng, ctx):
        eng.assign(ctx["_pos"], ctx["_half"], fx=self.unit)


class SetupOption(Behaviour):
    """Cycles a device option through `values` (turn: forwards/backwards; press: forwards)."""

    def __init__(self, option, values):
        self.option, self.values = option, list(values)

    def _move(self, eng, ctx, step):
        dev = eng.devices[ctx["_pos"]]
        current = dev.options.get(self.option, self.values[0])
        i = self.values.index(current) if current in self.values else 0
        eng.set_option(ctx["_pos"], self.option, self.values[(i + step) % len(self.values)])

    def press(self, eng, ctx):
        self._move(eng, ctx, 1)

    def turn(self, eng, ctx, steps):
        self._move(eng, ctx, 1 if steps > 0 else -1)


# --- Part FX ---------------------------------------------------------------------------------------------

PART_STEMS = ("Drums", "Vocal", "Inst")


class PartFxGroup:
    """The Part FX selection (global in Rekordbox, shared by every control that uses it).

    A pad solos its stem as soon as it's pressed. Held, it's momentary: when the last held pad is let go, the selection
    from before the first press comes back. Tapped (let go within TAP seconds, no other pad held meanwhile), it
    toggles that stem in the selection and keeps it, so Part FX can be latched on and off too.
    Values come from Rekordbox's feedback; a stem it hasn't reported keeps the value last sent (off at first).
    """

    TAP = 0.3

    def __init__(self):
        self.held = {}          # stem -> when it was pressed, in press order
        self.chord = False      # more than one pad was held during this press
        self.snapshot = None    # selection to restore when the last held pad is released
        self.sent = {}          # the selection last sent, for stems Rekordbox hasn't reported

    @staticmethod
    def ref(stem):
        return Ref(f"FXPartSelect{stem}")

    def current(self, eng):
        out = {}
        for s in PART_STEMS:
            f = eng.state.field((f"FXPartSelect{s}", None))
            out[s] = bool(f.value) if f is not None and f.status == OBSERVED else self.sent.get(s, False)
        return out

    def apply(self, eng, ctx, selection):
        # Always send all three: they follow the value, and the last observed state can be ~10 ms stale.
        self.sent = dict(selection)
        for stem in PART_STEMS:
            eng.set_on(self.ref(stem), ctx, selection[stem])

    def hold(self, eng, ctx, stem):
        if not self.held:
            self.snapshot, self.chord = self.current(eng), False
        else:
            self.chord = True
        self.held[stem] = eng.clock()
        self.apply(eng, ctx, {s: s in self.held for s in PART_STEMS})

    def let_go(self, eng, ctx, stem):
        since = self.held.pop(stem, None)
        if self.held:
            self.apply(eng, ctx, {s: s in self.held for s in PART_STEMS})
            return
        if self.snapshot is None:
            return
        selection = self.snapshot
        if since is not None and not self.chord and eng.clock() - since <= self.TAP:
            selection = {**selection, stem: not selection[stem]}        # a tap: toggle it, and keep it
        self.apply(eng, ctx, selection)
        self.snapshot = None

    def shutdown(self, eng):
        if self.held and self.snapshot is not None:
            self.apply(eng, {}, self.snapshot)
        self.held, self.snapshot = {}, None


def part_fx(eng):
    return eng.shared.setdefault("part_fx", PartFxGroup())


class PartFxHold(Behaviour):
    """Beat FX on this stem only while held (the previous selection returns on release); a tap toggles it."""

    def __init__(self, stem):
        self.stem = stem

    def uses(self):
        return [PartFxGroup.ref(s) for s in PART_STEMS]

    def press(self, eng, ctx):
        part_fx(eng).hold(eng, ctx, self.stem)

    def release(self, eng, ctx):
        part_fx(eng).let_go(eng, ctx, self.stem)


# --- Colour FX -------------------------------------------------------------------------------------------

class CfxGroup:
    """Colour FX state shared by every control that drives it (X1 pages, F1 filter knobs).

    Rekordbox has no per-channel Colour FX on/off over MIDI, only the amount (centre = no effect). So on/off is
    emulated: off sends centre and remembers the knob value; on sends the remembered value back. Knob turns while
    off are remembered, not sent. The type (one for all channels, Rekordbox's CFX1-6 buttons) is commanded state:
    Rekordbox's CFX panel shows which type is really active.
    """

    CENTRE = 64
    TYPES = 6

    def __init__(self):
        self.on, self.value, self.type = {}, {}, None

    @staticmethod
    def ref(key):
        return Ref(f"CFXParameterCH{{{key}}}")

    def knob(self, eng, ctx, key, value, physical):
        ch = ctx[key]
        self.value[ch] = value
        if self.on.get(ch, True):
            eng.knob(self.ref(key), ctx, value, False, physical)

    def toggle(self, eng, ctx, key):
        ch = ctx[key]
        on = self.on[ch] = not self.on.get(ch, True)
        value = self.value.get(ch, self.CENTRE) if on else self.CENTRE
        eng.set7(self.ref(key), ctx, value)
        if on:
            eng.knob_sent[self.ref(key).resolve(ctx)] = value     # the knob carries on from here, no pickup
        for position in eng.devices:
            eng.refresh_leds(position)

    def select(self, eng, ctx, index):
        if index != self.type:
            self.type = index
            eng.tap(Ref(f"CFX{index + 1}On"), ctx)


def cfx(eng):
    return eng.shared.setdefault("cfx", CfxGroup())


class CfxKnob(Behaviour):
    """Colour FX amount for the channel in context key `key` ("deck", or "d1".."d4" for a fixed channel)."""

    def __init__(self, key="deck"):
        self.key = key

    def uses(self):
        return [CfxGroup.ref(self.key)]

    def value(self, eng, ctx, value, physical):
        cfx(eng).knob(eng, ctx, self.key, value, physical)


class CfxToggle(Behaviour):
    """Colour FX on/off for one channel (emulated, see CfxGroup)."""

    def __init__(self, key="deck"):
        self.key = key

    def uses(self):
        return [CfxGroup.ref(self.key)]

    def press(self, eng, ctx):
        cfx(eng).toggle(eng, ctx, self.key)


class CfxTypeKnob(Behaviour):
    """Picks the Colour FX type by knob position: six zones for Rekordbox's CFX1-6 type buttons."""

    def uses(self):
        return [Ref(f"CFX{n}On") for n in range(1, CfxGroup.TYPES + 1)]

    def value(self, eng, ctx, value, physical):
        cfx(eng).select(eng, ctx, min(CfxGroup.TYPES - 1, value * CfxGroup.TYPES // 128))


class CfxNextType(Behaviour):
    """Steps to the next Colour FX type (CFX1 → CFX6 → CFX1)."""

    def uses(self):
        return [Ref(f"CFX{n}On") for n in range(1, CfxGroup.TYPES + 1)]

    def press(self, eng, ctx):
        group = cfx(eng)
        group.select(eng, ctx, 0 if group.type is None else (group.type + 1) % CfxGroup.TYPES)


def cfx_on_led(key):
    """LED value: lit while that channel's Colour FX is on (emulated on/off)."""
    def value(eng, dev, half):
        return 127 if cfx(eng).on.get(dev.context(half)[key], True) else 0
    return value
