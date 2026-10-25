"""X1 MK3 "Performance Mod" profile: the X1MK3 Community Performance Mod v14 (Sûlherokhh and contributors,
NI forum) re-created for Rekordbox in MIDI mode, as closely as Rekordbox's functions allow. Anything Rekordbox can't
do is bound to Disabled with the reason.

MIDI-mode substitutes for what the X1 can't send in MIDI mode (Shift on its own and Mode send nothing):
  Shift + FX Assign 1 / 2  previous / next FX-section page   (mod: Mode cycles overlays)
  Shift + FX button 4      Browser Mode on/off                (mod: tap Shift)
  hold FX Assign 1 + 2     setup for that half                (mod: hold Mode)

FX section pages (the 4 knobs and 4 buttons under FX Assign; each X1 half has its own page). The FX buttons light
with each page's colour (PAGE_COLOURS):
  Mixer        knobs: EQ high, mid, low, volume (Shift + knob 4 = gain); button 4 = headphone cue
  Stems        knobs: Drums, Vocal, Inst level, filter; buttons: stem mutes, filter on/off; Shift + 1-3 = Part FX
  FX (default) knobs: Beat FX slot 1-3 level, beat; buttons: slot 1-3 on, next effect; Shift + 1-3 = next effect
  SFX          knob 1: SFX amount; buttons 1-3: SFX slot on (Shift = next effect); button 4: engage on/off
  CFX multi    knobs: Colour FX on decks 1-4; buttons: Colour FX on/off per deck
  CFX single   knobs: this deck's Colour FX, PARAM, type (6 zones); buttons: on/off, next type
  Colour FX on/off is emulated (Rekordbox has none over MIDI): off = centre, on = the knob's value.

FX assign follows Rekordbox's model (2 Beat FX units, each on/off per deck, Sampler and Master), not Traktor's
4 units: FX Assign 1/2 = FX1/FX2 on this half's deck. (Master is greyed out in Rekordbox's external-mixer mode.)

Hot cues: Hotcue 1-4 = A-D, Sync + Hotcue 1-4 = E-H; Shift deletes (Sync + Shift for E-H). (The mod reaches 5-8
through its setup menu, which sets what hot cue buttons 1-2 / 3-4 do; REV stays reverse.)
Memory cues: Sync + CUE sets one, Sync + REV deletes the one at the playhead (the mod's set / delete grid marker;
Rekordbox's grid editing has no MIDI control).

Encoders, as the mod's two encoder modes (X1MK3Deck.qml: legacyEncoderActive / customBrowserModeActive):
  Stock X1 (the mod's default): Browse turn = list, push = load (hold 1 s = Instant Doubles), Shift + turn = folder
    tree, Shift + push = open / close the folder. Loop turn = loop size, push = loop on/off, Shift + turn = move
    the loop if one is active, otherwise beat jump (beatjump_size), Shift + push = reloop / exit; or, with the
    mod's "Shift + Loop" setting on key, Shift + turn = key, Shift + push = key lock.
  Performance Mod: Browse turn = beat jump by beatjump_size (moves an active loop), push = loop on/off, Shift +
    turn = 1-beat jump, Shift + push = loopback. Loop as stock, but Shift + Loop is always key.
  Both: Browse held + turn = 16-beat jumps (an addition).

Setup (hold both FX Assign buttons on a half; LEDs show the current settings):
  Hotcue 1-4      this half controls deck 1-4
  FX button 1/2   this half uses Beat FX / SFX unit 1/2
  PLAY            vinyl brake on PLAY hold                 on/off (default on, as in the mod)
  SYNC            encoders: stock X1 / Performance Mod     off = stock
  CUE             Shift + Loop (stock encoders): beat jump / key   off = beat jump
  Browse turn     beat jump size: 1 (beat-jump pads), 4, 8, 16 (shown in the window)
  Loop turn       large tempo step: 2, 4, 10 Rekordbox steps (0.5% each) per click (shown in the window)

Tempo: Sync hold + Loop turn = fine (0.5%, Rekordbox's smallest relative step in every range);
Sync hold + Loop pushed + turn = large (2%); Sync hold + Loop tap = tempo reset. Relative steps never jump.
"""
from rekordtrakt.engine.behaviours import (PART_STEMS, BeatJump, BrowseList, BrowseTree, Button, CfxKnob, CfxNextType,
                                           CfxToggle, CfxTypeKnob, Disabled, HoldOrTap, Knob, Latch, ModifierTap,
                                           PartFxHold, PlayBrake, Ref, Rotary, SetupDeck, SetupFx, SetupOption, Split,
                                           Tempo, ToggleMode, TreeBack, TreeOpen, cfx_on_led, latched_led)
