"""The main window's view (labels, layers, pages, pickup) and live settings, with simulated controllers.

Run from the repo root:  python -m unittest discover -s tests
"""
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_engine import EXAMPLE, Rig                                     # noqa: E402
from rekordtrakt.devices.base import PRESS, RELEASE, VALUE, Event          # noqa: E402
from rekordtrakt.engine.labels import function_label                     # noqa: E402
from rekordtrakt.midi.fake import FakeMidi                               # noqa: E402
from rekordtrakt.service import RUNNING, Translator, as_installed       # noqa: E402
from rekordtrakt.shell.events import EventHub                            # noqa: E402

L, SL, OFF = 0x90, 0x92, 0x80


def half(view, position="x1_left", index=0):
    dev = next(d for d in view["devices"] if d["position"] == position)
    return dev, dev["halves"][index]


class Labels(unittest.TestCase):
    def test_function_labels(self):
        self.assertEqual(function_label("PAD6_HotCue"), "Hot cue F")
        self.assertEqual(function_label("PAD2_HotCue+Shift"), "Delete hot cue B")
        self.assertEqual(function_label("FX2-3Select"), "FX2 slot 3 next effect")
        self.assertEqual(function_label("PartIsolatorVocal"), "Vocal level")
        self.assertEqual(function_label("Jump16Prev"), "Jump −16 beats")
        self.assertEqual(function_label("SomethingNew"), "Something New")


class View(unittest.TestCase):
    def setUp(self):
        self.r = Rig("performance_mod")

    def test_base_layer_labels_with_shift(self):
        dev, h = half(self.r.engine.view())
        c = h["controls"]
        self.assertEqual((h["half"], h["deck"], h["fx"], h["modes"]["page"]), ("L", 1, 1, "fx"))
        self.assertEqual(c["hotcue_1"]["label"], "Hot cue A")
        self.assertEqual(c["hotcue_1"]["shift"], "Delete hot cue A")
        self.assertEqual(c["fx_knob_1"]["label"], "FX1 slot 1 level")
        self.assertEqual(c["browse_push"]["label"], "Load to deck 1")
        self.assertNotIn("shift", c["play"])                 # Shift + Play is unavailable: nothing to say
        self.assertEqual(dev["pages"], ["mixer", "stems", "fx", "sfx", "cfx_multi", "cfx_single"])
        self.assertEqual(dev["page_names"]["cfx_multi"], "CFX multi")
        self.assertIn("encoders", dev["option_info"])

    def test_held_modifier_shows_its_layer(self):
        self.r.msg("x1_left", L, 0x0B, 0x7F)                  # hold Sync
        _, h = half(self.r.engine.view())
        self.assertEqual(h["layer"], "Sync layer")
        self.assertEqual(h["controls"]["loop"]["label"], "Tempo ±0.5%")
        self.assertEqual(h["controls"]["hotcue_1"]["label"], "Hot cue E")
        self.r.msg("x1_left", OFF, 0x0B, 0)
        _, h = half(self.r.engine.view())
        self.assertIsNone(h["layer"])
        self.assertEqual(h["controls"]["loop"]["label"], "Loop size")

    def test_setup_layer(self):
        self.r.msg("x1_left", L, 0x00, 0x7F)
        self.r.msg("x1_left", L, 0x01, 0x7F)
        _, h = half(self.r.engine.view())
        self.assertEqual(h["layer"], "Setup")
        self.assertEqual(h["controls"]["hotcue_3"]["label"], "Deck 3")

    def test_page_changes_labels_and_version(self):
        before = self.r.engine.view_version
        self.r.msg("x1_left", SL, 0x01, 0x7F)                 # Shift + FX Assign 2: next page (sfx)
        self.r.msg("x1_left", OFF, 0x01, 0)
        self.assertGreater(self.r.engine.view_version, before)
        _, h = half(self.r.engine.view())
        self.assertEqual(h["modes"]["page"], "sfx")
        self.assertEqual(h["controls"]["fx_knob_1"]["label"], "SFX1 amount")

    def test_led_state_and_knob_pickup(self):
        self.r.engine.set_option("x1_left", "knob_pickup", True)
        self.r.feedback("PAD1_HotCue", 1, 127)
        self.r.msg("x1_left", 0xB0, 0x10, 100)                # knob 1 on the FX page
        self.r.engine.set_mode("x1_left", "L", "page", "mixer")
        self.r.msg("x1_left", 0xB0, 0x10, 30)                 # EQ high, sent
        self.r.engine.set_mode("x1_left", "L", "page", "fx")
        _, h = half(self.r.engine.view())
        self.assertEqual(h["controls"]["hotcue_1"]["led"], 127)
        self.assertEqual(h["controls"]["fx_knob_1"]["value"], 30)
        self.assertEqual(h["controls"]["fx_knob_1"]["pickup"], 100)     # back on FX: turn to 100 to take over

    def test_f1_view(self):
        _, h = half(self.r.engine.view(), "f1_left")
        self.assertEqual((h["half"], h["decks"]), (None, [1, 3]))
        self.assertEqual((h["controls"]["pad_1"]["label"], h["controls"]["pad_1"]["detail"]), ("Drums on/off", "deck 1"))
        self.assertNotIn("label", h["controls"]["pad_16"])

    def test_view_is_json(self):
        json.dumps(self.r.engine.view())


