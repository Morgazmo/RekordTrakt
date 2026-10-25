"""The app shell without hardware: bridge create-or-reuse, the translator service, the watchdog, the event hub, the
local web server, start at login and the tray icons.

Run from the repo root:  python -m unittest discover -s tests
"""
import http.client
import json
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from isolated import EXAMPLE                                              # noqa: E402  (first)
from rekordtrakt import rig as rig_mod                                    # noqa: E402
from rekordtrakt.bridge import ports                                      # noqa: E402
from rekordtrakt.midi.fake import FakeMidi                                # noqa: E402
from rekordtrakt.service import FAILED, RUNNING, STOPPED, Translator, as_installed      # noqa: E402
from rekordtrakt.shell import autostart                                   # noqa: E402
from rekordtrakt.shell.events import EventHub, FileLog                    # noqa: E402
from rekordtrakt.shell.icons import ICO_SIZES, ico_bytes, png_bytes, render   # noqa: E402
from rekordtrakt.shell.server import UiServer                             # noqa: E402
from rekordtrakt.shell.supervisor import Supervisor                       # noqa: E402

APP, BRIDGE = EXAMPLE["bridge"]["app_port"], EXAMPLE["bridge"]["rekordbox_port"]


def wait_until(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- fakes -------------------------------------------------------------------------------------------------------
class FakeHelper:
    def __init__(self, usable=True, create_ok=True, midi=None, active=(), saved=()):
        self.calls = []
        self.usable, self.create_ok, self.midi = usable, create_ok, midi
        self.active, self.saved = list(active), list(saved)

    def __call__(self, *args):
        self.calls.append(args)
        cmd = args[0]
        if cmd == "check":
            return {"usable": self.usable, "windows_supported": self.usable}
        if cmd == "create":
            if self.create_ok and self.midi is not None:
                self.midi.names += [args[2], args[4]]
            return {"success": self.create_ok, "association_id": "guid-1", "error": None if self.create_ok else "boom"}
        if cmd == "list":
            return {"success": True, "active": self.active, "saved": self.saved}
        if cmd == "remove":
            return {"success": True}
        raise AssertionError(cmd)


def loopback(guid, a=APP, b=BRIDGE, muted_for_feedback=False):
    return {"association_id": guid, "endpoint_a": {"name": a}, "endpoint_b": {"name": b}, "muted": False,
            "muted_for_feedback": muted_for_feedback}


# --- bridge ports ------------------------------------------------------------------------------------------------
class BridgePorts(unittest.TestCase):
    def test_existing_pair_is_used_as_it_is(self):
        midi, helper = FakeMidi([APP, BRIDGE]), FakeHelper(active=[loopback("g")])
        result = ports.ensure_pair(APP, BRIDGE, midi, helper=helper)
        self.assertEqual((result["ok"], result["state"]), (True, "existing"))
        self.assertNotIn("create", [c[0] for c in helper.calls])

    def test_missing_pair_is_created_with_fixed_ids(self):
        midi = FakeMidi([])
        helper = FakeHelper(midi=midi)
        result = ports.ensure_pair(APP, BRIDGE, midi, helper=helper, sleep=lambda s: None)
        self.assertEqual((result["ok"], result["state"]), (True, "created"))
        create = next(c for c in helper.calls if c[0] == "create")
        self.assertEqual(create, ("create", "--name-a", APP, "--name-b", BRIDGE,
                                  "--id-a", ports.UNIQUE_IDS[0], "--id-b", ports.UNIQUE_IDS[1]))

    def test_duplicate_names_fail_closed(self):
        helper = FakeHelper()
        result = ports.ensure_pair(APP, BRIDGE, FakeMidi([APP, BRIDGE, APP, BRIDGE]), helper=helper)
        self.assertEqual((result["ok"], result["state"]), (False, "duplicate"))
        result = ports.ensure_pair(APP, BRIDGE, FakeMidi([APP, BRIDGE, BRIDGE]), helper=helper)
        self.assertFalse(result["ok"])
        self.assertNotIn("create", [c[0] for c in helper.calls])

    def test_pairing_check(self):
        paired = FakeMidi([APP, BRIDGE], links={APP: BRIDGE, BRIDGE: APP})
        self.assertIsNone(ports.verify_pair(APP, BRIDGE, paired, timeout=0.2))
        crossed = FakeMidi([APP, BRIDGE, "Other"], links={APP: "Other", BRIDGE: APP})
        self.assertIn("aren't connected", ports.verify_pair(APP, BRIDGE, crossed, timeout=0.2))
        self.assertIn("couldn't open", ports.verify_pair(APP, BRIDGE, FakeMidi([APP]), timeout=0.2))
        single = FakeMidi(["loopMIDI Port"], links={"loopMIDI Port": "loopMIDI Port"})     # loopMIDI echoes
        self.assertIsNone(ports.verify_pair("loopMIDI Port", "loopMIDI Port", single, timeout=0.2))

    def test_no_windows_midi_services_suggests_loopmidi(self):
        result = ports.ensure_pair(APP, BRIDGE, FakeMidi([]), helper=FakeHelper(usable=False))
        self.assertEqual((result["ok"], result["state"]), (False, "unavailable"))
        self.assertIn("loopMIDI", result["message"])

    def test_created_ports_that_never_appear_fail(self):
        result = ports.ensure_pair(APP, BRIDGE, FakeMidi([]), helper=FakeHelper(), wait=0.05, sleep=lambda s: None)
        self.assertEqual((result["ok"], result["state"]), (False, "failed"))

    def test_muted_for_feedback_is_reported(self):
        helper = FakeHelper(active=[loopback("g", muted_for_feedback=True)])
        result = ports.ensure_pair(APP, BRIDGE, FakeMidi([APP, BRIDGE]), helper=helper)
        self.assertTrue(result["muted"])
        self.assertIn("feedback loop", result["message"])

    def test_remove_leaves_midi_settings_pairs_alone(self):
        helper = FakeHelper(active=[loopback("saved-guid")], saved=[{"association_id": "saved-guid"}])
        self.assertFalse(ports.remove_pair(APP, BRIDGE, helper=helper)["ok"])
        self.assertNotIn("remove", [c[0] for c in helper.calls])
        helper = FakeHelper(active=[loopback("ours")])
        self.assertEqual(ports.remove_pair(APP, BRIDGE, helper=helper)["removed"], ["ours"])


# --- translator service ------------------------------------------------------------------------------------------
def example_rig():
    return json.loads(json.dumps(EXAMPLE))


class TranslatorService(unittest.TestCase):
    def setUp(self):
        self.rig = example_rig()
        self.x1 = self.rig["devices"]["x1_left"]["port"]
        self.midi = FakeMidi([APP, BRIDGE, self.x1], links={APP: BRIDGE, BRIDGE: APP})
        self.events = []
        self.t = Translator(self.midi, load_rig=lambda: self.rig, trace=self.events.append,
                            ensure_bridge=lambda a, b: {"ok": True, "state": "existing", "message": "ok"},
                            checks=lambda rig, csv: ["mapping out of date"], read_rekordbox=as_installed)

    def tearDown(self):
        self.t.stop()

    def test_runs_routes_and_neutralises_on_stop(self):
        self.t.start()
        self.assertTrue(wait_until(lambda: self.t.state == RUNNING))
        self.assertEqual(self.t.warnings, ["mapping out of date"])
        self.assertFalse(self.t.devices["x1_right"]["connected"])
        self.midi.inject(self.x1, 0x90, 0x0A, 0x7F)          # left half Play
        self.assertTrue(wait_until(lambda: any(e["kind"] == "send" for e in self.events)))
        press = next(e for e in self.events if e["kind"] == "input")
        self.assertEqual((press["position"], press["control"], press["raw"]), ("x1_left", "L.play", [0x90, 0x0A, 0x7F]))
        sends = [e for e in self.events if e["kind"] == "send"]
        self.assertTrue(all(e["input"] == press["input"] for e in sends))
        self.assertTrue(any(e["kind"] == "binding" and e["input"] == press["input"] for e in self.events))
        before = len(self.midi.sent[APP])
        self.t.stop()
        self.assertEqual(self.t.state, STOPPED)
        released = self.midi.sent[APP][before:]
        self.assertTrue(released and all(d2 == 0 for s, _, d2 in released if s & 0xF0 == 0x90))

    def test_counts_and_reports_missing_controllers(self):
        self.t.start()
        self.assertTrue(wait_until(lambda: self.t.state == RUNNING))
        x1_right = self.rig["devices"]["x1_right"]["port"]
        self.assertEqual(self.t.missing_ports([APP, BRIDGE, self.x1]), [])
        self.assertEqual(self.t.missing_ports([APP, BRIDGE, self.x1, x1_right]), ["x1_right"])

    def test_a_changed_bridge_file_is_noticed(self):
        from rekordtrakt.service import full_bridge
        found = {"bridge": full_bridge(self.rig)[0], "direct": []}
        self.t.read_rekordbox = lambda rig: found
        self.t.start()
        self.assertTrue(wait_until(lambda: self.t.state == RUNNING))
        self.assertFalse(self.t.bridge_changed())
        rows = found["bridge"].strip().split("\r\n")
        found["bridge"] = "\r\n".join(rows[:-1]) + "\r\n"          # a row gone (Rekordbox dropped one)
        self.assertTrue(self.t.bridge_changed())

    def test_unpaired_bridge_ports_are_refused(self):
        self.midi.links = {}
        self.t.start()
        self.assertTrue(wait_until(lambda: self.t.state == FAILED))
        self.assertIn("aren't connected", self.t.error)
        self.assertEqual(self.t.bridge["state"], "unpaired")

    def test_bridge_problem_fails_with_the_reason(self):
        self.t.ensure_bridge = lambda a, b: {"ok": False, "state": "unavailable", "message": "no MIDI service"}
        self.t.start()
        self.assertTrue(wait_until(lambda: self.t.state == FAILED))
        self.assertIn("no MIDI service", self.t.error)
        self.assertTrue(any(e["kind"] == "error" for e in self.events))


# --- watchdog ----------------------------------------------------------------------------------------------------
class FakeTranslator:
    def __init__(self, outcome):
        self.outcome = outcome            # RUNNING or FAILED when started
        self.state, self.error, self.alive = STOPPED, None, False
        self.devices, self.started_at, self.app_port = {}, None, APP
        self.missing = []
        self.stopped = False

    def start(self):
        self.state = self.outcome
        self.error = "boom" if self.outcome == FAILED else None
        self.started_at = time.time()

    def stop(self):
        self.stopped = True
        self.state = STOPPED

    def missing_ports(self, inputs):
        return self.missing

    def snapshot(self):
        return {"state": self.state, "error": self.error, "devices": self.devices, "warnings": [], "bridge": None,
                "stats": {}, "started_at": self.started_at}


class RekordboxVersion(unittest.TestCase):
    def test_the_version_comes_from_the_program_folder(self):
        from rekordtrakt.shell.supervisor import version_from_path
        self.assertEqual(version_from_path(r"C:\Program Files\Pioneer\rekordbox 6.8.7\rekordbox.exe"), "6.8.7")
        self.assertEqual(version_from_path(r"C:\Program Files\rekordbox\rekordbox 7.2.19\rekordbox.exe"), "7.2.19")
        self.assertIsNone(version_from_path(r"D:\Apps\rb\rekordbox.exe"))

    def test_the_supervisor_reports_which_rekordbox_started(self):
        seen = []
        sup = Supervisor(lambda: FakeTranslator(RUNNING), FakeMidi([APP]), lambda e: None, clock=lambda: 0.0,
                         dj_software=lambda: ["rekordbox"], rekordbox_version=lambda: "7.2.19",
                         on_rekordbox_version=seen.append)
        sup.check()
        self.assertEqual((sup.snapshot()["rekordbox_version"], seen), ("7.2.19", ["7.2.19"]))

    def _setup(self, rig, restarts):
        from rekordtrakt.shell.rekordbox_setup import RekordboxSetup

        class Sup:
            def restart(inner, reason):
                restarts.append(reason)

        def save(new):
            rig.clear()
            rig.update(new)
        return RekordboxSetup(Sup(), load_rig=lambda: json.loads(json.dumps(rig)), save_rig=save,
                              later=lambda fn, *a: fn(*a))

    def test_the_bridge_follows_the_rekordbox_you_run(self):
        from rekordtrakt.service import rekordbox_target
        rig, restarts = example_rig(), []
        rig["bridge"].pop("rekordbox", None)
        setup = self._setup(rig, restarts)
        self.assertNotIn("rekordbox-version", setup.actions())        # nothing to choose
        self.assertEqual(rekordbox_target(rig), 6)
        setup.seen("7.2.19")
        self.assertEqual((rekordbox_target(rig), len(restarts)), (7, 1))
        setup.seen("7.2.19")                                    # the same version again: nothing to do
        self.assertEqual(len(restarts), 1)
        setup.seen("6.8.7")
        self.assertEqual((rekordbox_target(rig), len(restarts)), (6, 2))

    def test_a_version_picked_by_hand_before_counts_until_rekordbox_is_seen(self):
        from rekordtrakt.service import rekordbox_target
        rig, restarts = example_rig(), []
        rig["bridge"]["rekordbox"] = 6                          # an older RekordTrakt's Settings choice
        rig["bridge"]["rekordbox_seen"] = 7
        setup = self._setup(rig, restarts)
        self.assertEqual(rekordbox_target(rig), 6)
        setup.seen("6.8.7")                                     # the same major: forget the old choice, no restart
        self.assertEqual((rekordbox_target(rig), "rekordbox" in rig["bridge"], restarts), (6, False, []))


class SilentRekordbox(unittest.TestCase):
    def test_rekordbox_that_never_answers_is_reported(self):
        now = [0.0]
        t = FakeTranslator(RUNNING)
        t.stats = {"sent": 0, "feedback": 0}
        t.snapshot = lambda: {"state": RUNNING, "stats": dict(t.stats)}
        sup = Supervisor(lambda: t, FakeMidi([APP]), lambda e: None, clock=lambda: now[0],
                         dj_software=lambda: ["rekordbox"])
        sup.check()                                   # Rekordbox seen
        now[0] = 30.0
        t.stats = {"sent": 12, "feedback": 0}
        self.assertFalse(sup.snapshot()["rekordbox_silent"])    # too soon to say
        now[0] = 90.0
        self.assertTrue(sup.snapshot()["rekordbox_silent"])
        t.stats = {"sent": 12, "feedback": 3}
        self.assertFalse(sup.snapshot()["rekordbox_silent"])


class Watchdog(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.made = []
        self.outcomes = []
        self.published = []

    def supervisor(self, outcomes=()):
        self.outcomes = list(outcomes)

        def make():
            t = FakeTranslator(self.outcomes.pop(0) if self.outcomes else RUNNING)
            self.made.append(t)
            return t
        self.sup = Supervisor(make, FakeMidi([APP, BRIDGE]), self.published.append, clock=lambda: self.now,
                              rekordbox_running=lambda: False)
        return self.sup

    def test_crash_restarts_with_growing_waits(self):
        self.supervisor([FAILED, FAILED, FAILED]).start()
        self.sup.check()
        self.assertEqual(self.sup.snapshot()["restart_in"], 1)
        self.now += 1
        self.sup.check()                  # restart 1 (fails again)
        self.sup.check()
        self.assertEqual(self.sup.snapshot()["restart_in"], 2)
        self.now += 2
        self.sup.check()                  # restart 2
        self.assertEqual(self.sup.restarts, 2)
        self.assertTrue(any("restarting in 2 s" in e["text"] for e in self.published))

    def test_stopping_by_hand_cancels_the_restart(self):
        self.supervisor([FAILED]).start()
        self.sup.check()
        self.assertEqual(self.sup.snapshot()["restart_in"], 1)
        self.sup.stop()
        self.now += 60
        self.sup.check()
        self.assertEqual(self.sup.restarts, 0)
        self.assertIsNone(self.sup.snapshot()["restart_in"])

    def test_plugging_in_a_missing_controller_restarts(self):
        self.supervisor().start()
        self.made[-1].missing = ["x1_right"]
        self.sup.check()
        self.assertEqual(self.sup.restarts, 1)
        self.assertTrue(self.made[0].stopped)
        self.assertEqual(self.made[-1].state, RUNNING)

    def test_unplugging_a_controller_restarts(self):
        self.supervisor().start()
        self.made[-1].devices = {"x1_left": {"connected": True, "port": "gone"}}
        self.sup.check()
        self.assertEqual(self.sup.restarts, 1)
        self.assertTrue(any("x1_left unplugged" in e["text"] for e in self.published))

    def test_bridge_port_disappearing_restarts(self):
        self.supervisor().midi.names = [BRIDGE]
        self.sup.start()
        self.sup.check()
        self.assertEqual(self.sup.restarts, 1)


# --- event hub and log -------------------------------------------------------------------------------------------
class Events(unittest.TestCase):
    def test_numbers_keeps_history_and_counts_drops(self):
        hub = EventHub(history=2)
        for i in range(3):
            hub.publish({"kind": "notice", "text": str(i)})
        q, backlog = hub.subscribe(maxsize=1)
        self.assertEqual([e["seq"] for e in backlog], [2, 3])
        hub.publish({"kind": "notice", "text": "a"})
        hub.publish({"kind": "notice", "text": "b"})
        self.assertEqual(q.get_nowait()["text"], "a")
        self.assertEqual(hub.dropped, 1)

    def test_file_log_writes_notices_not_traffic(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = EventHub()
            log = FileLog(hub, folder=tmp)
            hub.publish({"kind": "send", "text": "-> PlayPause"})
            hub.publish({"kind": "error", "text": "translator stopped", "detail": "Traceback..."})
            log.close()
            text = log.path.read_text(encoding="utf-8")
            self.assertIn("translator stopped", text)
            self.assertIn("Traceback", text)
            self.assertNotIn("PlayPause", text)


# --- local web server --------------------------------------------------------------------------------------------
class WebServer(unittest.TestCase):
    def setUp(self):
        self.hub = EventHub()
        self.acted = []
        self.server = UiServer(self.hub, lambda: {"state": "running"},
                               {"start": lambda body: self.acted.append(("start", body)) or "started"})
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def request(self, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=3)
        conn.request(method, path, headers=headers or {})
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r, body

    def test_needs_the_token(self):
        self.assertEqual(self.request("GET", "/api/status")[0].status, 403)
        self.assertEqual(self.request("GET", "/api/status?token=wrong")[0].status, 403)
        r, body = self.request("GET", f"/api/status?token={self.server.token}")
        self.assertEqual((r.status, json.loads(body)), (200, {"state": "running"}))

    def test_rejects_other_host_names(self):            # DNS rebinding
        r, _ = self.request("GET", f"/api/status?token={self.server.token}", {"Host": f"evil.example:{self.server.port}"})
        self.assertEqual(r.status, 403)

    def test_actions_need_the_header_and_a_local_origin(self):
        t = self.server.token
        self.assertEqual(self.request("POST", f"/api/start?token={t}")[0].status, 403)
        r, _ = self.request("POST", "/api/start", {"X-RekordTrakt-Token": t, "Origin": "https://evil.example"})
        self.assertEqual(r.status, 403)
        r, body = self.request("POST", "/api/start", {"X-RekordTrakt-Token": t})
        self.assertEqual((r.status, json.loads(body)["result"]), (200, "started"))
        self.assertEqual(self.acted, [("start", {})])

    def test_the_windows_own_code_is_served_and_nothing_else(self):
        r, _ = self.request("GET", "/web/app.css")                      # public code: no token needed
        self.assertEqual((r.status, r.getheader("Content-Type")), (200, "text/css; charset=utf-8"))
        r, _ = self.request("GET", "/web/js/main.js")
        self.assertEqual((r.status, r.getheader("Content-Type")), (200, "text/javascript; charset=utf-8"))
        for path in ("/web/../server.py", "/web/js/../../server.py", "/web/missing.js", "/web/app.html"):
            self.assertIn(self.request("GET", path)[0].status, (403, 404), path)
        r, _ = self.request("GET", f"/app?token={self.server.token}")
        policy = r.getheader("Content-Security-Policy")
        self.assertIn("script-src 'self';", policy)                        # no inline scripts on the main page

    def test_debug_page_has_a_strict_policy(self):
        r, body = self.request("GET", f"/debug?token={self.server.token}")
        self.assertEqual(r.status, 200)
        self.assertIn("default-src 'none'", r.getheader("Content-Security-Policy"))
        self.assertIn(b"RekordTrakt Debug", body)

    def test_actions_get_the_json_body_and_bad_bodies_are_refused(self):
        t = self.server.token
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=3)
        conn.request("POST", "/api/start", body=json.dumps({"deck": 2}),
                     headers={"X-RekordTrakt-Token": t, "Content-Type": "application/json"})
        r = conn.getresponse()
        r.read()
        conn.close()
        self.assertEqual((r.status, self.acted[-1]), (200, ("start", {"deck": 2})))
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=3)
        conn.request("POST", "/api/start", body="[1, 2]", headers={"X-RekordTrakt-Token": t})
        r = conn.getresponse()
        r.read()
        conn.close()
        self.assertEqual(r.status, 400)

    def test_stream_can_be_limited_to_some_kinds(self):
        self.hub.publish({"kind": "send", "text": "noise"})
        self.hub.set_state("view", {"devices": []})
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=3)
        conn.request("GET", f"/events?token={self.server.token}&kinds=view")
        r = conn.getresponse()
        lines = []
        while True:
            line = r.fp.readline().decode().rstrip("\n")
            if not line:
                break
            lines.append(line)
        backlog = json.loads(lines[1][len("data: "):])
        conn.close()
        self.assertEqual([e["kind"] for e in backlog], ["view"])

    def test_stream_sends_the_backlog_then_live_events(self):
        self.hub.publish({"kind": "notice", "text": "before"})
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=3)
        conn.request("GET", f"/events?token={self.server.token}")
        r = conn.getresponse()
        self.assertEqual(r.getheader("Content-Type"), "text/event-stream; charset=utf-8")

        def message():
            lines = []
            while True:
                line = r.fp.readline().decode().rstrip("\n")
                if not line:
                    return lines
                if not line.startswith(":"):
                    lines.append(line)
        backlog = message()
        self.assertEqual(backlog[0], "event: backlog")
        self.assertEqual(json.loads(backlog[1][len("data: "):])[0]["text"], "before")
        self.hub.publish({"kind": "notice", "text": "after"})
        live = message()
        self.assertEqual(json.loads(live[0][len("data: "):])["text"], "after")
        conn.close()


