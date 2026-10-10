from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from autotype.featherine import edit_plan
from autotype.session import DERIVED_HOLD, SHORT_PROMPT_HOLD, BoardWatch, MatchSession
from autotype.test_regressions import app_module, frame, make_app
from dyoe2_engine import Dyoe2Engine, TrapPools


def session(words):
    return MatchSession(Dyoe2Engine(list(words), traps=TrapPools(), validate_giveable=False))


class NeverStallTests(unittest.TestCase):
    def test_a_prompt_whose_only_answers_hand_a_banned_prompt_is_still_answered(self):
        # "tgif" hands over "if" and "fsr" hands over "sr", both banned.
        s = session(["tgif", "fsr", "fsrs"])
        self.assertEqual(s.choose("tg")[0], "tgif")
        self.assertIn(s.choose("fs")[0], ("fsr", "fsrs"))

    def test_a_banned_hand_over_is_still_avoided_when_there_is_another_answer(self):
        s = session(["tgif", "tgxyz"])
        self.assertEqual(s.choices("tg", 3), ["tgxyz"])
        s.engine.mark_rejected("tgxyz")
        self.assertEqual(s.choices("tg", 3), ["tgif"])

    def test_last_resort_retries_a_refused_word_but_never_a_used_one(self):
        s = session(["tgif", "tgifs"])
        s.engine.mark_rejected("tgif")
        s.engine.mark_used("tgifs")
        self.assertEqual(s.choose("tg")[0], "")
        self.assertEqual(s.last_resort("tg"), "tgif")
        self.assertEqual(s.last_resort("tg", {"tgif"}), "")

    def test_the_app_types_a_last_resort_instead_of_waiting_out_the_clock(self):
        app, _ = make_app(("tgif",))
        app.engine.mark_rejected("tgif")
        app._start_typing = app_module.AutotypeApp._start_typing.__get__(app)
        with patch.object(app, "_launch_typing") as launch:
            app._start_typing("tg")
            app._start_typing("tg")
        self.assertEqual([c[0][1] for c in launch.call_args_list], ["tgif"])

    def test_the_opponents_own_word_is_never_a_self_solve(self):
        s = session(["vpn", "vpns"])
        s.opponent_word = "vpn"
        for _ in range(20):
            self.assertEqual(s.choose("vpn", 0.5)[0], "vpns")

    def test_the_opponents_unconfirmed_word_is_never_answered_again(self):
        s = session(["sksksk", "skskx"])
        s.opponent_word = "sksksk"
        self.assertEqual(s.choose("sksk")[0], "skskx")
        self.assertEqual(s.alternative("sksk", "skskx")[0], "")
        self.assertEqual(s.last_resort("sksk", {"skskx"}), "")


class DescrambleTests(unittest.TestCase):
    def test_a_clean_prompt_after_a_clipped_word_is_not_reshuffled(self):
        s = session(["abstracts", "abstractist", "tsar", "star"])
        self.assertEqual(s.descramble_prompt("ts", "abstrac", "ab", ["abstrac"]), "")
        self.assertEqual(s.descramble_prompt("tsx", "abstrac", "ab", ["abstrac"]), "")

    def test_a_row_still_drawing_in_is_not_a_shorter_prompt_with_strays(self):
        # Mirrored "ols" draws in as "s", "sl", "slo". After a timeout their
        # prompt was read from its first tile, but prompts never get shorter.
        s = session(["cesspools", "olsen"])
        self.assertEqual(s.descramble_prompt("sl", "cesspools", "c", [], floor=3), "")
        self.assertEqual(s.descramble_prompt("slo", "cesspools", "c", [], floor=3), "ols")

    def test_a_whole_row_reversed_beats_a_shorter_prompt_with_a_stray(self):
        s = session(["allylamines", "inesite", "nesting"])
        self.assertEqual(s.descramble_prompt("seni", "allylamines", "", [], floor=3), "ines")
        # Their last reading was clipped: the dictionary finishes it.
        self.assertEqual(s.descramble_prompt("seni", "allylamin", "al", ["allylamin"], floor=3), "ines")