class ShortLabels(unittest.TestCase):
    def setUp(self):
        self.r = Rig("performance_mod")

    def test_rows_short_labels_and_sync_layer_cues(self):
        _, h = half(self.r.engine.view())
        c = h["controls"]
        self.assertEqual(h["rows"], ["Slot 1", "Slot 2", "Slot 3", "FX"])
        self.assertEqual((c["fx_button_1"]["short"], c["fx_knob_1"]["short"]), ("On", "Level"))
        self.assertEqual((c["hotcue_1"]["short"], c["hotcue_1"]["alt"]), ("Cue A", "Cue E"))
        self.assertEqual(c["hotcue_1"]["shift_short"], "Delete A")
        self.r.engine.set_mode("x1_left", "L", "page", "stems")
        _, h = half(self.r.engine.view())
        self.assertEqual(h["rows"][0], "Drums")
        self.assertEqual(h["controls"]["fx_knob_1"]["short"], "Level")


class ShiftLatch(unittest.TestCase):
    def setUp(self):
        self.r = Rig("performance_mod")

    def test_latched_shift_applies_to_the_hardware(self):
        self.r.engine.set_shift_latch("x1_left", True)
        self.r.msg("x1_left", L, 0x02, 0x7F)                  # hot cue 1, pressed on the hardware without Shift
        self.r.msg("x1_left", OFF, 0x02, 0)
        self.assertEqual(self.r.sent(), [("PAD1_HotCue+Shift", 1, 127), ("PAD1_HotCue+Shift", 1, 0)])
        dev, _ = half(self.r.engine.view())
        self.assertTrue(dev["shift_latched"])
        self.r.engine.set_shift_latch("x1_left", False)
        self.r.msg("x1_left", L, 0x02, 0x7F)
        self.assertEqual(self.r.sent(), [("PAD1_HotCue", 1, 127)])

    def test_devices_without_shift_refuse_the_latch(self):
        with self.assertRaises(ValueError):
            self.r.engine.set_shift_latch("f1_left", True)

    def test_fx_assign_short_labels(self):
        _, h = half(self.r.engine.view())
        self.assertEqual((h["controls"]["fx_assign_1"]["short"], h["controls"]["fx_assign_2"]["short"]), ("FX1", "FX2"))
        self.assertEqual(h["controls"]["browse"]["short"], "Browse")
        self.assertEqual(h["controls"]["browse_push"]["short"], "Load")


