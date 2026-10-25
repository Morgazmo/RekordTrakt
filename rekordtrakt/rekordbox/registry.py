"""The action registry: every Rekordbox 6.8.7 function RekordTrakt can send, versioned.

The bridge mapping installed into Rekordbox covers this whole registry, so changing a mapping, a deck
or a controller never needs Rekordbox restarted. Only a new registry version (an app update that adds functions)
needs the bridge updated, and addresses.json keeps every existing function's address when that happens.

Each function says how Rekordbox sees it (control type, per deck or global, options), how it behaves, whether
Rekordbox reports it back, and how the editor lists it (category and label). Sources: Rekordbox's own mapping files
(scope, feedback and options per function, rekordbox/catalogues) and live tests.

Semantics:
  toggle      acts on press; release is harmless          e.g. PlayPause, Sync
  momentary   active while held; needs a release          e.g. Cue, PitchBendDown, hot cue preview
  trigger     one-shot on press                           e.g. Jump4Fwd, TapBpm
  value_held  follows the value: 7F on, 00 off             e.g. FXPartSelect*
  relative    one message per step, magnitude ignored
  absolute7 / absolute14   knob or fader value
  feedback    output only
Buttons always send a press and a release, so a wrong toggle/momentary/trigger guess only affects labels.
Releases are always sent as note-on velocity 0: Rekordbox ignores note-off.
Feedback is selective: only states a controller LED or the window can show (no level meters or beat counters).
"""
from dataclasses import dataclass

from rekordtrakt.bridge.compiler import Action

REKORDBOX = "6.8.7"
REKORDBOX_7 = "7.2.19"      # its shipped mappings were checked too: every function here exists in both unless marked 7
VERSION = 2                 # bump when functions are added; addresses.json records the version that added each one


@dataclass(frozen=True)
class Function:
    name: str               # Rekordbox function name, e.g. "PlayPause"
    rb_type: str            # Rekordbox control type: Button, Pad, Rotary, KnobSlider, KnobSliderHiRes, Indicator, ...
    scope: str              # "deck" or "global"
    semantics: str
    feedback: str = ""      # "note" / "cc" when Rekordbox reports it back
    options: str = ""       # Rekordbox's options column
    category: str = ""
    label: str = ""
    since: int = 1          # registry version that added it
    rekordbox: int = 6      # the oldest Rekordbox major version that has it


FUNCTIONS = []


_since = 1


def _f(name, rb_type, scope, semantics, feedback="", options="", category="", label="", rekordbox=6):
    FUNCTIONS.append(Function(name, rb_type, scope, semantics, feedback, options, category, label or name, _since,
                              rekordbox))


# --- deck: transport -------------------------------------------------------------------------------------------------
C = "Transport"
_f("PlayPause", "Button", "deck", "toggle", "note", "Fast;Priority=50", C, "Play/pause")
_f("Cue", "Button", "deck", "momentary", "note", "Fast;Priority=50", C, "Cue")
_f("JumpToTrackStart", "Button", "deck", "trigger", "", "Fast;Priority=50", C, "Jump to track start")
_f("Sync", "Button", "deck", "toggle", "note", "Blink=600", C, "Sync")
_f("Master", "Button", "deck", "toggle", "note", "", C, "Master deck")
_f("Slip", "Button", "deck", "toggle", "note", "", C, "Slip")
_f("Reverse", "Button", "deck", "toggle", "note", "Fast", C, "Reverse")
_f("DirectionSlipRev", "Button", "deck", "momentary", "", "", C, "Slip reverse (held)")
_f("SlipReverse", "Button", "deck", "momentary", "note", "Fast", C, "Slip reverse")
_f("Vinyl", "Button", "deck", "toggle", "note", "", C, "Vinyl mode")
_f("Quantize", "Button", "deck", "toggle", "note", "", C, "Quantize")
_f("SearchFwd", "Button", "deck", "momentary", "", "", C, "Search forward")
_f("SearchRev", "Button", "deck", "momentary", "", "", C, "Search back")
_f("TrackNext", "Button", "deck", "trigger", "", "", C, "Next track")
_f("TrackPrev", "Button", "deck", "trigger", "", "", C, "Previous track")
_f("Load", "Button", "deck", "trigger", "", "", C, "Load")
_f("ForwardAndLoad", "Button", "deck", "trigger", "", "", C, "Load (or open folder)")
_f("InstDoubles", "Button", "deck", "trigger", "", "", C, "Instant doubles")

