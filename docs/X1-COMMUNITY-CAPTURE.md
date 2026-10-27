# Community capture: Traktor Kontrol X1 MK2 and MK1

RekordTrakt includes both older X1 faceplates. The MK1 includes the default CC map published in its manual, cross-checked against a community mapping, at the **community** evidence level. The MK2 is **capture required**: its physical layout and starter preset exist, but its MIDI addresses are blank until learned. A contributor can complete either device without editing code. Use the [controller capture issue template](../.github/ISSUE_TEMPLATE/controller-capture.md) to report results, and keep MK1 and MK2 traces separate.

## Before recording

- Record the exact model/revision, Windows version, driver/firmware and Controller Editor versions, MIDI port names, and template name. Do not post a serial number publicly.
- Confirm that the controller appears as a MIDI input and that button presses produce messages. This is the first gate for **MK1 on Windows 11**: NI does not list it among its officially compatible Windows 11 controllers. NI does list MK2. See [NI's compatibility list](https://support.native-instruments.com/support/solutions/articles/69000879301-compatibility-of-native-instruments-products-on-windows).
- Enter MIDI mode using the model's own gesture: **MK1: Shift + Hotcue; MK2: Shift + both Load buttons**, per [NI's MIDI-mode instructions](https://support.native-instruments.com/support/solutions/articles/69000880031-native-instruments-switching-your-controller-to-midi-mode). Note any difference with your firmware/template.

## Input sweep

With other DJ software closed, add the controller and first use the card's **MIDI** button to learn its controls. Then enable **TEST**, open **Debug**, enable **Raw MIDI**, click **Clear**, and operate one control at a time. Test mode keeps that controller from operating Rekordbox. Press and release every button on hardware page 1 and hardware page 2 (selected with Shift). Turn every encoder both ways, at slow and fast speeds; move every knob to minimum, midpoint and maximum. On MK2, move the touch strip across its range and try its tap/hold gestures separately. Export the trace before the Debug window's 20,000-event history fills. Include a note of the exact control order and which actions produced no message.

The present decoder may label unfamiliar messages `unrecognised`; the exported event's `raw` bytes still let us define them. Check the `.jsonl` file for those bytes before uploading. Remove usernames, paths and unrelated session activity.

## After input capture

An output probe will test LEDs and, for MK2, the seven-segment display after the input definition is reviewed. A successful input sweep alone earns a **capture available** label, not device support. A beta preset additionally needs live press/release, LED and unplug/replug testing; general support needs independent confirmation on a second system.
