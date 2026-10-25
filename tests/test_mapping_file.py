"""Controllers from .midi.xml mapping files, and adding/removing controllers from the window.
Run from the repo root:  python -m unittest discover -s tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from isolated import EXAMPLE                                                 # noqa: E402  (first)
from rekordtrakt import rig as rig_mod                                       # noqa: E402
from rekordtrakt.bridge.client import BridgeClient                           # noqa: E402
from rekordtrakt.devices import DEVICE_TYPES, mapping_file, reload_device_types   # noqa: E402
from rekordtrakt.devices.defined import DefinedDevice                        # noqa: E402
from rekordtrakt.engine.engine import Engine                                 # noqa: E402
from rekordtrakt.engine.leds import LedEngine                                # noqa: E402
from rekordtrakt.profiles import PROFILES                                    # noqa: E402
from rekordtrakt.service import full_bridge                                  # noqa: E402
from rekordtrakt.shell.controller_setup import ControllerSetup               # noqa: E402

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<MixxxControllerPreset mixxxVersion="2.4" schemaVersion="1">
  <info><name>Acme DJ-2</name><author>someone</author></info>
  <controller id="DJ2">
    <scriptfiles><file filename="Acme-DJ2.js" functionprefix="DJ2"/></scriptfiles>
    <controls>
      <control><group>[Channel1]</group><key>play</key><description>Play (left)</description>
        <status>0x90</status><midino>0x0B</midino><options><normal/></options></control>
      <control><group>[Channel1]</group><key>play</key><status>0x80</status><midino>0x0B</midino>
        <options><normal/></options></control>
      <control><group>[Channel1]</group><key>cue_default</key><description>Cue (left)</description>
        <status>0x90</status><midino>0x0C</midino></control>
      <control><group>[Channel1]</group><key>hotcue_1_activate</key><status>0x97</status><midino>0x00</midino></control>
      <control><group>[Channel2]</group><key>play</key><description>Play (right)</description>
        <status>0x91</status><midino>0x0B</midino></control>
      <control><group>[Channel1]</group><key>volume</key><description>Volume (left)</description>
        <status>0xB0</status><midino>0x13</midino></control>
      <control><group>[EqualizerRack1_[Channel1]_Effect1]</group><key>parameter1</key><description>Low (left)</description>
        <status>0xB0</status><midino>0x0F</midino></control>
      <control><group>[Library]</group><key>MoveVertical</key><description>Browse</description>
        <status>0xB6</status><midino>0x40</midino><options><selectknob/></options></control>
      <control><group>[Channel1]</group><key>DJ2.jogTurn</key><description>Jog (left)</description>
        <status>0xB0</status><midino>0x21</midino><options><script-binding/></options></control>
      <control><group>[Channel1]</group><key>rate</key><description>Tempo (left)</description>
        <status>0xB0</status><midino>0x00</midino><options><fourteen-bit-msb/></options></control>
      <control><group>[Channel1]</group><key>rate</key><status>0xB0</status><midino>0x20</midino>
        <options><fourteen-bit-lsb/></options></control>
    </controls>
    <outputs>
      <output><group>[Channel1]</group><key>play_indicator</key><status>0x90</status><midino>0x0B</midino>
        <on>0x7F</on><off>0x00</off><minimum>0.5</minimum></output>
    </outputs>
  </controller>
</MixxxControllerPreset>"""


class Import(unittest.TestCase):
    def setUp(self):
        self.definition, self.mapping, self.report = mapping_file.to_rekordtrakt(SAMPLE, "DJ-2 MIDI")

    def test_a_definition_rekordtrakt_can_load(self):
        dev = DefinedDevice(self.definition)
        self.assertRegex(self.definition["type"], r"^imported_acme_dj_2_[0-9a-f]{6}$")
        self.assertEqual(self.report["controls"], 9)                 # note-off and the 14-bit LSB aren't controls
        kinds = dev.control_kinds()
        self.assertEqual(kinds[next(c["id"] for c in self.definition["controls"] if c["name"] == "Browse")], "encoder")
        self.assertTrue(next(c for c in self.definition["controls"] if c["name"] == "Play (left)").get("led"))
        self.assertEqual(len(self.definition["layout"]["items"]), 9)

    def test_controls_with_a_rekordbox_equivalent_are_mapped_to_the_right_deck(self):
        got = {next(c["name"] for c in self.definition["controls"] if c["id"] == b["control"]):
               (b["action"]["function"], b["action"].get("deck")) for b in self.mapping["bindings"]}
        # Each deck the file drives is a deck slot of its own, starting on that deck, so it can be moved.
        self.assertEqual(self.definition["deck_slots"], [{"key": "a", "label": "First deck", "default": 1},
                                                         {"key": "b", "label": "Second deck", "default": 2}])
        self.assertEqual(got["Play (left)"], ("PlayPause", "a"))
        self.assertEqual(got["Play (right)"], ("PlayPause", "b"))
        self.assertEqual(got["Cue (left)"], ("Cue", "a"))
        self.assertEqual(got["Volume (left)"], ("ChannelFader", "a"))
        self.assertEqual(got["Low (left)"], ("EQLow", "a"))
        self.assertEqual(got["Browse"], ("Browse", None))
        self.assertIn(("PAD1_HotCue", "a"), got.values())
        self.assertEqual(self.report["mapped"], 8)
        self.assertIn("Jog (left)", self.report["scripted"])

    def test_not_a_mapping_file(self):
        with self.assertRaises(mapping_file.MappingFileError):
            mapping_file.to_rekordtrakt("<html></html>")

    def test_the_window_never_names_other_software_as_a_source(self):
        # The import reads a file the user picks; the window doesn't suggest RekordTrakt depends on anyone's library.
        from rekordtrakt.shell.app import midi_devices

        class Midi:
            def input_names(self):
                return ["Acme DJ-2 MIDI"]
        texts = [d["text"] for d in midi_devices(Midi(), {"devices": {}, "bridge": {}})]
        web = Path(__file__).resolve().parents[1] / "rekordtrakt" / "shell" / "web"
        texts += [f.read_text(encoding="utf-8") for f in web.rglob("*") if f.suffix in (".js", ".html", ".css")]
        self.assertFalse([t for t in texts if "mixxx" in t.lower()])
        self.assertNotIn("mixxx", json.dumps(self.definition).lower())