# --- deck: tempo and key -----------------------------------------------------------------------------------------------
C = "Tempo and key"
_f("TempoSlider", "KnobSliderHiRes", "deck", "absolute14", "", "Fast", C, "Tempo")
_f("TempoReset", "Button", "deck", "trigger", "", "", C, "Tempo reset")
_f("TempoRange", "Button", "deck", "trigger", "", "", C, "Tempo range")
_f("TempoIncMedium", "Button", "deck", "trigger", "", "", C, "Tempo up")
_f("TempoDecMedium", "Button", "deck", "trigger", "", "", C, "Tempo down")
_f("PitchBendUp", "Button", "deck", "momentary", "", "", C, "Nudge faster")
_f("PitchBendDown", "Button", "deck", "momentary", "", "", C, "Nudge slower")
_f("TapBpm", "Button", "deck", "trigger", "", "", C, "Tap BPM")
_f("MasterTempo", "Button", "deck", "toggle", "note", "", C, "Master tempo (key lock)")
_f("KeySync", "Button", "deck", "toggle", "note", "", C, "Key sync")
_f("KeyReset", "Button", "deck", "trigger", "", "", C, "Key reset")
_f("SemitoneUp", "Button", "deck", "trigger", "", "", C, "Key up")
_f("SemitoneDown", "Button", "deck", "trigger", "", "", C, "Key down")
_f("VinylAdjustBrake", "KnobSlider", "deck", "absolute7", "", "", C, "Brake time")

# --- deck: loops and beat jump ---------------------------------------------------------------------------------------
C = "Loops"
_f("AutoLoop", "Button", "deck", "toggle", "", "", C, "Auto loop")
_f("ActiveLoop", "Button", "deck", "toggle", "", "", C, "Loop active")
_f("ReloopExit", "Button", "deck", "toggle", "", "Fast", C, "Reloop/exit")
_f("LoopIn", "Button", "deck", "trigger", "", "Fast", C, "Loop in")
_f("LoopOut", "Button", "deck", "trigger", "", "Fast", C, "Loop out")
_f("LoopHalf", "Button", "deck", "trigger", "", "Fast", C, "Loop ½")
_f("LoopDouble", "Button", "deck", "trigger", "", "Fast", C, "Loop ×2")
_f("LoopMoveLeft", "Button", "deck", "trigger", "", "", C, "Move loop back")
_f("LoopMoveRight", "Button", "deck", "trigger", "", "", C, "Move loop forward")
_f("LoopHalfDouble", "Rotary", "deck", "relative", "", "Fast", C, "Loop size")
_f("LoopMove", "Rotary", "deck", "relative", "", "", C, "Move loop")
for size, text in (("1_16", "1/16"), ("1_8", "1/8"), ("1_4", "1/4"), ("1_2", "1/2"), ("1", "1"), ("2", "2"), ("4", "4"),
                   ("8", "8")):
    _f(f"BeatLoop{size}", "Button", "deck", "toggle", "", "", C, f"Beat loop {text}")
_f("GetLoopActive", "Indicator", "deck", "feedback", "note", "RO;Priority=100", C, "Loop active (light)")
C = "Beat jump"
for beats in (4, 8, 16):
    _f(f"Jump{beats}Fwd", "Button", "deck", "trigger", "", "Fast", C, f"Jump {beats} beats forward")
    _f(f"Jump{beats}Prev", "Button", "deck", "trigger", "", "Fast", C, f"Jump {beats} beats back")

