"""A stand-in for rekordtrakt.midi.winmm with no Windows ports, for tests.

Port names are a plain list; outputs record what was sent; inject() feeds an input as if a message arrived.
`links` makes loopback pairs: a message sent to output A arrives on input B ({A: B, B: A} for a bridge pair).
"""
import time


class FakeMidi:
    def __init__(self, names, links=None):
        self.names = list(names)
        self.links = dict(links or {})
        self.sent = {}          # port name -> [(status, data1, data2)]
        self.queues = {}        # input port name -> the queue it was opened with

    def input_names(self):
        return list(self.names)

    def output_names(self):
        return list(self.names)

    def MidiOut(self, name):
        if name not in self.names:
            raise LookupError(f"MIDI output '{name}' not found")
        midi = self

        class Out:
            def send(self, status, data1, data2=0):
                midi.sent.setdefault(name, []).append((status, data1, data2))
                target = midi.links.get(name)
                if target in midi.queues:
                    midi.inject(target, status, data1, data2)

            def close(self):
                pass
        return Out()

    def MidiIn(self, name, sink):
        if name not in self.names:
            raise LookupError(f"MIDI input '{name}' not found")
        self.queues[name] = sink
        midi = self

        class In:
            def close(self):
                if midi.queues.get(name) is sink:
                    del midi.queues[name]
        return In()

    def inject(self, name, status, data1, data2):
        self.queues[name].put((name, status, data1, data2, time.perf_counter()))
