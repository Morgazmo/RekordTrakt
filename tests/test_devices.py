"""Device definitions (data files) against the hand-written classes they replaced: every possible note and CC
message must decode the same, and every LED must light the same way.

Run from the repo root:  python -m unittest discover -s tests
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import isolated                                                            # noqa: E402,F401  (first)
from legacy_devices import LegacyF1, LegacyX1MK3                          # noqa: E402
from rekordtrakt.devices import DEVICE_TYPES                              # noqa: E402
from rekordtrakt.devices.defined import DefinedDevice, DefinitionError    # noqa: E402

VALUES = (0, 1, 2, 63, 64, 65, 126, 127)


class Parity(unittest.TestCase):
    def check(self, legacy, new):
        for status in range(0x80, 0xC0):
            for d1 in range(128):
                for d2 in VALUES:
                    self.assertEqual(legacy.decode(status, d1, d2), new.decode(status, d1, d2),
                                     f"{status:02X} {d1:02X} {d2:02X}")
        self.assertEqual(sorted(legacy.led_controls()), sorted(new.led_controls()))
        names = {n for n, _ in legacy.controls()} | set(new.led_controls())
        for control in names:
            for value in (0, 1, 64, 127, True, False):
                self.assertEqual(legacy.led(control, value), new.led(control, value), (control, value))
        self.assertEqual(sorted(legacy.controls()), sorted(new.controls()))
        for attr in ("type_name", "display_name", "led_interval", "has_halves", "has_shift"):
            self.assertEqual(getattr(legacy, attr), getattr(new, attr), attr)

    def test_x1mk3(self):
        self.check(LegacyX1MK3(), DEVICE_TYPES["x1mk3"]())

    def test_f1(self):
        self.check(LegacyF1(), DEVICE_TYPES["f1"]())


class Layouts(unittest.TestCase):
    def test_every_control_is_placed_once(self):
        for t, make in DEVICE_TYPES.items():
            dev = make()
            pub = dev.public()
            placed = []
            for item in pub["layout"]["items"]:
                if "control" in item:
                    placed.append(item["control"])
                    if item.get("push"):
                        placed.append(item["push"])
            self.assertEqual(sorted(placed), sorted(pub["controls"]), t)

    def test_positions_dont_overlap(self):
        for t, make in DEVICE_TYPES.items():
            cells = {}
            for item in make().public()["layout"]["items"]:
                if item.get("role") == "row":          # row frames sit behind their controls on purpose
                    continue
                for dc in range(item.get("w", 1)):
                    for dr in range(item.get("h", 1)):
                        key = (item["c"] + dc, item["r"] + dr)
                        self.assertNotIn(key, cells, f"{t}: {item} overlaps {cells.get(key)}")
                        cells[key] = item


class Validation(unittest.TestCase):
    def test_clashing_messages_are_refused(self):
        bad = json.loads(json.dumps(DEVICE_TYPES["f1"]().definition))
        bad["controls"][1]["in"] = dict(bad["controls"][0]["in"])
        with self.assertRaises(DefinitionError):
            DefinedDevice(bad)

    def test_encoders_need_a_relative_style(self):
        bad = json.loads(json.dumps(DEVICE_TYPES["f1"]().definition))
        enc = next(c for c in bad["controls"] if c["kind"] == "encoder")
        del enc["in"]["relative"]
        with self.assertRaises(DefinitionError):
            DefinedDevice(bad)


if __name__ == "__main__":
    unittest.main()