# --- when Windows' MIDI service stops responding ------------------------------------------------------------------
class StuckMidiService(unittest.TestCase):
    def test_a_stuck_open_is_reported_and_the_port_released_when_it_finally_opens(self):
        import threading
        from unittest import mock
        from rekordtrakt.midi import winmm
        release, closed = threading.Event(), []
        with mock.patch.object(winmm, "OPEN_LIMIT", 0.2):
            with self.assertRaises(winmm.MidiServiceStuck) as e:
                winmm._open("Port A", lambda: release.wait() and 0, lambda: closed.append("A"))
            self.assertIn("restart the Windows MIDI Service", str(e.exception))
            self.assertTrue(winmm.service_stuck())
            with self.assertRaises(winmm.MidiServiceStuck) as e:    # fails at once while one open is stuck
                winmm._open("Port B", lambda: 0, lambda: closed.append("B"))
            self.assertIn("Port A", str(e.exception))
            release.set()                                           # the service recovers
            self.assertTrue(wait_until(lambda: not winmm.service_stuck()))
            self.assertEqual(closed, ["A"])                         # nobody wanted it any more: closed again
            self.assertEqual(winmm._open("Port B", lambda: 0, lambda: closed.append("B")), 0)
            self.assertEqual(closed, ["A"])

    def test_status_stays_available_while_a_restart_waits_for_the_translator(self):
        import threading

        class Slow(FakeTranslator):
            def stop(inner):
                time.sleep(0.6)
                FakeTranslator.stop(inner)

        made = []

        def make():
            made.append(Slow(RUNNING))
            return made[-1]

        sup = Supervisor(make, FakeMidi([APP]), lambda e: None, clock=time.monotonic, dj_software=lambda: [])
        sup.start()
        restarting = threading.Thread(target=sup.restart, args=("test",))
        restarting.start()
        time.sleep(0.1)
        began = time.monotonic()
        sup.snapshot()
        sup.check()                                       # the watchdog mustn't think it stopped by itself
        self.assertLess(time.monotonic() - began, 0.3)
        restarting.join()
        self.assertTrue(sup.wanted)
        self.assertEqual((len(made), made[-1].state), (2, RUNNING))


