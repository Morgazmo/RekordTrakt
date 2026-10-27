"""The translator as a service: the engine on its own thread, so the tray app can start, stop and watch it.

The command line's `run` uses it too. Start-up: load the rig, read the bridge mapping Rekordbox has installed (the
translator always sends what Rekordbox loaded, so an older bridge keeps working until it's updated), compare it with
the action registry's, make sure the bridge ports exist (creating them through the helper if needed), open the
controllers, then route messages until stopped. Stopping (or crashing) always neutralises: held bridge buttons
released, LEDs off.

Trace events go to `trace` (the engine's, plus status, stats and errors from here). The main window's view (what
every control does now) goes to `on_view` when it changes, at most every VIEW_EVERY seconds, and None on stop. Both
are called on the translator thread and must not block.

Settings changes from the windows run on the translator thread too (call()), so they never race the engine.
"""
import concurrent.futures
import json
import queue
import threading
import time
import traceback

from rekordtrakt import rig as rig_mod
from rekordtrakt.bridge import install as rb_install
from rekordtrakt.bridge import ports as bridge_ports
from rekordtrakt.bridge.client import BridgeClient
from rekordtrakt.bridge.compiler import canonical_mappings, compile_bridge, read_bridge
from rekordtrakt.devices.base import PRESS, RELEASE, TURN, VALUE, Event
from rekordtrakt.engine.engine import Engine
from rekordtrakt.engine.leds import LedEngine
from rekordtrakt.profiles import PROFILES
from rekordtrakt.rekordbox import registry

STOPPED, STARTING, RUNNING, STOPPING, FAILED = "stopped", "starting", "running", "stopping", "failed"
STATS_EVERY = 1.0
VIEW_EVERY = 0.12


class _NullOut:
    def send(self, *_):
        pass


def make_engine(rig, bridge, leds, save_device=rig_mod.save_device, **kwargs):
    """save_device(dev) is called after a deck, FX unit or option change (setup mode or the settings window)."""
    return Engine(rig_mod.device_configs(rig), PROFILES, bridge, leds, time.monotonic, on_config_change=save_device,
                  **kwargs)


def rekordbox_target(rig):
    """The Rekordbox major version the bridge is built for (6 or 7): the one last seen running, so there's nothing
    to choose. A version picked by hand in an older RekordTrakt ("rekordbox") counts until a Rekordbox is seen."""
    bridge = rig.get("bridge", {})
    for key in ("rekordbox", "rekordbox_seen"):
        if bridge.get(key) in (6, 7):
            return bridge[key]
    return 6


def full_bridge(rig):
    """The bridge mapping for the whole action registry (CSV, manifest): what gets installed into Rekordbox."""
    target = rekordbox_target(rig)
    return compile_bridge(rig["bridge"]["rekordbox_port"], registry.full_actions(target), rekordbox=target)


def read_rekordbox(rig):
    """What Rekordbox has: the installed bridge mapping's text (None if missing), and which controllers still have
    their own direct mappings (they would fire twice alongside the bridge)."""
    path = rb_install.MAPPINGS_DIR / f"{rig['bridge']['rekordbox_port']}.midi.csv"
    return {"bridge": path.read_text(encoding="ascii", errors="replace") if path.exists() else None,
            "direct": [pos for pos, d in rig["devices"].items()
                       if rb_install.has_mappings(rb_install.MAPPINGS_DIR / f"{d['port']}.midi.csv")]}


def as_installed(rig):
    """Rekordbox with the current bridge installed and no direct mappings left (for tests)."""
    return {"bridge": full_bridge(rig)[0], "direct": []}


def installed_manifest(found):
    return read_bridge(found["bridge"], lambda f: registry.BY_NAME[f].semantics if f in registry.BY_NAME else "")


def bridge_status(rig, found, uses):
    """How Rekordbox's bridge mapping compares with RekordTrakt's:
    current   it covers the whole registry
    update    everything this rig uses works, and a newer bridge (more functions) is ready
    required  some functions this rig uses aren't in it (they do nothing until it's updated)
    missing   not installed
    Plus "direct": controllers whose own mappings would fire twice."""
    target = rekordbox_target(rig)
    status = {"version": registry.VERSION, "target": target,
              "rekordbox": registry.REKORDBOX_7 if target == 7 else registry.REKORDBOX, "direct": list(found.get("direct", ())),
              "missing": [], "entries": 0}
    if found.get("bridge") is None:
        return {**status, "state": "missing"}
    manifest = installed_manifest(found)
    have = {(e["function"], e["deck"]) for e in manifest["entries"]}
    missing = sorted({f for f, d in uses if (f, d) not in have})
    status.update(entries=len(have), missing=missing)
    if missing:
        return {**status, "state": "required"}
    current = canonical_mappings(found["bridge"]) == canonical_mappings(full_bridge(rig)[0])
    return {**status, "state": "current" if current else "update"}