from rekordtrakt.engine.engine import Profile

MOD_RELEASE = "X1MK3_TP4.5.1_PerformanceMod_14d (v14), default setup options"
PAGES = ("mixer", "stems", "fx", "sfx", "cfx_multi", "cfx_single")     # Shift + FX Assign 1 / 2 steps through
PAGE_NAMES = {"mixer": "Mixer", "stems": "Stems", "fx": "FX", "sfx": "SFX", "cfx_multi": "CFX multi",
              "cfx_single": "CFX single"}
# (on, off) velocity for the FX buttons on each page: the X1 shows one colour per button in MIDI mode.
PAGE_COLOURS = {page: (127, 0) for page in PAGES}
DEFAULT_OPTIONS = {"encoders": "legacy", "shift_loop": "jump", "vinyl_brake": True,
                   "beatjump_size": 4, "tempo_fine_steps": 1, "tempo_coarse_steps": 4, "pages": list(PAGES),
                   "knob_pickup": False}
OPTION_CHOICES = {"encoders": ("legacy", "mod"), "shift_loop": ("jump", "key"),
                  "vinyl_brake": (False, True), "beatjump_size": (1, 4, 8, 16), "tempo_fine_steps": (1, 2),
                  "tempo_coarse_steps": (2, 4, 10), "knob_pickup": (False, True)}
PAGE_SHORT = {"mixer": "Mix", "stems": "Stems", "fx": "FX", "sfx": "SFX", "cfx_multi": "CFX×4", "cfx_single": "CFX"}
# What each FX-section row (button + knob) is on each page, so the controls themselves can just say "On", "Level".
ROW_TITLES = {
    "fx": ["Slot 1", "Slot 2", "Slot 3", "FX"],
    "mixer": ["High", "Mid", "Low", "Channel"],
    "stems": ["Drums", "Vocal", "Inst", "Filter"],
    "sfx": ["SFX 1", "SFX 2", "SFX 3", "SFX"],
    "cfx_multi": ["Deck 1", "Deck 2", "Deck 3", "Deck 4"],
    "cfx_single": ["Colour FX", "Param", "Type", ""],
}
MODIFIER_NAMES = {"sync": "Sync layer", "loop": "large tempo steps", "browseheld": "16-beat jumps",
                  "fxa1": "FX Assign 1 layer", "fxa2": "FX Assign 2 layer", "fxa1+fxa2": "Setup",
                  "loop+sync": "Sync + Loop (large tempo steps)"}
FX_BUTTONS = tuple(f"fx_button_{n}" for n in range(1, 5))


def _tags(dev, half):
    m, o = dev.modes[half], {**DEFAULT_OPTIONS, **dev.options}
    tags = []
    if m.get("browser"):
        tags.append("browser")
    tags.append(f"p_{m.get('page', 'fx')}")     # "p_fx" too, so your own FX-page bindings have a layer
    if o["encoders"] == "mod":
        tags.append("modenc")
    if o["shift_loop"] == "key":
        tags.append("shiftkey")
    if o["vinyl_brake"]:
        tags.append("brake")
    return tags


def _led_colour(dev, half, control, value):
    """FX buttons show their state in the current page's colour."""
    if control not in FX_BUTTONS:
        return value
    on, off = PAGE_COLOURS.get(dev.modes[half].get("page", "fx"), (127, 0))     # your own pages: plain
    return on if value else off


def _option_led(name, on_value=True):
    return lambda eng, dev, half: 127 if {**DEFAULT_OPTIONS, **dev.options}[name] == on_value else 0