# --- updating Rekordbox's mapping from the window ----------------------------------------------------------------
class RekordboxFlow(unittest.TestCase):
    """Close Rekordbox, install, start it: each on a click, never while a deck plays without asking."""

    def setUp(self):
        from rekordtrakt.bridge import install as rb
        from rekordtrakt.shell.rekordbox_setup import RekordboxSetup
        self.rb = rb
        self.running, self.closed, self.launched, self.applied, self.restarts = True, 0, [], [], []
        self.playing, self.conflict = [], False

        class Translator:
            def call(inner, fn):
                return fn(type("E", (), {"playing_decks": lambda _self: self.playing})())

        class Sup:
            translator = Translator()

            def restart(inner, reason):
                self.restarts.append(reason)

        def apply(path, direct, overwrite_user_edit=False, announce=print, wait=True):
            if self.conflict and not overwrite_user_edit:
                raise rb.InstallConflict("edited by hand")
            self.applied.append((Path(path).name, list(direct), Path(path).read_text(encoding="ascii")))

        self.midi_stuck = False
        self.setup = RekordboxSetup(Sup(), load_rig=example_rig, running=lambda: self.running, apply=apply,
                                    close=lambda: setattr(self, "closed", self.closed + 1),
                                    find=lambda: Path("rekordbox.exe"), launch=self.launched.append,
                                    out_dir=tempfile.mkdtemp(), midi_stuck=lambda: self.midi_stuck,
                                    later=lambda fn, *args: fn(*args))

    def test_close_asks_first_while_a_deck_plays(self):
        self.playing = [1]
        self.assertEqual(self.setup.close({}), {"closing": False, "running": True, "playing": [1]})
        self.assertEqual(self.closed, 0)
        self.assertTrue(self.setup.close({"anyway": True})["closing"])
        self.assertEqual(self.closed, 1)

    def test_install_waits_for_rekordbox_then_installs_everything_and_restarts(self):
        self.assertEqual(self.setup.install({}), {"installed": False, "needs": "close"})
        self.running = False
        result = self.setup.install({})
        self.assertTrue(result["installed"])
        name, direct, csv_text = self.applied[0]
        rig = example_rig()
        self.assertEqual(name, f"{rig['bridge']['rekordbox_port']}.midi.csv")
        self.assertEqual(direct, [f"{d['port']}.midi.csv" for d in rig["devices"].values()])
        from rekordtrakt.service import full_bridge
        self.assertEqual(result["entries"], len(full_bridge(rig)[1]["entries"]))
        self.assertIn("PAD8_Keyboard,", csv_text)               # the whole registry, not just what the rig uses
        self.assertEqual(len(self.restarts), 1)

    def test_a_hand_edited_mapping_is_only_replaced_on_a_second_click(self):
        self.running, self.conflict = False, True
        self.assertIn("conflict", self.setup.install({}))
        self.assertEqual(self.applied, [])
        self.assertTrue(self.setup.install({"overwrite": True})["installed"])

    def test_start(self):
        self.assertEqual(self.setup.start({}), {"starting": False, "running": True})
        self.running = False
        self.midi_stuck = True                  # Rekordbox would freeze while starting: say so instead
        with self.assertRaises(RuntimeError) as e:
            self.setup.start({})
        self.assertIn("MIDI service", str(e.exception))
        self.midi_stuck = False
        self.assertEqual(self.setup.start({}), {"starting": True})
        self.assertEqual(self.launched, ["rekordbox.exe"])

    def test_a_rekordbox_that_isnt_responding_can_be_ended_on_a_click(self):
        from rekordtrakt.shell.rekordbox_setup import parse_tasklist
        listing = ('"rekordbox.exe","41652","Console","1","1,846,892 K","Not Responding","PC\\me","0:00:51",'
                   '"rekordbox"\n"rekordboxAgent.exe","15728","Console","1","40 K","Running","PC\\me","0:00:00","N/A"\n')
        self.assertEqual(parse_tasklist(listing), [{"pid": 41652, "status": "Not Responding", "window": "rekordbox"}])
        self.setup.processes = lambda: parse_tasklist(listing)
        self.assertEqual(self.setup.check({})["responding"], False)
        ended = []
        self.setup.end_rekordbox = lambda: ended.append(True)
        self.assertTrue(self.setup.close({"end": True})["ended"])
        self.assertEqual((ended, self.closed), ([True], 0))

    def test_finds_the_version_the_registry_was_made_for(self):
        from rekordtrakt.shell.rekordbox_setup import find_rekordbox
        root = Path(tempfile.mkdtemp())
        for version in ("6.6.4", "6.8.7", "6.8.9"):
            (root / "Pioneer" / f"Rekordbox {version}").mkdir(parents=True)
            (root / "Pioneer" / f"Rekordbox {version}" / "rekordbox.exe").write_bytes(b"")
        self.assertEqual(find_rekordbox(str(root)).parent.name, "Rekordbox 6.8.7")
        self.assertIsNone(find_rekordbox(tempfile.mkdtemp()))


