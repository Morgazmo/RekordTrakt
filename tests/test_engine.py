"""Simulated X1 MK3 / F1 input through the basic presets, checking exactly what reaches the bridge and the LEDs.

Run from the repo root:  python -m unittest discover -s tests
"""
import json
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from isolated import EXAMPLE                                  # noqa: E402  (first: per-user files to a temp folder)
from rekordtrakt import rig as rig_mod                        # noqa: E402
from rekordtrakt.bridge.client import BridgeClient            # noqa: E402
from rekordtrakt.bridge.compiler import canonical_mappings, compile_bridge  # noqa: E402
from rekordtrakt.engine.engine import Engine                  # noqa: E402
from rekordtrakt.engine.leds import LedEngine                 # noqa: E402
from rekordtrakt.devices.defined import DefinedDevice         # noqa: E402
from rekordtrakt.profiles import PROFILES                     # noqa: E402
from rekordtrakt.rekordbox.registry import bridge_actions      # noqa: E402



def rig_with(x1_profile):
    rig = json.loads(json.dumps(EXAMPLE))
    for pos in ("x1_left", "x1_right"):
        rig["devices"][pos]["profile"] = x1_profile
    return rig


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, s, d1, d2):
        self.sent.append((s, d1, d2))


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Rig:
    """Engine wired to recorders instead of MIDI ports."""

    def __init__(self, x1_profile=""):
        self.clock = Clock()
        rig = rig_with(x1_profile)
        probe = Engine(rig_mod.device_configs(rig), PROFILES, None, None, self.clock)
        self.csv, self.manifest = compile_bridge("RekordTrakt Bridge", bridge_actions(probe.uses()))
        self.out = Recorder()
        self.bridge = BridgeClient(self.out, self.manifest)
        self.leds = LedEngine(self.clock)
        self.led_out = {}
        devices = rig_mod.device_configs(rig)
        for dev in devices:
            self.led_out[dev.position] = Recorder()
            self.leds.add_device(dev.position, dev.device, self.led_out[dev.position])
        self.saved = []
        self.notices = []
        self.engine = Engine(devices, PROFILES, self.bridge, self.leds, self.clock, log=self.notices.append,
                             on_config_change=self.saved.append)
        self.entries = {(e["function"], e["deck"]): e for e in self.manifest["entries"]}

    def msg(self, position, status, d1, d2):
        self.engine.device_message(position, status, d1, d2)

    def sent(self):
        """Decode what went to the bridge into (function, deck, value) using the manifest."""
        by_input = {}
        for e in self.manifest["entries"]:
            if e["input"]:
                by_input[(e["input"]["status"], e["input"]["data1"])] = (e["function"], e["deck"])
                if "lsb" in e["input"]:
                    by_input[(e["input"]["status"], e["input"]["lsb"])] = (e["function"] + ".lsb", e["deck"])
        out = [(*by_input[(s, d1)], d2) for s, d1, d2 in self.out.sent]
        self.out.sent.clear()
        return out

    def feedback(self, function, deck, value):
        o = self.entries[(function, deck)]["output"]
        self.engine.feedback(o["status"], o["data1"], value)


