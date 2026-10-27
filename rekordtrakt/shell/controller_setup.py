"""Adding and removing controllers from the window (Settings > This PC > MIDI devices), including one brought in from
a .midi.xml mapping file. Each change is saved to the rig file and the translator restarts to pick it up.
"""
import copy
import hashlib
import threading

from rekordtrakt import rig as rig_mod
from rekordtrakt.devices import mapping_file, reload_device_types
from rekordtrakt.devices.defined import USER_DEFINITIONS_DIR, DefinedDevice, save_user_definition, update_user_definition


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
        return {"device-add": self.add, "device-remove": self.remove, "device-import": self.import_file,
                "device-learn": self.learn}

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

    def learn(self, body):
        """Give one control in a packaged physical layout the raw MIDI message the user just operated.

        Built-in files are immutable. On the first learned control we clone the whole layout into the user's
        device folder and switch only this rig entry to it; later learns atomically update that clone.
        """
        rig = self.load_rig()
        position = str(body.get("position", ""))
        if position not in rig.get("devices", {}):
            raise ValueError(f"no controller '{position}'")
        entry = rig["devices"][position]
        current_type = entry["type"]
        try:
            definition = copy.deepcopy(rig_mod.DEVICE_TYPES[current_type]().definition)
        except KeyError:
            raise ValueError(f"no controller type '{current_type}'") from None
        control_id = str(body.get("control", ""))
        control = next((c for c in definition["controls"] if c.get("id") == control_id), None)
        if control is None:
            raise ValueError(f"{definition['name']} has no control '{control_id}'")

        try:
            status, number, value = (int(body[k]) for k in ("status", "data1", "data2"))
        except (KeyError, TypeError, ValueError):
            raise ValueError("the learned MIDI message is incomplete") from None
        family, channel = status & 0xF0, (status & 0x0F) + 1
        if family in (0x80, 0x90):
            msg = "note"
        elif family == 0xB0:
            msg = "cc"
        else:
            raise ValueError(f"MIDI {status:02X} is not a note or control-change message")
        if control["kind"] in ("knob", "fader", "encoder") and msg != "cc":
            raise ValueError(f"{control['name']} needs a control-change message")
        spec = {"msg": msg, "ch": channel, "num": number}
        if control["kind"] == "encoder":
            relative = body.get("relative")
            if relative not in ("twos_complement", "offset64"):
                relative = "twos_complement" if value in (1, 127) else "offset64" if value in (63, 65) else None
            if relative is None:
                raise ValueError("turn the encoder by one click left or right so its relative format can be detected")
            spec["relative"] = relative
        # A community map can give this message to the wrong control: learning moves it here, and the control
        # that had it needs learning again (MIDI?), so a wrong address never blocks the right one.
        same = lambda s: (s.get("msg"), s.get("ch"), s.get("num")) == (msg, channel, number)  # noqa: E731
        moved = []
        for other in definition["controls"]:
            if other is not control and other.get("in") and same(other["in"]):
                for key in ("in", "alternates", "led"):
                    other.pop(key, None)
                moved.append(other.get("name", other["id"]))
            elif other.get("alternates"):
                other["alternates"] = [a for a in other["alternates"] if not same(a)]
        control["in"] = spec

        template = definition.get("template") or current_type
        if (definition.get("midi") or {}).get("status") != "learned":
            suffix = hashlib.sha1(f"{template}\0{entry['port']}".encode("utf-8")).hexdigest()[:8]
            definition["type"] = f"learned_{template}_{suffix}"
            definition["template"] = template
        definition["port_hints"] = [entry["port"]]
        mapped = sum(bool(c.get("in")) for c in definition["controls"])
        definition["midi"] = {"status": "learned", "note": f"{mapped}/{len(definition['controls'])} inputs learned on this device",
                              "source": "hardware learn"}
        # Check for an address already owned by another control before changing either saved file.
        DefinedDevice(definition)
        update_user_definition(definition, self.definitions)
        reload_device_types(user_folder=self.definitions)
        entry["type"] = definition["type"]
        if not entry.get("profile"):
            entry["profile"] = template
        self.save_rig(rig)
        # The controls and slots are unchanged, so the running translator can adopt the new decoder in place. This
        # keeps MIDI Learn and Device Test active across a whole capture. Older/fake supervisors fall back to the
        # restart path used by controller import.
        def apply_definition():
            translator = getattr(self.supervisor, "translator", None)
            if translator and hasattr(translator, "replace_device_definition"):
                try:
                    translator.replace_device_definition(position, definition)
                    return
                except (RuntimeError, TimeoutError):
                    pass
            self.supervisor.restart(f"{definition['name']}: learned {control['name']}")
        self.later(apply_definition)
        return {"position": position, "type": definition["type"], "control": control_id,
                "mapped": mapped, "controls": len(definition["controls"]), "message": spec, "moved": moved}
