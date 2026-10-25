"""Controller types, each defined by a data file in definitions/ or your own devices folder (see defined.py)."""
from rekordtrakt.devices.defined import device_types

DEVICE_TYPES = device_types()


def reload_device_types(**kwargs):
    """After a controller is imported: the same dict, refreshed, so everything holding it sees the new type."""
    fresh = device_types(**kwargs)
    DEVICE_TYPES.clear()
    DEVICE_TYPES.update(fresh)
    return DEVICE_TYPES
