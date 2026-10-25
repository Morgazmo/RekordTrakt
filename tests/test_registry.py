"""The action registry, its permanent addresses and the full-coverage bridge.

Run from the repo root:  python -m unittest discover -s tests
"""
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from isolated import EXAMPLE                                                       # noqa: E402  (first)
from rekordtrakt.bridge.client import BridgeClient                                 # noqa: E402
from rekordtrakt.bridge.compiler import (CATALOGUES, canonical_mappings, compile_bridge,  # noqa: E402
                                         load_catalogue, read_bridge)
from rekordtrakt.rekordbox import addresses, registry                              # noqa: E402
from rekordtrakt.service import bridge_status, full_bridge, make_engine, preflight  # noqa: E402


# Each shipped registry version's part of addresses.json, frozen: (functions, sha256 of their entries). An address
# that changes after Rekordbox has it installed would make presses fire the wrong function. Add a line per version.
FROZEN = {1: (255, "6ed17643e37b86008c57d90f6d551f4e57ef1c2346cfebc32bdf2f85582816c4"),
          2: (230, "d1cb41859282fb145b6f9f6fc5a8a051e1d7fb2fc01f92680e36e4e5114ab46a")}


def rig():
    return json.loads(json.dumps(EXAMPLE))


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, *msg):
        self.sent.append(msg)


def rekordbox_rewrite(csv_text):
    """What Rekordbox does to a mapping file it rewrites: rows sorted, "base + channel per deck"
    expanded into explicit messages, ';' after options, "Pad" renamed "DdjSxPad"."""
    header, *rows = csv_text.strip().split("\r\n")
    out = []
    for row in rows:
        f = row.split(",")
        for first in (3, 8):
            base, cols = f[first], f[first + 1:first + 5]
            if base and any(cols):
                f[first + 1:first + 5] = [f"{base[0]}{int(c):X}{base[2:]}" if c else "" for c in cols]
        if f[13]:
            f[13] += ";"
        if f[2] == "Pad":
            f[2] = "DdjSxPad"
        out.append(",".join(f))
    return "\r\n".join([header, *sorted(out)]) + "\r\n"


class Registry(unittest.TestCase):
    def test_every_function_is_one_its_rekordbox_has(self):
        v6, v7 = load_catalogue(CATALOGUES[6]), load_catalogue(CATALOGUES[7])
        self.assertEqual([f.name for f in registry.FUNCTIONS if f.rekordbox == 6 and (f.name, f.rb_type) not in v6], [])
        self.assertEqual([f.name for f in registry.FUNCTIONS if (f.name, f.rb_type) not in v7], [])

    def test_every_function_the_mappings_use_is_in_it(self):
        for x1_profile in ("performance_mod", ""):
            r = rig()
            r["devices"]["x1_left"]["profile"] = x1_profile
            missing = {f for f, _ in make_engine(r, None, None).uses() if f not in registry.BY_NAME}
            self.assertEqual(missing, set(), x1_profile)

    def test_editor_metadata(self):
        for f in registry.FUNCTIONS:
            self.assertTrue(f.category and f.label, f.name)
            self.assertIn(f.scope, ("deck", "global"))
            self.assertEqual(f.semantics == "feedback", f.rb_type in addresses.OUTPUT_ONLY_TYPES, f.name)


