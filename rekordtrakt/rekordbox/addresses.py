"""The permanent address of every registry function on the bridge (addresses.json), and the tool that appends to it.

An address never changes once a registry version has shipped: new functions are only appended, so an update never
renumbers what Rekordbox already has installed. tests/test_registry.py freezes each version's part.

Address plan (MIDI channels counted from 0 here; 1-16 on screen):
  inputs to Rekordbox      per deck: channels 0-3 (deck - 1), the same number on each   global: channel 4
  feedback from Rekordbox  per deck: channels 8-11 (deck + 7)                            global: channel 12
  overflow                 inputs: channels 5-7     feedback: channels 13-15   (explicit per-deck addresses)
  numbers: notes 0-127 for buttons and pads; CC 64-119 for 7-bit knobs and relative encoders; CC 0-31 (+32 for the
  LSB) for 14-bit. Rekordbox's echo of its own feedback lands on channels it has no input rows for (echo-safe).
  When the notes run out, buttons go on overflow CCs 0-119 ("cc_button": 7F pressed, 00 released), as some of
  Pioneer's own controllers send them.
Pad families (PAD1-8 of one kind) are placed together: all eight on the main channels, or all eight in overflow.

  python -m rekordtrakt.rekordbox.addresses           append addresses for registry functions that have none
  python -m rekordtrakt.rekordbox.addresses --check   exit 1 if any are missing
"""
import json
import re
import sys
from pathlib import Path

TABLE = Path(__file__).with_name("addresses.json")
DECK_IN, GLOBAL_IN, OVERFLOW_IN = (0, 1, 2, 3), 4, (5, 6, 7)
DECK_OUT, GLOBAL_OUT, OVERFLOW_OUT = (8, 9, 10, 11), 12, (13, 14, 15)
RANGES = {"note": range(0, 128), "cc": range(64, 120), "cc14": range(0, 32), "cc_button": range(0, 120)}
OUTPUT_ONLY_TYPES = {"Indicator", "IndicatorHiRes", "JogIndicator", "JogIndicatorHiRes", "Value"}


def input_kind(rb_type):
    if rb_type in OUTPUT_ONLY_TYPES:
        return None
    if rb_type in ("Button", "Pad"):
        return "note"
    return "cc14" if rb_type == "KnobSliderHiRes" else "cc"


def load_table(path=TABLE):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {e["function"]: e for e in data["functions"]}


def save_table(entries, path=TABLE):
    """One function per line, in the order they were added."""
    lines = [json.dumps(e, separators=(", ", ": ")) for e in entries]
    head = {"about": "Permanent bridge addresses for Rekordbox 6.8.7 (see addresses.py). Append only: never edit or "
                     "remove a line once its registry version has shipped.",
            "channels": "0-based: inputs 0-3 deck, 4 global, 5-7 overflow; feedback 8-11 deck, 12 global, 13-15 overflow"}
    text = "{\n" + "".join(f"  {json.dumps(k)}: {json.dumps(v)},\n" for k, v in head.items())
    text += '  "functions": [\n    ' + ",\n    ".join(lines) + "\n  ]\n}\n"
    Path(path).write_text(text, encoding="utf-8", newline="\n")


