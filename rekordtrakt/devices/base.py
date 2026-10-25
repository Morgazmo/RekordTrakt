"""Controller events, independent of any device's MIDI layout."""
from dataclasses import dataclass

PRESS, RELEASE, TURN, VALUE = "press", "release", "turn", "value"


@dataclass(frozen=True)
class Event:
    position: str        # rig position, e.g. "x1_left"
    control: str         # physical control, e.g. "L.play" (X1 half prefix) or "pad_12"
    kind: str            # press | release | turn | value
    value: int = 0       # turn: signed steps; value: 0-127
    shift: bool = False  # hardware shift layer (X1 sends shifted controls on other channels)
    source: str = "hw"   # "hw" (the controller) or "ui" (the window): each source holds its own presses


@dataclass(frozen=True)
class Decoded:
    control: str
    kind: str
    value: int = 0
    shift: bool = False


def relative_offset64(v):
    """0x41 = +1, 0x3F = -1 (X1 MK3 encoders)."""
    return v - 64


def relative_twos_complement(v):
    """0x01 = +1, 0x7F = -1 (F1 encoder)."""
    return v if v < 64 else v - 128