# --- deck: cues --------------------------------------------------------------------------------------------------------
C = "Cues"
_f("CallNext", "Button", "deck", "trigger", "", "", C, "Next memory cue")
_f("CallPrev", "Button", "deck", "trigger", "", "", C, "Previous memory cue")
_f("Memory", "Button", "deck", "trigger", "", "", C, "Set memory cue")
_f("Delete", "Button", "deck", "trigger", "", "", C, "Delete memory cue")

# --- deck: mixer and stems -------------------------------------------------------------------------------------------
C = "Mixer"
_f("EQHigh", "KnobSlider", "deck", "absolute7", "", "Fast", C, "EQ high")
_f("EQMid", "KnobSlider", "deck", "absolute7", "", "Fast", C, "EQ mid")
_f("EQLow", "KnobSlider", "deck", "absolute7", "", "Fast", C, "EQ low")
_f("Gain", "KnobSlider", "deck", "absolute7", "", "Fast", C, "Trim")
_f("ChannelFader", "KnobSlider", "deck", "absolute7", "", "", C, "Channel fader")
_f("HeadphoneCue", "Button", "deck", "toggle", "note", "", C, "Headphone cue")
_f("CrossfaderAssign.A", "Button", "deck", "trigger", "", "", C, "Crossfader: A")
_f("CrossfaderAssign.B", "Button", "deck", "trigger", "", "", C, "Crossfader: B")
_f("CrossfaderAssign.Thru", "Button", "deck", "trigger", "", "", C, "Crossfader: thru")
C = "Stems"
for part in ("Drums", "Vocal", "Inst"):
    _f(f"ActivePart{part}", "Button", "deck", "toggle", "note", "", C, f"{part} on/off")
    _f(f"PartIsolator{part}", "KnobSliderHiRes", "deck", "absolute14", "", "Fast", C, f"{part} level")
    _f(f"{part}PartInstDoubles", "Button", "deck", "trigger", "", "", C, f"{part} instant doubles")

# --- deck: pads (eight per deck in each family) ------------------------------------------------------------------------
PAD_FAMILIES = [
    # family, semantics, feedback, category, label
    ("HotCue", "momentary", "note", "Hot cues", "Hot cue {letter}"),
    ("HotCue+Shift", "trigger", "", "Hot cues", "Delete hot cue {letter}"),
    ("BeatJump", "trigger", "", "Beat jump", "Beat jump pad {n}"),
    ("Sampler", "trigger", "note", "Sampler", "Sample slot {n}"),
    ("Sampler+Shift", "trigger", "", "Sampler", "Stop sample slot {n}"),
    ("PadFx1", "momentary", "", "Pad FX", "Pad FX 1, slot {n}"),
    ("PadFx2", "momentary", "", "Pad FX", "Pad FX 2, slot {n}"),
    ("BeatLoop", "toggle", "note", "Loops", "Beat loop pad {n}"),      # first in overflow
    ("Slicer", "momentary", "note", "Slicer", "Slice {n}"),
    ("KeyShift", "trigger", "", "Tempo and key", "Key shift pad {n}"),
    ("Keyboard", "momentary", "", "Tempo and key", "Keyboard pad {n}"),
]
for family, semantics, feedback, category, label in PAD_FAMILIES:
    for n in range(1, 9):
        _f(f"PAD{n}_{family}", "Pad", "deck", semantics, feedback, "Fast", category,
           label.format(n=n, letter="ABCDEFGH"[n - 1]))

# --- deck: what Rekordbox reports back on its own ----------------------------------------------------------------------
C = "Indicators"
_f("TempoUp", "Indicator", "deck", "feedback", "note", "RO", C, "Tempo above the original (light)")
_f("TempoDown", "Indicator", "deck", "feedback", "note", "RO", C, "Tempo below the original (light)")
_f("JogPlayPauseIndicator", "JogIndicator", "deck", "feedback", "cc", "RO;Min=1;Max=72;Priority=100", C,
   "Play position (jog ring)")
