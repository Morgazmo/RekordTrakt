"""Minimal MIDI 1.0 port access through the Windows multimedia API (winmm.dll), using ctypes only.

Incoming messages arrive on a winmm thread and are pushed onto a thread-safe queue as
(port_name, status, data1, data2, time.perf_counter()).

Opening a port is time-limited. When Windows' MIDI service stops responding, listing ports still works but every
open hangs (any port, any program), which freezes Rekordbox while it starts too. An open that takes longer than
OPEN_LIMIT raises MidiServiceStuck with what to do, and while one is still stuck, further opens fail at once instead
of piling up more stuck threads.
"""
import ctypes
import queue
import threading
import time
from ctypes import wintypes

_winmm = ctypes.WinDLL("winmm")

MAXPNAMELEN = 32
CALLBACK_FUNCTION = 0x00030000
MIM_DATA = 0x3C3


class _MidiInCaps(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * MAXPNAMELEN), ("dwSupport", wintypes.DWORD)]


class _MidiOutCaps(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * MAXPNAMELEN), ("wTechnology", wintypes.WORD),
                ("wVoices", wintypes.WORD), ("wNotes", wintypes.WORD), ("wChannelMask", wintypes.WORD),
                ("dwSupport", wintypes.DWORD)]


_MidiInProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t)

OPEN_LIMIT = 5.0            # seconds; a healthy open takes milliseconds
STUCK_ADVICE = ("Windows' MIDI service isn't responding, so MIDI ports can't be opened (Rekordbox freezes while "
                "starting like this too). Close Rekordbox, then restart the Windows MIDI Service, or restart Windows.")
_pending = set()            # names of ports whose open hasn't returned yet
_pending_lock = threading.Lock()


class MidiServiceStuck(OSError):
    pass


def service_stuck():
    """True while an earlier open is still waiting on Windows' MIDI service."""
    with _pending_lock:
        return bool(_pending)


def _open(name, open_fn, close_fn):
    """Runs open_fn() (it returns a winmm error code) on a helper thread and waits at most OPEN_LIMIT. If the open
    finishes after we stopped waiting, close_fn() releases the port again so nothing is left holding it."""
    with _pending_lock:
        if _pending:
            raise MidiServiceStuck(f"{STUCK_ADVICE} (Still waiting to open '{next(iter(_pending))}'.)")
        _pending.add(name)
    state = {"err": None, "abandoned": False}
    done, lock = threading.Event(), threading.Lock()

    def run():
        err = open_fn()
        with lock:
            state["err"] = err
            if state["abandoned"] and not err:
                close_fn()
            done.set()
        with _pending_lock:
            _pending.discard(name)

    threading.Thread(target=run, name=f"midi open {name}", daemon=True).start()
    if not done.wait(OPEN_LIMIT):
        with lock:
            if not done.is_set():
                state["abandoned"] = True
                raise MidiServiceStuck(f"{STUCK_ADVICE} (Opening '{name}' took over {OPEN_LIMIT:.0f} s.)")
    return state["err"]


def input_names():
    names = []
    for i in range(_winmm.midiInGetNumDevs()):
        caps = _MidiInCaps()
        _winmm.midiInGetDevCapsW(ctypes.c_size_t(i), ctypes.byref(caps), ctypes.sizeof(caps))
        names.append(caps.szPname)
    return names


def output_names():
    names = []
    for i in range(_winmm.midiOutGetNumDevs()):
        caps = _MidiOutCaps()
        _winmm.midiOutGetDevCapsW(ctypes.c_size_t(i), ctypes.byref(caps), ctypes.sizeof(caps))
        names.append(caps.szPname)
    return names


class MidiOut:
    def __init__(self, name):
        names = output_names()
        if name not in names:
            raise LookupError(f"MIDI output '{name}' not found. Outputs: {names}")
        self.name = name
        self._handle = wintypes.HANDLE()
        index = names.index(name)
        err = _open(name, lambda: _winmm.midiOutOpen(ctypes.byref(self._handle), index, None, None, 0),
                    lambda: _winmm.midiOutClose(self._handle))
        if err:
            raise OSError(f"midiOutOpen('{name}') failed with error {err}")

    def send(self, status, data1, data2=0):
        msg = (status & 0xFF) | ((data1 & 0x7F) << 8) | ((data2 & 0x7F) << 16)
        err = _winmm.midiOutShortMsg(self._handle, wintypes.DWORD(msg))
        if err:
            raise OSError(f"midiOutShortMsg on '{self.name}' failed with error {err}")

    def close(self):
        if self._handle:
            _winmm.midiOutClose(self._handle)
            self._handle = wintypes.HANDLE()


class MidiIn:
    """Opens one input port; messages go to `sink` (a queue.Queue shared between ports is fine)."""

    def __init__(self, name, sink: queue.Queue):
        names = input_names()
        if name not in names:
            raise LookupError(f"MIDI input '{name}' not found. Inputs: {names}")
        self.name = name
        self._sink = sink
        self._callback = _MidiInProc(self._on_message)   # must stay referenced while the port is open
        self._handle = wintypes.HANDLE()
        index = names.index(name)

        def open_and_start():
            err = _winmm.midiInOpen(ctypes.byref(self._handle), index, self._callback, None, CALLBACK_FUNCTION)
            if not err:
                _winmm.midiInStart(self._handle)
            return err

        err = _open(name, open_and_start, lambda: _winmm.midiInClose(self._handle))
        if err:
            raise OSError(f"midiInOpen('{name}') failed with error {err}")

    def _on_message(self, handle, msg, instance, param1, param2):
        if msg != MIM_DATA:
            return
        status, data1, data2 = param1 & 0xFF, (param1 >> 8) & 0xFF, (param1 >> 16) & 0xFF
        if status < 0xF0:   # ignore clock, active sensing, sysex
            self._sink.put((self.name, status, data1, data2, time.perf_counter()))

    def close(self):
        if self._handle:
            _winmm.midiInStop(self._handle)
            _winmm.midiInClose(self._handle)
            self._handle = wintypes.HANDLE()
