"""Controller events, independent of any device's MIDI layout."""
from dataclasses import dataclass

PRESS, RELEASE, TURN, VALUE = "press", "release", "turn", "value"

# What a controller without halves is assigned to, unless its definition says otherwise: two decks and an FX unit.
# Bindings name them by key ("a"); Settings and the controller's card let you move each one.
DEFAULT_DECK_SLOTS = ({"key": "a", "label": "First deck", "default": 1},
                      {"key": "b", "label": "Second deck", "default": 2})
DEFAULT_FX_SLOTS = ({"key": "fx", "label": "FX unit", "default": 1},)
# Context keys a slot can't take: a half's own deck and FX unit, fixed decks, hot cue numbers, the engine's own.
RESERVED_KEYS = {"deck", "fx", "d1", "d2", "d3", "d4", "hc1", "hc2", "hc3", "hc4", "_pos", "_half"}


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