class Definitions(unittest.TestCase):
    def test_the_window_gets_every_device_layout(self):
        from rekordtrakt.shell.app import definitions
        d = definitions()
        self.assertEqual(set(d), {"x1mk3", "f1"})
        self.assertEqual(d["x1mk3"]["name"], "Kontrol X1 MK3")
        self.assertTrue(d["x1mk3"]["has_shift"])
        self.assertIn("layout", d["f1"])
        self.assertNotIn("in", next(iter(d["f1"]["controls"].values())))      # no MIDI details for the window


class WindowAsController(unittest.TestCase):
    """The window's on-screen controls (source "ui") next to the hardware."""

    def setUp(self):
        self.r = Rig("performance_mod")

    def ui(self, control, kind, value=0, shift=False):
        self.r.engine.handle(Event("x1_left", control, kind, value, shift, "ui"))

    def test_window_and_hardware_hold_separately(self):
        self.r.msg("x1_left", L, 0x08, 0x7F)                  # hardware: Cue down
        self.ui("L.cue", PRESS)                               # window: Cue down too
        self.ui("L.cue", RELEASE)                             # window lets go...
        self.assertEqual(self.r.sent(), [("Cue", 1, 127)])     # ...Rekordbox still has Cue held, by the hardware
        self.assertIn(("x1_left", "L.cue", "hw"), self.r.engine.held)
        self.r.msg("x1_left", 0x80, 0x08, 0)
        self.assertEqual(self.r.sent(), [("Cue", 1, 0)])

    def test_release_source_lets_go_of_window_presses_only(self):
        self.r.msg("x1_left", L, 0x08, 0x7F)
        self.ui("L.play", PRESS)
        self.r.sent()
        self.r.engine.release_source("ui")
        self.assertEqual(self.r.sent(), [("PlayPause", 1, 0)])
        self.assertEqual(list(self.r.engine.held), [("x1_left", "L.cue", "hw")])

    def test_window_knob_makes_the_hardware_knob_pick_up(self):
        self.r.engine.set_option("x1_left", "knob_pickup", True)
        self.r.msg("x1_left", 0xB0, 0x10, 30)                 # hardware knob 1 at 30
        self.ui("L.fx_knob_1", VALUE, 100)                    # moved to 100 in the window
        self.r.sent()
        self.r.msg("x1_left", 0xB0, 0x10, 31)                 # hardware nudged: must not jump back to 31
        self.assertEqual(self.r.sent(), [])
        _, h = half(self.r.engine.view())
        self.assertEqual(h["controls"]["fx_knob_1"]["pickup"], 100)

    def test_knob_defaults(self):
        self.r.engine.set_mode("x1_left", "L", "page", "mixer")
        _, h = half(self.r.engine.view())
        self.assertEqual(h["controls"]["fx_knob_1"]["default"], 64)        # EQ: centre
        self.assertNotIn("default", h["controls"]["fx_knob_4"])            # volume: no neutral position

    def test_rename_is_saved_and_shown(self):
        self.r.engine.rename("x1_left", "  Booth X1 ")
        dev, _ = half(self.r.engine.view())
        self.assertEqual((dev["name"], self.r.saved[-1].name), ("Booth X1", "Booth X1"))
        self.assertEqual((dev["type_name"], dev["mapping"]), ("Kontrol X1 MK3", "X1 MK3 default (based on the Performance Mod)"))