# --- what's on this PC ------------------------------------------------------------------------------------------
class Discovery(unittest.TestCase):
    def test_midi_devices_are_sorted_into_what_rekordtrakt_does_with_them(self):
        from rekordtrakt.shell.app import midi_devices
        rig = json.loads(json.dumps(EXAMPLE))
        x1 = rig["devices"]["x1_left"]["port"]
        midi = FakeMidi([APP, BRIDGE, x1, "DDJ-XP1", "LPProMK3 MIDI", "5 - TRAKTOR X1 MK3"])
        status = {d["port"]: d["status"] for d in midi_devices(midi, rig)}
        self.assertEqual(status, {APP: "bridge", BRIDGE: "bridge", x1: "added", "DDJ-XP1": "rekordbox",
                                  "LPProMK3 MIDI": "unknown", "5 - TRAKTOR X1 MK3": "supported"})

    def test_other_dj_software_from_the_process_list(self):
        from unittest import mock
        from rekordtrakt.shell import supervisor
        listing = ('"rekordbox.exe","1","Console","1","1 K"\n"Traktor.exe","2","Console","1","1 K"\n'
                   '"Ableton Live 12 Suite.exe","3","Console","1","1 K"\n"notepad.exe","4","Console","1","1 K"\n')
        with mock.patch.object(supervisor.subprocess, "run", return_value=mock.Mock(stdout=listing)):
            self.assertEqual(supervisor.running_dj_software(), ["rekordbox", "Traktor", "Ableton Live"])


