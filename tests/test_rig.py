"""Your rig file: the first run, and controllers that follow their unit when Windows renumbers identical ports."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from isolated import EXAMPLE                                       # noqa: E402  (first)
from rekordtrakt import rig as rig_mod                             # noqa: E402
from rekordtrakt.bridge import ports                               # noqa: E402
from rekordtrakt.midi.fake import FakeMidi                         # noqa: E402
from rekordtrakt.service import Translator                         # noqa: E402

LEFT, RIGHT = "USB\\VID_17CC&PID_2200\\A1B2C3D4", "USB\\VID_17CC&PID_2200\\E5F6A7B8"


def rig_with_units():
    rig = json.loads(json.dumps(EXAMPLE))
    rig["devices"]["x1_left"]["unit"] = LEFT              # on "2 - TRAKTOR X1 MK3"
    rig["devices"]["x1_right"]["unit"] = RIGHT            # on "TRAKTOR X1 MK3"
    return rig


class FirstRun(unittest.TestCase):
    def test_a_new_rig_has_the_bridge_ports_and_no_controllers(self):
        path = Path(tempfile.mkdtemp()) / "rig.json"
        self.assertEqual(rig_mod.load(path), {"bridge": {"app_port": "RekordTrakt App",
                                                         "rekordbox_port": "RekordTrakt Bridge"}, "devices": {}})
        self.assertTrue(path.exists())

    def test_a_rig_from_a_source_checkout_moves_to_the_user_folder(self):
        folder = Path(tempfile.mkdtemp())
        old, new = folder / "rig.local.json", folder / "data" / "rig.json"
        old.write_text(json.dumps(EXAMPLE), encoding="utf-8")
        with mock.patch.object(rig_mod, "RIG_FILE", new), mock.patch.object(rig_mod, "OLD_RIG_FILE", old):
            self.assertEqual(rig_mod.load(new)["devices"].keys(), EXAMPLE["devices"].keys())
        self.assertTrue(old.exists())                     # copied, never removed

    def test_saving_never_leaves_half_a_file(self):
        path = Path(tempfile.mkdtemp()) / "rig.json"
        rig_mod.save(EXAMPLE, path)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), EXAMPLE)
        self.assertFalse(path.with_suffix(".tmp").exists())


class Units(unittest.TestCase):
    def test_identical_controllers_renumbered_by_windows_follow_their_units(self):
        rig = rig_with_units()
        moves = rig_mod.follow_units(rig, {"TRAKTOR X1 MK3": LEFT, "2 - TRAKTOR X1 MK3": RIGHT})   # swapped
        self.assertEqual((rig["devices"]["x1_left"]["port"], rig["devices"]["x1_right"]["port"]),
                         ("TRAKTOR X1 MK3", "2 - TRAKTOR X1 MK3"))
        self.assertEqual(len(moves), 1)                   # one move swaps both

    def test_a_controller_without_a_unit_learns_the_one_on_its_port(self):
        rig = json.loads(json.dumps(EXAMPLE))
        rig_mod.follow_units(rig, {"2 - TRAKTOR X1 MK3": LEFT})
        self.assertEqual(rig["devices"]["x1_left"]["unit"], LEFT)
        self.assertNotIn("unit", rig["devices"]["x1_right"])

    def test_a_unit_that_isnt_connected_keeps_its_port(self):
        rig = rig_with_units()
        self.assertEqual(rig_mod.follow_units(rig, {"TRAKTOR X1 MK3": RIGHT}), [])
        self.assertEqual(rig["devices"]["x1_left"]["port"], "2 - TRAKTOR X1 MK3")

    def test_a_unit_with_several_ports_keeps_the_one_with_its_name(self):
        rig = {"devices": {"pad": {"type": "x1mk3", "port": "MIDIIN2 (LPProMK3 MIDI)", "unit": "USB\\LP"}}}
        rig_mod.follow_units(rig, {"LPProMK3 MIDI": "USB\\LP", "2 - MIDIIN2 (LPProMK3 MIDI)": "USB\\LP"})
        self.assertEqual(rig["devices"]["pad"]["port"], "2 - MIDIIN2 (LPProMK3 MIDI)")

    def test_virtual_ports_have_no_unit(self):
        helper = lambda *args: {"success": True, "ports": [                         # noqa: E731
            {"name": "TRAKTOR X1 MK3", "unit": RIGHT}, {"name": "RekordTrakt App", "unit": "SWD\\MIDISRV\\LOOP"}]}
        self.assertEqual(ports.port_units(helper), {"TRAKTOR X1 MK3": RIGHT})
        self.assertEqual(ports.port_units(lambda *args: {"success": False}), {})

    def test_a_replugged_controller_under_a_new_name_is_picked_up(self):
        t = Translator(FakeMidi([]), port_units=lambda: {"3 - TRAKTOR X1 MK3": LEFT})
        t.devices = {"x1_left": {"port": "2 - TRAKTOR X1 MK3", "connected": False, "unit": LEFT}}
        self.assertEqual(t.missing_ports(["3 - TRAKTOR X1 MK3"]), ["x1_left"])
        t.port_units = lambda: self.fail("asked again with no change in the port list")
        self.assertEqual(t.missing_ports(["3 - TRAKTOR X1 MK3"]), [])


if __name__ == "__main__":
    unittest.main()