class PartialPromptTests(unittest.TestCase):
    def test_a_read_shorter_than_the_last_prompt_waits_for_the_rest_to_land(self):
        watch = BoardWatch()
        watch.rearm("leet", 0.0)
        watch.played = "leet"
        watch.typed = "lettuce"
        watch.observe("ce", "theirs", now=0.1)
        self.assertEqual(watch.floor, 4)
        watch.observe("lee", "ours", now=1.0)
        self.assertFalse(watch.observe("lee", "ours", now=1.02)["play"])
        self.assertEqual(watch.observe("leet", "ours", now=1.06)["play"], "")
        self.assertEqual(watch.observe("leet", "ours", now=1.08)["play"], "leet")

    def test_a_shorter_prompt_that_stays_is_played_and_lowers_the_floor(self):
        watch = BoardWatch()
        watch.rearm("leet", 0.0)
        watch.observe("w", "ours", now=5.0)
        self.assertFalse(watch.observe("w", "ours", now=5.02)["play"])
        self.assertEqual(watch.observe("w", "ours", now=5.01 + SHORT_PROMPT_HOLD)["play"], "w")
        self.assertEqual(watch.floor, 1)

    def test_their_prompt_is_the_longest_ending_of_our_word_read_on_their_turn(self):
        watch = BoardWatch()
        watch.rearm("rs", 0.0)
        watch.played = "rs"
        watch.typed = "rsvp"
        watch.observe("s", "theirs", now=0.1)
        watch.observe("sv", "theirs", now=0.15)
        watch.observe("svp", "theirs", now=0.2)
        watch.observe("svpa", "theirs", now=0.5)
        self.assertEqual(watch._given, "svp")
        self.assertEqual(watch.floor, 3)

    def test_a_partial_first_tile_is_not_vouched_by_their_ending(self):
        watch = BoardWatch()
        watch.rearm("ed", 0.0)
        watch.played = "ed"
        watch.typed = "edplot"
        watch.observe("ot", "theirs", now=0.1)
        watch.observe("otxt", "theirs", now=0.3)
        # Their word ends in "t", but "t" is shorter than the prompt they had.
        self.assertFalse(watch.observe("t", "ours", now=0.5)["play"])
        self.assertFalse(watch.observe("t", "ours", now=0.52)["play"])

    def test_their_prompt_read_while_drawing_in_grows_to_the_last_length(self):
        # After our timeout their prompt is not an ending of our word.
        watch = BoardWatch()
        watch.rearm("ies", 0.0)
        for i, board in enumerate(("c", "ce", "ces", "cess")):
            watch.observe(board, "theirs", now=0.1 + i * 0.05)
        self.assertEqual(watch._given, "ces")

    def test_a_board_worked_out_from_their_word_has_to_stay(self):
        def watch_after_their_word():
            watch = BoardWatch()
            watch.rearm("ies", 0.0)
            watch.observe("cesspools", "theirs", now=0.1)
            return watch

        plain = watch_after_their_word()
        self.assertEqual(plain.observe("ols", "ours", now=0.5)["play"], "ols")
        fixed = watch_after_their_word()
        self.assertFalse(fixed.observe("ols", "ours", now=0.5, derived=True)["play"])
        self.assertFalse(fixed.observe("ols", "ours", now=0.53, derived=True)["play"])
        self.assertEqual(fixed.observe("ols", "ours", now=0.5 + DERIVED_HOLD, derived=True)["play"], "ols")


class GlitchStaysFixedTests(unittest.TestCase):
    def test_every_capture_of_a_shuffled_prompt_is_solved_the_same(self):
        app, _ = make_app(("kinging", "kingdom", "gingham", "gignitive", "ginger"))
        app._name = "player"
        for board in ("king", "kingi", "kingin"):
            app._handle_frame(frame(board, "opponent"))
        for _ in range(4):
            app._handle_frame(frame("ngig", "player"))
        self.assertEqual({c[0][0] for c in app._start_typing.call_args_list}, {"ging"})