_f("LoadedIndicator", "Indicator", "deck", "feedback", "note", "RO;Priority=100", C, "Track loaded (light)")
_f("EndWarningIndicator", "Indicator", "deck", "feedback", "note", "RO;Priority=100", C, "Track ending (light)")

# --- global: Beat FX ---------------------------------------------------------------------------------------------------
C = "Beat FX"
for unit in (1, 2):
    for slot in (1, 2, 3):
        _f(f"FX{unit}-{slot}", "KnobSlider", "global", "absolute7", "", "", C, f"FX{unit} slot {slot} level")
        _f(f"FX{unit}-{slot}On", "Button", "global", "toggle", "note", "", C, f"FX{unit} slot {slot} on/off")
        _f(f"FX{unit}-{slot}Select", "Button", "global", "trigger", "", "", C, f"FX{unit} slot {slot} next effect")
    _f(f"FX{unit}BeatUpDown", "KnobSlider", "global", "absolute7", "", "", C, f"FX{unit} beat (knob)")
    _f(f"FX{unit}BeatUp", "Button", "global", "trigger", "", "", C, f"FX{unit} beat up")
    _f(f"FX{unit}BeatDown", "Button", "global", "trigger", "", "", C, f"FX{unit} beat down")
    _f(f"FX{unit}TapBeat", "Button", "global", "trigger", "", "", C, f"FX{unit} tap beat")
    _f(f"FX{unit}FXMode", "Button", "global", "trigger", "", "", C, f"FX{unit} single/multi mode")
    for ch in (1, 2, 3, 4):
        _f(f"FX{unit}Assign{ch}", "Button", "global", "toggle", "note", "", C, f"FX{unit} on deck {ch}")
    _f(f"FX{unit}AssignMaster", "Button", "global", "toggle", "note", "", C, f"FX{unit} on master")

# --- global: Sound Color FX ----------------------------------------------------------------------------------------------
C = "Sound Color FX"
for n in range(1, 7):
    _f(f"CFX{n}On", "Button", "global", "toggle", "note", "Fast", C, f"Colour FX {n} on/off")
for ch in (1, 2, 3, 4):
    _f(f"CFXParameterCH{ch}", "KnobSlider", "global", "absolute7", "", "Fast", C, f"Colour FX deck {ch}")
    _f(f"CFXParameterCH{ch}Center", "Button", "global", "trigger", "", "Fast", C, f"Colour FX deck {ch} to centre")
_f("CFXSubParameter", "KnobSlider", "global", "absolute7", "", "Fast", C, "Colour FX parameter")

# --- global: SFX (Rekordbox's Smart FX section) --------------------------------------------------------------------------
C = "SFX"
for unit in (1, 2):
    for slot in (1, 2, 3):
        _f(f"SFX{unit}-{slot}On", "Button", "global", "toggle", "note", "Fast", C, f"SFX{unit} slot {slot} on/off")
        _f(f"SFX{unit}-{slot}Select", "Button", "global", "trigger", "", "Fast", C, f"SFX{unit} slot {slot} next effect")
    _f(f"SFX{unit}-Slider", "KnobSliderHiRes", "global", "absolute14", "", "Fast", C, f"SFX{unit} slider")
    _f(f"SFX{unit}-Touch", "Button", "global", "momentary", "", "Fast", C, f"SFX{unit} touch")

# --- global: stems FX, mixer, browser ------------------------------------------------------------------------------------
for part in ("Drums", "Vocal", "Inst"):
    _f(f"FXPartSelect{part}", "Button", "global", "value_held", "note", "", "Stems", f"FX on {part.lower()}")
C = "Mixer"
_f("CrossFader", "KnobSlider", "global", "absolute7", "", "Fast", C, "Crossfader")
_f("MasterCue", "Button", "global", "toggle", "note", "", C, "Master cue")
C = "Browser"
_f("Browse", "Rotary", "global", "relative", "", "", C, "Browse")
_f("BrowseUp", "Button", "global", "trigger", "", "", C, "Browse up")
_f("BrowseDown", "Button", "global", "trigger", "", "", C, "Browse down")
_f("Back", "Button", "global", "trigger", "", "", C, "Back (close folder)")
_f("Forward", "Button", "global", "trigger", "", "", C, "Forward (open folder)")
_f("AddToTagList", "Button", "global", "trigger", "", "", C, "Add to tag list")
_f("RelatedTracks", "Button", "global", "trigger", "", "", C, "Related tracks")
_f("Zoom", "Rotary", "global", "relative", "", "", C, "Waveform zoom")
del C

