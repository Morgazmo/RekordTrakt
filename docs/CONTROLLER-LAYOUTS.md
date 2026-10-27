# Controller layouts, MIDI evidence and community onboarding

RekordTrakt deliberately separates a controller's **physical layout** from its **MIDI contract**. A useful faceplate can be bundled from an official top-panel diagram even when nobody on the project owns that hardware. The app shows the confidence of its MIDI data instead of guessing.

## Evidence levels

| Status | Meaning |
|---|---|
| `verified` | Input messages were exercised on the intended hardware/template and have regression tests. |
| `community` | A published manual or an open-source community mapping supplies the addresses, but this RekordTrakt definition still needs a live confirmation. |
| `capture_required` | The physical layout and starter Rekordbox preset are present; hardware input addresses are deliberately blank. |
| `learned` | This PC created a private definition by operating controls in MIDI Learn. |

Current bundled layouts:

| Device | MIDI evidence | Starting point |
|---|---|---|
| Kontrol X1 MK3 | Verified on the project's hardware | Basic and Performance Mod mappings |
| Kontrol F1 | Tekken v3.4 inputs verified on both MIDI pages | Two-deck stems mapping |
| Kontrol X1 MK1 | Community: NI's published default MIDI chart, cross-checked against a community mapping | Two-deck basic mapping |
| Kontrol X1 MK2 | Capture required | Two-deck basic mapping; touch strip intentionally unassigned |
| Akai AMX | Community: an open-source community mapping | Two-channel mixer; relative gain encoders intentionally unassigned because Rekordbox trim is absolute |
| Akai AFX | Capture required | Hot cues, loop and two FX banks |

## Learn an included faceplate

1. Put the hardware in MIDI mode and add it under **Settings › MIDI devices**. Devices with an unverified contract say **layout ready**.
2. On its controller card, click **MIDI**. Click the on-screen control first, then operate that control on the hardware.
3. For an encoder, turn exactly one detent. RekordTrakt recognises the common `1/127` two's-complement and `63/65` offset formats. Buttons learn from their press rather than their release.
4. Repeat the controls marked `MIDI?`, then click **DONE**. Learned addresses take effect immediately without reopening the controller. The first one creates a user-owned clone of the bundled definition; application upgrades do not overwrite it.
5. Click **TEST** and sweep the device. Hardware actions from that controller are isolated from Rekordbox while mapped buttons and absolute values animate. Debug continues to show raw and `unrecognised` messages.

MIDI Learn currently discovers input note/CC addresses. It does not infer LED/display output, 14-bit LSB pairs, SysEx/HID protocols or a second hardware page automatically. Record those facts in a controller-capture issue. Never publish device serial numbers.

## Import a mapping instead

For a controller without a bundled layout, **Settings › MIDI devices › Import** reads a `.midi.xml` controller mapping (current and older versions of the format). It creates a generic grid, imports note/CC inputs and matching LEDs, and translates the standard actions that have a Rekordbox equivalent. The file is only read: scripts it refers to are never run.

A `.midi.xml` mapping holds MIDI addresses and actions, not where each control sits on the hardware, so an import creates its own generic controller rather than guessing how its names match a bundled faceplate.

## Contributing a device

Attach the exported trace or learned JSON, the exact model and template, and the control order to a controller-capture issue. A maintainer can promote proven addresses into the packaged JSON definition. General support still requires press/release, encoder direction, unplug/replug and representative LED tests on hardware; a faceplate alone is never described as verified support.