def _bindings():
    b = {
        # --- transport (stock X1 MK3 + mod) ---------------------------------------------------------------
        ("base", "play"): Button("PlayPause", "deck"),
        ("base@brake", "play"): PlayBrake(),                                  # mod: vinyl break on PLAY hold
        ("base", "cue"): Button("Cue", "deck"),
        ("base", "sync"): ModifierTap("sync", "Sync", "deck", max_tap=0.3),   # tap = Sync, hold = Sync layer
        ("base", "rev"): Button("DirectionSlipRev", "deck"),                  # stock and mod: REV held = Flux reverse
        ("base", "nudge_left"): Button("PitchBendDown", "deck"),
        ("base", "nudge_right"): Button("PitchBendUp", "deck"),
        ("shift", "play"): Disabled("gridlock: Rekordbox has no grid lock control"),
        ("shift", "cue"): Button("JumpToTrackStart", "deck"),                 # stock: Shift + CUE = back to start
        ("shift", "sync"): Button("MasterTempo", "deck"),                     # key lock (mod: master; Rekordbox picks it)
        ("shift", "rev"): Button("Slip", "deck"),                             # stock: Shift + REV = Flux on/off
        ("shift", "nudge_left"): Button("Jump4Prev", "deck"),
        ("shift", "nudge_right"): Button("Jump4Fwd", "deck"),

        # --- Sync held: tempo, beat grid, hot cues E-H ----------------------------------------------------
        ("sync", "loop"): Tempo(fine=True),                                   # 0.5%
        ("sync", "loop_push"): ModifierTap("loop", "TempoReset", "deck"),     # tap = reset, hold = large steps
        ("loop+sync", "loop"): Tempo(fine=False),                             # 2%
        ("sync", "play"): Button("TapBpm", "deck"),                           # mod: beat tap
        ("sync", "cue"): Button("Memory", "deck"),                            # mod: set grid marker
        ("sync", "rev"): Button("Delete", "deck"),                            # mod: delete grid marker
        # Sync + nudge falls through to the base nudge, as in the mod.

        # --- encoders: stock X1 (default) -----------------------------------------------------------------
        ("base", "browse"): BrowseList(),
        ("base", "browse_push"): ModifierTap("browseheld", "ForwardAndLoad", "deck",   # tap = load,
                                             long_function="InstDoubles", long_after=1.0),  # hold 1 s = doubles
        ("browseheld", "browse"): Split("Jump16Fwd", "Jump16Prev", "deck"),   # held + turn = 16-beat jumps
        ("shift", "browse"): BrowseTree(),
        ("shift", "browse_push"): TreeOpen(),
        ("base", "loop"): Rotary("LoopHalfDouble", "deck"),
        ("base", "loop_push"): Button("AutoLoop", "deck"),
        ("shift", "loop"): BeatJump(),                                        # move loop, or beat jump
        ("shift", "loop_push"): Button("ActiveLoop", "deck"),
        ("shift@shiftkey", "loop"): Split("SemitoneUp", "SemitoneDown", "deck"),
        ("shift@shiftkey", "loop_push"): Button("MasterTempo", "deck"),      # key lock

        # --- encoders: mod style (option) -----------------------------------------------------------------
        ("base@modenc", "browse"): BeatJump(),                                # Move by beatjump_size
        ("shift@modenc", "browse"): BeatJump(size=1),                         # Move 1 beat
        ("base@modenc", "browse_push"): Button("ReloopExit", "deck"),         # loop active on/off
        ("shift@modenc", "browse_push"): Button("ActiveLoop", "deck"),        # loopback (approximation)
        ("shift@modenc", "loop"): Split("SemitoneUp", "SemitoneDown", "deck"),   # mod: key_control.coarse
        ("shift@modenc", "loop_push"): Button("MasterTempo", "deck"),        # key lock

        # --- Browser Mode (Shift + FX button 4) -----------------------------------------------------------
        ("base@browser", "browse"): BrowseList(),
        ("shift@browser", "browse"): BrowseList(page=10),
        ("base@browser", "browse_push"): HoldOrTap(Ref("ForwardAndLoad", "deck"), Ref("InstDoubles", "deck")),
        ("shift@browser", "browse_push"): TreeBack(),
        ("base@browser", "L.loop"): BrowseTree(),
        ("shift@browser", "L.loop"): BrowseTree(page=10),
        ("base@browser", "L.loop_push"): TreeOpen(),
        ("base@browser", "R.loop"): BrowseList(page=10),                     # mod: preview seek (not in Rekordbox)
        ("base@browser", "R.loop_push"): Button("AddToTagList"),              # mod: preview load / prep list
        ("shift@browser", "R.loop"): Disabled("favourites: no Rekordbox equivalent over MIDI"),

        # --- FX Assign: assign (tap), pages (Shift), setup (hold both) ------------------------------------
        ("base", "fx_assign_1"): ModifierTap("fxa1", "FX1Assign{deck}"),      # tap = FX1 on this deck
        ("base", "fx_assign_2"): ModifierTap("fxa2", "FX2Assign{deck}"),
        ("shift", "fx_assign_1"): ToggleMode("page", PAGES, step=-1, values_option="pages"),   # previous page
        ("shift", "fx_assign_2"): ToggleMode("page", PAGES, step=1, values_option="pages"),    # next page
        ("shift", "fx_button_4"): ToggleMode("browser"),                     # mod: tap Shift

        # --- page: FX (default, "base") -------------------------------------------------------------------
        ("base", "fx_knob_4"): Knob("FX{fx}BeatUpDown"),
        ("base", "fx_button_4"): Button("FX{fx}-1Select"),

        # --- page: Mixer (Rekordbox's internal mixer) -----------------------------------------------------
        ("base@p_mixer", "fx_knob_1"): Knob("EQHigh", "deck"),
        ("base@p_mixer", "fx_knob_2"): Knob("EQMid", "deck"),
        ("base@p_mixer", "fx_knob_3"): Knob("EQLow", "deck"),
        ("base@p_mixer", "fx_knob_4"): Knob("ChannelFader", "deck"),
        ("shift@p_mixer", "fx_knob_4"): Knob("Gain", "deck"),
        ("base@p_mixer", "fx_button_4"): Button("HeadphoneCue", "deck"),

        # --- page: Stems ----------------------------------------------------------------------------------
        ("base@p_stems", "fx_knob_4"): CfxKnob("deck"),                       # filter (Colour FX)
        ("base@p_stems", "fx_button_4"): CfxToggle("deck"),                   # filter on/off

        # --- page: SFX (this half's unit) -----------------------------------------------------------------
        ("base@p_sfx", "fx_knob_1"): Knob("SFX{fx}-Slider", hires=True),
        ("base@p_sfx", "fx_button_4"): Latch("SFX{fx}-Touch"),                # engage on/off (as touching the XP1 strip)

        # --- page: Colour FX single (this deck) -----------------------------------------------------------
        ("base@p_cfx_single", "fx_knob_1"): CfxKnob("deck"),
        ("base@p_cfx_single", "fx_knob_2"): Knob("CFXSubParameter"),         # PARAM
        ("base@p_cfx_single", "fx_knob_3"): CfxTypeKnob(),                    # type, by position (6 zones)
        ("base@p_cfx_single", "fx_knob_4"): Disabled("nothing on this page"),
        ("base@p_cfx_single", "fx_button_1"): CfxToggle("deck"),              # on/off
        ("base@p_cfx_single", "fx_button_2"): CfxNextType(),                  # next type
        ("base@p_cfx_single", "fx_button_3"): Disabled("nothing on this page"),
        ("base@p_cfx_single", "fx_button_4"): Disabled("nothing on this page"),
    }
    unused = "nothing on this page"
    for n in range(1, 5):
        b[("base", f"hotcue_{n}")] = Button(f"PAD{{hc{n}}}_HotCue", "deck")
        b[("shift", f"hotcue_{n}")] = Button(f"PAD{{hc{n}}}_HotCue+Shift", "deck")
        b[("sync", f"hotcue_{n}")] = Button(f"PAD{n + 4}_HotCue", "deck")              # E-H
        b[("sync/shift", f"hotcue_{n}")] = Button(f"PAD{n + 4}_HotCue+Shift", "deck")
        b[("base@browser", f"hotcue_{n}")] = Button("ForwardAndLoad", f"d{n}")   # mod: instant-double picker
        b[("fxa1+fxa2", f"hotcue_{n}")] = SetupDeck(n)
        # Colour FX multi: knob n / button n = channel n
        b[("base@p_cfx_multi", f"fx_knob_{n}")] = CfxKnob(f"d{n}")
        b[("base@p_cfx_multi", f"fx_button_{n}")] = CfxToggle(f"d{n}")
    for n in range(1, 4):
        stem = PART_STEMS[n - 1]
        b[("base", f"fx_knob_{n}")] = Knob(f"FX{{fx}}-{n}")
        b[("base", f"fx_button_{n}")] = Button(f"FX{{fx}}-{n}On")
        b[("shift", f"fx_button_{n}")] = Button(f"FX{{fx}}-{n}Select")
        b[("base@p_mixer", f"fx_button_{n}")] = Disabled("EQ kill: Rekordbox has no EQ kill control")
        b[("base@p_stems", f"fx_knob_{n}")] = Knob(f"PartIsolator{stem}", "deck", hires=True)
        b[("base@p_stems", f"fx_button_{n}")] = Button(f"ActivePart{stem}", "deck")   # mute
        b[("shift@p_stems", f"fx_button_{n}")] = PartFxHold(stem)                     # mod: FX send
        b[("base@p_sfx", f"fx_button_{n}")] = Button(f"SFX{{fx}}-{n}On")
        b[("shift@p_sfx", f"fx_button_{n}")] = Button(f"SFX{{fx}}-{n}Select")
    for n in (2, 3, 4):
        b[("base@p_sfx", f"fx_knob_{n}")] = Disabled(unused)
    b.update({
        ("fxa1+fxa2", "fx_button_1"): SetupFx(1),
        ("fxa1+fxa2", "fx_button_2"): SetupFx(2),
        ("fxa1+fxa2", "play"): SetupOption("vinyl_brake", (False, True)),
        ("fxa1+fxa2", "sync"): SetupOption("encoders", ("legacy", "mod")),
        ("fxa1+fxa2", "cue"): SetupOption("shift_loop", ("jump", "key")),
        ("fxa1+fxa2", "browse"): SetupOption("beatjump_size", (1, 4, 8, 16)),
        ("fxa1+fxa2", "loop"): SetupOption("tempo_coarse_steps", (2, 4, 10)),
    })
    return b


