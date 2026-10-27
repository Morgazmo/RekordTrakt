"""Routes controller events through a profile to Rekordbox, and Rekordbox feedback back to LEDs and state.

Layer resolution for an event on X1 half H, first match wins:
  1. modifiers held on H: the combination ("fxa1+fxa2"), then each one ("sync")
  2. the hardware Shift layer if the event is shifted (knobs/faders fall back to the base layer)
  3. the base layer
Each layer is tried with the half's active tags first ("base@browser", "base@stems", ...) and then plain.
Tags come from the profile: modes (Browser Mode, overlay, hot cue bank) and options (encoder style, ...).

A press remembers which binding it fired, so the release goes to the same binding even if Shift, a modifier
or a mode changed in between.

Everything the engine does is also reported as trace events (dicts with a "kind": input, binding, send, pickup,
feedback, notice, log, unrecognised) for the debug window. Events caused by a controller message carry its "input"
number.
"""
import heapq
from collections import deque
from dataclasses import dataclass, field

from rekordtrakt.devices.base import DEFAULT_DECK_SLOTS, DEFAULT_FX_SLOTS, PRESS, RELEASE, TURN, VALUE, Event
from rekordtrakt.engine import actions as user_actions
from rekordtrakt.engine.behaviours import CfxGroup, CfxKnob, Knob, ModifierTap
from rekordtrakt.engine.labels import OPTION_INFO, OPTION_WHEN, describe, knob_default, short
from rekordtrakt.engine.state import OBSERVED, State

PICKUP_WINDOW = 2       # a knob takes over once it's within this many steps of the last value sent
BLINK_CHANGES, BLINK_SPAN, BLINK_GONE = 3, 2.0, 1.0   # 3 on/off changes within 2 s = blinking; quiet 1 s = stopped


@dataclass
class Profile:
    device_type: str
    bindings: dict                                   # (layer, control) -> Behaviour
    leds: dict = field(default_factory=dict)         # "control" or "control@tag" -> Ref whose feedback drives it
    mode_leds: dict = field(default_factory=dict)    # tag -> {control: value or fn(eng, dev, half)}; overrides
    tags: object = None                              # fn(dev, half) -> list of active tags, highest priority first
    reassignable: bool = True                        # its decks and FX units can be moved (window, setup mode)
    default_modes: dict = field(default_factory=dict)
    default_options: dict = field(default_factory=dict)  # filled into each device's options at start-up
    combo_taps: dict = field(default_factory=dict)   # frozenset of modifier names -> Behaviour, fired when they're
    combo_max_tap: float = 0.6                       # pressed together and released quickly with nothing else used
    led_colour: object = None                        # fn(dev, half, control, value) -> MIDI velocity, or None
    pages: tuple = ()                                # FX-section pages (mode "page"), in their default order
    page_names: dict = field(default_factory=dict)   # page -> label for the main window
    option_choices: dict = field(default_factory=dict)   # option -> allowed values (settings window)
    modifier_names: dict = field(default_factory=dict)   # modifier or combination -> label ("sync": "Sync layer")
    title: str = ""                                  # the mapping's name in the window
    row_titles: dict = field(default_factory=dict)   # page -> titles for the FX-section rows ("Slot 1", ...)
    page_short: dict = field(default_factory=dict)   # page -> short name for page tabs
    alt_layer: str = None                            # a modifier whose labels show in brackets ("Cue A (E)")
    page_controls: tuple = ()                        # controls whose job changes with the page (custom pages blank them)
    edit_layers: tuple = ()                          # (layer, label) the mapping editor offers; default Normal (+ Shift)


@dataclass
class DeviceConfig:
    position: str
    device: object                                   # device type instance (X1MK3, F1)
    decks: list                                      # X1: per half [L, R]; F1: [first deck, second deck]
    fx_units: list                                   # X1: per half; F1: [unit]
    options: dict = field(default_factory=dict)
    profile: str = ""
    modes: dict = field(default_factory=dict)        # half -> {mode: value}, runtime only
    name: str = ""                                   # the user's name for it ("X1 Left")
    shift_latched: bool = False                      # the window's SHIFT latch: every press counts as shifted
    mapping: dict = field(default_factory=dict)      # your own bindings and pages over the preset (engine/actions.py)

    def halves(self):
        return ("L", "R") if self.device.has_halves else (None,)

    def deck_slots(self):
        """A unit without halves: the decks it drives, [{key, label, default?}] (none for a unit with halves)."""
        return () if self.device.has_halves else getattr(self.device, "deck_slots", DEFAULT_DECK_SLOTS)

    def fx_slots(self):
        return () if self.device.has_halves else getattr(self.device, "fx_slots", DEFAULT_FX_SLOTS)

    def deck_keys(self):
        """The deck keys this device's bindings may use: a half's own "deck", its slots' keys, or a fixed deck."""
        own = ("deck",) if self.device.has_halves else tuple(s["key"] for s in self.deck_slots())
        return own + ("d1", "d2", "d3", "d4")

    @staticmethod
    def _at(values, i, default):
        return values[i] if i < len(values) else default

    def context(self, half, deck=None, fx=None, bank=None):
        if half is None:                         # deck / fx given: every slot on that one (possible_contexts)
            ctx = {"_pos": self.position, "_half": None}
            for i, s in enumerate(self.deck_slots()):
                ctx[s["key"]] = deck or self._at(self.decks, i, s.get("default", i + 1))
            for i, s in enumerate(self.fx_slots()):
                ctx[s["key"]] = fx or self._at(self.fx_units, i, s.get("default", 1))
            ctx.setdefault("fx", fx or self._at(self.fx_units, 0, 1))
            ctx.update({f"d{n}": n for n in range(1, 5)})
            return ctx
        i = ("L", "R").index(half)
        bank = self.modes.get(half, {}).get("bank", 0) if bank is None else bank
        ctx = {"deck": self.decks[i] if deck is None else deck, "fx": self.fx_units[i] if fx is None else fx,
               "_pos": self.position, "_half": half}
        ctx.update({f"hc{n}": n + 4 * bank for n in range(1, 5)})       # hot cue number for button n
        ctx.update({f"d{n}": n for n in range(1, 5)})                   # fixed decks, e.g. "load to deck 3"
        return ctx

    def possible_contexts(self, reassignable):
        """Every context this device could be in, so the bridge mapping covers all of them."""
        for half in self.halves():
            if half is None:
                if not reassignable:
                    yield half, self.context(half)
                    continue
                for deck in range(1, 5):
                    for fx in (1, 2):
                        yield half, self.context(half, deck, fx)
                continue
            decks = range(1, 5) if reassignable else (self.decks[("L", "R").index(half)],)
            fxs = (1, 2) if reassignable else (self.fx_units[("L", "R").index(half)],)
            for deck in decks:
                for fx in fxs:
                    for bank in (0, 1):
                        yield half, self.context(half, deck, fx, bank)


