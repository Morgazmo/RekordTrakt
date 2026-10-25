"""Fans trace events out to the debug window(s) and the log file without ever blocking the translator.

publish() is called on the translator thread: it numbers the event, keeps it in a short history (so a window opened
later still sees the last few seconds) and drops it for any listener that has fallen behind, counting the drops.
set_state() is for snapshots (the main window's view): only the latest is kept, and new listeners get it.
"""
import json
import os
import queue
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from rekordtrakt import paths

APP_DIR = paths.DATA_DIR
LOGGED_KINDS = {"notice", "error", "bridge", "supervisor"}


class EventHub:
    def __init__(self, history=3000, clock=time.time):
        self.clock = clock
        self.history = deque(maxlen=history)
        self.dropped = 0
        self._seq = 0
        self.states = {}                    # kind -> latest event
        self._subs = set()
        self._lock = threading.Lock()

    def publish(self, event):
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "t": self.clock(), **event}
            self.history.append(event)
            for q in self._subs:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    self.dropped += 1
        return event

    def set_state(self, kind, data):
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "t": self.clock(), "kind": kind, "data": data}
            self.states[kind] = event
            for q in self._subs:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    self.dropped += 1
        return event

    def subscribe(self, maxsize=10000):
        """Returns (queue, backlog): the history and latest states up to the moment of subscribing."""
        q = queue.Queue(maxsize)
        with self._lock:
            self._subs.add(q)
            return q, sorted([*self.history, *self.states.values()], key=lambda e: e["seq"])

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)


class FileLog:
    """Writes notices, errors and bridge/supervisor events to a daily log file, on its own thread."""

    def __init__(self, hub, folder=APP_DIR / "logs", keep_days=14):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._queue, _ = hub.subscribe()
        self._hub = hub
        self._prune(keep_days)
        self._thread = threading.Thread(target=self._run, name="file-log", daemon=True)
        self._thread.start()

    @property
    def path(self):
        return self.folder / f"rekordtrakt-{datetime.now():%Y%m%d}.log"

    def _prune(self, keep_days):
        cutoff = time.time() - keep_days * 86400
        for f in self.folder.glob("rekordtrakt-*.log"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)

    def _run(self):
        while True:
            event = self._queue.get()
            if event is None:
                return
            if event["kind"] not in LOGGED_KINDS:
                continue
            line = f"{datetime.fromtimestamp(event['t']):%H:%M:%S.%f}"[:-3] + f" {event['kind']:10s} {event['text']}"
            if event.get("detail"):
                line += "\n" + event["detail"].rstrip()
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def close(self):
        self._hub.unsubscribe(self._queue)
        self._queue.put(None)
        self._thread.join(2)


def to_json(event):
    return json.dumps(event, default=str, separators=(",", ":"))