class ShuffledBoardTests(unittest.TestCase):
    def their_turn(self, words, word, start):
        app, _ = make_app(words)
        app._name = "player"
        for k in range(start, len(word) + 1):
            app._handle_frame(frame(word[:k], "opponent"))
        return app

    def test_an_emptied_input_showing_the_shuffled_prompt_is_the_prompt(self):
        app = self.their_turn(("hexagram", "ramble", "ramp"), "hexagram", 3)
        app._handle_frame(frame("ram"))
        app._handle_frame(frame("ram"))
        app._start_typing.reset_mock()
        with patch.object(app, "_erase_suffix"):
            app._clear_input("ram")
        app._clear["working"] = False
        for _ in range(2):
            app._handle_frame(frame("rmarn"))
        app._start_typing.assert_called_once_with("ram")
        self.assertIsNone(app._clear)

    def test_the_prompt_being_erased_for_wins_over_a_shorter_reading(self):
        # Their word was never read, so only the prompt itself says what
        # "ono" is: "oon" shuffled, not a fresh "on".
        app, _ = make_app(("oonts", "onion"))
        app._name = "player"
        app._current_turn = "ours"
        app.watch.rearm("oon", time.monotonic())
        with patch.object(app, "_erase_suffix"):
            app._clear_input("oon")
        app._clear["working"] = False
        for _ in range(2):
            app._handle_frame(frame("ono"))
        app._start_typing.assert_called_once_with("oon")

    def test_the_first_tiles_of_a_mirrored_row_are_not_played(self):
        # "tion" mirrored draws in as "n", "no", "noi", "noit"; "noi" reads
        # as a whole mirrored "ion" until the last tile lands.
        app = self.their_turn(("capsulation", "ionic", "tional"), "capsulation", 3)
        app._handle_frame(frame("noi"))
        app._handle_frame(frame("noi"))
        app._start_typing.assert_not_called()
        app._handle_frame(frame("noit"))
        app._handle_frame(frame("noit"))
        app._start_typing.assert_called_once_with("tion")

    def test_a_shuffled_board_after_enter_means_it_was_refused(self):
        app = self.their_turn(("hoodshy", "dshyly", "dsomo"), "hoodshy", 4)
        app._handle_frame(frame("ds"))
        app._handle_frame(frame("ds"))
        app._typing_prompt = app.watch.played = "ds"
        app._typed_word = app.watch.typed = "dsomo"
        app._submitted_at = app._submit_read_at = time.monotonic() - 1
        app._submit_attempts = 1
        app._start_typing.reset_mock()
        for _ in range(3):
            app._handle_frame(dict(frame("yhds"), captured_at=time.monotonic()))
        self.assertNotIn("dsomo", app.engine.used_words)
        app._start_typing.assert_called_with("dshy")