class X1Tests(unittest.TestCase):
    def setUp(self):
        self.r = Rig()

    def test_play_routes_by_unit_and_half(self):
        self.r.msg("x1_left", 0x90, 0x0A, 0x7F)      # left X1, left half
        self.r.msg("x1_left", 0x80, 0x0A, 0x00)      # note-off release
        self.r.msg("x1_left", 0x91, 0x0A, 0x7F)      # left X1, right half
        self.r.msg("x1_right", 0x90, 0x0A, 0x7F)     # right X1, left half
        self.assertEqual(self.r.sent(), [("PlayPause", 1, 127), ("PlayPause", 1, 0),
                                         ("PlayPause", 3, 127), ("PlayPause", 2, 127)])

    def test_note_off_becomes_velocity_zero_release(self):
        self.r.msg("x1_left", 0x90, 0x08, 0x7F)      # cue
        self.r.msg("x1_left", 0x80, 0x08, 0x00)
        e = self.r.entries[("Cue", 1)]["input"]
        self.assertEqual(self.r.out.sent[-1], (e["status"], e["data1"], 0))   # note-on, velocity 0
        self.assertEqual(e["status"] & 0xF0, 0x90)

    def test_device_test_decodes_controls_without_sending_to_rekordbox(self):
        self.r.engine.set_device_test("x1_left", True)
        self.r.msg("x1_left", 0x90, 0x0A, 0x7F)
        self.assertEqual(self.r.sent(), [])
        self.assertIn(("x1_left", "L.play"), self.r.engine.down)
        view = next(d for d in self.r.engine.view()["devices"] if d["position"] == "x1_left")
        self.assertTrue(view["midi_test"])
        self.r.engine.set_device_test("x1_left", False)
        self.r.msg("x1_left", 0x90, 0x0A, 0x7F)
        self.assertEqual(self.r.sent(), [("PlayPause", 1, 127)])

    def test_a_learned_device_keeps_the_bundled_profile_when_adopted_live(self):
        rig = rig_mod.new_rig()
        position = rig_mod.with_device(rig, "X1 MK2", "x1mk2")
        dev = rig_mod.device_configs(rig)[0]
        engine = Engine([dev], PROFILES, None, None, self.r.clock)
        definition = copy.deepcopy(dev.device.definition)
        definition["type"], definition["template"] = "learned_x1mk2_test", "x1mk2"
        next(c for c in definition["controls"] if c["id"] == "L.play")["in"] = {
            "msg": "note", "ch": 1, "num": 22}
        engine.replace_device_definition(position, DefinedDevice(definition), definition["template"])
        self.assertEqual((dev.profile, engine.profile(dev).title), ("x1mk2", "X1 MK2 basic"))
        self.assertEqual(dev.device.decode(0x90, 22, 127).control, "L.play")

    def test_shift_layer_and_release_after_shift_let_go(self):
        self.r.msg("x1_left", 0x92, 0x02, 0x7F)      # Shift + hotcue 1 (channel 3)
        self.r.msg("x1_left", 0x80, 0x02, 0x00)      # released after Shift, on channel 1
        self.assertEqual(self.r.sent(), [("PAD1_HotCue+Shift", 1, 127), ("PAD1_HotCue+Shift", 1, 0)])

    def test_sync_tap_toggles_on_release(self):
        self.r.msg("x1_left", 0x90, 0x0B, 0x7F)
        self.assertEqual(self.r.sent(), [])          # nothing yet: might become a hold
        self.r.clock.t += 0.15
        self.r.msg("x1_left", 0x80, 0x0B, 0x00)
        self.assertEqual(self.r.sent(), [("Sync", 1, 127), ("Sync", 1, 0)])

    def test_sync_long_hold_does_not_toggle(self):
        self.r.msg("x1_left", 0x90, 0x0B, 0x7F)
        self.r.clock.t += 0.8
        self.r.msg("x1_left", 0x80, 0x0B, 0x00)
        self.assertEqual(self.r.sent(), [])

    def test_sync_hold_layer(self):
        self.r.msg("x1_left", 0x91, 0x0B, 0x7F)      # hold Sync, right half (deck 3)
        self.r.msg("x1_left", 0x91, 0x15, 0x7F)      # loop push -> tempo reset
        self.r.msg("x1_left", 0x81, 0x15, 0x00)
        self.r.msg("x1_left", 0xB1, 0x15, 0x41)      # loop turn -> tempo +0.5%
        self.r.msg("x1_left", 0x91, 0x06, 0x7F)      # nudge falls through to pitch bend
        self.r.msg("x1_left", 0x81, 0x06, 0x00)
        self.r.msg("x1_left", 0x81, 0x0B, 0x00)      # release Sync quickly, but it was used: no toggle
        self.assertEqual(self.r.sent(), [("TempoReset", 3, 127), ("TempoReset", 3, 0),
                                         ("TempoIncMedium", 3, 127), ("TempoIncMedium", 3, 0),
                                         ("PitchBendDown", 3, 127), ("PitchBendDown", 3, 0)])

    def test_sync_layer_only_on_its_own_half(self):
        self.r.msg("x1_left", 0x90, 0x0B, 0x7F)      # hold Sync on the left half
        self.r.msg("x1_left", 0x91, 0x15, 0x7F)      # loop push on the right half: normal auto loop
        self.assertEqual(self.r.sent(), [("AutoLoop", 3, 127)])

    def test_encoders_one_message_per_step(self):
        self.r.msg("x1_left", 0xB0, 0x14, 0x43)      # browse +3
        self.r.msg("x1_left", 0xB0, 0x15, 0x3F)      # loop size -1
        self.assertEqual(self.r.sent(), [("Browse", None, 0x41)] * 3 + [("LoopHalfDouble", 1, 0x3F)])


    def test_shift_loop_beat_jumps_4_when_no_loop(self):
        self.r.feedback("GetLoopActive", 1, 0)
        self.r.msg("x1_left", 0xB2, 0x15, 0x3F)      # Shift + loop -1, no loop active
        self.assertEqual(self.r.sent(), [("Jump4Prev", 1, 127), ("Jump4Prev", 1, 0)])

    def test_shift_loop_moves_loop_when_rekordbox_reports_one(self):
        self.r.feedback("GetLoopActive", 1, 127)
        self.r.msg("x1_left", 0xB2, 0x15, 0x41)
        self.assertEqual(self.r.sent(), [("LoopMove", 1, 0x41)])

    def test_fx_section_uses_half_fx_unit(self):
        self.r.msg("x1_right", 0xB1, 0x10, 90)       # right X1, right half -> FX2 knob 1
        self.r.msg("x1_right", 0x90, 0x11, 0x7F)     # left half -> FX1 slot 2 on
        self.r.msg("x1_right", 0x91, 0x00, 0x7F)     # right half FX assign 1 -> FX1 on CH4
        self.assertEqual(self.r.sent(), [("FX2-1", None, 90), ("FX1-2On", None, 127), ("FX1Assign4", None, 127)])

    def test_knob_still_works_while_shift_held(self):
        self.r.msg("x1_left", 0xB2, 0x10, 64)
        self.assertEqual(self.r.sent(), [("FX1-1", None, 64)])

    def test_feedback_drives_leds_on_the_right_unit_and_half(self):
        self.r.feedback("PlayPause", 4, 127)          # deck 4 = right X1, right half
        self.r.engine.tick()
        self.assertEqual(self.r.led_out["x1_right"].sent, [(0x91, 0x0A, 127)])
        self.assertEqual(self.r.led_out["x1_left"].sent, [])

    def test_start_and_stop_neutralise(self):
        self.r.msg("x1_left", 0x90, 0x08, 0x7F)      # cue held when the translator stops
        self.r.out.sent.clear()
        self.r.engine.stop()
        cue = self.r.entries[("Cue", 1)]["input"]
        self.assertIn((cue["status"], cue["data1"], 0), self.r.out.sent)
        self.assertTrue(all(d2 == 0 for s, d1, d2 in self.r.out.sent if s & 0xF0 == 0x90))