def _leds():
    leds = {
        "play": Ref("PlayPause", "deck"), "cue": Ref("Cue", "deck"), "sync": Ref("Sync", "deck"),
        "rev": Ref("Reverse", "deck"), "loop_push": Ref("GetLoopActive", "deck"),
        "fx_assign_1": Ref("FX1Assign{deck}"), "fx_assign_2": Ref("FX2Assign{deck}"),
        "fx_button_4@p_mixer": Ref("HeadphoneCue", "deck"),
    }
    for n in range(1, 5):
        leds[f"hotcue_{n}"] = Ref(f"PAD{{hc{n}}}_HotCue", "deck")
        leds[f"hotcue_{n}@sync"] = Ref(f"PAD{n + 4}_HotCue", "deck")     # while Sync is held: E-H
    for n in range(1, 4):
        leds[f"fx_button_{n}"] = Ref(f"FX{{fx}}-{n}On")
        leds[f"fx_button_{n}@p_stems"] = Ref(f"ActivePart{PART_STEMS[n - 1]}", "deck")
        leds[f"fx_button_{n}@p_sfx"] = Ref(f"SFX{{fx}}-{n}On")
    return leds


def _mode_leds():
    def deck_is(n):
        return lambda eng, dev, half: 127 if dev.decks[("L", "R").index(half)] == n else 0

    def fx_is(n):
        return lambda eng, dev, half: 127 if dev.fx_units[("L", "R").index(half)] == n else 0

    def page_colour_off(eng, dev, half):     # FX buttons with no state still show the page colour
        return PAGE_COLOURS.get(dev.modes[half].get("page", "fx"), (127, 0))[1]

    setup = {f"hotcue_{n}": deck_is(n) for n in range(1, 5)}
    setup.update({
        "fx_button_1": fx_is(1), "fx_button_2": fx_is(2), "fx_button_3": 0, "fx_button_4": 0,
        "rev": 0, "play": _option_led("vinyl_brake"),
        "sync": _option_led("encoders", "mod"), "cue": _option_led("shift_loop", "key"),
        "fx_assign_1": 127, "fx_assign_2": 127, "nudge_left": 0, "nudge_right": 0,
        "loop_push": 0,
    })
    return {
        "fxa1+fxa2": setup,
        "browser": {"loop_push": 127},                                       # Browser Mode indicator
        "p_mixer": {f"fx_button_{n}": page_colour_off for n in (1, 2, 3)},
        "p_stems": {"fx_button_4": cfx_on_led("deck")},
        "p_sfx": {"fx_button_4": latched_led("SFX{fx}-Touch")},
        "p_cfx_multi": {f"fx_button_{n}": cfx_on_led(f"d{n}") for n in range(1, 5)},
        "p_cfx_single": {"fx_button_1": cfx_on_led("deck"), "fx_button_2": page_colour_off,
                         "fx_button_3": page_colour_off, "fx_button_4": page_colour_off},
    }


PROFILE = Profile("x1mk3", _bindings(), _leds(), _mode_leds(), tags=_tags, reassignable=True,
                  default_modes={"browser": False, "page": "fx"}, default_options=DEFAULT_OPTIONS,
                  led_colour=_led_colour, pages=PAGES, page_names=PAGE_NAMES, option_choices=OPTION_CHOICES,
                  modifier_names=MODIFIER_NAMES, title="X1 MK3 default (based on the Performance Mod)",
                  row_titles=ROW_TITLES, page_short=PAGE_SHORT, alt_layer="sync",
                  # FX Assign 1 + 2 together is setup, never an FX assign, even when just tapped
                  combo_taps={frozenset({"fxa1", "fxa2"}): None},
                  page_controls=tuple(f"fx_{k}_{n}" for k in ("button", "knob") for n in range(1, 5)),
                  edit_layers=(("base", "Normal"), ("shift", "Shift"), ("sync", "Sync held"),
                               ("sync/shift", "Sync held + Shift")))