# ======================================================================================================================
# Version 2: the rest of what a DJ might map, so app updates rarely need the bridge updated. Appended after v1, so
# every v1 address stays where Rekordbox already has it. Functions marked Rekordbox=7 exist only in Rekordbox 7 and go
# on the bridge only when Rekordbox 7 is the target.
# ======================================================================================================================
_since = 2

C = "Transport"
_f("ReTrigger", "Button", "deck", "trigger", "note", "Fast", C, "Re-trigger")
_f("TempoCenter", "Button", "deck", "trigger", "", "", "Tempo and key", "Tempo to centre")
C = "Loops"
_f("4BeatLoop", "Button", "deck", "toggle", "", "Fast", C, "4-beat loop")
C = "Beat grid"
_f("GridAdjust", "Button", "deck", "toggle", "note", "", C, "Grid adjust mode")
_f("GridSlide", "Button", "deck", "toggle", "note", "", C, "Grid slide mode")
_f("GridAdjustDouble", "Button", "deck", "trigger", "", "", C, "Grid ×2")
_f("GridAdjustHalf", "Button", "deck", "trigger", "", "", C, "Grid ½")
C = "Mix point link"
_f("MixPointLink", "Button", "deck", "toggle", "note", "", C, "Mix point link")
_f("MixPointLinkDeck", "Button", "deck", "trigger", "", "", C, "Mix point link: deck")
_f("MixPointLinkExit", "Button", "deck", "trigger", "", "", C, "Mix point link: exit")
_f("MixPointLinkSilent", "Button", "deck", "toggle", "note", "", C, "Mix point link: silent")
_f("MixPointSelectNext", "Button", "deck", "trigger", "", "", C, "Next mix point")
_f("MixPointSelectPrev", "Button", "deck", "trigger", "", "", C, "Previous mix point")
C = "Stems"
_f("Stems", "Button", "deck", "toggle", "note", "Fast", C, "Stems on/off")
_f("PartIsolator", "Button", "deck", "toggle", "note", "", C, "Part isolator on/off")
_f("Mute", "Button", "deck", "toggle", "note", "", "Mixer", "Mute")
C = "Sequencer"
_f("SequencerRec", "Button", "deck", "toggle", "note", "Blink=500", C, "Record sequence")
_f("SequencerStart", "Button", "deck", "toggle", "note", "", C, "Play sequence")
_f("SaveSequence", "Button", "deck", "trigger", "", "", C, "Save sequence")
_f("SequenceLoad", "Button", "deck", "trigger", "", "", C, "Load sequence")
_f("SelectSlot", "Button", "deck", "trigger", "", "", C, "Select sequence slot")
_f("SlicerCapture", "Button", "deck", "trigger", "", "", "Slicer", "Slicer capture")
# Pad-mode parameters (the arrows beside the pads on Pioneer controllers)
for mode, category, down, up in (("BeatJump", "Beat jump", "Beat jump pads: smaller jumps", "Beat jump pads: bigger jumps"),
                                 ("PadFx1", "Pad FX", "Pad FX 1: beat down", "Pad FX 1: beat up"),
                                 ("PadFx2", "Pad FX", "Pad FX 2: beat down", "Pad FX 2: beat up"),
                                 ("Sampler", "Sampler", "Sampler: previous bank", "Sampler: next bank"),
                                 ("Slicer", "Slicer", "Slicer: roll down", "Slicer: roll up"),
                                 ("SlicerLoop", "Slicer", "Slicer loop: roll down", "Slicer loop: roll up")):
    _f(f"Parameter1Left_{mode}", "Button", "deck", "trigger", "", "", category, down)
    _f(f"Parameter1Right_{mode}", "Button", "deck", "trigger", "", "", category, up)

