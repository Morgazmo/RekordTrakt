# Changelog

## 1.1.0

A test release: it adds the Kontrol X1 MK1 and MK2 and the Akai AMX and AFX for community testing.

- The Kontrol X1 MK1 and MK2 and the Akai AMX and AFX, each with its faceplate and a starter mapping. The MK1 and AMX come with a MIDI map from published sources that still needs confirming on hardware; the MK2 and AFX are learned on the hardware.
- MIDI Learn: click **MIDI** on a controller's card, click a control, then use it on the hardware. What you learn is saved as your own copy of the controller and works straight away. Controls still to learn show `MIDI?`.
- MIDI Test: **TEST** shows what a controller sends on its card without sending anything to Rekordbox.
- A new controller's on-screen controls start locked; one you'd unlocked stays unlocked.
- The F1's second Controller Editor page (Shift, in the Tekken v3.4 template): its pads, Sync and encoder can have their own mappings. The mapping editor offers that page only on the controls that change on it.
- The mapping editor keeps unsaved changes while you move between layers and controls, and asks before discarding them.
- A sequence step that would release a control that's being held is skipped, and the window says so.
- Import also reads older `.midi.xml` files.
- Debug's export keeps every input message, even with the Input filter off.
- MIDI devices tells an X1 MK1, MK2 and MK3 apart.
- The README says which Rekordbox versions have been tested live.

## 1.0.1

- Every controller's decks and FX units can be changed, in Settings and on its card: an X1's halves as before, an F1's first deck, second deck and FX unit, and the decks an imported controller drives. Its stems, mutes, Colour FX and LEDs follow.
- A controller definition can say which decks and FX units the controller drives (`deck_slots`, `fx_slots`), so a new controller gets the same choices without code.

## 1.0.0

The first release.

- Traktor Kontrol X1 MK3 and F1 controllers for Rekordbox 6 and 7, in MIDI mode, through RekordTrakt's MIDI bridge (tested with Rekordbox 6.8.7).
- The X1 MK3 preset re-creates the X1MK3 Community Performance Mod: Sync tap/hold with a tempo layer, eight hot cues, memory cues, vinyl brake, Browser Mode, the mod's two encoder styles and FX-section pages. The F1 preset is a stem controller for two decks.
- The RekordTrakt window: each controller drawn as it looks, with what every control does now, its LEDs and the held layer; on-screen controls; a live Debug view.
- The mapping editor: one function, several at once, timed sequences or a value on any control, per layer and page; your own FX-section pages; export and import.
- Controllers are added in the window, and imported from `.midi.xml` mappings for ones RekordTrakt doesn't know yet. Identical controllers keep their places by serial number.
- The MIDI mapping is installed into Rekordbox from the window, with backups, built for the Rekordbox version you run. Uninstalling puts Rekordbox's mapping files back.
- A per-user installer, with Start with Windows from Settings.
