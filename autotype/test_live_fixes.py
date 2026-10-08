"""Regression cases from the reported screenshots and missed-key behavior."""
from __future__ import annotations

import queue
import random
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from autotype.featherine import turn_plan
from autotype.session import BoardWatch, MatchSession, header_is_ours, phase_for_prompt, speaker_from_header
from autotype.tiles import scan_rgba
from autotype.test_regressions import app_module, frame, make_app
from dyoe2_engine import Dyoe2Engine, TrapPools

FIXTURES = Path(__file__).parent / "fixtures"


class ScreenshotTests(unittest.TestCase):
    def test_actual_punctuation_and_fullscreen_tile_at_multiple_scales(self):
        for name, expected in (("punctuation", "-'"), ("fullscreen_turn", "x"), ("cropped_turn", "ned")):
            with Image.open(FIXTURES / f"{name}.png") as source:
                image = source.convert("RGBA")
            for width in (640, 960, 1280, 1600):
                resized = image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS)
                result = scan_rgba(resized.tobytes(), *resized.size)
                self.assertEqual(result["prompt"], expected, (name, width, result))
                self.assertTrue(result["full"], result)
                if name == "fullscreen_turn":
                    self.assertTrue(header_is_ours("gugugaga2323332", result["header"]), result)

    def test_manual_confirmation_plays_when_header_is_outside_capture(self):
        app, face = make_app(("nedder", "nedging"))
        image = Image.open(FIXTURES / "cropped_turn.png").convert("RGBA")
        app._handle_frame(scan_rgba(image.tobytes(), *image.size))
        self.assertIn("ned", face.values["C1"])
        self.assertEqual(face.values["TURN"], "WATCHING")
        app._confirm_turn()
        self.assertEqual(face.values["TURN"], "YOUR TURN")
        app._start_typing.assert_called_once_with("ned")
        self.assertTrue(app._manual_turn)


