"""Profiles by name. A rig device uses its "profile" entry, or the one named after its device type."""
from rekordtrakt.profiles import basic, performance_mod

PROFILES = {
    "x1mk3": basic.PROFILES["x1mk3"],
    "f1": basic.PROFILES["f1"],
    "performance_mod": performance_mod.PROFILE,  # the X1 MK3 preset a new X1 starts with
}