class AddingControllers(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.rig = json.loads(json.dumps(EXAMPLE))
        self.restarts = []

        class Sup:
            def restart(inner, reason):
                self.restarts.append(reason)

        self.setup = ControllerSetup(Sup(), load_rig=lambda: json.loads(json.dumps(self.rig)),
                                     save_rig=lambda rig: self.rig.update(rig), definitions=self.folder,
                                     later=lambda fn, *args: fn(*args))

    def tearDown(self):
        reload_device_types()                       # leave the built-in types as they were

    def test_import_adds_a_working_controller(self):
        result = self.setup.import_file({"xml": SAMPLE, "port": "DJ-2 MIDI"})
        self.assertIn(result["type"], DEVICE_TYPES)
        self.assertTrue((self.folder / f"{result['type']}.json").exists())
        entry = self.rig["devices"][result["position"]]
        self.assertEqual((entry["type"], entry["port"]), (result["type"], "DJ-2 MIDI"))
        self.assertEqual(len(self.restarts), 1)
        # the engine runs it with no preset: its imported mapping does the work
        sent = []

        class Out:
            def send(self, *m):
                sent.append(m)

        manifest = full_bridge(self.rig)[1]
        devices = [d for d in rig_mod.device_configs(self.rig) if d.position == result["position"]]
        leds = LedEngine(lambda: 0.0)
        for d in devices:
            leds.add_device(d.position, d.device, Out())
        engine = Engine(devices, PROFILES, BridgeClient(Out(), manifest), leds, lambda: 0.0, log=lambda *_: None)
        self.assertEqual((entry["decks"], entry["fx_units"]), ([1, 2], []))
        engine.device_message(result["position"], 0x90, 0x0B, 0x7F)                 # Play (left)
        play = next(e for e in manifest["entries"] if e["function"] == "PlayPause" and e["deck"] == 1)["input"]
        self.assertIn((play["status"], play["data1"], 0x7F), sent)
        # moving its first deck to deck 3 moves the controls that drove deck 1
        engine.device_message(result["position"], 0x80, 0x0B, 0)
        engine.assign(result["position"], deck=3, slot=0)
        sent.clear()
        engine.device_message(result["position"], 0x90, 0x0B, 0x7F)
        play3 = next(e for e in manifest["entries"] if e["function"] == "PlayPause" and e["deck"] == 3)["input"]
        self.assertIn((play3["status"], play3["data1"], 0x7F), sent)

    def test_a_different_file_with_the_same_name_never_changes_the_first(self):
        first = self.setup.import_file({"xml": SAMPLE})
        saved = (self.folder / f"{first['type']}.json").read_text(encoding="utf-8")
        other = self.setup.import_file({"xml": SAMPLE.replace("<midino>0x0B</midino>", "<midino>0x2B</midino>")})
        self.assertNotEqual(first["type"], other["type"])
        self.assertEqual((self.folder / f"{first['type']}.json").read_text(encoding="utf-8"), saved)
        self.assertEqual((first["name"], other["name"]), ("Acme DJ-2", "Acme DJ-2 (2)"))
        again = self.setup.import_file({"xml": SAMPLE})                  # the same file: the same controller
        self.assertEqual(again["type"], first["type"])

    def test_a_first_run_starts_with_an_empty_rig_and_controllers_can_be_added(self):
        path = Path(tempfile.mkdtemp()) / "rig.json"
        setup = ControllerSetup(type(self.setup.supervisor)(), load_rig=lambda: rig_mod.load(path),
                                save_rig=lambda rig: rig_mod.save(rig, path), definitions=self.folder,
                                later=lambda fn, *args: fn(*args))
        self.assertEqual(rig_mod.load(path), rig_mod.new_rig())
        position = setup.add({"port": "TRAKTOR X1 MK3", "type": "x1mk3"})["position"]
        self.assertEqual(rig_mod.load(path)["devices"][position]["port"], "TRAKTOR X1 MK3")

    def test_an_added_controller_is_known_by_its_unit(self):
        self.setup.port_units = lambda: {"5 - TRAKTOR X1 MK3": "USB\\VID_17CC&PID_2200\\A1B2C3D4"}
        position = self.setup.add({"port": "5 - TRAKTOR X1 MK3", "type": "x1mk3"})["position"]
        self.assertEqual(self.rig["devices"][position]["unit"], "USB\\VID_17CC&PID_2200\\A1B2C3D4")

    def test_add_and_remove(self):
        result = self.setup.add({"port": "5 - TRAKTOR X1 MK3", "type": "x1mk3"})
        entry = self.rig["devices"][result["position"]]
        self.assertEqual((entry["profile"], entry["decks"]), ("performance_mod", [1, 2]))
        with self.assertRaises(ValueError):
            self.setup.add({"port": "5 - TRAKTOR X1 MK3", "type": "x1mk3"})     # already added
        self.setup.remove({"position": result["position"]})
        self.assertNotIn(result["position"], self.rig["devices"])
        self.assertEqual(len(self.restarts), 2)


if __name__ == "__main__":
    unittest.main()