# --- start at login and icons ------------------------------------------------------------------------------------
class FakeReg:
    HKEY_CURRENT_USER, KEY_SET_VALUE, REG_SZ = "HKCU", 2, 1

    def __init__(self):
        self.values = {}

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(self, root, path, reserved=0, access=0):
        return self._Key()

    def CreateKey(self, root, path):
        return self._Key()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class StartAtLogin(unittest.TestCase):
    def test_enable_and_disable(self):
        reg = FakeReg()
        self.assertFalse(autostart.is_enabled(reg))
        autostart.enable(reg)
        self.assertTrue(autostart.is_enabled(reg))
        self.assertIn("RekordTrakt.pyw", reg.values["RekordTrakt"])
        self.assertTrue(reg.values["RekordTrakt"].endswith("--login"))
        autostart.disable(reg)
        autostart.disable(reg)                           # already off: fine
        self.assertFalse(autostart.is_enabled(reg))


class Icons(unittest.TestCase):
    def test_ico_layout(self):
        data = ico_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", data)
        self.assertEqual((reserved, kind, count), (0, 1, len(ICO_SIZES)))
        for i, n in enumerate(ICO_SIZES):
            w, h, _, _, planes, bits, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
            self.assertEqual((w, h, planes, bits), (n % 256, n % 256, 1, 32))
            if n >= 256:
                self.assertEqual(data[offset:offset + 8], b"\x89PNG\r\n\x1a\n")     # big sizes as PNG
            else:
                self.assertEqual(struct.unpack_from("<I", data, offset)[0], 40)     # BITMAPINFOHEADER
            self.assertLessEqual(offset + size, len(data))

    def test_mark_geometry(self):
        rgba = render(96)
        px = lambda x, y: rgba[(y * 96 + x) * 4:(y * 96 + x) * 4 + 4]                # noqa: E731
        self.assertEqual(px(48, 48), bytes((255, 255, 255, 255)))                    # centre dot
        self.assertEqual(px(48 + 28, 48)[:3], bytes((93, 202, 165)))                # ring, right side
        self.assertEqual(px(0, 0)[3], 0)                                             # rounded corner: clear
        self.assertEqual(px(2, 2)[3], 0)
        self.assertEqual(px(48, 8)[:3], bytes((28, 31, 38)))                         # tile background
        self.assertEqual(png_bytes(4, render(4))[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
