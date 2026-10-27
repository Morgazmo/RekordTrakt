"""The tray app: runs the translator in the background, with a tray icon, the RekordTrakt window (Controllers,
Settings and Debug tabs) and start at login.

  RekordTrakt.exe [--debug]               the installed app (what start-at-login runs, with --login)
  pythonw RekordTrakt.pyw [--debug]       the same from source, no console window
  python -m rekordtrakt app [--debug]     the same with a console (Ctrl+C to quit)

It opens the window unless started at login (--login) or with --no-window; --debug opens it on the Debug tab.
Launching it again while it runs opens the running copy's window; --quit closes it instead (the installer uses
that before an upgrade or uninstall).
"""
import argparse
import threading
import time
import urllib.request
import webbrowser

from rekordtrakt import __version__
from rekordtrakt import rig as rig_mod
from rekordtrakt.bridge import ports as bridge_ports
from rekordtrakt.devices import DEVICE_TYPES
from rekordtrakt.midi import winmm
from rekordtrakt.service import FAILED, RUNNING, STARTING, STOPPED, STOPPING, Translator
from rekordtrakt.shell import autostart, instance, window
from rekordtrakt.shell.events import EventHub, FileLog
from rekordtrakt.shell.icons import write_icons
from rekordtrakt.shell.controller_setup import ControllerSetup
from rekordtrakt.shell.rekordbox_setup import RekordboxSetup
from rekordtrakt.shell.server import UiServer, open_folder
from rekordtrakt.shell.supervisor import Supervisor
from rekordtrakt.shell.tray import SEPARATOR, MenuItem, Tray, set_dpi_aware

NOTIFY_AGAIN_AFTER = 120.0          # seconds between "stopped working" balloons
SUPPORT_URL = "https://ko-fi.com/rekordtrakt"
PROJECT_URL = "https://github.com/Morgazmo/RekordTrakt"
PREFERRED_PORTS = range(47800, 47810)   # a stable address keeps the window's remembered settings between runs


def make_server(*args, **kwargs):
    """The window's server on a stable port if one is free, else any."""
    for port in PREFERRED_PORTS:
        try:
            return UiServer(*args, port=port, **kwargs)
        except OSError:
            continue
    return UiServer(*args, port=0, **kwargs)


def definitions():
    """Each controller type's names, kinds and layout, for the window to draw."""
    return {t: make().public() for t, make in DEVICE_TYPES.items()}


def functions():
    """Everything the mapping editor can offer (the action registry), grouped by category in registry order."""
    from rekordtrakt.engine.actions import BUTTON_TYPES, TURN_TYPES, VALUE_TYPES
    from rekordtrakt.rekordbox import registry
    out = []
    for f in registry.FUNCTIONS:
        if f.semantics == "feedback":
            continue
        kind = "button" if f.rb_type in BUTTON_TYPES else "value" if f.rb_type in VALUE_TYPES else \
            "turn" if f.rb_type in TURN_TYPES else None
        if kind:
            out.append({"name": f.name, "label": f.label, "category": f.category, "kind": kind, "scope": f.scope,
                        "lights": bool(f.feedback), "since": f.since, "rekordbox": f.rekordbox})
    return {"rekordbox": registry.REKORDBOX, "version": registry.VERSION, "functions": out}


PIONEER_HINTS = ("DDJ", "XDJ", "CDJ", "DJM", "PIONEER", "ALPHATHETA", "XP1", "RMX-")


