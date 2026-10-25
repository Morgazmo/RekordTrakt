"""Adding and removing controllers from the window (Settings > This PC > MIDI devices), including one brought in from
a .midi.xml mapping file. Each change is saved to the rig file and the translator restarts to pick it up.
"""
import threading

from rekordtrakt import rig as rig_mod
from rekordtrakt.devices import mapping_file, reload_device_types
from rekordtrakt.devices.defined import USER_DEFINITIONS_DIR, save_user_definition


class ControllerSetup:
    def __init__(self, supervisor, load_rig=rig_mod.load, save_rig=rig_mod.save, definitions=USER_DEFINITIONS_DIR,
                 later=lambda fn, *args: threading.Thread(target=fn, args=args, daemon=True).start(),
                 port_units=lambda: {}):
        self.supervisor = supervisor
        self.load_rig, self.save_rig = load_rig, save_rig
        self.definitions = definitions
        self.later = later                    # restarting waits for the translator: not on the request
        self.port_units = port_units          # so a controller is known by its unit, not only its port's name

    def actions(self):
        return {"device-add": self.add, "device-remove": self.remove, "device-import": self.import_file}

    def add(self, body):
        rig = self.load_rig()
        port = str(body.get("port", ""))
        position = rig_mod.with_device(rig, port, str(body.get("type", "")), unit=self.port_units().get(port))
        self.save_rig(rig)
        self.later(self.supervisor.restart, f"{position} added")
        return {"position": position}

    def remove(self, body):
        rig = self.load_rig()
        rig_mod.without_device(rig, str(body.get("position", "")))
        self.save_rig(rig)
        self.later(self.supervisor.restart, f"{body.get('position')} removed")
        return {"removed": body.get("position")}

    def import_file(self, body):
        """A .midi.xml mapping (its text) -> your own controller type, added on `port` with its starting mapping."""
        definition, mapping, report = mapping_file.to_rekordtrakt(str(body.get("xml", "")), str(body.get("port", "")))
        save_user_definition(definition, self.definitions)
        reload_device_types(user_folder=self.definitions)
        position = None
        if body.get("port"):
            rig = self.load_rig()
            position = rig_mod.with_device(rig, body["port"], definition["type"], mapping,
                                           unit=self.port_units().get(body["port"]))
            self.save_rig(rig)
            self.later(self.supervisor.restart, f"{definition['name']} added from a mapping file")
        return {**report, "type": definition["type"], "name": definition["name"], "position": position}