class F1Tests(unittest.TestCase):
    def setUp(self):
        self.r = Rig()

    def test_stem_knobs_and_faders(self):
        self.r.msg("f1_left", 0xBC, 0x02, 127)       # knob 1 -> drums deck 1, 14-bit
        self.r.msg("f1_right", 0xBC, 0x08, 0)        # right F1 fader 3 -> inst deck 4
        self.assertEqual(self.r.sent(), [("PartIsolatorDrums", 1, 127), ("PartIsolatorDrums.lsb", 1, 127),
                                         ("PartIsolatorInst", 4, 0), ("PartIsolatorInst.lsb", 4, 0)])

    def test_an_f1_can_move_to_other_decks_and_fx_unit(self):
        e = self.r.engine
        e.assign("f1_left", deck=2, slot=0)              # first deck: 1 -> 2
        e.assign("f1_left", deck=4, slot=1)              # second deck: 3 -> 4
        e.assign("f1_left", fx=2, slot=0)                # FX unit 1 -> 2
        self.assertEqual((e.devices["f1_left"].decks, e.devices["f1_left"].fx_units), ([2, 4], [2]))
        self.r.msg("f1_left", 0xBC, 0x02, 127)           # knob 1: drums on the first deck
        self.r.msg("f1_left", 0xB7, 0x41, 0x7F)          # pad 8: Colour FX centre on the second deck's channel
        self.assertEqual(self.r.sent(), [("PartIsolatorDrums", 2, 127), ("PartIsolatorDrums.lsb", 2, 127),
                                         ("CFXParameterCH4Center", None, 127)])
        self.assertEqual(self.r.saved[-1].decks, [2, 4])

    def test_settings_describe_what_each_controller_can_move(self):
        devices = {d["position"]: d for d in self.r.engine.view()["devices"]}
        f1 = devices["f1_left"]["assign"]
        self.assertEqual([(r["label"], r["items"]) for r in f1], [
            ("First deck", [{"slot": 0, "kind": "deck", "value": 1}]),
            ("Second deck", [{"slot": 1, "kind": "deck", "value": 3}]),
            ("FX unit", [{"slot": 0, "kind": "fx", "value": 1}])])
        x1 = devices["x1_left"]["assign"]
        self.assertEqual([r["label"] for r in x1], ["Left deck", "Right deck"])
        self.assertEqual(x1[0]["items"], [{"half": "L", "kind": "deck", "value": 1}, {"half": "L", "kind": "fx", "value": 1}])

    def test_the_bridge_covers_every_deck_an_f1_can_move_to(self):
        uses = self.r.engine.uses()
        self.assertTrue(all(("PartIsolatorDrums", deck) in uses for deck in (1, 2, 3, 4)))
        self.assertTrue(all((f"CFXParameterCH{n}Center", None) in uses for n in (1, 2, 3, 4)))

    def test_filter_knob_and_reset(self):
        self.r.msg("f1_left", 0xBC, 0x05, 30)        # knob 4 -> CFX CH1
        self.r.msg("f1_left", 0xB7, 0x41, 0x7F)      # pad 8 -> CFX CH3 centre
        self.assertEqual(self.r.sent(), [("CFXParameterCH1", None, 30), ("CFXParameterCH3Center", None, 127)])

    def test_stem_pads(self):
        self.r.msg("f1_right", 0xB1, 0x3B, 0x7F)     # pad 2 -> vocal on/off deck 2
        self.r.msg("f1_right", 0xB4, 0x3E, 0x7F)     # pad 5 -> drums deck 4
        self.assertEqual(self.r.sent(), [("ActivePartVocal", 2, 127), ("ActivePartDrums", 4, 127)])

    def part_fx(self, drums, vocal, inst):
        return [("FXPartSelectDrums", None, drums), ("FXPartSelectVocal", None, vocal), ("FXPartSelectInst", None, inst)]

    def test_part_fx_hold_solos_then_restores_previous_selection(self):
        for stem, value in (("Drums", 127), ("Vocal", 0), ("Inst", 127)):   # what Rekordbox reported
            self.r.feedback(f"FXPartSelect{stem}", None, value)
        self.r.msg("f1_left", 0xB9, 0x43, 0x7F)      # hold pad 10 (vocal)
        self.r.clock.t += 0.5
        self.r.msg("f1_left", 0xB9, 0x43, 0x00)
        self.assertEqual(self.r.sent(), self.part_fx(0, 127, 0) + self.part_fx(127, 0, 127))

    def test_part_fx_tap_toggles_and_keeps_it(self):
        self.r.msg("f1_left", 0xB9, 0x43, 0x7F)      # tap pad 10 (vocal): nothing reported yet = all off
        self.r.msg("f1_left", 0xB9, 0x43, 0x00)
        self.assertEqual(self.r.sent(), self.part_fx(0, 127, 0) + self.part_fx(0, 127, 0))     # vocal stays on
        self.r.clock.t += 1
        self.r.msg("f1_left", 0xB8, 0x42, 0x7F)      # hold pad 9 (drums): drums only while held
        self.r.clock.t += 0.5
        self.r.msg("f1_left", 0xB8, 0x42, 0x00)      # back to the latched selection: vocal on
        self.assertEqual(self.r.sent(), self.part_fx(127, 0, 0) + self.part_fx(0, 127, 0))
        self.r.msg("f1_left", 0xB9, 0x43, 0x7F)      # tap vocal again: off
        self.r.msg("f1_left", 0xB9, 0x43, 0x00)
        self.assertEqual(self.r.sent()[-3:], self.part_fx(0, 0, 0))

    def test_part_fx_two_pads_held_across_both_f1s(self):
        self.r.msg("f1_left", 0xB8, 0x42, 0x7F)      # hold drums on the left F1
        self.r.msg("f1_right", 0xBA, 0x44, 0x7F)     # and inst on the right F1
        self.r.msg("f1_left", 0xB8, 0x42, 0x00)      # let go of drums: inst stays soloed
        self.r.msg("f1_right", 0xBA, 0x44, 0x00)     # let go of inst: back to before (nothing reported = off)
        self.assertEqual(self.r.sent(), self.part_fx(127, 0, 0) + self.part_fx(127, 0, 127)
                         + self.part_fx(0, 0, 127) + self.part_fx(0, 0, 0))

    def test_stopping_mid_hold_restores_part_fx(self):
        for stem in ("Drums", "Vocal", "Inst"):
            self.r.feedback(f"FXPartSelect{stem}", None, 127)
        self.r.msg("f1_left", 0xB8, 0x42, 0x7F)
        self.r.sent()
        self.r.engine.stop()
        self.assertEqual([s for s in self.r.sent() if s[0].startswith("FXPartSelect")], self.part_fx(127, 127, 127))

    def test_pad_12_is_unassigned(self):
        self.r.msg("f1_left", 0xBB, 0x45, 0x7F)
        self.assertEqual(self.r.sent(), [])

    def test_f1_encoder_twos_complement(self):
        self.r.msg("f1_left", 0xBC, 0x4E, 0x7F)      # -1
        self.assertEqual(self.r.sent(), [("Browse", None, 0x3F)])

    def test_f1_leds_are_rate_limited(self):
        self.r.feedback("ActivePartDrums", 1, 127)    # pad 1
        self.r.feedback("ActivePartVocal", 1, 127)    # pad 2
        self.r.engine.tick()
        self.r.engine.tick()                          # same instant: second message must wait
        self.assertEqual(self.r.led_out["f1_left"].sent, [(0xB0, 0x3A, 127)])
        self.r.clock.t += 0.03
        self.r.engine.tick()
        self.assertEqual(self.r.led_out["f1_left"].sent, [(0xB0, 0x3A, 127), (0xB1, 0x3B, 127)])


class BridgeTests(unittest.TestCase):
    def test_bridge_compiles_and_survives_rekordbox_reformatting(self):
        r = Rig()
        self.assertGreater(len(r.manifest["entries"]), 100)
        # What Rekordbox does on exit: rows reordered, ';' appended to options, "Pad" renamed.
        header, *rows = r.csv.strip().split("\r\n")
        rewritten = []
        for row in reversed(rows):
            f = row.split(",")
            if f[13]:
                f[13] += ";"
            if f[2] == "Pad":
                f[2] = "DdjSxPad"
            rewritten.append(",".join(f))
        self.assertIn(",DdjSxPad,", "\n".join(rewritten))
        self.assertEqual(canonical_mappings(r.csv), canonical_mappings("\r\n".join([header, *rewritten])))


if __name__ == "__main__":
    unittest.main()