PAD_FAMILIES_V2 = [
    ("BeatJump+Shift", "trigger", "", "Beat jump", "Beat jump pad {n} (Shift)"),
    ("BeatLoop+Shift", "toggle", "", "Loops", "Beat loop pad {n} (Shift)"),
    ("PadFx1+Shift", "toggle", "", "Pad FX", "Pad FX 1, slot {n} (latch)"),
    ("PadFx2+Shift", "toggle", "", "Pad FX", "Pad FX 2, slot {n} (latch)"),
    ("SlicerLoop", "momentary", "note", "Slicer", "Slicer loop {n}"),
    ("SampleScratch", "trigger", "", "Sampler", "Scratch sample {n}"),
    ("VelocitySampler", "trigger", "note", "Sampler", "Velocity sample {n}"),
    ("VelocitySampler+Shift", "trigger", "", "Sampler", "Stop velocity sample {n}"),
    ("Keyboard+Shift", "momentary", "", "Tempo and key", "Keyboard pad {n} (Shift)"),
    ("SequenceCall", "trigger", "note", "Sequencer", "Sequence {n}"),
    ("SequenceCall+Shift", "trigger", "", "Sequencer", "Stop sequence {n}"),
]
for family, semantics, feedback, category, label in PAD_FAMILIES_V2:
    for n in range(1, 9):
        _f(f"PAD{n}_{family}", "Pad", "deck", semantics, feedback, "Fast", category, label.format(n=n))

C = "Beat FX"
for effect, name in (("DELAY", "Delay"), ("ECHO", "Echo"), ("ENIGMAJET", "Enigma jet"), ("FILTER", "Filter"),
                     ("FLANGER", "Flanger"), ("HELIX", "Helix"), ("LOWCUTECHO", "Low cut echo"), ("MOBIUSSAW", "Mobius saw"),
                     ("MOBIUSTRI", "Mobius triangle"), ("MTDELAY", "MT delay"), ("PHASER", "Phaser"), ("PINGPONG", "Ping pong"),
                     ("PITCH", "Pitch"), ("REVERB", "Reverb"), ("ROLL", "Roll"), ("SLIPROLL", "Slip roll"), ("SPIRAL", "Spiral"),
                     ("STRETCH", "Stretch"), ("TRANS", "Trans"), ("VINYLBRAKE", "Vinyl brake")):
    _f(f"FX1-1Select.{effect}", "Button", "global", "trigger", "", "", "Beat FX effects", f"FX1 slot 1: {name}")
for unit in (1, 2):
    _f(f"FX{unit}AutoBeat", "Button", "global", "toggle", "", "", C, f"FX{unit} auto beat")
    _f(f"FX{unit}ReleaseFXOn", "Button", "global", "trigger", "", "Fast", C, f"FX{unit} release FX")
    _f(f"FX{unit}AssignSampler", "Button", "global", "toggle", "note", "", C, f"FX{unit} on sampler")
    for slot in (1, 2, 3):
        _f(f"FX{unit}-{slot}OnMomentary", "Button", "global", "momentary", "", "", C, f"FX{unit} slot {slot} on while held")
for bank in "ABCD":
    _f(f"FxBank{bank}Load", "Button", "global", "trigger", "", "", C, f"Load FX bank {bank}")
C = "Panels"
_f("FxPanel", "Button", "global", "trigger", "", "", C, "Show FX panel")
_f("SamplerPanel", "Button", "global", "trigger", "", "", C, "Show sampler panel")
_f("PanelForward", "Button", "global", "trigger", "", "", C, "Next panel")
_f("PanelBack", "Button", "global", "trigger", "", "", C, "Previous panel")
C = "Mixer"
for curve, name in (("MID", "medium"), ("SHARP", "sharp"), ("STRAIGHT", "straight")):
    _f(f"ChFaderCurve.{curve}", "Button", "global", "trigger", "", "", C, f"Channel fader curve: {name}")