def preflight(rig, status):
    """Warnings that would make a set go wrong, from bridge_status()."""
    problems = []
    state = status.get("state")
    if state == "missing":
        problems.append("Rekordbox doesn't have RekordTrakt's MIDI mapping yet: install it (Rekordbox closed)")
    elif state == "required":
        problems.append(f"Rekordbox's MIDI mapping is missing {len(status['missing'])} function(s) this setup uses: "
                        "update it (Rekordbox closed)")
    elif state == "update":
        problems.append("an update to Rekordbox's MIDI mapping is ready (everything works until then)")
    for pos in status.get("direct", ()):
        d = rig["devices"][pos]
        problems.append(f"{d.get('name') or rig_mod.default_name(pos)}: Rekordbox still has its own mapping for "
                        f"'{d['port']}', so presses would fire twice: update Rekordbox's MIDI mapping")
    return problems


def _device(eng, position):
    if position not in eng.devices:
        raise ValueError(f"no controller '{position}'")
    return eng.devices[position]


class Translator:
    def __init__(self, midi, load_rig=rig_mod.load, trace=None, log=None, verbose=False, ensure_bridge=None,
                 checks=preflight, on_view=None, save_device=rig_mod.save_device, verify_bridge=None,
                 bypass=False, read_rekordbox=read_rekordbox, port_units=None, save_rig=rig_mod.save):
        self.midi = midi
        self.port_units = port_units         # {port name: physical unit} (bridge.ports.port_units), or None
        self.save_rig = save_rig
        self._inputs_checked = None
        self.bypass = bypass                 # nothing is sent to Rekordbox while on
        self.verify_bridge = verify_bridge or (lambda app, rb: bridge_ports.verify_pair(app, rb, midi))
        self.save_device = save_device
        self.on_view = on_view or (lambda view: None)
        self._commands = queue.Queue()
        self.load_rig = load_rig
        self.checks = checks
        self.read_rekordbox = read_rekordbox
        self.bridge_mapping = None           # bridge_status(): how Rekordbox's bridge mapping compares
        self._trace = trace or (lambda event: None)
        self._log = log                      # print-like, for the command line; None in the tray app
        self.verbose = verbose
        self.ensure_bridge = ensure_bridge or (lambda app, rb: bridge_ports.ensure_pair(app, rb, midi))
        self.state = STOPPED
        self.error = None
        self.bridge = None                   # result of ensure_bridge
        self.devices = {}                    # position -> {"type", "port", "connected"}
        self.warnings = []
        self.stats = {}
        self.started_at = None
        self._window = self._new_window()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    # --- control (any thread) -------------------------------------------------------------------------
    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self.error = None
            self._set_state(STARTING)
            self._thread = threading.Thread(target=self._run, name="translator", daemon=True)
            self._thread.start()

    def stop(self, timeout=5.0):
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout)

    @property
    def alive(self):
        return bool(self._thread and self._thread.is_alive())

    def missing_ports(self, inputs=None):
        """Configured controllers that weren't connected at start but are now (so a restart would pick them up),
        under their own port name or, after a replug that renumbered it, under another one their unit has."""
        inputs = self.midi.input_names() if inputs is None else inputs
        missing = [pos for pos, d in self.devices.items() if not d["connected"]]
        back = [pos for pos in missing if self.devices[pos]["port"] in inputs]
        if missing and not back and self.port_units and set(inputs) != self._inputs_checked:
            self._inputs_checked = set(inputs)              # asked once per change in the port list
            units = set(self.port_units().values())
            back = [pos for pos in missing if self.devices[pos].get("unit") in units]
        return back

    # --- settings, applied live on the translator thread ------------------------------------------------
    def call(self, fn, timeout=2.0):
        """Runs fn(engine) on the translator thread and returns its result (or raises its exception)."""
        if self.state != RUNNING:
            raise RuntimeError("the translator isn't running")
        future = concurrent.futures.Future()
        self._commands.put((fn, future))
        return future.result(timeout)

    def set_option(self, position, key, value):
        def run(eng):
            choices = eng.profile(_device(eng, position)).option_choices
            if key not in choices or value not in choices[key]:
                raise ValueError(f"{key} can't be {value!r}")
            eng.set_option(position, key, value)
        return self.call(run)

    def assign(self, position, half=None, deck=None, fx=None, slot=None):
        """A half's deck and/or FX unit; or, on a unit without halves, one deck slot or FX slot (`slot`)."""
        def run(eng):
            dev = _device(eng, position)
            if not eng.profile(dev).reassignable:
                raise ValueError(f"{dev.name} can't be reassigned")
            if (deck is not None and deck not in (1, 2, 3, 4)) or (fx is not None and fx not in (1, 2)):
                raise ValueError("deck must be 1-4 and FX unit 1-2")
            if half is not None:
                if half not in dev.halves():
                    raise ValueError(f"{dev.name} has no half '{half}'")
            else:
                slots = dev.deck_slots() if deck is not None else dev.fx_slots()
                if dev.device.has_halves or (deck is None) == (fx is None) or not isinstance(slot, int) \
                        or not 0 <= slot < len(slots):
                    raise ValueError(f"choose one of {dev.name}'s decks or FX units")
            eng.assign(position, half, deck=deck, fx=fx, slot=slot)
        return self.call(run)

    def set_pages(self, position, pages, order=None):
        return self.call(lambda eng: eng.set_pages(_device(eng, position).position, list(pages),
                                                   None if order is None else list(order)))

    def set_page(self, position, half, page):
        def run(eng):
            dev = _device(eng, position)
            if half not in dev.halves() or page not in eng.pages(dev):
                raise ValueError(f"no page {page!r} on {position} {half}")
            eng.set_mode(position, half, "page", page)
        return self.call(run)

    def rename(self, position, name):
        name = str(name).strip()
        if not name:
            raise ValueError("a name can't be empty")

        def run(eng):
            eng.rename(_device(eng, position).position, name)
            self.devices[position]["name"] = eng.devices[position].name
        return self.call(run)

    def ui_input(self, position, control, action, value=0, shift=False):
        """A control used in the window, as if on the hardware (source "ui", so it holds its own presses)."""
        def run(eng):
            dev = _device(eng, position)
            kinds = dict(dev.device.controls())
            if control not in kinds:
                raise ValueError(f"{position} has no control {control!r}")
            kind = kinds[control]
            if action not in (PRESS, RELEASE, TURN, VALUE) or (action in (PRESS, RELEASE)) != (kind == PRESS) \
                    or (action in (TURN, VALUE) and action != kind):
                raise ValueError(f"{control} can't be used with {action!r}")
            v = int(value)
            if action == VALUE and not 0 <= v <= 127 or action == TURN and not -16 <= v <= 16:
                raise ValueError("value out of range")
            supports_shift = getattr(dev.device, "supports_shift", None)
            if shift and not (getattr(dev.device, "has_shift", False) or
                              callable(supports_shift) and supports_shift(control)):
                raise ValueError(f"{position} has no Shift layer")
            eng.handle(Event(position, control, action, v, bool(shift), "ui"))
        return self.call(run)

    def set_shift_latch(self, position, on):
        return self.call(lambda eng: eng.set_shift_latch(_device(eng, position).position, on))

    # --- the installed bridge mapping can change under us -----------------------------------------------------
    @staticmethod
    def _meaning(found):
        return frozenset(canonical_mappings(found["bridge"])) if found.get("bridge") is not None else None

    def bridge_changed(self):
        """True when the installed bridge mapping now means something else than when this translator started: e.g.
        Rekordbox 6 drops Rekordbox 7's rows when it rewrites the file after starting, or someone
        installed from the command line. A rewrite that keeps the meaning doesn't count."""
        if self.state != RUNNING or not getattr(self, "_rig", None):
            return False
        try:
            return self._meaning(self.read_rekordbox(self._rig)) != self._bridge_meaning
        except OSError:
            return False

    # --- your own mapping (the mapping editor) ------------------------------------------------------------
    def set_binding(self, position, layer, page, control, action):
        return self.call(lambda eng: eng.set_binding(_device(eng, position).position, layer, page, control, action))

    def control_info(self, position, control, page=None):
        return self.call(lambda eng: eng.control_info(_device(eng, position).position, control, page))

    def add_page(self, position, name):
        return self.call(lambda eng: eng.add_page(_device(eng, position).position, name))

    def rename_page(self, position, page, name):
        return self.call(lambda eng: eng.rename_page(_device(eng, position).position, page, name))

    def remove_page(self, position, page):
        return self.call(lambda eng: eng.remove_page(_device(eng, position).position, page))

    def export_mapping(self, position):
        def run(eng):
            dev = _device(eng, position)
            return {"rekordtrakt_mapping": 1, "device_type": dev.device.type_name,
                    "preset": dev.profile or dev.device.type_name, "name": dev.name, "mapping": dev.mapping}
        return self.call(run)

    def set_device_test(self, position, on):
        return self.call(lambda eng: eng.set_device_test(_device(eng, position).position, bool(on)))

    def replace_device_definition(self, position, definition):
        from rekordtrakt.devices.defined import DefinedDevice
        return self.call(lambda eng: eng.replace_device_definition(position, DefinedDevice(definition),
                                                                    definition.get("template")))

    def import_mapping(self, position, data):
        def run(eng):
            dev = _device(eng, position)
            if not isinstance(data, dict) or data.get("rekordtrakt_mapping") != 1:
                raise ValueError("that isn't a RekordTrakt mapping file")
            if data.get("device_type") != dev.device.type_name:
                raise ValueError(f"that mapping is for a {data.get('device_type')}, not a {dev.device.type_name}")
            eng.set_mapping(position, data.get("mapping") or {})
        return self.call(run)

    def release_ui(self):
        if self.state == RUNNING:
            return self.call(lambda eng: eng.release_source("ui"))

    def set_bypass(self, on):
        """Bypass on: release everything held in Rekordbox, then send nothing more. The window, Debug and LEDs
        keep working."""
        self.bypass = bool(on)
        if self.state != RUNNING:
            return

        def run(eng):
            if on:
                eng.cancel_waiting()
                eng.bridge.release_all()
            eng.bridge.bypassed = bool(on)
        self.call(run)
        self._say("notice", "Bypass on: nothing is sent to Rekordbox" if on else "Bypass off")

    def snapshot(self):
        return {"bypass": self.bypass, "state": self.state, "error": self.error, "bridge": self.bridge,
                "bridge_mapping": self.bridge_mapping, "warnings": list(self.warnings),
                "devices": {k: dict(v) for k, v in self.devices.items()}, "stats": dict(self.stats),
                "started_at": self.started_at}

    # --- internals (translator thread) ----------------------------------------------------------------
    @staticmethod
    def _new_window():
        return {"events": 0, "feedback": 0, "sent": 0, "max_queue_ms": 0.0}

    def _emit(self, event):
        if event["kind"] == "send":
            self.stats["sent"] = self.stats.get("sent", 0) + 1
            self._window["sent"] += 1
        try:
            self._trace(event)
        except Exception:               # a broken listener must never stop the translator
            pass

    def _say(self, kind, text, **data):
        if self._log:
            self._log(text)
        self._emit({"kind": kind, "text": text, **data})

    def _set_state(self, state):
        self.state = state
        self._emit({"kind": "status", "text": f"translator {state}", **self.snapshot()})

    def _run(self):
        ports, engine = [], None
        try:
            engine = self._open(ports)
            if engine:
                self._loop(engine)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self._say("error", f"translator stopped: {self.error}", detail=traceback.format_exc())
        finally:
            if engine:
                try:
                    engine.stop()
                except Exception as e:           # e.g. a controller unplugged: its LEDs can't be turned off
                    self._say("notice", f"while stopping: {type(e).__name__}: {e}")
            for p in ports:
                try:
                    p.close()
                except Exception:
                    pass
            self._fail_commands()
            try:
                self.on_view(None)
            except Exception:
                pass
            self._set_state(FAILED if self.error else STOPPED)

    def _open(self, ports):
        rig = self.load_rig()
        units = self.port_units() if self.port_units else {}
        if units:
            before = json.dumps(rig, sort_keys=True)
            for pos, old, new in rig_mod.follow_units(rig, units):
                self._say("notice", f"{pos}: its unit is on '{new}' now (was '{old}'), so it moves there")
            if json.dumps(rig, sort_keys=True) != before:
                self.save_rig(rig)
        uses = make_engine(rig, None, None).uses()
        found = self.read_rekordbox(rig)
        self._rig, self._bridge_meaning = rig, self._meaning(found)
        manifest = installed_manifest(found) if found.get("bridge") is not None else {"entries": []}
        self.bridge_mapping = bridge_status(rig, found, uses)
        self.warnings = self.checks(rig, self.bridge_mapping)
        for w in self.warnings:
            self._say("notice", f"WARNING: {w}", warning=True)

        b = rig["bridge"]
        self.bridge = self.ensure_bridge(b["app_port"], b["rekordbox_port"])
        self._say("bridge", f"MIDI bridge: {self.bridge['message']}", **self.bridge)
        if not self.bridge["ok"]:
            raise RuntimeError(self.bridge["message"])
        problem = self.verify_bridge(b["app_port"], b["rekordbox_port"])
        if problem:
            self.bridge = {**self.bridge, "ok": False, "state": "unpaired", "message": problem}
            raise RuntimeError(problem)

        q = queue.Queue()
        self._queue = q
        app_port = b["app_port"]
        out = self.midi.MidiOut(app_port)
        ports.append(out)
        ports.append(self.midi.MidiIn(app_port, q))
        bridge = BridgeClient(out, manifest, scope=uses)
        bridge.bypassed = self.bypass
        leds = LedEngine(time.monotonic)
        self.position_of = {}
        inputs = self.midi.input_names()
        self.devices = {}
        for pos, d in rig["devices"].items():
            connected = d["port"] in inputs
            self.devices[pos] = {"type": d["type"], "port": d["port"], "connected": connected,
                                 "profile": d.get("profile") or d["type"], "decks": d["decks"],
                                 "name": d.get("name") or rig_mod.default_name(pos), "unit": d.get("unit")}
            if not connected:
                self._say("notice", f"{pos} ('{d['port']}') is not connected; continuing without it")
                leds.add_device(pos, rig_mod.DEVICE_TYPES[d["type"]](), _NullOut())
                continue
            dev_out = self.midi.MidiOut(d["port"])
            ports.append(dev_out)
            ports.append(self.midi.MidiIn(d["port"], q))
            leds.add_device(pos, rig_mod.DEVICE_TYPES[d["type"]](), dev_out)
            self.position_of[d["port"]] = pos

        engine = make_engine(rig, bridge, leds, save_device=self.save_device, log=self._log or (lambda *_: None),
                             verbose=self.verbose, trace=self._emit)
        engine.start()
        self.app_port = app_port
        self.started_at = time.time()
        self.stats = {"events": 0, "feedback": 0, "sent": 0, "max_queue_ms": 0.0}
        self._set_state(RUNNING)
        self._say("notice", f"RekordTrakt running: {len(self.position_of)} controller(s), bridge '{app_port}'.")
        return engine

    def _fail_commands(self):
        while True:
            try:
                _, future = self._commands.get_nowait()
            except queue.Empty:
                return
            future.set_exception(RuntimeError("the translator stopped"))

    def _run_commands(self, engine):
        while True:
            try:
                fn, future = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                future.set_result(fn(engine))
            except Exception as e:
                future.set_exception(e)

    def _publish_view(self, engine):
        try:
            self.on_view(engine.view())
        except Exception as e:
            self._say("notice", f"main window view failed: {type(e).__name__}: {e}")

    def _loop(self, engine):
        q, app_port, position_of = self._queue, self.app_port, self.position_of
        stats = self.stats
        window = self._window = self._new_window()
        next_stats = time.monotonic() + STATS_EVERY
        view_version, next_view = engine.view_version, time.monotonic() + VIEW_EVERY
        self._publish_view(engine)
        while not self._stop.is_set():
            try:
                port, status, d1, d2, t = q.get(timeout=0.002)
            except queue.Empty:
                pass
            else:
                wait_ms = (time.perf_counter() - t) * 1000
                window["max_queue_ms"] = max(window["max_queue_ms"], wait_ms)
                stats["max_queue_ms"] = max(stats["max_queue_ms"], wait_ms)
                if port == app_port:
                    stats["feedback"] += 1
                    window["feedback"] += 1
                    engine.feedback(status, d1, d2)
                elif port in position_of:
                    stats["events"] += 1
                    window["events"] += 1
                    engine.device_message(position_of[port], status, d1, d2)
            engine.tick()
            if not self._commands.empty():
                self._run_commands(engine)
            now = time.monotonic()
            if engine.view_version != view_version and now >= next_view:
                view_version, next_view = engine.view_version, now + VIEW_EVERY
                self._publish_view(engine)
            if now >= next_stats:
                self._emit({"kind": "stats", "text": "", "per_second": {k: v / STATS_EVERY for k, v in window.items()
                                                                        if k != "max_queue_ms"},
                            "max_queue_ms": round(window["max_queue_ms"], 2), "totals": dict(stats)})
                window = self._window = self._new_window()
                next_stats = now + STATS_EVERY
