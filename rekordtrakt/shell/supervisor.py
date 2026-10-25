"""Keeps the translator running while the user wants it running (the watchdog).

- After a crash it restarts the translator, waiting a little longer each time (1 s up to 30 s). A run that lasts a
  minute resets the wait.
- When a controller is plugged in or unplugged, or the bridge ports disappear (e.g. the MIDI service restarted), it
  restarts the translator, which picks the controller up, carries on without it, or recreates the bridge.
- Stopping by hand stops the restarts.

Also keeps the slower-changing status the windows show: Rekordbox running, restarts, next restart.
"""
import csv
import ctypes
import io
import re
import subprocess
import threading
import time
from ctypes import wintypes

from rekordtrakt.service import FAILED, RUNNING, STOPPED

BACKOFF = (1, 2, 5, 10, 30)
# Rekordbox running this long, RekordTrakt having sent this much, and not one message back: Rekordbox isn't using the
# bridge (Rekordbox 7 without a paid plan, for one: its MIDI mapping is locked).
SILENT_AFTER, SILENT_SENT = 60.0, 5
STABLE_AFTER = 60.0
PORT_CHECK_EVERY = 3.0
BRIDGE_CHECK_EVERY = 20.0                # the installed bridge mapping file, for changes Rekordbox or an install make
REKORDBOX_CHECK_EVERY = 5.0
# Image name (lower case; a trailing * matches a prefix) -> what to call it. Other DJ software may hold the same
# controllers or MIDI ports, so it's worth knowing when it runs alongside.
DJ_SOFTWARE = {"rekordbox.exe": "rekordbox", "traktor.exe": "Traktor", "serato dj pro.exe": "Serato DJ Pro",
               "serato dj lite.exe": "Serato DJ Lite", "virtualdj*": "VirtualDJ", "mixxx.exe": "Mixxx",
               "djay pro*": "djay Pro", "engine dj.exe": "Engine DJ", "ableton live*": "Ableton Live",
               "bitwig studio.exe": "Bitwig Studio", "fl64.exe": "FL Studio", "max.exe": "Max"}


def running_dj_software():
    """Names of the DJ and music software running now (one tasklist call, no console window)."""
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    images = {line.split('","', 1)[0].strip('"').lower() for line in out.splitlines() if line.startswith('"')}
    found = []
    for pattern, name in DJ_SOFTWARE.items():
        if (pattern.endswith("*") and any(i.startswith(pattern[:-1]) for i in images)) or pattern in images:
            found.append(name)
    return found


def _process_path(pid):
    """The program file of a running process (no administrator rights needed for your own processes)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def version_from_path(path):
    """'7.2.19' from '...\\rekordbox 7.2.19\\rekordbox.exe' (Rekordbox installs each version in its own folder)."""
    m = re.search(r"rekordbox (\d+\.\d+\.\d+)", path or "", re.IGNORECASE)
    return m[1] if m else None


def rekordbox_version():
    """The running Rekordbox's version ('6.8.7', '7.2.19'), or None."""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq rekordbox.exe", "/FO", "CSV", "/NH"], capture_output=True,
                         text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    for row in csv.reader(io.StringIO(out)):
        if len(row) > 1 and row[0].lower() == "rekordbox.exe" and row[1].isdigit():
            version = version_from_path(_process_path(int(row[1])))
            if version:
                return version
    return None