class OwnKeysTests(unittest.TestCase):
    """Frames while our keys are going out, as the controller sees them."""

    def typing_app(self, words, prompt, typed):
        app, _ = make_app(words)
        app._name = "player"
        app._current_turn = "ours"
        app.typing = True
        app._typing_prompt = app.watch.played = prompt
        app._keys_now = app._keys_sent = typed
        app._input_length = len(typed)
        return app

    def test_letters_left_of_the_prompt_mean_the_row_is_mirrored(self):
        app = self.typing_app(("sfoufs", "fsr"), "sf", "o")
        with patch.object(app, "_clear_input") as clear:
            app._handle_frame(frame("osf"))
            app._handle_frame(frame("osf"))
        clear.assert_called_once_with("fs")
        self.assertEqual(app._typing_prompt, "fs")
        self.assertEqual(app._seen_as("rsf"), "fsr")
        self.assertEqual(app._seen_as("sf"), "fs")

    def test_a_partial_mirrored_prompt_is_completed_from_our_letters(self):
        # "ot" was drawn mirrored as "to"; only its "t" had landed.
        app = self.typing_app(("tranq", "otp"), "t", "r")
        with patch.object(app, "_clear_input") as clear:
            app._handle_frame(frame("rto"))
            app._handle_frame(frame("rto"))
        clear.assert_called_once_with("ot")

    def test_tiles_after_a_short_read_are_the_rest_of_the_prompt(self):
        app = self.typing_app(("leech", "leetle"), "lee", "ch")
        with patch.object(app, "_clear_input") as clear:
            app._handle_frame(frame("leetch"))
            app._handle_frame(frame("leetch"))
        clear.assert_called_once_with("leet")
        self.assertEqual(app.watch.played, "leet")
        self.assertEqual(app.watch.floor, 4)

    def test_a_shuffled_prompt_solved_one_tile_short_is_corrected(self):
        # "fnig" after "histing" was taken for "ng"; typed, the row shows "ing".
        app = self.typing_app(("histing", "ingot", "ngwees"), "ng", "wees")
        app._view = {"shown": "fnig", "real": "ng", "mirrored": None}
        app.watch._opponent_word = "histing"
        with patch.object(app, "_clear_input") as clear:
            app._handle_frame(frame("ingwees"))
            app._handle_frame(frame("ingwees"))
        clear.assert_called_once_with("ing")

    def test_a_doubled_key_is_not_taken_for_a_longer_prompt(self):
        app = self.typing_app(("leet", "leetle"), "lee", "t")
        with patch.object(app, "_clear_input") as clear:
            for _ in range(3):
                app._handle_frame(frame("leett"))
        clear.assert_not_called()
        self.assertEqual(app._typing_prompt, "lee")

    def test_a_prompt_tile_is_found_even_if_our_word_has_that_letter_later(self):
        app = self.typing_app(("disterr", "dsomo"), "d", "isterr")
        with patch.object(app, "_clear_input") as clear:
            app._handle_frame(frame("dsisterr"))
            app._handle_frame(frame("dsisterr"))
        clear.assert_called_once_with("ds")

    def test_a_deleted_first_key_left_behind_is_not_a_prompt_tile(self):
        app = self.typing_app(("disterr", "dxylo"), "d", "isterr")
        app._keys_sent = "xisterr"
        with patch.object(app, "_clear_input") as clear:
            for _ in range(3):
                app._handle_frame(frame("dxisterr"))
        clear.assert_not_called()

    def test_a_plain_row_is_left_alone(self):
        app = self.typing_app(("stone",), "s", "to")
        with patch.object(app, "_clear_input") as clear:
            for _ in range(3):
                app._handle_frame(frame("sto"))
        clear.assert_not_called()

    def test_only_our_own_letters_decide_which_way_the_row_is_drawn(self):
        app = self.typing_app(("ionograms", "tional"), "ion", "ograms")
        app._view = {"shown": "noi", "real": "ion", "mirrored": None}
        # The input was emptied; the "t" is the last tile of "noit".
        self.assertEqual(app._seen_as("noit"), "noit")
        self.assertIsNone(app._view["mirrored"])

    def test_a_doubled_first_key_does_not_hide_a_mirrored_row(self):
        app = self.typing_app(("ionograms", "tional"), "ion", "ograms")
        app._view = {"shown": "noi", "real": "ion", "mirrored": None}
        board = ("tion" + "oograms")[::-1]
        with patch.object(app, "_clear_input") as clear:
            app._handle_frame(frame(board))
            app._handle_frame(frame(board))
        clear.assert_called_once_with("tion")

    def test_a_mirrored_prompt_answered_from_the_reverse_is_read_through(self):
        app, _ = make_app(("fsr",))
        app._fix = ("sf", "fs")
        with patch.object(app_module.threading, "Thread"):
            app._launch_typing("fs", "fsr", edit_plan("", "r"))
        app._keys_now = "r"
        self.assertEqual(app._seen_as("rsf"), "fsr")
        self.assertEqual(app._view["mirrored"], True)
        self.assertEqual(app._seen_as("sf"), "fs")