class _Pools:
    """Which (channel, number) pairs are taken, per message kind. Notes and CCs never clash with each other."""

    def __init__(self, entries):
        self.used = set()
        for e in entries:
            for side in ("in", "out"):
                if e.get(side):
                    self._mark(e[side]["kind"], e[side]["at"])

    def _mark(self, kind, at):
        for ch, num in at:
            self.used.add((self._space(kind), ch, num))
            if kind == "cc14":
                self.used.add(("cc", ch, num + 32))

    @staticmethod
    def _space(kind):
        return "note" if kind == "note" else "cc"

    def free(self, kind, ch, num):
        space = self._space(kind)
        if (space, ch, num) in self.used:
            return False
        return kind != "cc14" or ("cc", ch, num + 32) not in self.used

    def same_number(self, kind, channels, count=1):
        """The lowest run of `count` numbers free on every one of `channels`, or None."""
        nums = RANGES[kind]
        for start in nums:
            run = range(start, start + count)
            if run[-1] in nums and all(self.free(kind, ch, n) for ch in channels for n in run):
                return list(run)
        return None

    def slots(self, kind, channels, count):
        """`count` free (channel, number) slots from `channels`, in order, or None."""
        out = []
        for ch in channels:
            for n in RANGES[kind]:
                if self.free(kind, ch, n):
                    out.append((ch, n))
                    if len(out) == count:
                        return out
        return None

    def take(self, kind, at):
        self._mark(kind, at)
        return {"kind": kind, "at": [list(a) for a in at]}


def _place(pools, kind, scope, main_channels, global_channel, overflow_channels, group_size):
    """Addresses for `group_size` functions placed together: a list (one per function) of {"kind", "at"}."""
    if scope == "deck":
        nums = pools.same_number(kind, main_channels, group_size)
        if nums is not None:
            return [pools.take(kind, [(ch, n) for ch in main_channels]) for n in nums]
        slots = pools.slots(kind, overflow_channels, 4 * group_size)
        if slots is None and kind == "note":
            kind = "cc_button"
            slots = pools.slots(kind, overflow_channels, 4 * group_size)
        if slots is None:
            raise ValueError(f"out of {kind} addresses for per-deck functions")
        return [pools.take(kind, slots[4 * i:4 * i + 4]) for i in range(group_size)]
    nums = pools.same_number(kind, (global_channel,), group_size)
    if nums is not None:
        return [pools.take(kind, [(global_channel, n)]) for n in nums]
    slots = pools.slots(kind, overflow_channels, group_size)
    if slots is None and kind == "note":
        kind = "cc_button"
        slots = pools.slots(kind, overflow_channels, group_size)
    if slots is None:
        raise ValueError(f"out of {kind} addresses for global functions")
    return [pools.take(kind, [s]) for s in slots]


def _groups(functions):
    """Registry functions in order, PAD1-8 of the same family kept as one group."""
    groups, by_family = [], {}
    for f in functions:
        m = re.fullmatch(r"PAD(\d+)_(.+)", f.name)
        if m:
            key = (m.group(2), f.scope, f.rb_type, f.feedback)
            if key in by_family:
                by_family[key].append(f)
                continue
            by_family[key] = [f]
            groups.append(by_family[key])
        else:
            groups.append([f])
    return groups


def append_missing(entries, functions):
    """Returns entries plus new ones for `functions` that have no address yet (existing ones untouched)."""
    entries = list(entries)
    known = {e["function"] for e in entries}
    pools = _Pools(entries)
    for group in _groups([f for f in functions if f.name not in known]):
        f = group[0]
        new = [{"function": g.name, "since": g.since} for g in group]
        kind = input_kind(f.rb_type)
        if kind:
            for e, addr in zip(new, _place(pools, kind, f.scope, DECK_IN, GLOBAL_IN, OVERFLOW_IN, len(group))):
                e["in"] = addr
        if f.feedback:
            for e, addr in zip(new, _place(pools, f.feedback, f.scope, DECK_OUT, GLOBAL_OUT, OVERFLOW_OUT, len(group))):
                e["out"] = addr
        entries.extend(new)
    return entries


def main(argv=None):
    from rekordtrakt.rekordbox import registry
    argv = sys.argv[1:] if argv is None else argv
    current = list(load_table().values()) if TABLE.exists() else []
    updated = append_missing(current, registry.FUNCTIONS)
    added = len(updated) - len(current)
    if "--check" in argv:
        print(f"{added} registry function(s) without an address" if added else "every registry function has an address")
        return 1 if added else 0
    if added:
        save_table(updated)
    print(f"added {added} address(es); {len(updated)} in {TABLE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
