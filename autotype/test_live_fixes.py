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

from autotype.featherine import AutotypePlan, AutotypeStep, human_plan
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
    def test_replaying_one_capture_cannot_trigger_enter(self):
        app, _ = make_app(("stone",))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app._process_event("SUBMIT", (app._gen, "stone", 4))
        reading = frame("stone")
        reading["captured_at"] = time.monotonic()
        with patch.object(app_module, "press_enter") as enter, patch.object(app_module, "roblox_focused", return_value=True):
            for _ in range(4):
                app._handle_frame(reading)
            enter.assert_not_called()
            reading = dict(reading, captured_at=time.monotonic())
            app._handle_frame(reading)
            enter.assert_called_once()

    def test_changing_unknown_tiles_can_confirm_every_letter_without_stalling(self):
        app, _ = make_app(("ecaboron",))
        app._name = "player"
        app._typing_prompt = app.watch.played = "e"
        app._process_event("SUBMIT", (app._gen, "ecaboron", 7))
        with patch.object(app_module, "press_enter") as enter, patch.object(app_module, "roblox_focused", return_value=True):
            for board in ("e?aboron", "ec?boron", "e?aboron"):
                app._handle_frame(frame(board, full=False))
                enter.assert_not_called()
            app._handle_frame(frame("ec?boron", full=False))
            enter.assert_called_once()
            self.assertEqual(app.watch.typed, "ecaboron")

    def test_a_clipped_row_cannot_confirm_the_word_even_if_its_visible_letters_match(self):
        app, _ = make_app(("stone",))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app._process_event("SUBMIT", (app._gen, "stone", 4))
        with patch.object(app_module, "press_enter") as enter:
            for _ in range(3):
                app._handle_frame(dict(frame("stone", full=False), row_complete=False))
            enter.assert_not_called()

    def test_missed_enter_retries_without_retyping_the_word(self):
        app, _ = make_app(("stone",))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app.watch.pending = app.watch.typed = app._typed_word = "stone"
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
        with patch.object(app, "_clear_input") as clear, patch.object(app_module, "press_enter") as enter:
            app._handle_frame(frame("stone"))
            app._handle_frame(frame("stone"))
            clear.assert_called_once_with("s")
            enter.assert_not_called()
        self.assertEqual(app.session.choose("s")[0], "star")
        self.assertFalse(app.engine.used_words)
        self.assertTrue(app.armed)

    def test_a_rejected_reset_to_the_original_prefix_retries(self):
        app, _ = make_app(("stone", "star"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app.watch.pending = app.watch.typed = app._typed_word = "stone"
        with patch.object(app, "_clear_input") as clear:
            app._handle_frame(frame("s"))
            clear.assert_not_called()
            app._handle_frame(frame("s"))
            clear.assert_called_once_with("s")
        self.assertIn("stone", app.engine.rejected_words)
        self.assertNotIn("stone", app.engine.used_words)

    def test_unreadable_long_word_is_preserved_until_readable(self):
        word = "electroencephalographically"
        app, _ = make_app((word, "enter", "equal"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "e"
        app._typed_suffix = word[1:]
        app._process_event("SUBMIT", (app._gen, word, len(word) - 1, time.monotonic() - 2))
        with patch.object(app, "_clear_input") as clear, patch.object(app_module, "press_enter") as enter:
            app._handle_frame(frame("electro?????", full=False))
            clear.assert_not_called()
            enter.assert_not_called()
        self.assertEqual(app._verify[1], word)
        self.assertNotIn(word, app.session.unreadable_words)
        self.assertNotIn(word, app.engine.rejected_words)
        app.session.new_game()
        self.assertFalse(app.session.unreadable_words)

    def test_enter_requires_two_fresh_complete_readings_of_exact_word(self):
        app, _ = make_app(("ecaboron",))
        app._name = "player"
        app._typing_prompt = "e"
        app.watch.played = "e"
        app._current_turn = "ours"
        with patch.object(app_module, "press_enter") as enter, patch.object(app_module, "roblox_focused", return_value=True):
            app._process_event("SUBMIT", (app._gen, "ecaboron", 7))
            enter.assert_not_called()
            before = app._verify[3] - 1
            stale = frame("ecaboron"); stale["captured_at"] = before
            app._handle_frame(stale); app._handle_frame(stale)
            app._handle_frame(frame("ecabor?n", full=False))
            enter.assert_not_called()
            app._handle_frame(frame("ecaboron"))
            enter.assert_not_called()
            app._handle_frame(frame("ecaboron"))
            enter.assert_called_once()
            self.assertEqual(app.watch.typed, "ecaboron")
            self.assertFalse(app.engine.used_words)
            app._handle_frame(frame("n", "opponent"))
            self.assertEqual(app.engine.used_words, {"ecaboron"})

    def test_own_growing_input_never_restarts_as_a_longer_prefix(self):
        app, _ = make_app()
        app._name = "player"
        app.typing = True
        app._typing_prompt = app.watch.played = "s"
        for board in ("st", "sto", "ston", "stone"):
            app._handle_frame(frame(board))
        app._start_typing.assert_not_called()
        self.assertTrue(app.typing)

    def test_a_dropped_backspace_is_repaired_before_final_enter(self):
        app, _ = make_app(("ecaboron",))
        app._start_typing = app_module.AutotypeApp._start_typing.__get__(app)
        app._name = "player"
        app._current_turn = "ours"
        board = ["e"]
        entered = []
        dropped = [False]
        lock = threading.Lock()
        # Duplicate the second suffix letter, then miss its first correction.
        steps = [AutotypeStep("c", 0, "type", "c"),
                 AutotypeStep("ca", .04, "type", "a"),
                 AutotypeStep("caa", .04, "type", "a"),
                 AutotypeStep("ca", .04, "back", "a")]
        shown = "ca"
        for char in "boron":
            shown += char
            steps.append(AutotypeStep(shown, .04, "type", char))
        plan = AutotypePlan("caboron", True, "human", 1, steps, .035)
        def key(kind, ch, hold):
            with lock:
                if kind == "back":
                    if not dropped[0]:
                        dropped[0] = True
                    elif len(board[0]) > 1:
                        board[0] = board[0][:-1]
                else:
                    board[0] += ch
        def enter():
            with lock:
                entered.append(board[0])
        with patch.object(app_module, "human_plan", return_value=plan), \
             patch.object(app_module, "focus_roblox", return_value=True), \
             patch.object(app_module, "roblox_focused", return_value=True), \
             patch.object(app_module, "tap_key", side_effect=key), \
             patch.object(app_module, "press_enter", side_effect=enter):
            app._start_typing("e")
            deadline = time.monotonic() + 4
            while not entered and time.monotonic() < deadline:
                while not app._queue.empty():
                    app._process_event(*app._queue.get_nowait())
                with lock:
                    reading = frame(board[0])
                reading["captured_at"] = time.monotonic()
                app._handle_frame(reading)
                time.sleep(.012)
            app._type_cancel.set()
            if app._typing_thread:
                app._typing_thread.join(timeout=1)
        self.assertTrue(dropped[0])
        self.assertEqual(entered, ["ecaboron"])
        self.assertEqual(app._verify_repairs, 1)

    def test_dropped_deletions_do_not_append_another_long_word(self):
        word = "electroencephalographically"
        app, _ = make_app((word,))
        app._start_typing = app_module.AutotypeApp._start_typing.__get__(app)
        app._name = "player"
        app._current_turn = "ours"
        board = ["e"]
        entered, repair_starts = [], []
        dropped = [False]
        lock = threading.Lock()
        steps = []
        shown = ""
        # A dropped correction duplicates the first suffix letter.
        for kind, char in [("type", "l"), ("type", "l"), ("back", "l")] + [("type", c) for c in word[2:]]:
            shown = shown[:-1] if kind == "back" else shown + char
            steps.append(AutotypeStep(shown, 0, kind, char))
        plan = AutotypePlan(word[1:], True, "human", 1, steps, 0)
        def key(kind, char, hold):
            with lock:
                if kind == "back":
                    # Drop the planned correction AND the first clear key.
                    if not dropped[0] or (app._clear and not dropped[1]):
                        if not dropped[0]:
                            dropped[0] = True
                            dropped.append(False)
                        else:
                            dropped[1] = True
                        return
                    if len(board[0]) > 1:
                        board[0] = board[0][:-1]
                else:
                    if char == "l" and app._verify_repairs and len(board[0]) <= 2:
                        repair_starts.append(board[0])
                    board[0] += char
        with patch.object(app_module, "human_plan", return_value=plan), \
             patch.object(app_module, "focus_roblox", return_value=True), \
             patch.object(app_module, "roblox_focused", return_value=True), \
             patch.object(app_module, "tap_key", side_effect=key), \
             patch.object(app_module, "press_enter", side_effect=lambda: entered.append(board[0])):
            app._start_typing("e")
            deadline = time.monotonic() + 6
            try:
                while not entered and time.monotonic() < deadline:
                    while not app._queue.empty():
                        app._process_event(*app._queue.get_nowait())
                    with lock:
                        reading = frame(board[0])
                    app._handle_frame(reading)
                    time.sleep(.008)
            finally:
                app._type_cancel.set()
                if app._typing_thread:
                    app._typing_thread.join(timeout=1)
        self.assertEqual(dropped, [True, True])
        self.assertEqual(repair_starts, ["e"])
        self.assertEqual(entered, [word])
        self.assertTrue(app.armed)

    def test_early_enter_is_optional_and_capped_and_valid_trial_is_blocked(self):
        trial_counts = []
        for seed in range(100):
            plan = human_plan("nesslerising", "player", random.Random(seed).random)
            trial_counts.append(sum(step.kind == "enter" for step in plan.steps))
        self.assertGreater(sum(trial_counts), 0)
        self.assertGreater(trial_counts.count(0), 70)
        self.assertLessEqual(max(trial_counts), 2)
        app, _ = make_app(("stone",))
        app._name = "player"
        app.typing = True
        with patch.object(app_module, "press_enter") as enter, patch.object(app_module, "roblox_focused", return_value=True):
            signal = threading.Event()
            app._process_event("TRIAL", (app._gen, "stone", signal, time.monotonic()))
            app._handle_frame(frame("stone"))
            enter.assert_not_called()
            for _ in range(4):
                signal = threading.Event()
                app._process_event("TRIAL", (app._gen, "stovne", signal, time.monotonic()))
                app._handle_frame(frame("stovne"))
            self.assertEqual(enter.call_count, 1)
            self.assertEqual(app._trial_count, 1)
            self.assertFalse(app.engine.used_words)


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
        app._process_event("SUBMIT", (old_gen, "likeness", 4))
        self.assertEqual(app.watch.played, "ism")
        self.assertFalse(app._aborted_prompt)
        self.assertIsNone(app._verify)

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
        app._process_event("SUBMIT", (app._gen, "star", 3))
        gen = app._gen
        # Cancellation takes effect before the queued native action is drained.
        app._put_event("ACTION", ("PAUSE", ""))
        self.assertTrue(cancel.is_set())
        app._process_event(*app._queue.get_nowait())
        self.assertTrue(app._paused.is_set())
        self.assertIsNone(app._verify)
        self.assertEqual(face.values["PAUSELABEL"], "RESUME")
        with patch.object(app_module, "press_enter") as enter:
            app._process_event("SUBMIT", (gen, "star", 3))
            app._handle_frame(frame("star"))
            enter.assert_not_called()
        self.assertEqual(app.engine.used_words, {"stone"})
        app._toggle_pause()
        self.assertFalse(app._paused.is_set())
        self.assertEqual(app.engine.used_words, {"stone"})
        app._new_game()
        self.assertFalse(app.engine.used_words)

    def test_phase_follows_actual_prefix_and_late_game_uses_all_trap_lengths(self):
        traps = TrapPools(casual_2=["xy"], casual_3=["zzz"], casual_4=["tone"])
        engine = Dyoe2Engine(["atone", "axy", "azzz", "aaaaaaaaaa"], traps, validate_giveable=False)
        engine.cancelled_prompts.clear()
        session = MatchSession(engine)
        session.round = 100
        self.assertEqual(phase_for_prompt(100, "abc"), 3)
        self.assertEqual(session.prepare("a"), 1)
        self.assertEqual(session.choose("a")[0], "azzz")
        for i in range(6):
            engine.mark_used(f"previous{i}")
        self.assertEqual(session.prepare("a"), 1)
        self.assertEqual(engine.trap_phases, (4, 3, 2))
        self.assertEqual(session.choose("a")[0], "atone")
        self.assertEqual(session.prepare("abc"), 3)
        self.assertEqual(session.prepare("abcd"), 4)
        self.assertEqual(engine.trap_phases, ())
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