class Blinking(unittest.TestCase):
    def setUp(self):
        self.r = Rig("performance_mod")

    def blink(self, times, every=0.25):
        for i in range(times):
            self.r.feedback("PlayPause", 1, 127 if i % 2 == 0 else 0)
            self.r.clock.t += every

    def test_a_steady_blink_is_one_state_not_a_stream_of_changes(self):
        self.blink(4)
        _, h = half(self.r.engine.view())
        self.assertEqual(h["controls"]["play"]["led"], "blink")
        version = self.r.engine.view_version
        self.blink(8)
        self.assertEqual(self.r.engine.view_version, version)           # nothing new to draw while it blinks
        self.r.engine.tick()
        self.assertEqual(self.r.engine.view_version, version)

    def test_blinking_stops_when_feedback_goes_quiet(self):
        self.blink(4)
        self.r.feedback("PlayPause", 1, 127)                            # playing: steady on
        self.r.clock.t += 1.5
        version = self.r.engine.view_version
        self.r.engine.tick()
        self.assertGreater(self.r.engine.view_version, version)
        _, h = half(self.r.engine.view())
        self.assertEqual(h["controls"]["play"]["led"], 127)

    def test_single_changes_are_not_blinking(self):
        self.r.feedback("PlayPause", 1, 127)
        self.r.clock.t += 2
        self.r.feedback("PlayPause", 1, 0)
        _, h = half(self.r.engine.view())
        self.assertEqual(h["controls"]["play"]["led"], 0)


class Pages(unittest.TestCase):
    def setUp(self):
        self.r = Rig("performance_mod")

    def next_page(self):
        self.r.msg("x1_left", SL, 0x01, 0x7F)
        self.r.msg("x1_left", OFF, 0x01, 0)
        return self.r.engine.devices["x1_left"].modes["L"]["page"]

    def test_disabled_pages_are_skipped_in_the_chosen_order(self):
        self.r.engine.set_pages("x1_left", ["fx", "stems", "cfx_single"])
        self.assertEqual([self.next_page() for _ in range(4)], ["stems", "cfx_single", "fx", "stems"])
        self.assertEqual(self.r.saved[-1].options["pages"], ["fx", "stems", "cfx_single"])

    def test_turning_off_the_current_page_moves_to_the_first(self):
        self.r.engine.set_pages("x1_left", ["stems", "mixer"])
        self.assertEqual(self.r.engine.devices["x1_left"].modes["L"]["page"], "stems")

    def test_bad_page_lists_are_refused(self):
        with self.assertRaises(ValueError):
            self.r.engine.set_pages("x1_left", [])
        with self.assertRaises(ValueError):
            self.r.engine.set_pages("x1_left", ["fx", "fx"])


