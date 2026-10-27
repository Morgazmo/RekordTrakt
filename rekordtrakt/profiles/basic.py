"""The basic presets: the X1 MK3's stock layout (with Sync tap/hold and a Sync-held tempo layer) and the F1 as a
stem controller for two decks.

Contexts: an X1 half has {deck, fx}; an F1 has {a, b, fx} (its first and second deck).
"""
from rekordtrakt.engine.behaviours import (PART_STEMS, BrowseTree, Button, CfxKnob, Disabled, Knob, LoopJump,
                                           ModifierTap, PartFxHold, Ref, Rotary, Sequence, Split, Tempo)
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
                   option_choices={"knob_pickup": (False, True)},
                   edit_layers=(("base", "MIDI base page"), ("shift", "MIDI Shift page")))


def _x1mk1():
    """Stock-style Rekordbox mapping for NI's original two-deck X1."""
    b = {
        ("base", "play"): Button("PlayPause", "deck"),
        ("base", "cue"): Button("Cue", "deck"),
        ("base", "cup"): Sequence([(0, Button("Cue", "deck")), (0, Button("PlayPause", "deck"))]),
        ("base", "sync"): Button("Sync", "deck"),
        ("base", "beat_left"): Button("PitchBendDown", "deck"),
        ("base", "beat_right"): Button("PitchBendUp", "deck"),
        ("base", "browse"): Rotary("Browse"),
        ("base", "browse_push"): Button("ForwardAndLoad", "deck"),
        ("base", "loop"): Rotary("LoopHalfDouble", "deck"),
        ("base", "loop_push"): Button("AutoLoop", "deck"),
        ("base", "loop_in"): Button("LoopIn", "deck"),
        ("base", "loop_out"): Button("LoopOut", "deck"),
        ("base", "fx_knob_1"): Knob("FX{fx}BeatUpDown"),
        ("base", "fx_button_1"): Button("FX{fx}FXMode"),
        ("base", "fx_assign_1"): Button("FX1Assign{deck}"),
        ("base", "fx_assign_2"): Button("FX2Assign{deck}"),
        ("shift", "cue"): Button("JumpToTrackStart", "deck"),
        ("shift", "sync"): Button("Slip", "deck"),
        ("shift", "beat_left"): Button("Jump4Prev", "deck"),
        ("shift", "beat_right"): Button("Jump4Fwd", "deck"),
        ("shift", "browse"): BrowseTree(),
        ("shift", "browse_push"): Button("Back"),
        ("shift", "loop"): LoopJump("deck"),
        ("shift", "loop_push"): Button("ActiveLoop", "deck"),
        ("shift", "play"): Button("TapBpm", "deck"),
    }
    for n in range(1, 4):
        control = n + 1
        b[("base", f"fx_knob_{control}")] = Knob(f"FX{{fx}}-{n}")
        b[("base", f"fx_button_{control}")] = Button(f"FX{{fx}}-{n}On")
        b[("shift", f"fx_button_{control}")] = Button(f"FX{{fx}}-{n}Select")
    leds = {
        "play": Ref("PlayPause", "deck"), "cue": Ref("Cue", "deck"), "sync": Ref("Sync", "deck"),
        "loop_push": Ref("GetLoopActive", "deck"), "fx_assign_1": Ref("FX1Assign{deck}"),
        "fx_assign_2": Ref("FX2Assign{deck}"),
    }
    leds.update({f"fx_button_{n + 1}": Ref(f"FX{{fx}}-{n}On") for n in range(1, 4)})
    return Profile("x1mk1", b, leds, title="X1 MK1 basic", default_options={"knob_pickup": False},
                   option_choices={"knob_pickup": (False, True)}, alt_layer="shift")


def _x1mk2():
    """A useful default for the MK2 faceplate; inputs remain user/community learned."""
    b = {
        ("base", "play"): Button("PlayPause", "deck"), ("base", "cue"): Button("Cue", "deck"),
        ("base", "sync"): Button("Sync", "deck"), ("base", "flux"): Button("Slip", "deck"),
        ("base", "load"): Button("ForwardAndLoad", "deck"),
        ("base", "browse"): Rotary("Browse"), ("base", "browse_push"): Button("ForwardAndLoad", "deck"),
        ("base", "loop"): Rotary("LoopHalfDouble", "deck"),
        ("base", "loop_push"): Button("AutoLoop", "deck"),
        ("base", "touch_strip"): Disabled("learn the touch-strip message, then choose its Rekordbox action"),
        ("base", "fx_knob_4"): Knob("FX{fx}BeatUpDown"),
        ("base", "fx_button_4"): Button("FX{fx}FXMode"),
        ("base", "fx_assign_1"): Button("FX1Assign{deck}"),
        ("base", "fx_assign_2"): Button("FX2Assign{deck}"),
    }
    for n in range(1, 5):
        b[("base", f"hotcue_{n}")] = Button(f"PAD{n}_HotCue", "deck")
    for n in range(1, 4):
        b[("base", f"fx_knob_{n}")] = Knob(f"FX{{fx}}-{n}")
        b[("base", f"fx_button_{n}")] = Button(f"FX{{fx}}-{n}On")
    return Profile("x1mk2", b, title="X1 MK2 basic", default_options={"knob_pickup": False},
                   option_choices={"knob_pickup": (False, True)})