class Addresses(unittest.TestCase):
    def setUp(self):
        self.table = addresses.load_table()

    def test_every_registry_function_has_an_address(self):
        self.assertEqual(len(addresses.append_missing(list(self.table.values()), registry.FUNCTIONS)), len(self.table))
        self.assertEqual(set(self.table), set(registry.BY_NAME))

    def test_shipped_addresses_never_change(self):
        entries = list(self.table.values())
        for version, (count, digest) in FROZEN.items():
            part = [e for e in entries if e["since"] == version]
            self.assertEqual(len(part), count, f"registry v{version}")
            self.assertEqual(hashlib.sha256(json.dumps(part, sort_keys=True).encode()).hexdigest(), digest,
                             f"addresses of registry v{version} changed: they must stay as installed")
        self.assertEqual([e["since"] for e in entries], sorted(e["since"] for e in entries), "append only")

    def test_appending_leaves_existing_addresses_alone(self):
        entries = list(self.table.values())
        new = registry.Function("TrackNext2", "Button", "deck", "trigger", since=3)
        grown = addresses.append_missing(entries, [*registry.FUNCTIONS, new])
        self.assertEqual(grown[:len(entries)], entries)
        added = grown[-1]
        self.assertEqual((added["function"], added["since"]), ("TrackNext2", 3))
        self.assertIn(added["in"]["kind"], ("note", "cc_button"))
        notes = added["in"]["kind"] == "note"
        taken = {(ch, n) for e in entries if e.get("in") and (e["in"]["kind"] == "note") == notes
                 for ch, n in e["in"]["at"]}
        self.assertFalse(taken & {tuple(a) for a in added["in"]["at"]})

    def test_plan_channels_and_ranges(self):
        for e in self.table.values():
            f = registry.BY_NAME[e["function"]]
            self.assertEqual("in" in e, addresses.input_kind(f.rb_type) is not None, f.name)
            self.assertEqual("out" in e, bool(f.feedback), f.name)
            for side, main, glob, over in (("in", addresses.DECK_IN, addresses.GLOBAL_IN, addresses.OVERFLOW_IN),
                                           ("out", addresses.DECK_OUT, addresses.GLOBAL_OUT, addresses.OVERFLOW_OUT)):
                if side not in e:
                    continue
                at = [tuple(a) for a in e[side]["at"]]
                self.assertEqual(len(at), 4 if f.scope == "deck" else 1, f.name)
                for ch, n in at:
                    self.assertIn(ch, (*main, glob, *over) if f.scope == "global" else (*main, *over), f.name)
                    self.assertIn(n, addresses.RANGES[e[side]["kind"]], f.name)
                if f.scope == "deck" and at[0][0] in main:
                    self.assertEqual(at, [(ch, at[0][1]) for ch in main], f.name)

    def test_pad_families_stay_together(self):
        families = {}
        for e in self.table.values():
            m = re.fullmatch(r"PAD\d_(.+)", e["function"])
            if m and "in" in e:
                families.setdefault(m.group(1), set()).add(e["in"]["at"][0][0] in addresses.DECK_IN)
        self.assertTrue(all(len(placed) == 1 for placed in families.values()), families)
        self.assertEqual(families["BeatLoop"], {False}, "the beat loop pads are the first overflow family")


class FullBridge(unittest.TestCase):
    def setUp(self):
        self.csv, self.manifest = full_bridge(rig())

    def test_covers_the_whole_registry_for_every_deck(self):
        for target in (6, 7):
            r = rig()
            r["bridge"]["rekordbox"] = target
            csv, manifest = full_bridge(r)
            functions = registry.for_target(target)
            deck = sum(1 for f in functions if f.scope == "deck")
            self.assertEqual(len(manifest["entries"]), 4 * deck + len(functions) - deck)
            self.assertEqual(len(csv.strip().split("\r\n")) - 1, len(functions))
        self.assertGreater(len(registry.for_target(7)), len(registry.for_target(6)))
        self.assertNotIn("ActivePartBass,", self.csv)                      # Rekordbox 7's only on a 7 bridge

    def test_buttons_past_the_notes_go_on_cc(self):
        row = next(r for r in self.csv.split("\r\n") if r.startswith("PAD1_SlicerLoop,"))
        self.assertTrue(all(col.startswith("B") for col in row.split(",")[4:8]), row)

    def test_overflow_rows_use_explicit_per_deck_messages(self):
        row = next(r for r in self.csv.split("\r\n") if r.startswith("PAD1_BeatLoop,"))
        self.assertEqual(row.split(",")[3:8], ["", "9500", "9501", "9502", "9503"])
        row = next(r for r in self.csv.split("\r\n") if r.startswith("PlayPause,"))
        self.assertEqual(row.split(",")[3:8], ["9000", "0", "1", "2", "3"])

    def test_reading_it_back_gives_the_same_addresses_even_after_rekordbox_rewrites_it(self):
        key = lambda m: {(e["function"], e["deck"]): (e["input"], e["output"]) for e in m["entries"]}  # noqa: E731
        rewritten = rekordbox_rewrite(self.csv)
        self.assertNotEqual(rewritten, self.csv)
        self.assertEqual(canonical_mappings(rewritten), canonical_mappings(self.csv))
        self.assertEqual(key(read_bridge(rewritten)), key(self.manifest))