class LiveSettings(unittest.TestCase):
    def setUp(self):
        self.rig = json.loads(json.dumps(EXAMPLE))
        for d in self.rig["devices"].values():
            d["profile"] = d.get("profile") or ""
        self.rig["devices"]["x1_left"]["profile"] = "performance_mod"
        names = [self.rig["bridge"]["app_port"], self.rig["bridge"]["rekordbox_port"],
                 self.rig["devices"]["x1_left"]["port"]]
        self.hub = EventHub()
        self.saved = []
        app, bridge = self.rig["bridge"]["app_port"], self.rig["bridge"]["rekordbox_port"]
        self.t = Translator(FakeMidi(names, links={app: bridge, bridge: app}), load_rig=lambda: self.rig,
                            ensure_bridge=lambda a, b: {"ok": True, "state": "existing", "message": "ok"},
                            checks=lambda rig, csv: [], on_view=lambda v: self.hub.set_state("view", v),
                            save_device=self.saved.append, read_rekordbox=as_installed)
        self.t.start()
        end = time.monotonic() + 3
        while self.t.state != RUNNING and time.monotonic() < end:
            time.sleep(0.01)

    def tearDown(self):
        self.t.stop()

    def latest_view(self):
        return self.hub.states["view"]["data"]

    def test_settings_apply_on_the_translator_thread_and_save(self):
        self.t.set_option("x1_left", "beatjump_size", 8)
        self.t.assign("x1_left", "L", deck=2)
        self.t.set_page("x1_left", "R", "stems")
        dev = self.t.call(lambda eng: eng.devices["x1_left"])
        self.assertEqual((dev.options["beatjump_size"], dev.decks[0], dev.modes["R"]["page"]), (8, 2, "stems"))
        self.assertTrue(self.saved)

    def test_view_is_published_after_changes(self):
        self.t.assign("x1_left", "L", deck=4)
        end = time.monotonic() + 2
        while time.monotonic() < end and half(self.latest_view())[1]["deck"] != 4:
            time.sleep(0.02)
        self.assertEqual(half(self.latest_view())[1]["deck"], 4)

    def test_bad_settings_are_refused(self):
        with self.assertRaises(ValueError):
            self.t.set_option("x1_left", "beatjump_size", 3)
        with self.assertRaises(ValueError):
            self.t.set_option("x1_left", "nonsense", 1)
        with self.assertRaises(ValueError):
            self.t.assign("x1_left", "L", deck=7)
        with self.assertRaises(ValueError):
            self.t.set_page("nowhere", "L", "fx")
        with self.assertRaises(ValueError):
            self.t.assign("f1_left", deck=2, slot=5)             # the F1 has two deck slots
        with self.assertRaises(ValueError):
            self.t.assign("f1_left", deck=2, fx=1, slot=0)       # one at a time
        with self.assertRaises(ValueError):
            self.t.assign("x1_left", deck=2, slot=0)             # an X1 is moved by half

    def test_an_f1_is_moved_by_slot(self):
        self.t.assign("f1_left", deck=4, slot=1)
        self.t.assign("f1_left", fx=2, slot=0)
        dev = self.t.call(lambda eng: eng.devices["f1_left"])
        self.assertEqual((dev.decks, dev.fx_units), ([1, 4], [2]))

    def test_bypass_releases_then_sends_nothing(self):
        app = self.rig["bridge"]["app_port"]
        midi = self.t.midi
        self.t.ui_input("x1_left", "L.cue", "press")
        before = len(midi.sent[app])
        self.t.set_bypass(True)
        released = midi.sent[app][before:]
        self.assertTrue(released and all(d2 == 0 for _, _, d2 in released))      # everything let go first
        after = len(midi.sent[app])
        self.t.ui_input("x1_left", "L.play", "press")
        self.t.ui_input("x1_left", "L.play", "release")
        self.assertEqual(len(midi.sent[app]), after)                              # then nothing reaches Rekordbox
        self.assertTrue(self.t.snapshot()["bypass"])
        self.t.set_bypass(False)
        self.t.ui_input("x1_left", "L.play", "press")
        self.assertGreater(len(midi.sent[app]), after)

    def test_window_input_is_validated(self):
        self.t.ui_input("x1_left", "L.play", "press")
        self.t.ui_input("x1_left", "L.play", "release")
        with self.assertRaises(ValueError):
            self.t.ui_input("x1_left", "L.play", "value", 3)         # a button can't take a value
        with self.assertRaises(ValueError):
            self.t.ui_input("x1_left", "L.fx_knob_1", "value", 300)
        with self.assertRaises(ValueError):
            self.t.ui_input("x1_left", "L.nothing", "press")

    def test_rename_updates_the_status_names(self):
        self.t.rename("x1_left", "Booth X1")
        self.assertEqual(self.t.snapshot()["devices"]["x1_left"]["name"], "Booth X1")
        with self.assertRaises(ValueError):
            self.t.rename("x1_left", "   ")

    def test_stopping_clears_the_view(self):
        self.t.stop()
        self.assertIsNone(self.hub.states["view"]["data"])
        with self.assertRaises(RuntimeError):
            self.t.set_option("x1_left", "beatjump_size", 8)


class States(unittest.TestCase):
    def test_latest_state_only_and_in_the_backlog(self):
        hub = EventHub()
        hub.publish({"kind": "notice", "text": "a"})
        hub.set_state("view", {"n": 1})
        hub.set_state("view", {"n": 2})
        _, backlog = hub.subscribe()
        self.assertEqual([e["kind"] for e in backlog], ["notice", "view"])
        self.assertEqual(backlog[-1]["data"], {"n": 2})


if __name__ == "__main__":
    unittest.main()