def _amx():
    b = {
        ("base", "shift"): ModifierTap("shift"),
        ("base", "browse"): Rotary("Browse"), ("base", "browse_push"): Button("Forward"),
        ("base", "crossfader"): Knob("CrossFader"),
        ("base", "load_l"): Button("ForwardAndLoad", "a"), ("base", "load_r"): Button("ForwardAndLoad", "b"),
        ("base", "sync_l"): Button("Sync", "a"), ("base", "sync_r"): Button("Sync", "b"),
        ("base", "cue_l"): Button("Cue", "a"), ("base", "cue_r"): Button("Cue", "b"),
        ("base", "play_l"): Button("PlayPause", "a"), ("base", "play_r"): Button("PlayPause", "b"),
        ("base", "pfl_l"): Button("HeadphoneCue", "a"), ("base", "pfl_r"): Button("HeadphoneCue", "b"),
        ("base", "fader_l"): Knob("ChannelFader", "a"), ("base", "fader_r"): Knob("ChannelFader", "b"),
        ("base", "eq_low_l"): Knob("EQLow", "a"), ("base", "eq_low_r"): Knob("EQLow", "b"),
        ("base", "eq_mid_l"): Knob("EQMid", "a"), ("base", "eq_mid_r"): Knob("EQMid", "b"),
        ("base", "eq_high_l"): Knob("EQHigh", "a"), ("base", "eq_high_r"): Knob("EQHigh", "b"),
        ("base", "filter_l"): CfxKnob("a"), ("base", "filter_r"): CfxKnob("b"),
        ("base", "gain_l"): Disabled("AMX gain is relative, but Rekordbox trim is absolute"),
        ("base", "gain_r"): Disabled("AMX gain is relative, but Rekordbox trim is absolute"),
        ("base", "panel"): Disabled("no stable Rekordbox panel address is registered"),
        ("base", "search_l"): Disabled("Serato search mode has no direct Rekordbox equivalent"),
        ("base", "search_r"): Disabled("Serato search mode has no direct Rekordbox equivalent"),
        ("base", "touch"): Disabled("touch mode changes AMX hardware gestures"),
        ("base", "master"): Disabled("master level is not safely exposed by the Rekordbox mapping"),
        ("base", "cue_gain"): Disabled("headphone level is not safely exposed by the Rekordbox mapping"),
        ("base", "cue_mix"): Disabled("cue mix is not safely exposed by the Rekordbox mapping"),
        ("base", "xf_curve"): Disabled("choose a fixed curve in Rekordbox preferences"),
        ("base", "xf_reverse"): Disabled("crossfader reverse has no continuous Rekordbox equivalent"),
        ("shift", "cue_l"): Button("JumpToTrackStart", "a"), ("shift", "cue_r"): Button("JumpToTrackStart", "b"),
        ("shift", "sync_l"): Button("Slip", "a"), ("shift", "sync_r"): Button("Slip", "b"),
    }
    leds = {
        "play_l": Ref("PlayPause", "a"), "play_r": Ref("PlayPause", "b"),
        "cue_l": Ref("Cue", "a"), "cue_r": Ref("Cue", "b"),
        "sync_l": Ref("Sync", "a"), "sync_r": Ref("Sync", "b"),
        "pfl_l": Ref("HeadphoneCue", "a"), "pfl_r": Ref("HeadphoneCue", "b"),
    }
    return Profile("akai_amx", b, leds, title="AMX two-channel mixer", default_options={"knob_pickup": False},
                   option_choices={"knob_pickup": (False, True)}, edit_layers=(("base", "Normal"), ("shift", "Shift")))


def _afx():
    b = {
        ("base", "shift"): ModifierTap("shift"), ("base", "quantize"): Button("Quantize", "a"),
        ("base", "touch_strip"): Disabled("learn and assign the touch strip for your preferred workflow"),
        ("base", "deck_13"): Disabled("select the active deck in RekordTrakt"),
        ("base", "deck_24"): Disabled("select the active deck in RekordTrakt"),
        ("base", "search_abs"): Disabled("Serato strip mode has no direct Rekordbox equivalent"),
        ("base", "pitch_rel"): Disabled("Serato strip mode has no direct Rekordbox equivalent"),
        ("base", "sfx_int"): Disabled("Serato strip mode has no direct Rekordbox equivalent"),
        ("base", "record_loop"): Button("LoopIn", "a"), ("base", "start_on"): Button("AutoLoop", "a"),
        ("base", "parameter"): Rotary("LoopHalfDouble", "a"),
        ("base", "fxa_beat"): Split("FX{fxa}BeatUp", "FX{fxa}BeatDown"),
        ("base", "fxb_beat"): Split("FX{fxb}BeatUp", "FX{fxb}BeatDown"),
        ("base", "fxa_tap"): Button("FX{fxa}TapBeat"), ("base", "fxb_tap"): Button("FX{fxb}TapBeat"),
        ("base", "fxa_assign"): Button("FX{fxa}Assign{a}"), ("base", "fxb_assign"): Button("FX{fxb}Assign{a}"),
    }
    for n in range(1, 4):
        b[("base", f"fxa_knob_{n}")] = Knob(f"FX{{fxa}}-{n}")
        b[("base", f"fxb_knob_{n}")] = Knob(f"FX{{fxb}}-{n}")
        b[("base", f"fxa_button_{n}")] = Button(f"FX{{fxa}}-{n}On")
        b[("base", f"fxb_button_{n}")] = Button(f"FX{{fxb}}-{n}On")
    for n in range(1, 9):
        b[("base", f"pad_{n}")] = Button(f"PAD{n}_HotCue", "a")
    return Profile("akai_afx", b, title="AFX performance", default_options={"knob_pickup": False},
                   option_choices={"knob_pickup": (False, True)}, edit_layers=(("base", "Normal"), ("shift", "Shift")))


PROFILES = {"x1mk3": _x1(), "f1": _f1(), "x1mk1": _x1mk1(), "x1mk2": _x1mk2(),
            "akai_amx": _amx(), "akai_afx": _afx()}
