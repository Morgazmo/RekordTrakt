"""Profiles by name. A rig device uses its "profile" entry, or the one named after its device type."""
from rekordtrakt.profiles import basic, performance_mod

PROFILES = {
    "x1mk3": basic.PROFILES["x1mk3"],
    "f1": basic.PROFILES["f1"],
    "x1mk1": basic.PROFILES["x1mk1"],
    "x1mk2": basic.PROFILES["x1mk2"],
    "akai_amx": basic.PROFILES["akai_amx"],
    "akai_afx": basic.PROFILES["akai_afx"],
    "performance_mod": performance_mod.PROFILE,  # the X1 MK3 preset a new X1 starts with
}