def midi_devices(midi, rig):
    """Every MIDI input on this PC and what RekordTrakt makes of it: one of yours, the bridge, a supported type
    not added yet, a controller Rekordbox handles itself, or not supported yet."""
    ports = {d["port"]: (pos, d) for pos, d in rig.get("devices", {}).items()}
    bridge = {rig.get("bridge", {}).get("app_port"), rig.get("bridge", {}).get("rekordbox_port")}
    out = []
    for name in midi.input_names():
        if name in bridge:
            out.append({"port": name, "status": "bridge", "text": "RekordTrakt's link to Rekordbox"})
        elif name in ports:
            pos, d = ports[name]
            out.append({"port": name, "status": "added", "position": pos,
                        "text": d.get("name") or rig_default_name(pos)})
        elif any(h.upper() in name.upper() for h in PIONEER_HINTS):
            out.append({"port": name, "status": "rekordbox", "text": "Rekordbox works with it directly"})
        else:
            matches = []
            for dev in (make() for make in DEVICE_TYPES.values()):
                definition = dev.definition
                if any(x.lower() in name.lower() for x in definition.get("port_excludes", [])):
                    continue
                hints = [h for h in definition.get("port_hints", []) if h.lower() in name.lower()]
                if hints:
                    matches.append((max(map(len, hints)), dev))
            match = max(matches, key=lambda item: item[0])[1] if matches else None
            if match:
                midi_status = (match.definition.get("midi") or {}).get("status", "verified")
                status = "layout" if midi_status == "capture_required" else "supported"
                text = (f"{match.display_name}: layout ready; learn its inputs" if status == "layout" else
                        f"{match.display_name}: add it to use it")
                out.append({"port": name, "status": status, "type": match.type_name,
                            "midi_status": midi_status, "text": text})
            else:
                out.append({"port": name, "status": "unknown", "text": "Import a mapping file for it to use it"})
    return out


def rig_default_name(position):
    from rekordtrakt.rig import default_name
    return default_name(position)


def settings_actions(translator):
    """Settings changes from the window, applied live by the running translator (which saves them to the rig file).
    translator() returns the current one (the watchdog replaces it on restart)."""
    return {
        "option": lambda body: translator().set_option(body["position"], body["key"], body["value"]),
        "assign": lambda body: translator().assign(body["position"], body.get("half"), body.get("deck"), body.get("fx"),
                                                   body.get("slot")),
        "pages": lambda body: translator().set_pages(body["position"], body["pages"], body.get("order")),
        "page": lambda body: translator().set_page(body["position"], body["half"], body["page"]),
        "rename": lambda body: translator().rename(body["position"], body["name"]),
        "shift-latch": lambda body: translator().set_shift_latch(body["position"], bool(body.get("on"))),
        "device-test": lambda body: translator().set_device_test(body["position"], bool(body.get("on"))),
        # your own mapping (the mapping editor)
        "control-info": lambda body: translator().control_info(body["position"], body["control"], body.get("page")),
        "binding": lambda body: translator().set_binding(body["position"], body["layer"], body.get("page"),
                                                         body["control"], body.get("action")),
        "page-add": lambda body: translator().add_page(body["position"], body["name"]),
        "page-rename": lambda body: translator().rename_page(body["position"], body["page"], body["name"]),
        "page-remove": lambda body: translator().remove_page(body["position"], body["page"]),
        "mapping-export": lambda body: translator().export_mapping(body["position"]),
        "mapping-import": lambda body: translator().import_mapping(body["position"], body.get("data")),
        # the window as a controller (when unlocked); "release-ui" lets go of everything it holds
        "input": lambda body: translator().ui_input(body["position"], body["control"], body["action"],
                                                    body.get("value", 0), body.get("shift", False)),
        "release-ui": lambda body: translator().release_ui(),
    }


def release_ui_when_window_closes(translator):
    """A window that held a control and then vanished (closed, crashed) must not leave it held."""
    def closed(kinds):
        if kinds and "view" in kinds:
            try:
                translator().release_ui()
            except Exception:
                pass
    return closed


def icon_key(snap):
    state = snap["state"]
    if snap.get("bypass") and state == RUNNING:
        return "stopped"
    if state in (STARTING, STOPPING) or (state == STOPPED and snap.get("restart_in") is not None):
        return "starting"
    if state == FAILED:
        return "failed" if snap["wanted"] else "stopped"
    if state == RUNNING:
        missing = [d for d in snap["devices"].values() if not d["connected"]]
        return "warning" if missing or snap["warnings"] or (snap.get("bridge") or {}).get("muted") else "running"
    return "stopped"


