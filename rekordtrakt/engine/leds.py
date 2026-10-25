"""Drives controller LEDs from Rekordbox feedback, rate-limited per device (the F1 drops bursts)."""
from collections import OrderedDict


class LedEngine:
    def __init__(self, clock):
        self.clock = clock
        self.devices = {}      # position -> (device type, output with send(), min interval)
        self.pending = {}      # position -> OrderedDict[(status, data1)] = data2   (latest value wins)
        self.last_sent = {}    # position -> time of last message
        self.current = {}      # (position, status, data1) -> data2 actually sent

    def add_device(self, position, device, out):
        self.devices[position] = (device, out, device.led_interval)
        self.pending[position] = OrderedDict()
        self.last_sent[position] = 0.0

    def set(self, position, control, value):
        device, _, _ = self.devices[position]
        msg = device.led(control, value)
        if msg is None:
            return
        status, d1, d2 = msg
        if self.current.get((position, status, d1)) == d2:
            self.pending[position].pop((status, d1), None)
            return
        self.pending[position][(status, d1)] = d2
        self.pending[position].move_to_end((status, d1))

    def all_off(self, position):
        device, _, _ = self.devices[position]
        for control in device.led_controls():
            msg = device.led(control, 0)
            if msg:
                self.pending[position][(msg[0], msg[1])] = 0
                self.current.pop((position, msg[0], msg[1]), None)

    def tick(self):
        now = self.clock()
        for position, queue in self.pending.items():
            if not queue:
                continue
            _, out, interval = self.devices[position]
            if now - self.last_sent[position] < interval:
                continue
            (status, d1), d2 = queue.popitem(last=False)
            out.send(status, d1, d2)
            self.current[(position, status, d1)] = d2
            self.last_sent[position] = now

    def flush(self):
        """Send everything now, ignoring the rate limit (shutdown)."""
        for position, queue in self.pending.items():
            _, out, _ = self.devices[position]
            while queue:
                (status, d1), d2 = queue.popitem(last=False)
                out.send(status, d1, d2)
                self.current[(position, status, d1)] = d2