for curve, name in (("MID", "medium"), ("SHARP", "sharp"), ("STRAIGHT", "straight"), ("THRU", "thru")):
    _f(f"CrossFaderCurve.{curve}", "Button", "global", "trigger", "", "", C, f"Crossfader curve: {name}")
_f("EqCurve", "Button", "global", "trigger", "", "", C, "EQ / isolator")
C = "Sound Color FX"
_f("CFXParameterMaster", "KnobSliderHiRes", "global", "absolute14", "", "Fast", C, "Colour FX master")
_f("CFXParameterSampler", "KnobSliderHiRes", "global", "absolute14", "", "Fast", C, "Colour FX sampler")
C = "Smart features"
_f("SmartCFX", "Button", "global", "toggle", "note", "", C, "Smart CFX on/off")
_f("SmartCFXSelect", "Button", "global", "trigger", "", "", C, "Smart CFX next")
_f("SmartFader", "Button", "global", "toggle", "note", "", C, "Smart fader on/off")
_f("TransitionFX", "Button", "global", "trigger", "", "", C, "Transition FX")
_f("PhraseSync", "Button", "global", "toggle", "", "", C, "Phrase sync")
C = "Sampler"
_f("SamplerVolume", "KnobSlider", "global", "absolute7", "", "", C, "Sampler volume")
_f("SamplerCue", "Button", "global", "toggle", "note", "", C, "Sampler headphone cue")
_f("SamplerMaster", "Button", "global", "toggle", "note", "", C, "Sampler to master")
_f("SamplerSync", "Button", "global", "toggle", "note", "", C, "Sampler sync")
_f("SamplerQuantize", "Button", "global", "toggle", "note", "", C, "Sampler quantize")
_f("SamplerTapBpm", "Button", "global", "trigger", "", "", C, "Sampler tap BPM")
_f("SamplerBpmUp", "Button", "global", "trigger", "", "", C, "Sampler BPM up")
_f("SamplerBpmDown", "Button", "global", "trigger", "", "", C, "Sampler BPM down")
_f("Rec", "Button", "global", "toggle", "note", "", "Recording", "Record the mix")
C = "Browser"
for key, name in (("TRACK", "track number"), ("SONG", "title"), ("ARTIST", "artist"), ("BPM", "BPM"), ("KEY", "key")):
    _f(f"Sort{key}", "Button", "global", "trigger", "", "", C, f"Sort by {name}")
_f("SwitchActiveWindow", "Button", "global", "trigger", "", "", C, "Switch browser pane")
_f("TrackFilter", "Button", "global", "trigger", "", "", C, "Track filter")

# --- Rekordbox 7 only ------------------------------------------------------------------------------------------------
C = "Stems"
_f("ActivePartBass", "Button", "deck", "toggle", "note", "", C, "Bass on/off", rekordbox=7)
_f("BassPartInstDoubles", "Button", "deck", "trigger", "", "", C, "Bass instant doubles", rekordbox=7)
for part in ("Drums", "Vocal", "Inst", "Bass"):
    _f(f"FXPartSelect{part}On", "Button", "global", "toggle", "note", "", C, f"FX on {part.lower()} (Rekordbox 7)", rekordbox=7)
C = "Drum tools"
_f("DrumReleaseFx", "Button", "deck", "toggle", "", "Fast", C, "Drum release FX", rekordbox=7)
_f("DrumReleaseFxSelect", "Button", "deck", "trigger", "", "", C, "Drum release FX type", rekordbox=7)
for size, name in (("1_8", "1/8"), ("1_4", "1/4"), ("1_2", "1/2"), ("1", "1")):
    _f(f"DrumRoll{size}", "Button", "deck", "momentary", "note", "Fast", C, f"Drum roll {name}", rekordbox=7)
    _f(f"DrumTrans{size}", "Button", "deck", "momentary", "note", "Fast", C, f"Drum trans {name}", rekordbox=7)