class Status(unittest.TestCase):
    def setUp(self):
        self.rig = rig()
        self.uses = make_engine(self.rig, None, None).uses()

    def status(self, csv_text, direct=()):
        return bridge_status(self.rig, {"bridge": csv_text, "direct": list(direct)}, self.uses)

    def test_states(self):
        full = full_bridge(self.rig)[0]
        self.assertEqual(self.status(None)["state"], "missing")
        self.assertEqual(self.status(full)["state"], "current")
        self.assertEqual(self.status(rekordbox_rewrite(full))["state"], "current")
        just_the_rig = compile_bridge("RekordTrakt Bridge", registry.bridge_actions(self.uses))[0]
        self.assertEqual(self.status(just_the_rig)["state"], "update")          # works; more is available
        fewer = registry.bridge_actions([u for u in self.uses if u[0] != "PlayPause"])
        status = self.status(compile_bridge("RekordTrakt Bridge", fewer)[0])
        self.assertEqual((status["state"], status["missing"]), ("required", ["PlayPause"]))

    def test_warnings_say_what_to_do_without_a_command_line(self):
        full = full_bridge(self.rig)[0]
        self.assertEqual(preflight(self.rig, self.status(full)), [])
        for state_csv, words in ((None, "doesn't have"), (compile_bridge("RekordTrakt Bridge", [])[0], "missing")):
            text = " ".join(preflight(self.rig, self.status(state_csv)))
            self.assertIn(words, text)
            self.assertNotIn("python", text)
        text = preflight(self.rig, self.status(full, direct=["x1_left"]))[0]
        self.assertIn("X1 Left", text)
        self.assertIn("fire twice", text)


class Client(unittest.TestCase):
    def test_release_all_only_touches_what_the_rig_can_press(self):
        out = Recorder()
        manifest = full_bridge(rig())[1]
        client = BridgeClient(out, manifest, scope={("PlayPause", 1), ("Cue", 1)})
        client.press("Sync", 2)                  # held, though outside the scope: released too
        out.sent.clear()
        client.release_all()
        entries = {(e["function"], e["deck"]): e["input"] for e in manifest["entries"]}
        expected = {(entries[k]["status"], entries[k]["data1"], 0) for k in (("PlayPause", 1), ("Cue", 1), ("Sync", 2))}
        self.assertEqual(set(out.sent), expected)

    def test_a_function_rekordbox_doesnt_have_is_reported_once(self):
        from rekordtrakt.engine.engine import Engine
        from rekordtrakt.engine.leds import LedEngine
        from rekordtrakt.profiles import PROFILES
        from rekordtrakt import rig as rig_mod
        r = rig()
        uses = make_engine(r, None, None).uses()
        older = compile_bridge("RekordTrakt Bridge",
                               registry.bridge_actions([u for u in uses if u[0] != "PlayPause"]))[1]
        out, notices = Recorder(), []
        devices = rig_mod.device_configs(r)
        leds = LedEngine(lambda: 0.0)
        for dev in devices:
            leds.add_device(dev.position, dev.device, Recorder())
        engine = Engine(devices, PROFILES, BridgeClient(out, older), leds, lambda: 0.0, log=notices.append)
        for _ in range(2):
            engine.device_message("x1_left", 0x90, 0x0A, 0x7F)      # left Play
            engine.device_message("x1_left", 0x90, 0x0A, 0x00)
        self.assertEqual(sum("PlayPause isn't in Rekordbox's MIDI mapping" in n for n in notices), 1, notices)


if __name__ == "__main__":
    unittest.main()