def tooltip(snap):
    state = snap["state"]
    if state == RUNNING and snap.get("bypass"):
        text = "bypassed (nothing is sent to Rekordbox)"
    elif state == RUNNING:
        devices = snap["devices"].values()
        connected = sum(d["connected"] for d in devices)
        text = f"running, {connected} of {len(devices)} controllers"
        if snap["warnings"]:
            text += f", {len(snap['warnings'])} warning(s)"
    elif state == FAILED and snap.get("restart_in") is not None:
        text = f"failed, retrying in {snap['restart_in']:.0f} s: {snap['error']}"
    elif state == FAILED:
        text = f"stopped: {snap['error']}"
    else:
        text = state
    return f"RekordTrakt: {text}"


class App:
    def __init__(self, open_window=None, start=True):
        self.hub = EventHub()
        self.log = FileLog(self.hub)
        self.bypass = False                 # not remembered: the app always starts sending
        self.supervisor = Supervisor(
            lambda: Translator(winmm, trace=self.hub.publish, on_view=lambda v: self.hub.set_state("view", v),
                               bypass=self.bypass, port_units=bridge_ports.port_units),
            winmm, self.hub.publish, on_rekordbox_version=lambda version: self.rekordbox.seen(version))
        self.rekordbox = RekordboxSetup(self.supervisor)
        self.controllers = ControllerSetup(self.supervisor, port_units=bridge_ports.port_units)
        self.server = make_server(self.hub, self.status, {
            "start": self._action(self.supervisor.start),
            "stop": self._action(self.supervisor.stop),
            "restart": self._action(self.supervisor.restart),
            "open-log-folder": lambda body: open_folder(self.log.folder),
            "quit": lambda body: self.tray.quit() or "quitting",
            "start-at-login": lambda body: autostart.set_enabled(bool(body.get("on"))) or autostart.is_enabled(),
            "bypass": lambda body: self.set_bypass(bool(body.get("on"))) or self.status(),
            "open-support": lambda body: webbrowser.open(SUPPORT_URL) and "opened",
            "open-project": lambda body: webbrowser.open(PROJECT_URL) and "opened",
            **settings_actions(lambda: self.supervisor.translator),
            **self.rekordbox.actions(),
            **self.controllers.actions(),
        }, on_stream_closed=release_ui_when_window_closes(lambda: self.supervisor.translator),
            gets={"/api/definitions": definitions, "/api/midi-devices": self.midi_devices, "/api/functions": functions})
        self.started = time.time()
        self._last_notified = (None, 0.0)
        self.tray = Tray(write_icons(), self._tray_status, self._menu, on_click=self.open_window)
        self.server.start()
        instance.write_info(self.server.port, self.server.token)
        self.supervisor.run_in_background()
        self.hub.publish({"kind": "supervisor", "text": f"RekordTrakt {__version__} started"})
        if start:
            self.supervisor.start()
        if open_window is not None:
            self.open_window(open_window)

    def midi_devices(self):
        try:
            rig = rig_mod.load()
        except (OSError, ValueError):
            rig = {}
        return midi_devices(winmm, rig)

    def set_bypass(self, on):
        self.bypass = on
        self.supervisor.translator.set_bypass(on)

    def _action(self, fn):
        def run(body=None):                 # the window passes a body; the tray menu calls it bare
            threading.Thread(target=fn, daemon=True).start()     # stopping waits for the translator thread
            return self.status()
        return run

    def status(self):
        return {"app": {"version": __version__, "started": self.started, "log_folder": str(self.log.folder),
                        "dropped_events": self.hub.dropped, "start_at_login": autostart.is_enabled(),
                        "support_url": SUPPORT_URL, "project_url": PROJECT_URL},
                **self.supervisor.snapshot(), "bypass": self.bypass}

    def open_window(self, tab="controllers"):
        window.open_window(f"{self.server.url('app')}#{tab}")

    def _tray_status(self):
        snap = {**self.supervisor.snapshot(), "bypass": self.bypass}
        self._maybe_notify(snap)
        return icon_key(snap), tooltip(snap)

    def _maybe_notify(self, snap):
        """One balloon when the translator stops working, repeated at most every couple of minutes."""
        if snap["state"] != FAILED or not snap["wanted"]:
            return
        error, at = self._last_notified
        if error == snap["error"] and time.monotonic() - at < NOTIFY_AGAIN_AFTER:
            return
        self._last_notified = (snap["error"], time.monotonic())
        self.tray.notify("RekordTrakt stopped working", f"{snap['error']}\nIt will keep retrying.", "error")

    def _menu(self):
        snap = {**self.supervisor.snapshot(), "bypass": self.bypass}
        login = autostart.is_enabled()
        return [
            MenuItem(tooltip(snap)[:80], enabled=False),
            SEPARATOR,
            MenuItem("Open RekordTrakt", self.open_window),
            MenuItem("Settings", lambda: self.open_window("settings")),
            MenuItem("Debug", lambda: self.open_window("debug")),
            SEPARATOR,
            MenuItem("Bypass (send nothing to Rekordbox)", lambda: self.set_bypass(not self.bypass),
                     checked=self.bypass),
            MenuItem("Start with Windows", lambda: autostart.set_enabled(not login), checked=login),
            MenuItem("Open log folder", lambda: open_folder(self.log.folder)),
            MenuItem("Support RekordTrakt on Ko-fi", lambda: webbrowser.open(SUPPORT_URL)),
            SEPARATOR,
            MenuItem("Quit RekordTrakt", self.tray.quit),
        ]

    def run(self):
        try:
            self.tray.run()
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def close(self):
        self.hub.publish({"kind": "supervisor", "text": "quitting: releasing everything and turning LEDs off"})
        self.supervisor.shutdown()
        self.server.stop()
        self.tray.close()
        instance.clear_info()
        self.log.close()