for n in range(1, 5):
    _f(f"DrumSwap{n}", "Button", "deck", "toggle", "note", "Fast", C, f"Drum swap {n}", rekordbox=7)
for bank in "AB":
    _f(f"DrumSwapBank{bank}", "Button", "deck", "trigger", "note", "", C, f"Drum swap bank {bank}", rekordbox=7)
_f("DrumSwapCapture", "Button", "deck", "trigger", "note", "", C, "Drum swap capture", rekordbox=7)
_f("DrumSwapCaptureLength", "Button", "deck", "trigger", "note", "", C, "Drum swap capture length", rekordbox=7)
_f("DrumSwapMulti", "Button", "deck", "toggle", "note", "", C, "Drum swap multi", rekordbox=7)
_f("DrumSwapSingle", "Button", "deck", "toggle", "note", "", C, "Drum swap single", rekordbox=7)
_f("DrumSwapGain", "KnobSliderHiRes", "deck", "absolute14", "", "", C, "Drum swap gain", rekordbox=7)
C = "Browser"
_f("BrowseJumpTop", "Button", "global", "trigger", "", "", C, "Jump to the top", rekordbox=7)
_f("BrowseJumpBottom", "Button", "global", "trigger", "", "", C, "Jump to the bottom", rekordbox=7)
_f("BrowseJumpUp", "Button", "global", "trigger", "", "", C, "Page up", rekordbox=7)
_f("BrowseJumpDown", "Button", "global", "trigger", "", "", C, "Page down", rekordbox=7)
_f("PlayPausePreview", "Button", "global", "toggle", "", "", C, "Preview play/pause", rekordbox=7)
_f("SkipPreview", "Button", "global", "trigger", "", "", C, "Preview skip", rekordbox=7)
_f("Discover", "Button", "global", "trigger", "", "", C, "Discover", rekordbox=7)
C = "Sound Color FX"
_f("CFXOn", "Button", "global", "toggle", "note", "Fast", C, "Colour FX on/off (rekordbox 7)", rekordbox=7)
_f("CFXSelect", "Button", "global", "trigger", "", "", C, "Colour FX next type (Rekordbox 7)", rekordbox=7)
_f("SmartCFXSelectBack", "Button", "global", "trigger", "", "", "Smart features", "Smart CFX previous", rekordbox=7)
del C

BY_NAME = {f.name: f for f in FUNCTIONS}
assert len(BY_NAME) == len(FUNCTIONS), "duplicate function in the registry"


def spec(function):
    try:
        return BY_NAME[function]
    except KeyError:
        raise KeyError(f"'{function}' is not in the action registry (rekordtrakt/rekordbox/registry.py)") from None


def action(f):
    """The compiler's view of a registry function: every deck for per-deck functions."""
    return Action(f.name, f.rb_type, f.semantics, decks=(1, 2, 3, 4) if f.scope == "deck" else (),
                  feedback=f.feedback, options=f.options)


def for_target(rekordbox=6):
    """The functions on the bridge for a Rekordbox major version (6 or 7)."""
    return [f for f in FUNCTIONS if f.rekordbox <= int(rekordbox)]


def full_actions(rekordbox=6):
    return [action(f) for f in for_target(rekordbox)]


def bridge_actions(uses):
    """`uses` is an iterable of (function, deck-or-None). Returns compiler Actions for just those, one per function
    (for tests; the installed bridge always covers the whole registry)."""
    decks_by_function = {}
    for function, deck in uses:
        s = spec(function)
        if s.scope == "deck" and deck is None:
            raise ValueError(f"{function} needs a deck")
        decks = decks_by_function.setdefault(function, set())
        if s.scope == "deck":
            decks.add(deck)
    actions = []
    for function in sorted(decks_by_function):
        s = spec(function)
        decks = tuple(sorted(decks_by_function[function])) if s.scope == "deck" else ()
        actions.append(Action(function, s.rb_type, s.semantics, decks=decks, feedback=s.feedback, options=s.options))
    return actions