class Supervisor:
    def __init__(self, make_translator, midi, publish, clock=time.monotonic, rekordbox_running=None,
                 dj_software=running_dj_software, rekordbox_version=rekordbox_version, on_rekordbox_version=None):
        self.make_translator = make_translator
        self.midi = midi
        self.publish = publish
        self.clock = clock
        self.dj_software = dj_software if rekordbox_running is None else (lambda: ["rekordbox"] if rekordbox_running() else [])
        self.others = []                     # other DJ software running (Traktor, Ableton Live, ...)
        self.translator = make_translator()
        self.wanted = False
        self.restarts = 0
        self.rekordbox = None
        self.rekordbox_since = None          # when Rekordbox was last seen starting
        self.rekordbox_version = None        # the running Rekordbox's version, e.g. "6.8.7"
        self._version_of = rekordbox_version
        self.on_rekordbox_version = on_rekordbox_version or (lambda version: None)
        self._failures = 0
        self._restart_at = None
        self._restarting = 0                 # restarts whose old translator is still stopping
        self._handled = None                 # the failed translator a restart is already scheduled for
        self._next_port_check = 0.0
        self._next_bridge_check = 0.0
        self._next_rekordbox_check = 0.0
        self._lock = threading.RLock()
        self._halt = threading.Event()
        self._thread = None

    # --- user actions (any thread) --------------------------------------------------------------------
    def start(self):
        with self._lock:
            self.wanted = True
            self._restart_at = None
            self._failures = 0
            self.translator.start()

    # Stopping waits for the translator thread (up to its timeout), so it happens outside the lock: the windows keep
    # getting status meanwhile instead of waiting with it.
    def stop(self):
        with self._lock:
            self.wanted = False
            self._restart_at = None
            t = self.translator
        t.stop()

    def restart(self, reason="restart requested"):
        with self._lock:
            self._say(f"restarting the translator: {reason}")
            old, self.translator = self.translator, self.make_translator()
            self.restarts += 1
            self._restarting += 1
        try:
            old.stop()
        finally:
            with self._lock:
                self._restarting -= 1
                if self.wanted and not self.translator.alive:
                    self.translator.start()

    def rekordbox_silent(self, stats):
        """True when Rekordbox has been running a while, RekordTrakt has sent to it, and it has answered nothing."""
        since = self.rekordbox_since
        return bool(self.rekordbox and since is not None and self.clock() - since > SILENT_AFTER
                    and stats.get("sent", 0) >= SILENT_SENT and not stats.get("feedback"))

    def snapshot(self):
        with self._lock:
            restart_in = max(0.0, self._restart_at - self.clock()) if self._restart_at else None
            return {"wanted": self.wanted, "restarts": self.restarts, "restart_in": restart_in,
                    "rekordbox_running": self.rekordbox, "other_dj_software": list(self.others),
                    "rekordbox_version": self.rekordbox_version,
                    "rekordbox_silent": self.rekordbox_silent(self.translator.snapshot().get("stats") or {}),
                    **self.translator.snapshot()}

    # --- watchdog thread ------------------------------------------------------------------------------
    def run_in_background(self, interval=0.25):
        self._thread = threading.Thread(target=self._watch, args=(interval,), name="supervisor", daemon=True)
        self._thread.start()

    def shutdown(self):
        self._halt.set()
        self.stop()
        if self._thread:
            self._thread.join(2)

    def _watch(self, interval):
        while not self._halt.wait(interval):
            try:
                self.check()
            except Exception as e:          # the watchdog itself must keep going
                self._say(f"watchdog error: {type(e).__name__}: {e}")

    def check(self):
        """One watchdog pass (called every `interval`; tests call it directly)."""
        now = self.clock()
        with self._lock:
            t = self.translator
            state = t.state
            if state == FAILED and self.wanted and not t.alive and self._restart_at is None and self._handled is not t:
                self._handled = t
                wait = BACKOFF[min(self._failures, len(BACKOFF) - 1)]
                self._failures += 1
                self._restart_at = now + wait
                self._say(f"translator failed; restarting in {wait} s", restart_in=wait)
            if state == RUNNING and t.started_at and time.time() - t.started_at > STABLE_AFTER:
                self._failures = 0
            if self._restart_at and now >= self._restart_at and self.wanted:
                self._restart_at = None
                self.translator = self.make_translator()
                self.restarts += 1
                self.translator.start()
            if state == RUNNING and now >= self._next_bridge_check:
                self._next_bridge_check = now + BRIDGE_CHECK_EVERY
                changed = getattr(t, "bridge_changed", None)
                if changed and changed():
                    self.restart("Rekordbox's MIDI mapping file changed")
                    return
            if state == RUNNING and now >= self._next_port_check:
                self._next_port_check = now + PORT_CHECK_EVERY
                self._check_ports(t)
            if state == STOPPED and self.wanted and not t.alive and not self._restart_at and not self._restarting:
                self.wanted = False            # it stopped by itself without an error (shouldn't happen)
        if now >= self._next_rekordbox_check:
            self._next_rekordbox_check = now + REKORDBOX_CHECK_EVERY
            try:
                found = self.dj_software()
            except OSError:
                found = None
            if found is not None:
                running = "rekordbox" in found
                others = [n for n in found if n != "rekordbox"]
                if running != self.rekordbox:
                    self.rekordbox = running
                    self.rekordbox_since = now if running else None
                    try:
                        self.rekordbox_version = self._version_of() if running else None
                    except OSError:
                        self.rekordbox_version = None
                    version = f" {self.rekordbox_version}" if self.rekordbox_version else ""
                    self.publish({"kind": "supervisor", "text": f"Rekordbox{version} {'running' if running else 'not running'}",
                                  "rekordbox_running": running, "rekordbox_version": self.rekordbox_version})
                    if self.rekordbox_version:
                        self.on_rekordbox_version(self.rekordbox_version)    # e.g. build the bridge for that version
                if others != self.others:
                    self.others = others
                    self.publish({"kind": "supervisor", "text": "Also running: " + (", ".join(others) or "none"),
                                  "other_dj_software": others})

    def _check_ports(self, t):
        inputs = self.midi.input_names()
        plugged = t.missing_ports(inputs)
        if plugged:
            self.restart(f"{', '.join(plugged)} plugged in")
            return
        unplugged = [pos for pos, d in t.devices.items() if d["connected"] and d["port"] not in inputs]
        if unplugged:
            self.restart(f"{', '.join(unplugged)} unplugged")
            return
        app_port = getattr(t, "app_port", None)
        if app_port and app_port not in inputs:
            self.restart(f"the bridge port '{app_port}' disappeared")

    def _say(self, text, **data):
        self.publish({"kind": "supervisor", "text": text, **data})