def quit_running(info, timeout=10.0):
    """Asks the running app to quit and waits for it to go."""
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/quit", method="POST",
                                 headers={"X-RekordTrakt-Token": info["token"]})
    try:
        urllib.request.urlopen(req, timeout=3).read()
    except OSError:
        return False
    end = time.monotonic() + timeout
    while instance.is_running() and time.monotonic() < end:
        time.sleep(0.1)
    return not instance.is_running()


def restore_rekordbox():
    """For the uninstaller: puts Rekordbox's MIDI mapping files back as they were before RekordTrakt (the
    controllers' own mappings on, the bridge mapping gone). 0 when done, 2 while Rekordbox runs (it rewrites the
    files when it quits, so it must be closed first)."""
    from rekordtrakt.bridge import install as rb_install
    if rb_install.rekordbox_running():
        return 2
    rig = rig_mod.load()
    quiet = lambda *_: None                                                         # noqa: E731
    for d in rig["devices"].values():
        try:
            rb_install.enable(f"{d['port']}.midi.csv", announce=quiet)
        except OSError:
            pass                                    # Rekordbox has a mapping for it again: leave that one
    try:
        rb_install.restore(f"{rig['bridge']['rekordbox_port']}.midi.csv", announce=quiet)
    except LookupError:
        pass                                        # never installed
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="rekordtrakt app", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--debug", action="store_true", help="open the window on its Debug tab")
    p.add_argument("--login", action="store_true", help="started at login: open no windows")
    p.add_argument("--no-window", action="store_true", help="don't open the window")
    p.add_argument("--no-start", action="store_true", help="don't start the translator")
    p.add_argument("--quit", action="store_true", help="close the running app (releases everything, LEDs off)")
    p.add_argument("--restore-rekordbox", action="store_true",
                   help="put Rekordbox's MIDI mapping files back as they were (the uninstaller runs this)")
    args = p.parse_args(argv)
    if args.restore_rekordbox:
        return restore_rekordbox()
    single = instance.SingleInstance()
    if not single.first:
        info = instance.read_info()
        if info and args.quit:
            return 0 if quit_running(info) else 1
        if info and not args.login:
            tab = "debug" if args.debug else "controllers"
            window.open_window(f"http://127.0.0.1:{info['port']}/app?token={info['token']}#{tab}")
        return 0
    if args.quit:
        single.release()
        print("RekordTrakt isn't running.")
        return 0
    set_dpi_aware()
    try:
        tab = None if args.login or args.no_window else ("debug" if args.debug else "controllers")
        App(open_window=tab, start=not args.no_start).run()
    finally:
        single.release()
    return 0
