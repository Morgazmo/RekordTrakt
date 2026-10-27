"""Your own mappings over the presets: the mapping editor's bindings, several functions on one control, sequences,
custom pages, and saving them. Run from the repo root:  python -m unittest discover -s tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_engine import Rig                                        # noqa: E402
from rekordtrakt.bridge.client import BridgeClient                 # noqa: E402
from rekordtrakt.bridge.compiler import compile_bridge             # noqa: E402
from rekordtrakt.engine.actions import MappingError, build         # noqa: E402
from rekordtrakt.rekordbox import registry                         # noqa: E402

L, R, OFF = 0x90, 0x91, 0x80
HOTCUE_1, HOTCUE_2, FX_BUTTON_1, FX_KNOB_1, LOOP = 0x02, 0x03, 0x10, 0x10, 0x15


class Mapped:
    """The X1/F1 test rig with the whole registry on the bridge, as installed."""

    def __init__(self):
        self.r = Rig("performance_mod")
        self.r.csv, self.r.manifest = compile_bridge("RekordTrakt Bridge", registry.full_actions())
        self.r.bridge = BridgeClient(self.r.out, self.r.manifest)
        self.r.engine.bridge = self.r.bridge
        self.r.entries = {(e["function"], e["deck"]): e for e in self.r.manifest["entries"]}
        self.e = self.r.engine

    def tap(self, status, note, pos="x1_left"):
        self.r.msg(pos, status, note, 0x7F)
        self.r.msg(pos, OFF | (status & 0x0F), note, 0)

    def fn(self, function, deck="deck", **extra):
        return {"do": "function", "function": function, "deck": deck, **extra}


class Bindings(unittest.TestCase):
    def setUp(self):
        self.m = Mapped()

    def test_a_binding_changes_one_half_only_and_resets(self):
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_1", self.m.fn("Memory"))
        self.m.tap(L, HOTCUE_1)
        self.m.tap(R, HOTCUE_1)
        self.assertEqual(self.m.r.sent(), [("Memory", 1, 127), ("Memory", 1, 0),
                                           ("PAD1_HotCue", 3, 127), ("PAD1_HotCue", 3, 0)])
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_1", None)      # back to the preset
        self.m.tap(L, HOTCUE_1)
        self.assertEqual(self.m.r.sent(), [("PAD1_HotCue", 1, 127), ("PAD1_HotCue", 1, 0)])

    def test_what_cant_work_is_refused_before_saving(self):
        for action in ({"do": "function", "function": "EQHigh", "deck": "deck"},     # a knob function on... fine
                       {"do": "function", "function": "Nonsense"},
                       {"do": "function", "function": "PlayPause"},                    # needs a deck
                       {"do": "sequence", "steps": []}):
            if action["function" if "function" in action else "do"] == "EQHigh":
                continue
            with self.assertRaises(ValueError):
                self.m.e.set_binding("x1_left", "base", None, "L.hotcue_1", action)
        self.assertEqual(self.m.e.devices["x1_left"].mapping["bindings"], [])
        with self.assertRaises(MappingError):
            build({"do": "function", "function": "EQHigh", "deck": "deck"}, "encoder")

    def test_shift_and_sync_layers(self):
        self.m.e.set_binding("x1_left", "shift", None, "L.hotcue_1", self.m.fn("CallPrev"))
        self.m.e.set_binding("x1_left", "sync", None, "L.hotcue_1", self.m.fn("CallNext"))
        self.m.tap(0x92, HOTCUE_1)                                  # Shift + hot cue 1
        self.m.r.msg("x1_left", L, 0x0B, 0x7F)                      # hold Sync
        self.m.tap(L, HOTCUE_1)
        self.m.r.msg("x1_left", OFF, 0x0B, 0)
        sent = self.m.r.sent()
        self.assertEqual(sent[:2], [("CallPrev", 1, 127), ("CallPrev", 1, 0)])
        self.assertIn(("CallNext", 1, 127), sent)

    def test_several_functions_on_one_button(self):
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_2", {"do": "functions", "items": [
            self.m.fn("Sync"), self.m.fn("MasterTempo"), {"function": "FX1Assign1"}]})
        self.m.tap(L, HOTCUE_2)
        self.assertEqual(self.m.r.sent(), [("Sync", 1, 127), ("MasterTempo", 1, 127), ("FX1Assign1", None, 127),
                                           ("FX1Assign1", None, 0), ("MasterTempo", 1, 0), ("Sync", 1, 0)])

    def test_one_knob_drives_several_functions_over_their_own_ranges(self):
        self.m.e.set_binding("x1_left", "base", "fx", "L.fx_knob_1", {"do": "functions", "items": [
            self.m.fn("EQHigh", **{"from": 0, "to": 127}), self.m.fn("EQLow", **{"from": 127, "to": 0})]})
        self.m.r.msg("x1_left", 0xB0, FX_KNOB_1, 127)
        self.assertEqual(self.m.r.sent(), [("EQHigh", 1, 127), ("EQLow", 1, 0)])

    def test_a_sequence_runs_its_steps_after_their_waits(self):
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_2", {"do": "sequence", "steps": [
            self.m.fn("JumpToTrackStart"), self.m.fn("PlayPause", wait=0.5)]})
        self.m.tap(L, HOTCUE_2)
        self.assertEqual(self.m.r.sent(), [("JumpToTrackStart", 1, 127), ("JumpToTrackStart", 1, 0)])
        self.m.r.clock.t += 0.6
        self.m.e.tick()
        self.assertEqual(self.m.r.sent(), [("PlayPause", 1, 127), ("PlayPause", 1, 0)])

    def test_a_button_can_set_a_knob_function(self):
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_2",
                             {"do": "value", "function": "EQLow", "deck": "deck", "value": 0, "release": 64})
        self.m.tap(L, HOTCUE_2)
        self.assertEqual(self.m.r.sent(), [("EQLow", 1, 0), ("EQLow", 1, 64)])

    def test_an_encoder_can_step_through_two_buttons(self):
        self.m.e.set_binding("x1_left", "base", None, "L.loop",
                             {"do": "function", "function": "Jump8Fwd", "minus": "Jump8Prev", "deck": "deck"})
        self.m.r.msg("x1_left", 0xB0, LOOP, 0x41)
        self.assertEqual(self.m.r.sent(), [("Jump8Fwd", 1, 127), ("Jump8Fwd", 1, 0)])

    def test_a_bound_button_lights_with_its_function(self):
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_2", self.m.fn("Slip"))
        self.m.r.feedback("Slip", 1, 127)
        self.assertEqual(self.m.e.led_value(self.m.e.devices["x1_left"], "L", "hotcue_2"), 127)


class Pages(unittest.TestCase):
    def setUp(self):
        self.m = Mapped()

    def test_a_custom_page_starts_blank_and_takes_its_own_bindings(self):
        page = self.m.e.add_page("x1_left", "Loops")
        self.assertIn(page, self.m.e.pages(self.m.e.devices["x1_left"]))
        self.m.e.set_mode("x1_left", "L", "page", page)
        self.m.tap(L, FX_BUTTON_1)
        self.assertEqual(self.m.r.sent(), [])                       # blank until bound
        self.m.e.set_binding("x1_left", "base", page, "L.fx_button_1", self.m.fn("AutoLoop"))
        self.m.tap(L, FX_BUTTON_1)
        self.m.e.set_mode("x1_left", "L", "page", "fx")
        self.m.tap(L, FX_BUTTON_1)
        self.assertEqual(self.m.r.sent(), [("AutoLoop", 1, 127), ("AutoLoop", 1, 0),
                                           ("FX1-1On", None, 127), ("FX1-1On", None, 0)])

    def test_shift_fx_assign_steps_onto_custom_pages_and_preset_pages_can_be_muted(self):
        dev = self.m.e.devices["x1_left"]
        page = self.m.e.add_page("x1_left", "Mine")
        self.m.e.set_pages("x1_left", ["fx", page])                  # every other preset page muted
        self.m.tap(0x92, 0x01)                                       # Shift + FX Assign 2: next page
        self.assertEqual(dev.modes["L"]["page"], page)
        self.m.tap(0x92, 0x01)
        self.assertEqual(dev.modes["L"]["page"], "fx")
        view = self.m.e.view()["devices"][0]
        self.assertEqual(view["pages"], ["fx", page])
        self.assertEqual(view["page_names"][page], "Mine")

    def test_a_page_that_is_off_keeps_its_place_in_the_order(self):
        e, dev = self.m.e, self.m.e.devices["x1_left"]
        page = e.add_page("x1_left", "Mine")
        self.assertEqual(e.pages(dev, enabled_only=False)[-1], page)        # added where its blank row was: last
        order = [page, "fx", "stems", "mixer", "sfx", "cfx_multi", "cfx_single"]
        e.set_pages("x1_left", ["fx", page, "mixer"], order=order)          # dragged first; stems off
        self.assertEqual(e.pages(dev, enabled_only=False), order)
        self.assertEqual(e.pages(dev), [page, "fx", "mixer"])               # the cycle follows the order
        e.set_pages("x1_left", [page, "fx", "mixer", "stems"], order=order)  # back on: in its old place
        self.assertEqual(e.pages(dev), [page, "fx", "stems", "mixer"])
        e.remove_page("x1_left", page)
        self.assertNotIn(page, dev.options["page_order"])

    def test_the_view_counts_what_is_set_on_each_of_your_pages(self):
        page = self.m.e.add_page("x1_left", "Mine")
        blank = self.m.e.add_page("x1_left", "Blank")
        self.m.e.set_binding("x1_left", "base", page, "L.fx_button_1", self.m.fn("AutoLoop"))
        view = self.m.e.view()["devices"][0]
        self.assertEqual(view["page_bindings"], {page: 1, blank: 0})   # the window asks before deleting only `page`

    def test_removing_a_page_removes_its_bindings(self):
        page = self.m.e.add_page("x1_left", "Mine")
        self.m.e.set_binding("x1_left", "base", page, "L.fx_button_1", self.m.fn("AutoLoop"))
        self.m.e.rename_page("x1_left", page, "Loops")
        self.m.e.remove_page("x1_left", page)
        dev = self.m.e.devices["x1_left"]
        self.assertEqual(dev.mapping, {"pages": [], "bindings": []})
        self.assertNotIn(page, self.m.e.pages(dev))


class Ownership(unittest.TestCase):
    """Several controls on one target, and sequences that outlive their press."""

    def setUp(self):
        self.m = Mapped()

    def hold(self, control, note, source="hw"):
        from rekordtrakt.devices.base import PRESS, Event
        if source == "hw":
            self.m.r.msg("x1_left", L, note, 0x7F)
        else:
            self.m.e.handle(Event("x1_left", control, PRESS, 0, False, source))

    def let_go(self, control, note, source="hw"):
        from rekordtrakt.devices.base import RELEASE, Event
        if source == "hw":
            self.m.r.msg("x1_left", OFF, note, 0)
        else:
            self.m.e.handle(Event("x1_left", control, RELEASE, 0, False, source))

    def test_two_controls_on_one_target_press_once_and_release_with_the_last(self):
        for control in ("L.hotcue_1", "L.hotcue_2"):
            self.m.e.set_binding("x1_left", "base", None, control, self.m.fn("Cue"))
        self.hold("L.hotcue_1", HOTCUE_1)
        self.hold("L.hotcue_2", HOTCUE_2)
        self.let_go("L.hotcue_1", HOTCUE_1)
        self.assertEqual(self.m.r.sent(), [("Cue", 1, 127)])                 # the second is still held
        self.let_go("L.hotcue_2", HOTCUE_2)
        self.assertEqual(self.m.r.sent(), [("Cue", 1, 0)])

    def test_the_window_and_the_hardware_hold_one_control_together(self):
        self.hold("L.hotcue_1", HOTCUE_1)
        self.hold("L.hotcue_1", HOTCUE_1, source="ui")
        self.let_go("L.hotcue_1", HOTCUE_1, source="ui")
        self.assertEqual(self.m.r.sent(), [("PAD1_HotCue", 1, 127)])
        self.let_go("L.hotcue_1", HOTCUE_1)
        self.assertEqual(self.m.r.sent(), [("PAD1_HotCue", 1, 0)])

    def test_a_tap_never_releases_a_target_someone_holds(self):
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_1", self.m.fn("Cue"))
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_2", {"do": "sequence", "steps": [self.m.fn("Cue")]})
        self.hold("L.hotcue_1", HOTCUE_1)
        self.m.tap(L, HOTCUE_2)
        self.assertEqual(self.m.r.sent(), [("Cue", 1, 127)])
        self.assertTrue(any("Skipped Cue deck 1" in n for n in self.m.r.notices))

    def test_duplicate_group_targets_balance_to_one_press_and_release(self):
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_2", {"do": "functions", "items": [
            self.m.fn("Cue"), self.m.fn("Cue")]})
        self.m.tap(L, HOTCUE_2)
        self.assertEqual(self.m.r.sent(), [("Cue", 1, 127), ("Cue", 1, 0)])

    def sequence(self):
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_2", {"do": "sequence", "steps": [
            self.m.fn("JumpToTrackStart"), self.m.fn("PlayPause", wait=1.0)]})
        self.m.tap(L, HOTCUE_2)
        self.m.r.sent()

    def later(self, seconds):
        self.m.r.clock.t += seconds
        self.m.e.tick()
        return self.m.r.sent()

    def test_a_deck_change_cancels_the_steps_still_waiting(self):
        self.sequence()
        self.m.e.assign("x1_left", "L", deck=3)
        self.assertEqual(self.later(1.1), [])

    def test_a_page_change_or_an_edit_cancels_them_too(self):
        self.sequence()
        self.m.e.set_mode("x1_left", "L", "page", "mixer")
        self.assertEqual(self.later(1.1), [])
        self.sequence()
        self.m.e.set_binding("x1_left", "base", None, "L.hotcue_1", self.m.fn("Cue"))
        self.assertEqual(self.later(1.1), [])

    def test_the_other_half_and_letting_go_dont(self):
        self.sequence()
        self.m.e.assign("x1_left", "R", deck=4)
        self.assertEqual(self.later(1.1), [("PlayPause", 1, 127), ("PlayPause", 1, 0)])

    def test_pressing_again_starts_it_over(self):
        self.sequence()
        self.m.r.clock.t += 0.6
        self.m.tap(L, HOTCUE_2)
        self.assertEqual(self.m.r.sent(), [("JumpToTrackStart", 1, 127), ("JumpToTrackStart", 1, 0)])
        self.assertEqual(self.later(0.5), [])                               # the first run's step: cancelled
        self.assertEqual(self.later(0.6), [("PlayPause", 1, 127), ("PlayPause", 1, 0)])


class Saving(unittest.TestCase):
    def test_the_mapping_is_saved_with_the_rig_and_loads_again(self):
        from isolated import EXAMPLE
        from rekordtrakt import rig as rig_mod
        path = Path(tempfile.mkdtemp()) / "rig.json"
        path.write_text(json.dumps(EXAMPLE), encoding="utf-8")
        m = Mapped()
        m.e.on_config_change = lambda dev: rig_mod.save_device(dev, path)
        m.e.set_binding("x1_left", "base", None, "L.hotcue_1", m.fn("Memory"))
        saved = json.loads(path.read_text(encoding="utf-8"))["devices"]["x1_left"]["mapping"]
        self.assertEqual(saved["bindings"][0]["action"]["function"], "Memory")
        dev = next(d for d in rig_mod.device_configs(json.loads(path.read_text(encoding="utf-8")))
                   if d.position == "x1_left")
        self.assertEqual(dev.mapping["bindings"][0]["control"], "L.hotcue_1")

    def test_editor_info_shows_the_preset_and_yours_per_layer(self):
        m = Mapped()
        m.e.set_binding("x1_left", "shift", None, "L.hotcue_1", m.fn("CallPrev"))
        info = m.e.control_info("x1_left", "L.hotcue_1")
        layers = {x["layer"]: x for x in info["layers"]}
        self.assertEqual(layers["base"]["preset"]["label"], "Hot cue A")
        self.assertEqual(layers["shift"]["mine"]["function"], "CallPrev")
        self.assertEqual(info["kind"], "button")

    def test_f1_only_offers_page_two_for_controls_with_a_second_address(self):
        m = Mapped()
        self.assertEqual([x["layer"] for x in m.e.control_info("f1_left", "pad_1")["layers"]],
                         ["base", "shift"])
        self.assertEqual([x["layer"] for x in m.e.control_info("f1_left", "knob_1")["layers"]], ["base"])
        with self.assertRaises(ValueError):
            m.e.set_binding("f1_left", "shift", None, "knob_1", m.fn("EQHigh", deck="a"))

        m.e.set_binding("f1_left", "shift", None, "pad_1", m.fn("CallPrev", deck="a"))
        m.r.msg("f1_left", 0xB0, 0x14, 0x7F)
        m.r.msg("f1_left", 0xB0, 0x14, 0)
        self.assertEqual(m.r.sent(), [("CallPrev", 1, 127), ("CallPrev", 1, 0)])


if __name__ == "__main__":
    unittest.main()
