"""Translator state with provenance: where each value came from.

observed     reported by Rekordbox feedback
commanded    the translator sent it; Rekordbox, the mouse or the XP1 may have changed it since
inferred     derived from other fields
"""
from dataclasses import dataclass

OBSERVED, COMMANDED, INFERRED = "observed", "commanded", "inferred"


@dataclass
class Field:
    value: object
    status: str
    time: float       # last update
    changed: float    # last time the value actually changed


class State:
    def __init__(self, clock):
        self.clock = clock
        self.fields = {}

    def set(self, key, value, status):
        now = self.clock()
        old = self.fields.get(key)
        changed = old.changed if old is not None and old.value == value else now
        self.fields[key] = Field(value, status, now, changed)

    def get(self, key, default=None):
        f = self.fields.get(key)
        return f.value if f else default

    def field(self, key):
        return self.fields.get(key)

    def clear_commanded(self, deck=None):
        """Drop commanded values (all, or one deck's) after a reconnect, deck load or mapping reload."""
        for key in [k for k, f in self.fields.items() if f.status == COMMANDED and (deck is None or deck in k)]:
            del self.fields[key]

    def playing(self, deck):
        """True while Rekordbox's jog-rotation feedback is ticking (~8 Hz, only while the deck plays; E1).
        Falls back to PlayPause, which Rekordbox holds at 127 while playing and blinks while paused."""
        jog = self.fields.get(("JogPlayPauseIndicator", deck))
        if jog and jog.status == OBSERVED and self.clock() - jog.time < 0.4:
            return True
        f = self.fields.get(("PlayPause", deck))
        return bool(f and f.status == OBSERVED and f.value and self.clock() - f.changed > 0.6)
