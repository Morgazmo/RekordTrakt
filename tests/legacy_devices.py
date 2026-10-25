"""Hand-written X1 MK3 and F1 decoders, independent of the definition files, so a test can prove the data-driven
devices decode and light LEDs exactly the same."""
from rekordtrakt.devices.base import PRESS, RELEASE, TURN, VALUE, Decoded, relative_offset64, relative_twos_complement

NOTES = {
    0x00: "fx_assign_1", 0x01: "fx_assign_2",
    0x02: "hotcue_1", 0x03: "hotcue_2", 0x04: "hotcue_3", 0x05: "hotcue_4",
    0x06: "nudge_left", 0x07: "nudge_right", 0x08: "cue", 0x09: "rev", 0x0A: "play", 0x0B: "sync",
    0x10: "fx_button_1", 0x11: "fx_button_2", 0x12: "fx_button_3", 0x13: "fx_button_4",
    0x14: "browse_push", 0x15: "loop_push",
}
KNOBS = {0x10: "fx_knob_1", 0x11: "fx_knob_2", 0x12: "fx_knob_3", 0x13: "fx_knob_4"}
ENCODERS = {0x14: "browse", 0x15: "loop"}
HALVES = ("L", "R")
NOTE_OF = {name: note for note, name in NOTES.items()}


class LegacyX1MK3:
    type_name = "x1mk3"
    display_name = "Kontrol X1 MK3"
    led_interval = 0.002      # seconds between LED messages
    has_halves = True
    has_shift = True          # shifted controls arrive on channels 3/4

    def decode(self, status, d1, d2):
        kind, ch = status & 0xF0, status & 0x0F
        if ch > 3:
            return None
        half, shift = HALVES[ch % 2], ch >= 2
        if kind in (0x80, 0x90) and d1 in NOTES:
            pressed = kind == 0x90 and d2 > 0
            return Decoded(f"{half}.{NOTES[d1]}", PRESS if pressed else RELEASE, shift=shift)
        if kind == 0xB0 and d1 in ENCODERS:
            return Decoded(f"{half}.{ENCODERS[d1]}", TURN, relative_offset64(d2), shift)
        if kind == 0xB0 and d1 in KNOBS:
            return Decoded(f"{half}.{KNOBS[d1]}", VALUE, d2, shift)
        return None

    def led(self, control, value):
        """MIDI message that sets the LED of `control` (e.g. 'R.play'), or None if it has none."""
        half, name = control.split(".", 1)
        if name not in NOTE_OF:
            return None
        # True/127 = on, 0 = off; any other velocity is passed through (page colours, if the X1 uses them)
        velocity = 127 if value is True else (max(0, min(127, int(value))) if value else 0)
        return 0x90 | HALVES.index(half), NOTE_OF[name], velocity

    def led_controls(self):
        return [f"{h}.{n}" for h in HALVES for n in NOTES.values()]

    def controls(self):
        """Every control as (name, kind), for the main window."""
        return ([(f"{h}.{n}", PRESS) for h in HALVES for n in NOTES.values()]
                + [(f"{h}.{n}", VALUE) for h in HALVES for n in KNOBS.values()]
                + [(f"{h}.{n}", TURN) for h in HALVES for n in ENCODERS.values()])

CH13 = {
    0x02: ("knob_1", VALUE), 0x03: ("knob_2", VALUE), 0x04: ("knob_3", VALUE), 0x05: ("knob_4", VALUE),
    0x06: ("fader_1", VALUE), 0x07: ("fader_2", VALUE), 0x08: ("fader_3", VALUE), 0x09: ("fader_4", VALUE),
    0x0D: ("quant", PRESS), 0x0E: ("capture", PRESS), 0x0F: ("reverse", PRESS),
    0x10: ("type", PRESS), 0x11: ("size", PRESS), 0x12: ("browse", PRESS),
    0x4E: ("encoder", TURN), 0x4F: ("encoder_push", PRESS),
}
STOPS = {0x25: "stop_1", 0x26: "stop_2", 0x27: "stop_3", 0x28: "stop_4"}
SYNC = (0x02, 0x33)            # channel 3, CC 0x33 (captured once; re-check)


class LegacyF1:
    type_name = "f1"
    display_name = "Kontrol F1"
    led_interval = 0.025
    has_halves = False
    has_shift = False         # Shift sends nothing and changes nothing in MIDI mode

    def decode(self, status, d1, d2):
        if status & 0xF0 != 0xB0:
            return None
        ch = status & 0x0F
        if d1 == 0x3A + ch:
            return Decoded(f"pad_{ch + 1}", PRESS if d2 else RELEASE)
        if ch == 0x0C and d1 in CH13:
            name, kind = CH13[d1]
            if kind == PRESS:
                return Decoded(name, PRESS if d2 else RELEASE)
            if kind == TURN:
                return Decoded(name, TURN, relative_twos_complement(d2))
            return Decoded(name, VALUE, d2)
        if ch == 0 and d1 in STOPS:
            return Decoded(STOPS[d1], PRESS if d2 else RELEASE)
        if (ch, d1) == SYNC:
            return Decoded("sync", PRESS if d2 else RELEASE)
        return None

    def led(self, control, value):
        on = 127 if value else 0
        if control.startswith("pad_"):
            n = int(control[4:]) - 1
            return 0xB0 | n, 0x3A + n, on
        for cc, (name, kind) in CH13.items():
            if name == control and kind == PRESS:
                return 0xBC, cc, on
        for cc, name in STOPS.items():
            if name == control:
                return 0xB0, cc, on
        return None

    def controls(self):
        """Every control as (name, kind), for the main window."""
        return ([(f"pad_{n}", PRESS) for n in range(1, 17)] + [(name, kind) for name, kind in CH13.values()]
                + [(name, PRESS) for name in STOPS.values()] + [("sync", PRESS)])

    def led_controls(self):
        return [f"pad_{n}" for n in range(1, 17)] + [n for n, k in CH13.values() if k == PRESS] + list(STOPS.values())