class SubmissionTests(unittest.TestCase):
    def test_enter_is_pressed_on_submit_and_long_unreadable_words_are_stored(self):
        word = "electroencephalographically"
        app, _ = make_app((word, "enter"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "e"
        with patch.object(app_module, "press_enter") as enter:
            app._process_event("SUBMIT", (app._gen, word, len(word) - 1))
            enter.assert_called_once()
            self.assertEqual(app.watch.typed, word)
            for _ in range(3):
                app._handle_frame(frame("electro?????", full=False))
            enter.assert_called_once()
        app._handle_frame(frame("ally", "opponent"))
        self.assertEqual(app.engine.used_words, {word})
        self.assertFalse(app._typed_word)

    def test_enter_waits_for_roblox_instead_of_another_app(self):
        app, _ = make_app(("stone",))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        with patch.object(app_module, "press_enter") as enter, \
             patch.object(app_module, "roblox_focused", return_value=False), \
             patch.object(app_module, "focus_roblox", return_value=False):
            app._process_event("SUBMIT", (app._gen, "stone", 4))
            app._handle_frame(frame("stone"))
            enter.assert_not_called()
        with patch.object(app_module, "press_enter") as enter:
            app._handle_frame(frame("stone"))
            enter.assert_called_once()

    def test_already_used_banner_deletes_only_the_extra_letters(self):
        app, _ = make_app(("ismailisms", "ismailism", "ismy"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "ism"
        with patch.object(app_module, "press_enter"):
            app._process_event("SUBMIT", (app._gen, "ismailisms", 7))
        with patch.object(app, "_launch_typing") as launch, patch.object(app, "_clear_input") as clear:
            app._handle_frame(dict(frame("ismailisms"), alert=True))
        clear.assert_not_called()
        prompt, word, plan = launch.call_args[0]
        self.assertEqual((prompt, word), ("ism", "ismailism"))
        self.assertEqual([s.kind for s in plan.steps], ["back", "enter"])
        self.assertIn("ismailisms", app.engine.used_words)

    def test_a_banner_left_over_from_before_enter_is_not_this_answers(self):
        app, _ = make_app(("ismailisms", "ismailism"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "ism"
        app._last_frame = dict(frame("ismailism"), alert=True)
        with patch.object(app_module, "press_enter"):
            app._process_event("SUBMIT", (app._gen, "ismailisms", 7))
        with patch.object(app, "_launch_typing") as launch:
            app._handle_frame(dict(frame("ismailisms"), alert=True))
            launch.assert_not_called()
            app._handle_frame(frame("ismailisms"))
            app._handle_frame(dict(frame("ismailisms"), alert=True))
            launch.assert_called_once()

    def test_missed_enter_retries_without_retyping_the_word(self):
        app, _ = make_app(("stone",))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app.watch.pending = app.watch.typed = app._typed_word = "stone"
        app._submit_attempts = 1
        app._submitted_at = app._submit_read_at = time.monotonic() - 2
        with patch.object(app_module, "press_enter") as enter, patch.object(app_module, "roblox_focused", return_value=True):
            app._handle_frame(frame("stone"))
            enter.assert_not_called()
            app._handle_frame(frame("stone"))
            enter.assert_called_once()
            app._handle_frame(frame("e", "opponent"))
            app._handle_frame(frame("e", "opponent"))
            enter.assert_called_once()
        app._start_typing.assert_not_called()
        self.assertEqual(app.engine.used_words, {"stone"})

    def test_bad_header_after_enter_does_not_falsely_accept_or_lose_enter_retry(self):
        app, _ = make_app(("stone",))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app.watch.pending = app.watch.typed = app._typed_word = "stone"
        app._submitted_at = app._submit_read_at = time.monotonic() - 2
        with patch.object(app_module, "press_enter") as enter, patch.object(app_module, "roblox_focused", return_value=True):
            app._handle_frame(frame("stone", "misread"))
            self.assertEqual(app._typed_word, "stone")
            self.assertFalse(app.engine.used_words)
            app._handle_frame(frame("stone"))
            enter.assert_called_once()
        app._start_typing.assert_not_called()

    def test_unacknowledged_submission_moves_to_another_answer_after_enter_retries(self):
        app, _ = make_app(("stone", "star"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app.watch.pending = app.watch.typed = app._typed_word = "stone"
        app._submit_attempts = 2
        app._submitted_at = app._submit_read_at = time.monotonic() - 2
        with patch.object(app, "_launch_typing") as launch, patch.object(app_module, "press_enter") as enter:
            app._handle_frame(frame("stone"))
            app._handle_frame(frame("stone"))
            self.assertEqual(launch.call_args[0][1], "star")
            enter.assert_not_called()
        self.assertIn("stone", app.engine.rejected_words)
        self.assertFalse(app.engine.used_words)
        self.assertTrue(app.armed)

    def test_a_rejected_reset_to_the_original_prefix_types_another_answer(self):
        app, _ = make_app(("stone", "star"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app.watch.pending = app.watch.typed = app._typed_word = "stone"
        with patch.object(app, "_launch_typing") as launch:
            app._handle_frame(frame("s"))
            launch.assert_not_called()
            app._handle_frame(frame("s"))
        prompt, word, plan = launch.call_args[0]
        self.assertEqual(word, "star")
        # The board shows only the prefix, so nothing is deleted.
        self.assertEqual([s.kind for s in plan.steps], ["type"] * 3 + ["enter"])
        self.assertIn("stone", app.engine.rejected_words)
        self.assertNotIn("stone", app.engine.used_words)

    def test_a_doubled_key_seen_on_the_board_is_edited_from_what_is_shown(self):
        app, _ = make_app(("stone", "stones"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app.watch.pending = app.watch.typed = app._typed_word = "stone"
        app._last_frame = frame("sttone")
        with patch.object(app, "_launch_typing") as launch:
            app._schedule_retry("stone", used=False)
        _prompt, word, plan = launch.call_args[0]
        self.assertEqual(word, "stones")
        self.assertEqual(plan.steps[-1].typed, "tones")
        self.assertEqual(sum(s.kind == "back" for s in plan.steps), 4)

    def test_own_growing_input_never_restarts_as_a_longer_prefix(self):
        app, _ = make_app()
        app._name = "player"
        app.typing = True
        app._typing_prompt = app.watch.played = "s"
        for board in ("st", "sto", "ston", "stone"):
            app._handle_frame(frame(board))
        app._start_typing.assert_not_called()
        self.assertTrue(app.typing)

    def test_a_full_typing_turn_presses_enter_once_right_after_the_last_key(self):
        app, _ = make_app(("ecaboron",))
        app._start_typing = app_module.AutotypeApp._start_typing.__get__(app)
        app._name = "player"
        app._current_turn = "ours"
        keys = []
        with patch.object(app_module, "tap_key", side_effect=lambda kind, key, hold: keys.append(key)), \
             patch.object(app_module, "press_enter", side_effect=lambda: keys.append("ENTER")), \
             patch.object(app_module, "turn_plan", side_effect=lambda s, p, b, is_word=None:
                          app_module.edit_plan("", s)):
            app._start_typing("e")
            app._typing_thread.join(timeout=3)
            while not app._queue.empty():
                app._process_event(*app._queue.get_nowait())
        self.assertEqual(keys, list("caboron") + ["ENTER"])
        self.assertEqual(app.watch.typed, "ecaboron")

    def test_early_enter_is_occasional_and_never_on_a_word(self):
        counts = []
        for seed in range(200):
            plan = turn_plan("esslerising", "n", 12, random.Random(seed).random, lambda w: False)
            counts.append(sum(step.kind == "early" for step in plan.steps))
            self.assertEqual(plan.steps[-1].kind, "enter")
            self.assertEqual(plan.steps[-1].typed, "esslerising")
        self.assertGreater(sum(counts), 0)
        self.assertGreater(counts.count(0), 160)
        self.assertLessEqual(max(counts), 1)
        for seed in range(200):
            plan = turn_plan("esslerising", "n", 12, random.Random(seed).random, lambda w: True)
            self.assertFalse(any(step.kind == "early" for step in plan.steps))


class PauseAndPhaseTests(unittest.TestCase):
    def test_lagging_own_header_cannot_replay_the_accepted_words_ending(self):
        watch = BoardWatch()
        watch.played = "s"
        watch.typed = watch.pending = "stone"
        self.assertTrue(watch.observe("e", "ours", now=1)["accepted"])
        for i in range(6):
            self.assertFalse(watch.observe("e", "ours", now=1.1 + i * .02)["play"])
        watch.observe("e", "theirs", now=1.3)
        watch.observe("elm", "theirs", now=1.4)
        self.assertFalse(watch.observe("m", "ours", now=1.5)["play"])
        self.assertEqual(watch.observe("m", "ours", now=1.6)["play"], "m")

    def test_word_ending_in_its_own_prefix_is_not_rejected_during_header_lag(self):
        watch = BoardWatch()
        watch.played = "s"
        watch.typed = watch.pending = "stones"
        for i in range(3):
            self.assertFalse(watch.observe("s", "ours", now=1 + i * .05)["rejected"])
        self.assertTrue(watch.observe("s", "theirs", now=1.2)["accepted"])

    def test_stale_worker_completion_cannot_unlock_a_new_attempt(self):
        app, _ = make_app()
        old_gen = app._gen
        app._cancel_typing(release=True)
        app.watch.played = app._typing_prompt = "ism"
        app._process_event("TYPE_DONE", (old_gen, False, 9, "Roblox lost focus."))
        with patch.object(app_module, "press_enter") as enter:
            app._process_event("SUBMIT", (old_gen, "likeness", 4))
        enter.assert_not_called()
        self.assertEqual(app.watch.played, "ism")
        self.assertFalse(app._aborted_prompt)
        self.assertFalse(app._typed_word)

    def test_focus_interruption_keeps_typing_armed_for_automatic_recovery(self):
        app, _ = make_app()
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app.typing = True
        app._process_event("TYPE_DONE", (app._gen, False, 2, "Roblox lost focus. Typing stopped."))
        self.assertTrue(app.armed)
        self.assertTrue(app._want_arm)
        with patch.object(app, "_clear_input") as clear:
            app._handle_frame(frame("sto"))
            clear.assert_called_once_with("s")
        self.assertEqual(app._input_length, 2)
        app._start_typing.assert_not_called()

    def test_retry_latch_does_not_block_an_unrelated_new_prompt(self):
        app, face = make_app(("likeness", "ismaticalness"))
        app._name = "player"
        app.watch.rearm("like", time.monotonic())
        app._shown = "like"
        app._handle_frame(frame("ism"))
        app._handle_frame(frame("ism"))
        app._start_typing.assert_called_once_with("ism")
        self.assertIn("ismaticalness", face.values["C1"])

    def test_missed_opponent_turn_releases_old_submission_and_refreshes_ism(self):
        app, face = make_app(("likeness", "ismaticalness"))
        app._name = "player"
        app._typing_prompt = app.watch.played = app._shown = "like"
        app.watch.pending = app.watch.typed = app._typed_word = "likeness"
        app._submitted_at = app._submit_read_at = time.monotonic() - 1
        app._handle_frame(frame("ism"))
        app._start_typing.assert_not_called()
        app._handle_frame(frame("ism"))
        app._start_typing.assert_called_once_with("ism")
        self.assertIn("ismaticalness", face.values["C1"])
        self.assertIn("likeness", app.engine.used_words)

    def test_blank_header_does_not_require_manual_confirmation_again(self):
        app, face = make_app()
        app._name = "player"
        app._handle_frame(frame("s"))
        app._handle_frame(dict(frame("s"), header=""))
        self.assertEqual(face.values["TURN"], "YOUR TURN")
        app._start_typing.assert_called_once_with("s")

    def test_split_username_and_partially_read_instruction_identify_our_turn(self):
        header = "g u gu ga ga2323332, type an eng?ish word starting with:"
        self.assertTrue(header_is_ours("gugugaga2323332", header))
        self.assertEqual(speaker_from_header(header, "gugugaga2323332"), "gugugaga2323332")
        app, _ = make_app()
        app._name = "gugugaga2323332"
        for _ in range(2):
            app._handle_frame(dict(frame("s"), header=header))
        app._start_typing.assert_called_once_with("s")

    def test_confirm_button_cannot_restart_a_submitted_word(self):
        app, _ = make_app()
        app._last_frame = frame("s")
        app._typing_prompt = app.watch.played = "s"
        app._typed_word = app.watch.typed = "stone"
        app._confirm_turn()
        app._start_typing.assert_not_called()
        self.assertEqual(app.watch.typed, "stone")

    def test_no_word_does_not_latch_the_prompt_or_stall_later_dictionary_updates(self):
        app, _ = make_app(("stone",))
        app._start_typing = app_module.AutotypeApp._start_typing.__get__(app)
        app._start_typing("ism")
        self.assertFalse(app.watch.played)
        self.assertTrue(app.armed)
        app.engine.set_words(("ismaticalness",), TrapPools(), validate_giveable=False)
        app._selection_retry_at = 0
        with patch.object(app_module.threading, "Thread") as thread:
            app._start_typing("ism")
            thread.return_value.start.assert_called_once()
        self.assertEqual(app.watch.played, "ism")

    def test_pause_stops_worker_and_pending_enter_and_keeps_used_words(self):
        app, face = make_app()
        app.engine.mark_used("stone")
        app.typing = True
        app._input_length = 3
        cancel = app._type_cancel
        gen = app._gen
        # Cancellation takes effect before the queued native action is drained,
        # so a worker's SUBMIT already in the queue cannot press Enter.
        app._put_event("ACTION", ("PAUSE", ""))
        self.assertTrue(cancel.is_set())
        with patch.object(app_module, "press_enter") as enter:
            app._process_event("SUBMIT", (gen, "star", 3))
            app._process_event(*app._queue.get_nowait())
            self.assertTrue(app._paused.is_set())
            self.assertEqual(face.values["PAUSELABEL"], "RESUME")
            app._process_event("SUBMIT", (gen, "star", 3))
            app._handle_frame(frame("star"))
            enter.assert_not_called()
        self.assertFalse(app._typed_word)
        self.assertEqual(app.engine.used_words, {"stone"})
        app._toggle_pause()
        self.assertFalse(app._paused.is_set())
        self.assertEqual(app.engine.used_words, {"stone"})
        app._new_game()
        self.assertFalse(app.engine.used_words)

    def test_phase_follows_actual_prefix_and_traps_match_the_next_prompt_length(self):
        traps = TrapPools(casual_2=["xy"], casual_3=["zzz"], casual_4=["tone"])
        words = ["atone", "axy", "azzz", "aaaaaaaaaa", "xyz", "zzzz", "tones",
                 "abtone", "abzzz", "abxy"]
        engine = Dyoe2Engine(words, traps, validate_giveable=False)
        engine.cancelled_prompts.clear()
        session = MatchSession(engine)
        session.round = 100
        self.assertEqual(phase_for_prompt(100, "abc"), 3)
        # A one-letter prompt hands over one letter; only the stage-change
        # hedge (two letters) can trap. A 4-letter trap is never mixed in.
        self.assertEqual(session.prepare("a"), 1)
        self.assertTrue(session.choose("a")[0].endswith("xy"))
        self.assertEqual(engine.trap_phases, ())
        # Two letters: the exact two-letter trap, before the three-letter hedge.
        self.assertEqual(session.choose("ab")[0], "abxy")
        engine.mark_used("abxy")
        self.assertEqual(session.choose("ab")[0], "abzzz")
        self.assertEqual(session.prepare("abc"), 3)
        self.assertEqual(session.prepare("abcd"), 4)
        session.new_game()
        self.assertEqual(engine.phase, 1)

    def test_punctuation_survives_watch_and_opponent_recovery(self):
        watch = BoardWatch()
        watch.observe("a'", "ours", tiles=2)
        self.assertEqual(watch.observe("a'", "ours", tiles=2)["play"], "a'")
        app, _ = make_app(("a-b", "a'c"))
        self.assertEqual(app.session.recover_partial(["a-"], "b", "a"), "a-b")
        self.assertEqual(app.session.recover_partial(["a'c"], "c", "a"), "a'c")

    def test_clipped_words_of_different_lengths_are_still_ambiguous(self):
        app, _ = make_app(("mhor", "mhorr"))
        self.assertEqual(app.session.recover_partial(["mho"], "r", "m"), "")
        self.assertFalse(app.engine.used_words)

    def test_missing_keyboard_permission_exposes_enable_action(self):
        app, face = make_app()
        with patch.object(app_module, "keyboard_available", return_value=False), \
             patch.object(app_module, "request_keyboard_access") as request:
            app._toggle_arm()
            self.assertFalse(app.armed)
            self.assertEqual(face.values["ARMLABEL"], "ENABLE TYPING")
            self.assertIn("ACCESSIBILITY", face.values["STATUS"])
            request.assert_called_once()
        with patch.object(app_module, "keyboard_available", return_value=True):
            app._handle_frame(frame("s"))
        self.assertTrue(app.armed)
        self.assertFalse(app._input_problem)

    def test_new_game_changes_first_trap_without_crossing_source_tiers(self):
        traps = TrapPools(pro_3=["abc", "xyz", "def", "uvw"],
                          source_tiers={"pro:3": [["abc", "xyz"], ["def", "uvw"]]})
        engine = Dyoe2Engine(["aabc", "axyz", "adef", "auvw"], traps, validate_giveable=False)
        session = MatchSession(engine)
        before = engine.get_ordered_trap_tiers(3, casual=False)
        for _ in range(4):
            session.new_game()
            after = engine.get_ordered_trap_tiers(3, casual=False)
            for left, right in zip(before, after):
                self.assertEqual(set(left), set(right))
                self.assertNotEqual(left[0], right[0])
            before = after

    def test_pause_during_first_key_still_checks_partial_input_on_resume(self):
        app, _ = make_app()
        app.typing = True
        app._input_length = 0  # The first key can still be held by the OS.
        app._typing_prompt = "s"
        app._name = "player"
        app._toggle_pause()
        self.assertTrue(app._needs_clear)
        app._toggle_pause()
        with patch.object(app, "_clear_input") as clear:
            app._handle_frame(frame("st"))
            clear.assert_called_once_with("s")
        self.assertEqual(app._input_length, 1)

    def test_manual_confirmation_recovers_partial_input_without_two_clear_workers(self):
        app, _ = make_app()
        app._typing_prompt = "s"
        app._needs_clear = app._resume_clear = True
        app._last_frame = frame("stone")
        with patch.object(app_module.threading, "Thread") as thread:
            app._confirm_turn()
            app._confirm_turn()
            thread.return_value.start.assert_called_once()
        self.assertTrue(app._erasing)
        self.assertFalse(app._resume_clear)
        self.assertEqual(app._input_length, 4)


if __name__ == "__main__":
    unittest.main()