class SubmissionTests(unittest.TestCase):
    def test_an_edit_does_not_retype_letters_already_in_the_box(self):
        app, _ = make_app(("ismailisms", "ismailism"))
        app._typing_prompt = "ism"
        keys = []
        with patch.object(app_module, "tap_key", side_effect=lambda kind, key, hold: keys.append(key)):
            app._type_suffix(app._gen, "ismailism", edit_plan("ailisms", "ailism"),
                             threading.Event(), "ailisms")
        self.assertEqual(keys, ["\b"])
        events = []
        while not app._queue.empty():
            events.append(app._queue.get_nowait())
        self.assertEqual(events[0][0], "SUBMIT")
        self.assertEqual(events[0][1][1], "ismailism")

    def test_a_key_dropped_mid_word_is_put_back_before_enter(self):
        app, _ = make_app(("sessionary",))
        keys = []
        state = {"text": "ses", "clock": time.monotonic()}

        def publish():
            state["clock"] += 0.05
            app._last_frame = {"prompt": state["text"], "full": True, "row_complete": True,
                               "tiles": len(state["text"]), "captured_at": state["clock"] + 10}

        def tap(kind, key, hold):
            keys.append("\b" if kind == "back" else key)
            if kind == "back":
                state["text"] = state["text"][:-1]
            elif not (key == "o" and keys.count("o") == 1):
                state["text"] += key
            publish()

        class Clock:
            def is_set(self):
                return False

            def wait(self, seconds):
                publish()
                return False

        with patch.object(app_module, "focus_roblox", return_value=True), \
             patch.object(app_module, "roblox_focused", return_value=True), \
             patch.object(app_module, "tap_key", side_effect=tap), \
             patch.object(app_module, "press_enter", side_effect=lambda: keys.append("ENTER")):
            app._typing_prompt = "ses"
            app._type_suffix(app._gen, "sessionary", edit_plan("", "sionary"), Clock())
            while not app._queue.empty():
                app._process_event(*app._queue.get_nowait())
        self.assertEqual(state["text"], "sessionary")
        self.assertEqual(keys, list("sionary") + ["\b"] * 4 + list("onary") + ["ENTER"])

    def test_the_retry_passes_what_is_typed_to_the_edit(self):
        app, _ = make_app(("ismailisms", "ismailism"))
        app._typing_prompt = app.watch.played = "ism"
        app._last_frame = {"prompt": "ismailisms", "full": True, "row_complete": True,
                           "tiles": 10, "captured_at": time.monotonic()}
        with patch.object(app, "_launch_typing") as launch:
            app._schedule_retry("ismailisms", used=True)
        self.assertEqual(launch.call_args[1]["start"], "ailisms")

    def test_enter_waits_shrink_when_the_clock_is_low(self):
        app, _ = make_app()
        with patch.object(app, "_time_left", return_value=None):
            self.assertEqual(app._ack_waits(), (app_module.ENTER_RETRY_AFTER, app_module.REFUSED_AFTER))
        with patch.object(app, "_time_left", return_value=2.0):
            retry, refused = app._ack_waits()
        self.assertLess(retry + refused, 1.0)

    def test_the_rest_of_the_prompt_after_enter_means_it_was_refused(self):
        app, _ = make_app(("leech", "leetle"))
        app._name = "player"
        app._current_turn = "ours"
        app._typing_prompt = app.watch.played = "lee"
        app._typed_word = app.watch.typed = "leech"
        app._submitted_at = app._submit_read_at = time.monotonic() - 1
        app._submit_attempts = 1
        for _ in range(3):
            app._handle_frame(dict(frame("leet"), captured_at=time.monotonic()))
        self.assertNotIn("leech", app.engine.used_words)
        app._start_typing.assert_called_with("leet")


if __name__ == "__main__":
    unittest.main()