class Engine:
    def __init__(self, devices, profiles, bridge, leds, clock, log=print, verbose=False, on_config_change=None,
                 trace=None):
        self.devices = {d.position: d for d in devices}
        self.profiles = dict(profiles)        # profile name (or device type name) -> Profile
        self.bridge = bridge
        self.leds = leds
        self.clock = clock
        self._print = log                     # notices always; the step-by-step log only when verbose
        self.verbose = verbose
        self.trace = trace                    # fn(event dict), or None
        self.input_count = 0                  # numbers controller messages, so trace events can point back to them
        self._cause = None                    # the input being handled now
        self.view_version = 0                 # bumped whenever the main window's view may have changed
        self.blink_times = {}                 # (function, deck) -> times of its last few on/off changes
        self.blinking = set()                 # (function, deck) Rekordbox is blinking (e.g. Cue/Play when paused)
        self.not_in_bridge = set()            # (function, deck) sends that Rekordbox's bridge mapping can't take
        self.on_config_change = on_config_change or (lambda dev: None)
        self.state = State(clock)
        self.held = {}                        # (position, control) -> (behaviour, ctx)
        self.down = {}                        # (position, control) -> {"shift", "source"}: pressed right now
        self.test_positions = set()            # devices monitored without executing their hardware bindings
        self.test_values = {}                  # latest absolute hardware value while Device Test isolates output
        self.modifiers = {}                   # (position, half) -> {name: {"since": t, "used": bool}}
        self.combos = {}                      # (position, half) -> {"names": set, "since": t, "used": bool}
        self.shared = {}                      # state shared between controls/devices (Part FX group, browser focus)
        self.knob_sent = {}                   # (function, deck) -> last 0-127 value a knob sent
        self.knob_state = {}                  # (position, control) -> (target, picked up?, last value)
        self.timers = []                      # heap of (due, seq, fn) for delayed actions
        self.runs = {}                        # (position, half) -> moves on to cancel sequence steps still waiting
        self.stopping = False
        self._seq = 0
        self.bound = {}                       # position -> {(layer, control): behaviour}: preset + your mapping
        self.dev_leds = {}                    # position -> LED sources: preset + your mapping's
        for dev in devices:
            dev.options = {**self.profile(dev).default_options, **dev.options}
            dev.mapping = user_actions.normalise(dev.mapping)
            for half in dev.halves():
                dev.modes.setdefault(half, dict(self.profile(dev).default_modes))
            self._compile_mapping(dev)
        self._rebuild_led_sources()

    def profile(self, dev):
        found = self.profiles.get(dev.profile) or self.profiles.get(dev.device.type_name)
        if found is None:                     # a controller with no preset (an imported one): your mapping only
            found = self.profiles[dev.device.type_name] = Profile(dev.device.type_name, {}, title="Your mapping")
        return found

    # --- your own mapping over the preset -------------------------------------------------------------
    @staticmethod
    def control_kinds(dev):
        kinds = getattr(dev.device, "control_kinds", None)
        if kinds:
            return kinds()
        return {c: {"press": "button", "value": "knob", "turn": "encoder"}[k] for c, k in dev.device.controls()}

    def edit_layers(self, dev, control=None):
        profile = self.profile(dev)
        layers = (list(profile.edit_layers) if profile.edit_layers else
                  [("base", "Normal")] + ([("shift", "Shift")] if getattr(dev.device, "has_shift", False) else []))
        # A definition can mark only some alternate MIDI messages as shifted. The F1's second hardware page does
        # this: its pads, Sync and encoder change address, while its knobs and faders do not. Do not offer a layer
        # that the selected physical control can never reach.
        supports = getattr(dev.device, "supports_shift", None)
        if control is not None and callable(supports) and not supports(control):
            layers = [(name, label) for name, label in layers if name != "shift"]
        return layers

    def _compile_mapping(self, dev):
        self.cancel_waiting(dev.position)     # steps from bindings that are about to be replaced
        profile = self.profile(dev)
        mine = user_actions.compile_bindings(dev.mapping, self.control_kinds(dev), profile.page_controls,
                                             [layer for layer, _ in self.edit_layers(dev)][:2], dev.deck_keys())
        self.bound[dev.position] = {**profile.bindings, **mine}
        self.dev_leds[dev.position] = {**profile.leds, **user_actions.feedback_leds(dev.mapping)}

    def _mapping_changed(self, dev):
        self._compile_mapping(dev)
        self.view_version += 1
        self._rebuild_led_sources()
        self.refresh_leds(dev.position)
        self.on_config_change(dev)

    def set_binding(self, position, layer, page, control, action):
        """Saves what `control` does on `layer` (and `page`, or every page); action None brings the preset's back."""
        dev = self.devices[position]
        kinds = self.control_kinds(dev)
        if control not in kinds:
            raise ValueError(f"{dev.name} has no control '{control}'")
        if layer not in [name for name, _ in self.edit_layers(dev, control)]:
            raise ValueError(f"{dev.name} has no '{layer}' layer to edit")
        if page is not None and page not in self.pages(dev, enabled_only=False):
            raise ValueError(f"no page '{page}'")
        if action is not None:
            user_actions.build(action, kinds[control], dev.deck_keys())     # refuse what can't work before saving
        bindings = [e for e in dev.mapping["bindings"]
                    if not (e.get("layer") == layer and e.get("page") == page and e.get("control") == control)]
        if action is not None:
            bindings.append({"layer": layer, "page": page, "control": control, "action": action})
        dev.mapping = {**dev.mapping, "bindings": bindings}
        self.notice(f"{dev.name}: {control} {'changed' if action is not None else 'back to the preset'}")
        self._mapping_changed(dev)

    def add_page(self, position, name):
        dev = self.devices[position]
        name = user_actions.check_name(name)
        page = {"id": user_actions.new_page_id(dev.mapping), "name": name, "short": name[:8]}
        order = self.pages(dev, enabled_only=False)            # before: the new page goes last, where it was added
        dev.mapping = {**dev.mapping, "pages": dev.mapping["pages"] + [page]}
        self._compile_mapping(dev)
        self.set_pages(position, self.pages(dev) + [page["id"]], order=order + [page["id"]])
        return page["id"]

    def rename_page(self, position, page_id, name):
        dev = self.devices[position]
        name = user_actions.check_name(name)
        if page_id not in user_actions.page_ids(dev.mapping):
            raise ValueError("only your own pages can be renamed")
        dev.mapping = {**dev.mapping, "pages": [{**p, "name": name, "short": name[:8]} if p["id"] == page_id else p
                                                for p in dev.mapping["pages"]]}
        self._mapping_changed(dev)

    def remove_page(self, position, page_id):
        dev = self.devices[position]
        if page_id not in user_actions.page_ids(dev.mapping):
            raise ValueError("only your own pages can be removed")
        dev.mapping = {"pages": [p for p in dev.mapping["pages"] if p["id"] != page_id],
                       "bindings": [e for e in dev.mapping["bindings"] if e.get("page") != page_id]}
        self._compile_mapping(dev)
        if "page_order" in dev.options:
            dev.options["page_order"] = [p for p in dev.options["page_order"] if p != page_id]
        remaining = [p for p in self.pages(dev) if p != page_id]
        self.set_pages(position, remaining or [self.profile(dev).pages[0]])

    def set_mapping(self, position, mapping):
        """Replaces a device's own mapping (import); the preset stays underneath."""
        dev = self.devices[position]
        m = user_actions.normalise(mapping)
        kinds = self.control_kinds(dev)
        for e in m["bindings"]:
            if e.get("control") in kinds:
                user_actions.build(e["action"], kinds[e["control"]], dev.deck_keys())
        for p in m["pages"]:
            user_actions.check_name(p.get("name"))
        dev.mapping = m
        self._compile_mapping(dev)
        ids = user_actions.page_ids(m)
        self.set_option(position, "pages", [p for p in self.pages(dev) if p in self.profile(dev).pages or p in ids])

    def control_info(self, position, control, page=None):
        """What the mapping editor shows for one control: per layer, the preset's job and yours."""
        dev = self.devices[position]
        profile = self.profile(dev)
        half, base = control.split(".", 1) if "." in control else (None, control)
        kinds = self.control_kinds(dev)
        if control not in kinds:
            raise ValueError(f"{dev.name} has no control '{control}'")
        page_bound = base in profile.page_controls
        page = (page or dev.modes.get(half, {}).get("page")) if page_bound else None
        ctx = dev.context(half)
        layers = []
        for layer, label in self.edit_layers(dev, control):
            mine = next((e["action"] for e in dev.mapping["bindings"] if e.get("layer") == layer
                         and e.get("page") == page and e.get("control") == control), None)
            preset = None
            for key in (user_actions.layer_key(layer, page), layer):
                beh = profile.bindings.get((key, control)) or profile.bindings.get((key, base))
                if beh is not None:
                    preset = describe(beh, self, ctx, profile.modifier_names)
                    break
            if preset is None and page in user_actions.page_ids(dev.mapping):
                preset = ("—", "nothing on this page")
            layers.append({"layer": layer, "label": label, "mine": mine,
                           "preset": {"label": preset[0], "detail": preset[1]} if preset else None})
        return {"position": position, "control": control, "kind": kinds[control], "page": page,
                "page_bound": page_bound, "half": half, "deck": ctx.get("deck"), "layers": layers,
                "slots": [[s["key"], s["label"], ctx[s["key"]]] for s in dev.deck_slots()]}

    def playing_decks(self):
        """Decks Rekordbox reports as playing (from its feedback), e.g. before asking Rekordbox to close."""
        return [deck for deck in (1, 2, 3, 4) if self.state.playing(deck)]

    # --- what the bridge mapping must contain ---------------------------------------------------------
    def uses(self):
        out = set()
        for dev in self.devices.values():
            profile = self.profile(dev)
            for _, ctx in dev.possible_contexts(profile.reassignable):
                for behaviour in self.bound[dev.position].values():
                    out.update(ref.resolve(ctx) for ref in behaviour.uses())
                out.update(ref.resolve(ctx) for ref in self.dev_leds[dev.position].values())
            decks = range(1, 5) if profile.reassignable else dev.decks
            # Deck loads clear commanded state, so every deck the rig may drive needs this feedback.
            out.update(("LoadedIndicator", deck) for deck in decks)
        return out

    # --- logging and tracing --------------------------------------------------------------------------
    def _event(self, kind, text, show=None, **data):
        """show: True prints always (notices), None prints when verbose, False never prints (feedback)."""
        if show or (show is None and self.verbose):
            self._print(text)
        if self.trace:
            self.trace({"kind": kind, "text": text.strip(), "input": self._cause, **data})

    def log(self, text):
        self._event("log", text)

    def notice(self, text):
        """Always shown: mode and setup changes, "not available"."""
        self._event("notice", text, show=True)

    # --- sending --------------------------------------------------------------------------------------
    def _send(self, verb, ref, ctx, text, *args):
        f, d = ref.resolve(ctx)
        entry = getattr(self.bridge, "entries", {}).get((f, d)) or {}
        raw = [entry["input"]["status"], entry["input"]["data1"]] if entry.get("input") else None
        self._event("send", f"   -> {f} {f'deck {d} ' if d else ''}{text}", function=f, deck=d, verb=verb,
                    value=text, raw=raw, position=ctx.get("_pos"), half=ctx.get("_half"),
                    bypassed=getattr(self.bridge, "bypassed", False))
        try:
            sent = getattr(self.bridge, verb)(f, d, *args)
            if verb == "tap" and sent is False:
                self.notice(f"Skipped {f}{f' deck {d}' if d else ''}: another control is holding it")
        except KeyError:                        # not in Rekordbox's (older) bridge mapping: say so once, carry on
            if (f, d) not in self.not_in_bridge:
                self.not_in_bridge.add((f, d))
                self.notice(f"{f} isn't in Rekordbox's MIDI mapping yet: update it to use this")

    def press(self, ref, ctx):
        self._send("press", ref, ctx, "press")

    def release(self, ref, ctx):
        self._send("release", ref, ctx, "release")

    def tap(self, ref, ctx):
        self._send("tap", ref, ctx, "tap")

    def step(self, ref, ctx, steps):
        self._send("step", ref, ctx, f"{steps:+d}", steps)

    def set7(self, ref, ctx, v):
        self._send("set7", ref, ctx, f"= {v}", v)

    def set14(self, ref, ctx, v):
        self._send("set14", ref, ctx, f"= {v}/16383", v)

    def set_on(self, ref, ctx, on):
        self._send("set_on", ref, ctx, "on" if on else "off", on)

    def knob(self, ref, ctx, value, hires, physical):
        """Absolute knob with pickup: after the knob's target changes (overlay, deck reassignment), it only
        takes over once it reaches the value last sent to that target, so nothing jumps. A knob moved in the
        window is a deliberate value, so it's sent at once; the real knob then picks up from it."""
        target = ref.resolve(ctx)
        last = self.knob_sent.get(target)
        prev_target, picked, prev_value = self.knob_state.get(physical, (None, True, None))
        dev = self.devices.get(ctx.get("_pos"))
        if physical[0] == "ui" or not (dev and dev.options.get("knob_pickup", False)):
            picked = True                       # the window, or pickup off: always send at once
        elif target != prev_target:
            picked = last is None or abs(value - last) <= PICKUP_WINDOW
        elif not picked and (abs(value - last) <= PICKUP_WINDOW or
                             (prev_value is not None and (prev_value - last) * (value - last) <= 0)):
            picked = True
        self.knob_state[physical] = (target, picked, value)
        if not picked:
            self._event("pickup", f"   (pickup: {target[0]} waits for the knob to reach {last})", function=target[0],
                        deck=target[1], value=value, waiting_for=last, position=ctx.get("_pos"))
            return
        self.knob_sent[target] = value
        if physical[0] == "ui":         # moved in the window: the real knob must pick up from here, not jump
            hw = physical[1:]
            state = self.knob_state.get(hw)
            if state and state[0] == target:
                self.knob_state[hw] = (target, False, state[2])
        if hires:
            self.set14(ref, ctx, value * 16383 // 127)
        else:
            self.set7(ref, ctx, value)

    # --- input ----------------------------------------------------------------------------------------
    def device_message(self, position, status, d1, d2):
        dev = self.devices[position]
        decoded = dev.device.decode(status, d1, d2)
        if decoded:
            self.handle(Event(position, decoded.control, decoded.kind, decoded.value, decoded.shift), (status, d1, d2))
        else:
            self._event("unrecognised", f"{position} unrecognised message {status:02X} {d1:02X} {d2:02X}",
                        position=position, raw=[status, d1, d2])

    def handle(self, ev, raw=None):
        self.input_count += 1
        self._cause = self.input_count
        try:
            self._handle(ev, raw)
        finally:
            self._cause = None

    def _handle(self, ev, raw):
        self.view_version += 1
        dev = self.devices[ev.position]
        if ev.kind == PRESS:                  # the window shows what's down, and Shift while a shifted press is held
            self.down[(ev.position, ev.control)] = {"shift": ev.shift, "source": ev.source}
        elif ev.kind == RELEASE:
            self.down.pop((ev.position, ev.control), None)
        if dev.shift_latched and not ev.shift and ev.kind != RELEASE:
            ev = Event(ev.position, ev.control, ev.kind, ev.value, True, ev.source)   # hardware and window alike
        profile = self.profile(dev)
        half, base = ev.control.split(".", 1) if "." in ev.control else (None, ev.control)
        ctx = dev.context(half)
        mods = self.modifiers.setdefault((ev.position, half), {})
        self._event("input", f"{ev.position} {ev.control}{' (shift)' if ev.shift else ''} {ev.kind}"
                             f"{'' if ev.kind in (PRESS, RELEASE) else ' ' + str(ev.value)}",
                    position=ev.position, control=ev.control, action=ev.kind, value=ev.value, shift=ev.shift,
                    modifiers=sorted(mods), raw=list(raw) if raw else None)

        # Device Test stops after decoding and updating the view. Controls animate and Debug keeps the raw
        # messages, but a community tester cannot accidentally operate Rekordbox while checking a map.
        if ev.source == "hw" and ev.position in self.test_positions:
            if ev.kind == VALUE:
                self.test_values[(ev.position, ev.control)] = ev.value
            return

        if ev.kind == RELEASE:
            binding = self.held.pop((ev.position, ev.control, ev.source), None)
            if binding:
                behaviour, bctx = binding
                self._event("binding", f"   release: {type(behaviour).__name__}", show=False, layer=None,
                            behaviour=type(behaviour).__name__, position=ev.position, release=True)
                if isinstance(behaviour, ModifierTap):
                    self._modifier_up(behaviour, mods, bctx)
                else:
                    behaviour.release(self, bctx)
            return

        for m in mods.values():          # any other control used while a modifier is held: it's not a tap
            m["used"] = True
        behaviour, layer = self._resolve(profile, dev, half, base, ev, mods)
        self._event("binding", f"   {layer or '-'}: {type(behaviour).__name__ if behaviour else 'nothing bound'}",
                    show=False, layer=layer, behaviour=type(behaviour).__name__ if behaviour else None,
                    position=ev.position, tags=self.tags(dev, half))
        modifier_press = ev.kind == PRESS and isinstance(behaviour, ModifierTap)
        combo = self.combos.get((ev.position, half))
        if combo and not modifier_press:
            combo["used"] = True         # something else was used while the combination was held
        if behaviour is None:
            return
        if ev.kind == PRESS:
            if modifier_press:
                names = set(mods) | {behaviour.name}
                # Part of a declared combo tap (e.g. FX Assign 1 + 2): neither button fires its own tap. Other
                # combinations (Sync held + tap Loop) keep the new button's own tap.
                in_combo = len(names) > 1 and any(names <= key for key in profile.combo_taps)
                if in_combo:
                    if combo is None:
                        combo = self.combos[(ev.position, half)] = {"names": set(), "since": self.clock(),
                                                                    "used": False}
                    combo["names"] |= names
                mods[behaviour.name] = {"since": self.clock(), "used": in_combo}
                self.refresh_leds(dev.position)
            else:
                behaviour.press(self, ctx)
            self.held[(ev.position, ev.control, ev.source)] = (behaviour, ctx)
        elif ev.kind == TURN:
            behaviour.turn(self, ctx, ev.value)
        elif ev.kind == VALUE:
            physical = (ev.position, ev.control) if ev.source == "hw" else (ev.source, ev.position, ev.control)
            behaviour.value(self, ctx, ev.value, physical)

    def release_source(self, source):
        """Lets go of everything `source` holds (the window: on unlock off, focus loss, disconnect)."""
        for position, control, src in [k for k in self.held if k[2] == source]:
            self.handle(Event(position, control, RELEASE, 0, False, source))

    def set_shift_latch(self, position, on):
        dev = self.devices[position]
        if not getattr(dev.device, "has_shift", False):
            raise ValueError(f"{dev.name} has no Shift layer")
        dev.shift_latched = bool(on)
        self.view_version += 1
        self.notice(f"{dev.name}: Shift {'latched' if on else 'released'}")
        self.refresh_leds(position)

    def set_device_test(self, position, on):
        """Monitor one controller without executing its hardware bindings."""
        if position not in self.devices:
            raise ValueError(f"no controller '{position}'")
        on = bool(on)
        if on:
            # Finish anything pressed before isolation begins, then suppress subsequent hardware input.
            for p, control, source in [k for k in self.held if k[0] == position and k[2] == "hw"]:
                self.handle(Event(p, control, RELEASE, 0, False, source))
            self.cancel_waiting(position)
            self.test_positions.add(position)
        else:
            self.test_positions.discard(position)
            for key in [k for k in self.test_values if k[0] == position]:
                self.test_values.pop(key, None)
            for key in [k for k in self.down if k[0] == position]:
                self.down.pop(key, None)
        self.view_version += 1
        self.notice(f"{self.devices[position].name}: MIDI test {'on' if on else 'off'}")

    def replace_device_definition(self, position, device, profile=None):
        """Adopt newly learned addresses without reopening the MIDI port or restarting the translator."""
        dev = self.devices.get(position)
        if dev is None:
            raise ValueError(f"no controller '{position}'")
        if (dev.device.has_halves != device.has_halves or dev.device.controls() != device.controls() or
                list(dev.deck_slots()) != list(getattr(device, "deck_slots", ())) or
                list(dev.fx_slots()) != list(getattr(device, "fx_slots", ()))):
            raise ValueError("a learned definition may change MIDI addresses, not the controller's controls or slots")
        if self.leds and position in self.leds.devices:
            self.leds.all_off(position)
            _, output, _ = self.leds.devices[position]
            self.leds.devices[position] = (device, output, device.led_interval)
        dev.device = device
        if profile and not dev.profile:
            dev.profile = profile             # a learned type keeps the bundled template's preset underneath
        self._compile_mapping(dev)
        self._rebuild_led_sources()
        if self.leds:
            self.refresh_leds(position)
        self.view_version += 1

    def rename(self, position, name):
        dev = self.devices[position]
        dev.name = name.strip()[:40] or dev.name
        self.view_version += 1
        self.on_config_change(dev)

    def tags(self, dev, half):
        profile = self.profile(dev)
        return list(profile.tags(dev, half)) if profile.tags else []

    def _resolve(self, profile, dev, half, base, ev, mods):
        tags = self.tags(dev, half)

        def layered(name):
            return [f"{name}@{t}" for t in tags] + [name]

        names = list(mods)
        candidates = (["+".join(sorted(names))] if len(names) > 1 else []) + names
        layers = []
        for c in candidates:             # with Shift held, "sync/shift" is tried before "sync"
            layers += (layered(f"{c}/shift") if ev.shift else []) + layered(c)
        if ev.shift:
            layers += layered("shift")
        bound = self.bound[dev.position]

        def lookup(layer):     # a half-specific binding ("L.loop") beats one for both halves ("loop")
            b = bound.get((layer, f"{half}.{base}")) if half else None
            return b if b is not None else bound.get((layer, base))

        for layer in layers:
            b = lookup(layer)
            if b is not None:
                return b, layer
        if ev.shift and ev.kind != VALUE:
            return None, None
        for layer in layered("base"):
            b = lookup(layer)
            if b is not None:
                return b, layer
        return None, None

    def _modifier_up(self, behaviour, mods, ctx):
        m = mods.pop(behaviour.name, None)
        held_for = self.clock() - m["since"] if m else 0
        if m and not m["used"] and behaviour.long_ref and held_for >= behaviour.long_after:
            self.tap(behaviour.long_ref, ctx)
            self.refresh_leds(ctx["_pos"])
            return
        tapped = m and not m["used"] and (behaviour.max_tap is None or held_for <= behaviour.max_tap)
        if tapped and behaviour.tap_behaviour:
            behaviour.tap_behaviour.press(self, ctx)
            behaviour.tap_behaviour.release(self, ctx)
        elif tapped and behaviour.tap_ref:
            self.tap(behaviour.tap_ref, ctx)
        key = (ctx["_pos"], ctx["_half"])
        combo = self.combos.get(key)
        if combo and not combo["names"] & set(mods):          # the whole combination has been let go
            del self.combos[key]
            profile = self.profile(self.devices[ctx["_pos"]])
            action = profile.combo_taps.get(frozenset(combo["names"]))
            if action and not combo["used"] and self.clock() - combo["since"] <= profile.combo_max_tap:
                action.press(self, ctx)
                action.release(self, ctx)
        self.refresh_leds(ctx["_pos"])

    # --- modes and configuration ----------------------------------------------------------------------
    def set_mode(self, position, half, key, value):
        dev = self.devices[position]
        if key == "page" and dev.modes[half].get("page") != value:
            self.cancel_waiting(position, half)
        dev.modes[half][key] = value
        self.view_version += 1
        self.notice(f"{position} {half or ''} {key} = {value}")
        self.refresh_leds(position)

    def assign(self, position, half=None, deck=None, fx=None, slot=None):
        """Moves a half to `deck` and/or FX unit `fx`; on a unit without halves, deck slot or FX slot number `slot`
        (whichever of deck / fx is given)."""
        dev = self.devices[position]
        self.cancel_waiting(position, half)
        if half is not None:
            i = dev.halves().index(half)
            what = f"{half}: "
        else:
            i = slot
            what = f"{(dev.deck_slots() if deck is not None else dev.fx_slots())[slot]['label']}: "
        for values, value in ((dev.decks, deck), (dev.fx_units, fx)):
            if value is not None:
                while len(values) <= i:                 # a definition that gained a slot: fill up to it
                    values.append(len(values) + 1)
                values[i] = value
        self.view_version += 1
        self.notice(f"{dev.name} {what}" + (f"deck {deck}" if deck is not None else f"FX unit {fx}"))
        self._rebuild_led_sources()
        self.refresh_leds(position)
        self.on_config_change(dev)

    def set_option(self, position, key, value):
        dev = self.devices[position]
        dev.options[key] = value
        self.view_version += 1
        self.notice(f"{position} option {key} = {value}")
        self._rebuild_led_sources()
        self.refresh_leds(position)
        self.on_config_change(dev)

    def pages(self, dev, enabled_only=True):
        """The device's enabled pages (option "pages"), falling back to the profile's list. Your own pages count
        too. enabled_only=False: every page it has, in the settings window's order (option "page_order", where
        pages that are off keep their place too; without it, enabled first)."""
        profile = self.profile(dev)
        known = list(profile.pages) + user_actions.page_ids(dev.mapping)
        chosen = [p for p in dev.options.get("pages", profile.pages) if p in known] or list(profile.pages)
        order = [p for p in dev.options.get("page_order", ()) if p in known]
        if not order:
            return chosen if enabled_only else chosen + [p for p in known if p not in chosen]
        full = order + [p for p in chosen if p not in order] + [p for p in known if p not in order and p not in chosen]
        return [p for p in full if p in chosen] if enabled_only else full

    def page_names(self, dev):
        profile = self.profile(dev)
        mine = {p["id"]: p["name"] for p in dev.mapping["pages"]}
        return {**profile.page_names, **mine}, {**profile.page_short, **{p["id"]: p.get("short") or p["name"]
                                                                         for p in dev.mapping["pages"]}}

    def set_pages(self, position, pages, order=None):
        """Turns pages on/off (and orders them); `order` is every page in the settings window's order, on or off.
        A half on a page that's now off moves to the first page."""
        dev = self.devices[position]
        known = self.pages(dev, enabled_only=False)
        pages = [p for p in pages if p in known]
        if not pages or len(set(pages)) != len(pages):
            raise ValueError("choose at least one page, each once")
        if order is not None:
            order = [p for p in order if p in known]
            if len(set(order)) != len(order):
                raise ValueError("each page once")
            dev.options["page_order"] = order + [p for p in known if p not in order]
            pages = [p for p in dev.options["page_order"] if p in pages]
        self.set_option(position, "pages", pages)
        for half in dev.halves():
            if dev.modes[half].get("page") not in pages:
                self.set_mode(position, half, "page", pages[0])

    # --- main window ----------------------------------------------------------------------------------
    @staticmethod
    def _assign_rows(dev):
        """What Settings offers to move: a half's deck and FX unit together, or each deck and FX slot of a unit
        without halves. Each item says how to send the change ({"half"} or {"slot"}) and what it is now."""
        if dev.device.has_halves:
            return [{"label": f"{'Left' if half == 'L' else 'Right'} deck", "help": "Its deck and FX unit.",
                     "items": [{"half": half, "kind": "deck", "value": dev.decks[i]},
                               {"half": half, "kind": "fx", "value": dev.fx_units[i]}]}
                    for i, half in enumerate(dev.halves())]
        ctx = dev.context(None)
        return ([{"label": s["label"], "items": [{"slot": i, "kind": "deck", "value": ctx[s["key"]]}]}
                 for i, s in enumerate(dev.deck_slots())] +
                [{"label": s["label"], "items": [{"slot": i, "kind": "fx", "value": ctx[s["key"]]}]}
                 for i, s in enumerate(dev.fx_slots())])

    def view(self):
        """What every control does right now, per device and half: deck, FX unit, page, held modifiers, and per
        control its label on the current layer (and with Shift), LED, knob position and pickup."""
        return {"devices": [self._device_view(dev) for dev in self.devices.values()]}

    def _device_view(self, dev):
        profile = self.profile(dev)
        led_names = set(dev.device.led_controls())
        out = {"position": dev.position, "name": dev.name or dev.position, "type": dev.device.type_name,
               "shift_latched": dev.shift_latched,
               "midi_test": dev.position in self.test_positions,
               # The X1's Shift sends nothing alone, but a press made with it arrives shifted: Shift is down then.
               "shift_held": any(v["shift"] for (p, _), v in self.down.items() if p == dev.position),
               "type_name": getattr(dev.device, "display_name", dev.device.type_name),
               "mapping": profile.title or dev.profile or dev.device.type_name,
               "profile": dev.profile or dev.device.type_name,
               "decks": list(dev.decks), "fx_units": list(dev.fx_units), "reassignable": profile.reassignable,
               "assign": self._assign_rows(dev),
               "pages": self.pages(dev) if profile.pages else [],
               "all_pages": self.pages(dev, enabled_only=False) if profile.pages else [],
               "builtin_pages": list(profile.pages), "custom_pages": user_actions.page_ids(dev.mapping),
               "page_names": self.page_names(dev)[0], "page_short": self.page_names(dev)[1],
               "edit_layers": [list(x) for x in self.edit_layers(dev)],
               "mine_count": len(dev.mapping["bindings"]),
               "page_bindings": {p: sum(e.get("page") == p for e in dev.mapping["bindings"])
                                 for p in user_actions.page_ids(dev.mapping)},
               "kinds": self.control_kinds(dev),
               "options": dict(dev.options),
               "option_choices": {k: list(v) for k, v in profile.option_choices.items()},
               "option_info": {k: {"title": t, "values": [[v, vl.get(v, str(v))] for v in profile.option_choices[k]],
                                   "help": h, "when": OPTION_WHEN.get(k)}
                               for k, (t, vl, h) in OPTION_INFO.items() if k in profile.option_choices},
               "halves": []}
        for half in dev.halves():
            ctx = dev.context(half)
            mods = self.modifiers.get((dev.position, half), {})
            layer = "+".join(sorted(mods)) if mods else None
            h = {"half": half, "deck": ctx.get("deck"), "fx": ctx["fx"],
                 "decks": None if half else [ctx[s["key"]] for s in dev.deck_slots()],
                 "slots": [{"key": s["key"], "label": s["label"], "deck": ctx[s["key"]]} for s in dev.deck_slots()],
                 "modes": dict(dev.modes.get(half, {})),
                 "tags": self.tags(dev, half), "held": sorted(mods),
                 "layer": profile.modifier_names.get(layer, layer) if layer else None, "controls": {},
                 "rows": list(profile.row_titles.get(dev.modes.get(half, {}).get("page"), []))}
            for name, kind in dev.device.controls():
                if half and not name.startswith(f"{half}."):
                    continue
                base = name.split(".", 1)[1] if half else name
                h["controls"][base] = self._control_view(dev, profile, half, base, name, kind, ctx, mods, led_names)
            out["halves"].append(h)
        return out

    def _control_view(self, dev, profile, half, base, name, kind, ctx, mods, led_names):
        c = {"kind": kind, "down": (dev.position, name) in self.down,
             "mine": any(e.get("control") == name for e in dev.mapping["bindings"])}
        behaviour, layer = self._resolve(profile, dev, half, base, Event(dev.position, name, kind, 0, False), mods)
        if behaviour is not None:
            c["label"], c["detail"] = describe(behaviour, self, ctx, profile.modifier_names)
            c["short"] = short(behaviour, self, ctx)
            c["layer"] = layer
            c["disabled"] = c["label"] == "—"
        supports_shift = getattr(dev.device, "supports_shift", None)
        if getattr(dev.device, "has_shift", False) or callable(supports_shift) and supports_shift(name):
            shifted, shift_layer = self._resolve(profile, dev, half, base, Event(dev.position, name, kind, 0, True), mods)
            if shifted is not None and shifted is not behaviour:
                label = describe(shifted, self, ctx, profile.modifier_names)[0]
                if label != "—":                # Shift does nothing there: say nothing
                    c["shift"] = label
                    c["shift_short"] = short(shifted, self, ctx)
        if profile.alt_layer and profile.alt_layer not in mods:
            alt, _ = self._resolve(profile, dev, half, base, Event(dev.position, name, kind, 0, False),
                                   {profile.alt_layer: None})
            if alt is not None and alt is not behaviour:
                c["alt"] = short(alt, self, ctx) or describe(alt, self, ctx, profile.modifier_names)[0]
        if name in led_names:
            c["led"] = self.led_value(dev, half, base)
            ref = self._led_source(dev, half, base)
            if ref and c["led"] is not None and ref.resolve(dev.context(half)) in self.blinking:
                c["led"] = "blink"
        state = self.knob_state.get((dev.position, name))
        if state:
            c["value"] = state[2]
        if dev.position in self.test_positions and (dev.position, name) in self.test_values:
            c["value"] = self.test_values[(dev.position, name)]
        target = self._knob_target(behaviour, ctx)
        if target:
            c["default"] = knob_default(target[0])
            c["sent"] = self.knob_sent.get(target)       # what Rekordbox has (from the knob or the window)
        if target and state and dev.options.get("knob_pickup", False):
            last = self.knob_sent.get(target)
            picked = state[1] if state[0] == target else (last is None or abs(state[2] - last) <= PICKUP_WINDOW)
            if not picked and last is not None:
                c["pickup"] = last
        return {k: v for k, v in c.items() if v is not None and v is not False}    # smaller to send

    @staticmethod
    def _knob_target(behaviour, ctx):
        if isinstance(behaviour, Knob):
            return behaviour.ref.resolve(ctx)
        if isinstance(behaviour, CfxKnob):
            return CfxGroup.ref(behaviour.key).resolve(ctx)
        return None

    # --- LEDs -----------------------------------------------------------------------------------------
    def _led_tags(self, dev, half):
        """Held modifiers (the combination first) count as LED tags, so e.g. holding FX Assign 1 can show stem
        mutes on the FX buttons; then the half's mode/option tags."""
        mods = list(self.modifiers.get((dev.position, half), {}))
        return (["+".join(sorted(mods))] if len(mods) > 1 else []) + mods + self.tags(dev, half)

    def _led_source(self, dev, half, control):
        profile = self.profile(dev)
        leds = self.dev_leds[dev.position]
        names = ([f"{half}.{control}"] if half else []) + [control]    # your own per-half LEDs first
        for tag in self._led_tags(dev, half):
            for name in names:
                if f"{name}@{tag}" in leds:
                    return leds[f"{name}@{tag}"]
        for name in names:
            if name in leds:
                return leds[name]
        return None

    def _rebuild_led_sources(self):
        self.led_sources = {}                 # (function, deck) -> [(position, half, control)]
        for dev in self.devices.values():
            for half in dev.halves():
                ctx = dev.context(half)
                for control in self._base_controls(dev, half):
                    ref = self._led_source(dev, half, control)
                    if ref:
                        self.led_sources.setdefault(ref.resolve(ctx), []).append((dev.position, half, control))

    @staticmethod
    def _base_controls(dev, half):
        prefix = f"{half}." if half else ""
        return [c[len(prefix):] for c in dev.device.led_controls() if c.startswith(prefix)]

    def led_value(self, dev, half, control):
        profile = self.profile(dev)
        for tag in self._led_tags(dev, half):
            override = profile.mode_leds.get(tag, {}).get(control)
            if override is not None:
                return override(self, dev, half) if callable(override) else override
        ref = self._led_source(dev, half, control)
        value = self.state.get(ref.resolve(dev.context(half)), 0) if ref else 0
        return profile.led_colour(dev, half, control, value) if profile.led_colour else value

    def refresh_leds(self, position):
        self._rebuild_led_sources()           # held modifiers and modes change what each LED follows
        dev = self.devices[position]
        for half in dev.halves():
            for control in self._base_controls(dev, half):
                self.leds.set(position, f"{half}.{control}" if half else control, self.led_value(dev, half, control))

    # --- feedback -------------------------------------------------------------------------------------
    def feedback(self, status, d1, d2):
        decoded = self.bridge.decode(status, d1, d2)
        if not decoded:
            return
        function, deck, value = decoded
        key = (function, deck)
        previous = self.state.get(key)
        was_blinking = key in self.blinking
        if value != previous:
            self.blink_times.setdefault(key, deque(maxlen=BLINK_CHANGES + 1)).append(self.clock())
        blinking = self._is_blinking(key)
        (self.blinking.add if blinking else self.blinking.discard)(key)
        # A steady blink (Rekordbox's paused Cue/Play) changes nothing on screen; only its start and end do.
        if (key in self.led_sources and not (blinking and was_blinking)) or function == "LoadedIndicator":
            self.view_version += 1
        self._event("feedback", f"<- {function} {f'deck {deck} ' if deck else ''}= {value}", show=False,
                    function=function, deck=deck, value=value, raw=[status, d1, d2], blink=blinking)
        self.state.set((function, deck), value, OBSERVED)
        if function == "LoadedIndicator" and value != previous:
            self.state.clear_commanded(deck)
        for position, half, control in self.led_sources.get((function, deck), ()):
            dev = self.devices[position]
            self.leds.set(position, f"{half}.{control}" if half else control, self.led_value(dev, half, control))

    # --- lifecycle ------------------------------------------------------------------------------------
    def start(self):
        """Neutralise: release every bridge button and clear LEDs; feedback then rebuilds the real state."""
        self.bridge.release_all()
        for position in self.devices:
            self.leds.all_off(position)
            self.refresh_leds(position)

    def stop(self):
        self.stopping = True                    # sequences drop their remaining steps
        while self.timers:                      # finish delayed actions (e.g. a loop exit) before releasing
            heapq.heappop(self.timers)[2]()
        for group in self.shared.values():      # e.g. put back a Part FX selection a held pad changed
            if hasattr(group, "shutdown"):
                group.shutdown(self)
        self.bridge.release_all()
        self.held.clear()
        self.down.clear()
        self.modifiers.clear()
        for position in self.devices:
            self.leds.all_off(position)
        self.leds.flush()

    def later(self, delay, fn):
        """Run fn() after `delay` seconds (from tick)."""
        self._seq += 1
        heapq.heappush(self.timers, (self.clock() + delay, self._seq, fn))

    # Sequence steps still waiting run only while nothing they depend on has changed: they're cancelled when their
    # half's deck, FX unit or page changes, the controller's mapping changes, Bypass turns on or the translator stops.
    def run_token(self, ctx):
        key = (ctx.get("_pos"), ctx.get("_half"))
        return key, self.runs.get(key, 0)

    def still_on(self, token):
        key, n = token
        return not self.stopping and self.runs.get(key, 0) == n

    def cancel_waiting(self, position=None, half=None):
        """One half, a whole controller (half None) or everything (position None)."""
        for dev in self.devices.values():
            if position is not None and dev.position != position:
                continue
            for h in dev.halves():
                if half is None or h == half:
                    self.runs[(dev.position, h)] = self.runs.get((dev.position, h), 0) + 1

    def _is_blinking(self, key):
        times = self.blink_times.get(key)
        now = self.clock()
        return bool(times and len(times) >= BLINK_CHANGES and times[-1] - times[-BLINK_CHANGES] <= BLINK_SPAN
                    and now - times[-1] <= BLINK_GONE)

    def tick(self):
        while self.timers and self.timers[0][0] <= self.clock():
            heapq.heappop(self.timers)[2]()
        for key in [k for k in self.blinking if not self._is_blinking(k)]:     # stopped blinking: show its state
            self.blinking.discard(key)
            self.view_version += 1
        self.leds.tick()
