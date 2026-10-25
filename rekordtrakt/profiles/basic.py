"""The basic presets: the X1 MK3's stock layout (with Sync tap/hold and a Sync-held tempo layer) and the F1 as a
stem controller for two decks.

Contexts: an X1 half has {deck, fx}; an F1 has {a, b, fx} (its first and second deck).
"""
from rekordtrakt.engine.behaviours import (PART_STEMS, BrowseTree, Button, CfxKnob, Knob, LoopJump, ModifierTap,
                                           PartFxHold, Ref, Rotary, Tempo)
from rekordtrakt.engine.engine import Profile

STEMS = PART_STEMS                     # F1 columns 1-3, left to right: Drums, Vocal, Inst


def _x1():
    b = {
        ("base", "play"): Button("PlayPause", "deck"),
        ("base", "cue"): Button("Cue", "deck"),
        ("base", "sync"): ModifierTap("sync", "Sync", "deck", max_tap=0.3),   # tap = Sync, hold = Sync layer
        ("base", "rev"): Button("Reverse", "deck"),
        ("base", "nudge_left"): Button("PitchBendDown", "deck"),
        ("base", "nudge_right"): Button("PitchBendUp", "deck"),
        ("base", "browse"): Rotary("Browse"),
        ("base", "browse_push"): Button("ForwardAndLoad", "deck"),
        ("base", "loop"): Rotary("LoopHalfDouble", "deck"),
        ("base", "loop_push"): Button("AutoLoop", "deck"),
        ("base", "fx_knob_4"): Knob("FX{fx}BeatUpDown"),
        ("base", "fx_button_4"): Button("FX{fx}-1Select"),
        ("base", "fx_assign_1"): Button("FX1Assign{deck}"),
        ("base", "fx_assign_2"): Button("FX2Assign{deck}"),

        ("shift", "cue"): Button("JumpToTrackStart", "deck"),
        ("shift", "sync"): Button("Slip", "deck"),
        ("shift", "rev"): Button("DirectionSlipRev", "deck"),
        ("shift", "nudge_left"): Button("Jump4Prev", "deck"),
        ("shift", "nudge_right"): Button("Jump4Fwd", "deck"),
        ("shift", "browse"): BrowseTree(),                                  # the folder tree
        ("shift", "browse_push"): Button("Back"),
        ("shift", "loop"): LoopJump("deck"),                                # jump by the current loop length
        ("shift", "loop_push"): Button("ActiveLoop", "deck"),

        ("sync", "loop"): Tempo(fine=True),                                 # 0.5% per click
        ("sync", "loop_push"): Button("TempoReset", "deck"),
        ("sync", "play"): Button("TapBpm", "deck"),
        # Sync + nudge falls through to the base nudge, as in the Performance Mod.
    }
    for n in range(1, 5):
        b[("base", f"hotcue_{n}")] = Button(f"PAD{n}_HotCue", "deck")
        b[("shift", f"hotcue_{n}")] = Button(f"PAD{n}_HotCue+Shift", "deck")
    for n in range(1, 4):
        b[("base", f"fx_knob_{n}")] = Knob(f"FX{{fx}}-{n}")
        b[("base", f"fx_button_{n}")] = Button(f"FX{{fx}}-{n}On")
        b[("shift", f"fx_button_{n}")] = Button(f"FX{{fx}}-{n}Select")

    leds = {
        "play": Ref("PlayPause", "deck"), "cue": Ref("Cue", "deck"), "sync": Ref("Sync", "deck"),
        "rev": Ref("Reverse", "deck"), "loop_push": Ref("GetLoopActive", "deck"),
        "fx_assign_1": Ref("FX1Assign{deck}"), "fx_assign_2": Ref("FX2Assign{deck}"),
    }
    leds.update({f"hotcue_{n}": Ref(f"PAD{n}_HotCue", "deck") for n in range(1, 5)})
    leds.update({f"fx_button_{n}": Ref(f"FX{{fx}}-{n}On") for n in range(1, 4)})
    return Profile("x1mk3", b, leds, title="X1 MK3 basic", default_options={"knob_pickup": False},
                   option_choices={"knob_pickup": (False, True)}, alt_layer="sync")


def _f1():
    b, leds = {}, {}
    for i, stem in enumerate(STEMS):
        col = i + 1
        b[("base", f"knob_{col}")] = Knob(f"PartIsolator{stem}", "a", hires=True)
        b[("base", f"fader_{col}")] = Knob(f"PartIsolator{stem}", "b", hires=True)
        b[("base", f"pad_{col}")] = Button(f"ActivePart{stem}", "a")          # row 1: first deck
        b[("base", f"pad_{col + 4}")] = Button(f"ActivePart{stem}", "b")      # row 2: second deck
        b[("base", f"pad_{col + 8}")] = PartFxHold(stem)                      # row 3: Part FX while held, then restore
        leds[f"pad_{col}"] = Ref(f"ActivePart{stem}", "a")
        leds[f"pad_{col + 4}"] = Ref(f"ActivePart{stem}", "b")
        leds[f"pad_{col + 8}"] = Ref(f"FXPartSelect{stem}")
    b[("base", "knob_4")] = CfxKnob("a")       # Colour FX, shared with the X1's on/off emulation
    b[("base", "fader_4")] = CfxKnob("b")
    b[("base", "pad_4")] = Button("CFXParameterCH{a}Center")
    b[("base", "pad_8")] = Button("CFXParameterCH{b}Center")
    b[("base", "encoder")] = Rotary("Browse")
    b[("base", "quant")] = Button("Quantize", "a")
    leds["quant"] = Ref("Quantize", "a")
    return Profile("f1", b, leds, title="F1 stems", default_options={"knob_pickup": False},
                   option_choices={"knob_pickup": (False, True)})


PROFILES = {"x1mk3": _x1(), "f1": _f1()}
