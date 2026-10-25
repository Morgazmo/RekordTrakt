"""Sends Rekordbox actions over the bridge port using the installed bridge's manifest, and decodes feedback."""


class BridgeClient:
    def __init__(self, out, manifest, scope=None):
        self.out = out                          # anything with send(status, data1, data2)
        self.entries = {(e["function"], e["deck"]): e for e in manifest["entries"]}
        self.scope = None if scope is None else set(scope)   # what release_all() may release: what the rig can press
        self.feedback = {(e["output"]["status"], e["output"]["data1"]): (e["function"], e["deck"])
                         for e in manifest["entries"] if e["output"]}
        self.held = {}                          # (function, deck) -> how many presses hold it now
        self.bypassed = False                   # Bypass: nothing reaches Rekordbox

    def _out(self, status, data1, data2):
        if not self.bypassed:
            self.out.send(status, data1, data2)

    def _input(self, function, deck):
        try:
            entry = self.entries[(function, deck)]
        except KeyError:
            raise KeyError(f"{function} deck {deck} is not in Rekordbox's bridge mapping") from None
        if not entry["input"]:
            raise ValueError(f"{function} is feedback-only")
        return entry["input"]

    def press(self, function, deck=None):
        """Several controls (or the window and the hardware) can hold one target: Rekordbox sees one press, from the
        first, and one release, from the last."""
        i = self._input(function, deck)
        key = (function, deck)
        if not self.held.get(key):
            self._out(i["status"], i["data1"], 0x7F)
        self.held[key] = self.held.get(key, 0) + 1

    def release(self, function, deck=None):
        i = self._input(function, deck)
        key = (function, deck)
        left = self.held.get(key, 0) - 1
        if left > 0:
            self.held[key] = left
            return
        self.held.pop(key, None)
        self._out(i["status"], i["data1"], 0x00)      # note-on velocity 0: Rekordbox ignores note-off

    def tap(self, function, deck=None):
        """Press and release, unless something holds the target now: a tap would release it under them."""
        if self.held.get((function, deck)):
            self._input(function, deck)
            return
        self.press(function, deck)
        self.release(function, deck)

    def set_on(self, function, deck, on):
        """For value-following functions (e.g. FXPartSelect*): set on/off without treating it as a held button."""
        i = self._input(function, deck)
        self._out(i["status"], i["data1"], 0x7F if on else 0x00)

    def step(self, function, deck, delta):
        """Relative control: one message per step (Rekordbox ignores magnitude)."""
        i = self._input(function, deck)
        for _ in range(abs(delta)):
            self._out(i["status"], i["data1"], 0x41 if delta > 0 else 0x3F)

    def set7(self, function, deck, value):
        i = self._input(function, deck)
        self._out(i["status"], i["data1"], max(0, min(127, value)))

    def set14(self, function, deck, value):
        i = self._input(function, deck)
        value = max(0, min(16383, value))
        self._out(i["status"], i["data1"], value >> 7)
        self._out(i["status"], i["lsb"], value & 0x7F)

    def release_all(self):
        """Neutralise: release every button-type input the rig can press, held or not (start-up, shutdown,
        disconnect). The bridge covers the whole registry, so the rest is left alone rather than sending hundreds of
        releases. Value-following functions are state, not held buttons, so they're left alone too."""
        for (function, deck), e in self.entries.items():
            if self.scope is not None and (function, deck) not in self.scope and (function, deck) not in self.held:
                continue
            button = e["input"] and (e["input"]["status"] & 0xF0 == 0x90 or e.get("type") in ("Button", "Pad"))
            if button and e["semantics"] != "value_held":       # notes, and buttons on CC
                self._out(e["input"]["status"], e["input"]["data1"], 0x00)
        self.held.clear()

    def decode(self, status, data1, data2):
        key = self.feedback.get((status, data1))
        return (key[0], key[1], data2) if key else None
