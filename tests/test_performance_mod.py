"""X1 MK3 Performance Mod profile, with simulated X1 input. Run: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_engine import Rig   # noqa: E402

L = 0x90      # left half note-on
R = 0x91      # right half
SL = 0x92     # left half with Shift
OFF = 0x80


class ModTests(unittest.TestCase):
    def setUp(self):
        self.r = Rig("performance_mod")

    def press(self, status, note, pos="x1_left"):
        self.r.msg(pos, status, note, 0x7F)

    def release(self, status, note, pos="x1_left"):
        self.r.msg(pos, OFF | (status & 0x0F), note, 0)

    def tap(self, status, note, pos="x1_left"):
        self.press(status, note, pos)
        self.release(status, note, pos)

    def turn(self, ch, cc, value, pos="x1_left"):
        self.r.msg(pos, 0xB0 | ch, cc, value)

    def option(self, key, value, pos="x1_left"):
        self.r.engine.set_option(pos, key, value)

    def page(self, step):
        self.tap(SL, 0x01 if step > 0 else 0x00)     # Shift + FX Assign 2 / 1 = next / previous page

    # --- transport ---------------------------------------------------------------------------------------
    def test_rev_is_slip_reverse_and_shift_rev_is_flux(self):
        self.tap(L, 0x09)
        self.tap(SL, 0x09)
        self.assertEqual(self.r.sent(), [("DirectionSlipRev", 1, 127), ("DirectionSlipRev", 1, 0),
                                         ("Slip", 1, 127), ("Slip", 1, 0)])

    def test_shift_sync_is_master_tempo(self):
        self.tap(SL, 0x0B)
        self.assertEqual(self.r.sent(), [("MasterTempo", 1, 127), ("MasterTempo", 1, 0)])


    # --- tempo ---------------------------------------------------------------------------------------------

    def test_sync_hold_loop_tap_resets_tempo(self):
        self.press(L, 0x0B)
        self.tap(L, 0x15)
        self.release(L, 0x0B)
        self.assertEqual(self.r.sent(), [("TempoReset", 1, 127), ("TempoReset", 1, 0)])


    def test_sync_cue_and_rev_set_and_delete_a_memory_cue(self):
        self.press(L, 0x0B)
        self.tap(L, 0x08)                            # CUE
        self.tap(L, 0x09)                            # REV
        self.assertEqual(self.r.sent(), [("Memory", 1, 127), ("Memory", 1, 0), ("Delete", 1, 127), ("Delete", 1, 0)])

    # --- setup mode ----------------------------------------------------------------------------------------
    def test_setup_assigns_deck_and_persists(self):
        self.press(L, 0x00)                          # hold FX assign 1
        self.press(L, 0x01)                          # and FX assign 2: setup
        self.tap(L, 0x04)                            # hotcue 3 -> this half = deck 3
        self.release(L, 0x01)
        self.release(L, 0x00)
        self.assertEqual(self.r.sent(), [])          # no FX assign toggled: both were used as a combo
        self.assertEqual(self.r.saved[-1].decks, [3, 3])
        self.tap(L, 0x0A)                            # PLAY now goes to deck 3
        self.assertEqual(self.r.sent(), [("PlayPause", 3, 127), ("PlayPause", 3, 0)])

    def test_setup_leds_show_current_deck(self):
        self.press(L, 0x00)
        self.press(L, 0x01)
        self.r.leds.flush()
        self.assertIn((0x90, 0x02, 127), self.r.led_out["x1_left"].sent)   # hotcue 1 lit: left half is deck 1

    def test_fx_assign_tap_still_assigns(self):
        self.tap(R, 0x00, "x1_right")                # right X1, right half (deck 4): FX1 on CH4
        self.assertEqual(self.r.sent(), [("FX1Assign4", None, 127), ("FX1Assign4", None, 0)])

    # --- Browser Mode --------------------------------------------------------------------------------------
    def test_browser_mode(self):
        self.tap(SL, 0x13)                           # Shift + FX button 4
        self.turn(0, 0x15, 0x41)                     # left Loop: tree (Back first)
        self.turn(0, 0x14, 0x41)                     # Browse: list (Forward first)
        self.tap(L, 0x03)                            # hotcue 2: load to deck 2
        self.assertEqual(self.r.sent(), [("Back", None, 127), ("Back", None, 0), ("Browse", None, 0x41),
                                         ("Forward", None, 127), ("Forward", None, 0), ("Browse", None, 0x41),
                                         ("ForwardAndLoad", 2, 127), ("ForwardAndLoad", 2, 0)])
        self.r.leds.flush()
        self.assertIn((0x90, 0x15, 127), self.r.led_out["x1_left"].sent)   # loop push LED = Browser Mode

    def test_browse_push_hold_is_instant_double(self):
        self.press(L, 0x14)
        self.r.clock.t += 1.2
        self.release(L, 0x14)
        self.tap(L, 0x14)
        self.assertEqual(self.r.sent(), [("InstDoubles", 1, 127), ("InstDoubles", 1, 0),
                                         ("ForwardAndLoad", 1, 127), ("ForwardAndLoad", 1, 0)])

    # --- overlays and knob pickup --------------------------------------------------------------------------

    # --- options -------------------------------------------------------------------------------------------
    def test_rev_never_switches_hot_cue_banks(self):
        # The mod keeps REV as reverse (its 5-8 come from its setup menu); here hot cues E-H are Sync + hot cue.
        self.assertNotIn("hotcue_bank_on_rev", self.r.engine.profile(self.r.engine.devices["x1_left"]).option_choices)
        self.tap(L, 0x09)                            # REV
        self.tap(L, 0x02)                            # hotcue 1: still A
        self.assertEqual(self.r.sent(), [("DirectionSlipRev", 1, 127), ("DirectionSlipRev", 1, 0),
                                         ("PAD1_HotCue", 1, 127), ("PAD1_HotCue", 1, 0)])

    def test_vinyl_brake(self):
        self.option("vinyl_brake", True)
        self.r.feedback("PlayPause", 1, 127)
        self.r.clock.t += 1.0                         # steady 127: playing
        self.press(L, 0x0A)
        self.r.clock.t += 1.1
        self.release(L, 0x0A)
        sent = self.r.sent()
        self.assertEqual(sent[0][0], "VinylAdjustBrake")
        self.assertEqual(sent[1:], [("PlayPause", 1, 127), ("PlayPause", 1, 0)])

    def test_vinyl_brake_option_leaves_paused_play_immediate(self):
        self.option("vinyl_brake", True)
        self.press(L, 0x0A)                          # not playing: press goes straight through
        self.assertEqual(self.r.sent(), [("PlayPause", 1, 127)])


    def test_shift_loop_key_option(self):
        self.option("shift_loop", "key")
        self.turn(2, 0x15, 0x3F)
        self.tap(SL, 0x15)
        self.assertEqual(self.r.sent(), [("SemitoneDown", 1, 127), ("SemitoneDown", 1, 0),
                                         ("MasterTempo", 1, 127), ("MasterTempo", 1, 0)])

    def test_mod_encoders_shift_loop_is_always_key(self):
        # The mod's own encoder mode (customBrowserModeActive): Shift + Browse moves 1 beat, Shift + Loop is key.
        self.option("encoders", "mod")
        self.option("shift_loop", "jump")            # the stock-encoders setting doesn't apply
        self.turn(2, 0x15, 0x3F)
        self.tap(SL, 0x15)
        self.assertEqual(self.r.sent(), [("SemitoneDown", 1, 127), ("SemitoneDown", 1, 0),
                                         ("MasterTempo", 1, 127), ("MasterTempo", 1, 0)])

    def test_shift_loop_setting_is_offered_only_with_stock_encoders(self):
        dev = next(d for d in self.r.engine.view()["devices"] if d["position"] == "x1_left")
        self.assertEqual(dev["option_info"]["shift_loop"]["when"], ("encoders", "legacy"))
        self.assertIsNone(dev["option_info"]["encoders"]["when"])


    def test_loop_tap_toggles_loop(self):
        self.tap(L, 0x15)
        self.assertEqual(self.r.sent(), [("AutoLoop", 1, 127), ("AutoLoop", 1, 0)])



    # --- hold FX Assign 1 / 2 -----------------------------------------------------------------------------



    # --- stem mode: combo tap of FX Assign 1 + 2 -----------------------------------------------------------
    def combo_tap(self, hold=0.2):
        self.press(L, 0x00)
        self.press(L, 0x01)
        self.r.clock.t += hold
        self.release(L, 0x01)
        self.release(L, 0x00)




    # --- FX Assign, Sync layer --------------------------------------------------------------------------

    def test_sync_hotcues_are_e_to_h(self):
        self.press(L, 0x0B)
        self.tap(L, 0x03)                            # Sync + hotcue 2 -> F
        self.tap(0x92, 0x03)                         # Sync + Shift + hotcue 2 -> delete F
        self.assertEqual(self.r.sent(), [("PAD6_HotCue", 1, 127), ("PAD6_HotCue", 1, 0),
                                         ("PAD6_HotCue+Shift", 1, 127), ("PAD6_HotCue+Shift", 1, 0)])

    def test_both_fx_assign_tapped_does_nothing(self):
        self.press(L, 0x00)
        self.press(L, 0x01)
        self.release(L, 0x01)
        self.release(L, 0x00)
        self.assertEqual(self.r.sent(), [])


    # --- FX section pages ---------------------------------------------------------------------------------
    def test_pages_step_both_ways_per_half(self):
        self.page(+1)                                # FX -> SFX
        self.turn(0, 0x10, 127)                      # knob 1 -> SFX1 amount
        self.page(-1)
        self.page(-1)                                # -> Stems
        self.turn(0, 0x11, 64)                       # knob 2 -> vocal level, deck 1
        self.turn(1, 0x10, 30)                       # right half is still on FX: FX2 slot 1
        sent = self.r.sent()
        self.assertEqual(sent[0], ("SFX1-Slider", None, 127))
        self.assertIn(("PartIsolatorVocal", 1, 64 * 16383 // 127 >> 7), sent)
        self.assertEqual(sent[-1], ("FX2-1", None, 30))

    def test_knobs_send_at_once_without_pickup(self):
        self.turn(0, 0x10, 30)                       # FX page, knob 1
        self.page(1)                                 # SFX: knob 1 = SFX amount
        self.page(-1)                                # back to FX
        self.r.sent()
        self.turn(0, 0x10, 99)                       # pickup off (the default): sent straight away
        self.assertEqual(self.r.sent(), [("FX1-1", None, 99)])

    def test_page_knob_pickup(self):
        self.option("knob_pickup", True)
        self.turn(0, 0x10, 20)                       # FX page: FX1-1 = 20
        self.page(+1)
        self.turn(0, 0x10, 100)                      # SFX page: knob moved to 100
        self.page(-1)                                # back to FX: knob is at 100, FX1-1 is still 20
        self.turn(0, 0x10, 99)                       # waits (pickup)
        self.turn(0, 0x10, 21)                       # reaches it: takes over
        sent = [s for s in self.r.sent() if s[0] == "FX1-1"]
        self.assertEqual(sent, [("FX1-1", None, 20), ("FX1-1", None, 21)])

    def test_mixer_and_stems_pages(self):
        self.page(-1)
        self.page(-1)                                # FX -> Stems -> Mixer
        self.turn(0, 0x12, 10)                       # knob 3 -> EQ low
        self.tap(L, 0x13)                            # button 4 -> headphone cue
        self.page(+1)                                # Stems
        self.tap(L, 0x10)                            # button 1 -> drums mute
        self.tap(SL, 0x11)                           # Shift + button 2 -> Part FX vocal while held
        sent = self.r.sent()
        self.assertEqual(sent[:3], [("EQLow", 1, 10), ("HeadphoneCue", 1, 127), ("HeadphoneCue", 1, 0)])
        self.assertIn(("ActivePartDrums", 1, 127), sent)
        self.assertIn(("FXPartSelectVocal", None, 127), sent)



    def test_fx_buttons_take_the_page_colour(self):
        from rekordtrakt.profiles import performance_mod
        saved = dict(performance_mod.PAGE_COLOURS)
        try:
            performance_mod.PAGE_COLOURS["stems"] = (45, 9)
            self.r.feedback("ActivePartDrums", 1, 127)
            self.page(-1)                            # Stems
            self.r.leds.flush()
            sent = self.r.led_out["x1_left"].sent
            self.assertIn((0x90, 0x10, 45), sent)    # button 1: drums on, in the Stems colour
            self.assertIn((0x90, 0x11, 9), sent)     # button 2: vocal off, dim Stems colour
        finally:
            performance_mod.PAGE_COLOURS.clear()
            performance_mod.PAGE_COLOURS.update(saved)

    # --- tempo (round 3) ------------------------------------------------------------------------------------
    def test_tempo_fine_by_default_large_with_loop_pressed(self):
        self.press(L, 0x0B)                          # hold Sync
        self.turn(0, 0x15, 0x41)                     # fine: 1 step (0.5%)
        self.press(L, 0x15)                          # hold Loop too
        self.turn(0, 0x15, 0x3F)                     # large: 4 steps down (2%)
        self.release(L, 0x15)
        self.release(L, 0x0B)
        sent = self.r.sent()
        self.assertEqual(sent.count(("TempoIncMedium", 1, 127)), 1)
        self.assertEqual(sent.count(("TempoDecMedium", 1, 127)), 4)
        self.assertNotIn(("TempoReset", 1, 127), sent)

    def test_large_tempo_step_from_setup(self):
        self.press(L, 0x00)
        self.press(L, 0x01)
        self.turn(0, 0x15, 0x41)                     # setup: Loop turn -> large step 4 -> 10
        self.release(L, 0x01)
        self.release(L, 0x00)
        self.press(L, 0x0B)
        self.press(L, 0x15)
        self.turn(0, 0x15, 0x41)
        self.assertEqual(self.r.sent().count(("TempoIncMedium", 1, 127)), 10)

    # --- loop and browse encoders (round 3) -----------------------------------------------------------------
    def test_loop_encoder_is_stock_x1(self):
        self.turn(0, 0x15, 0x41)                     # turn = loop size
        self.tap(L, 0x15)                            # push = loop on/off
        self.turn(2, 0x15, 0x41)                     # Shift + turn, no loop = beat jump 4
        self.assertEqual(self.r.sent(), [("LoopHalfDouble", 1, 0x41), ("AutoLoop", 1, 127), ("AutoLoop", 1, 0),
                                         ("Jump4Fwd", 1, 127), ("Jump4Fwd", 1, 0)])

    def test_beat_jump_size_1_uses_beat_jump_pads(self):
        self.option("beatjump_size", 1)
        self.turn(2, 0x15, 0x41)
        self.turn(2, 0x15, 0x3F)
        self.assertEqual(self.r.sent(), [("PAD2_BeatJump", 1, 127), ("PAD2_BeatJump", 1, 0),
                                         ("PAD1_BeatJump", 1, 127), ("PAD1_BeatJump", 1, 0)])

    def test_browse_held_and_turned_jumps_16_beats(self):
        self.press(L, 0x14)
        self.turn(0, 0x14, 0x3F)                     # -16 beats
        self.release(L, 0x14)                        # used: no load
        self.assertEqual(self.r.sent(), [("Jump16Prev", 1, 127), ("Jump16Prev", 1, 0)])

    def test_mod_encoders(self):
        self.option("encoders", "mod")
        self.turn(0, 0x14, 0x41)                     # Browse = Move by beatjump_size (4)
        self.option("beatjump_size", 8)
        self.turn(0, 0x14, 0x3F)                     # Move 8 back
        self.turn(2, 0x14, 0x41)                     # Shift + Browse = move 1 beat (beat-jump pad)
        self.assertEqual(self.r.sent(), [("Jump4Fwd", 1, 127), ("Jump4Fwd", 1, 0),
                                         ("Jump8Prev", 1, 127), ("Jump8Prev", 1, 0),
                                         ("PAD2_BeatJump", 1, 127), ("PAD2_BeatJump", 1, 0)])

    # --- SFX and Colour FX pages (round 3) --------------------------------------------------------------------
    def test_sfx_touch_toggles(self):
        self.page(+1)                                # SFX page
        self.tap(L, 0x13)                            # engage
        self.tap(L, 0x13)                            # and release
        self.assertEqual(self.r.sent(), [("SFX1-Touch", None, 127), ("SFX1-Touch", None, 0)])

    def test_colour_fx_multi_on_off_is_emulated(self):
        for _ in range(2):
            self.page(+1)                            # FX -> SFX -> CFX multi
        self.turn(0, 0x11, 100)                      # knob 2 -> channel 2 = 100
        self.tap(L, 0x11)                            # button 2 -> off: centre
        self.turn(0, 0x11, 110)                      # turned while off: remembered, not sent
        self.tap(L, 0x11)                            # on: the remembered value
        self.assertEqual(self.r.sent(), [("CFXParameterCH2", None, 100), ("CFXParameterCH2", None, 64),
                                         ("CFXParameterCH2", None, 110)])

    def test_colour_fx_single_type_knob_and_next_button(self):
        for _ in range(3):
            self.page(+1)                            # -> CFX single
        self.turn(0, 0x11, 70)                       # knob 2 -> PARAM
        self.turn(0, 0x12, 100)                      # knob 3 -> type zone 5 of 6 -> CFX5
        self.turn(0, 0x12, 101)                      # same zone: nothing
        self.tap(L, 0x11)                            # button 2 -> next type -> CFX6
        self.tap(L, 0x10)                            # button 1 -> this deck's Colour FX off
        self.assertEqual(self.r.sent(), [("CFXSubParameter", None, 70), ("CFX5On", None, 127), ("CFX5On", None, 0),
                                         ("CFX6On", None, 127), ("CFX6On", None, 0), ("CFXParameterCH1", None, 64)])

    def test_mod_bridge_covers_every_deck(self):
        functions = {(e["function"], e["deck"]) for e in self.r.manifest["entries"]}
        for deck in (1, 2, 3, 4):
            self.assertIn(("PlayPause", deck), functions)
            self.assertIn(("PAD8_HotCue", deck), functions)


if __name__ == "__main__":
    unittest.main()
