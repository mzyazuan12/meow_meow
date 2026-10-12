"""Recovery when captures lag the keys or the game refuses deletion."""
from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from autotype.test_regressions import app_module, frame, make_app


class InputRecoveryTests(unittest.TestCase):
    def test_clear_counts_visible_letters_instead_of_the_planned_answer(self):
        app, _ = make_app()
        app._typing_prompt = "s"
        app._typed_suffix = "upercalifragilistic"
        app._input_length = 8  # Older than the now-complete capture.
        app._last_frame = frame("st")
        with patch.object(app, "_erase_suffix") as erase:
            app._clear_input("s")
        self.assertEqual(erase.call_args.args[2], 1)

    def test_unreadable_clear_uses_sent_letters_instead_of_planned_letters(self):
        app, _ = make_app()
        app._typed_suffix = "upercalifragilistic"
        app._input_length = 2
        app._last_frame = frame("s???", full=False)
        with patch.object(app, "_erase_suffix") as erase:
            app._clear_input("s")
        self.assertEqual(erase.call_args.args[2], 2)

    def test_unchanged_short_row_releases_deletion_and_answers_the_real_prompt(self):
        app, _ = make_app(("stone", "star"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "s"
        app._last_frame = frame("st")
        with patch.object(app, "_erase_suffix") as erase:
            app._clear_input("s")
            for _ in range(8):
                app._process_event("ERASED", (app._gen, "s", True))
                if not app._clear:
                    break
                after = app._clear["after"]
                for offset in (0.8, 0.9):
                    app._check_clear(dict(frame("st"), captured_at=after + offset), "ours", after + offset)
        self.assertLessEqual(erase.call_count, 3)
        self.assertIsNone(app._clear)
        self.assertFalse(app._needs_clear)
        self.assertFalse(app._erasing)
        app._start_typing.assert_called_once_with("st")

    def test_unchanged_long_row_resumes_by_editing_the_visible_input(self):
        app, _ = make_app(("stone", "stones"))
        app._typing_prompt = app.watch.played = "s"
        app._last_frame = frame("stone")
        with patch.object(app, "_erase_suffix") as erase, patch.object(app, "_launch_typing") as launch:
            app._clear_input("s", word="stones")
            for _ in range(8):
                app._process_event("ERASED", (app._gen, "s", True))
                if not app._clear:
                    break
                after = app._clear["after"]
                for offset in (0.8, 0.9):
                    app._check_clear(dict(frame("stone"), captured_at=after + offset), "ours", after + offset)
        self.assertLessEqual(erase.call_count, 3)
        self.assertIsNone(app._clear)
        self.assertFalse(app._erasing)
        prompt, word, plan = launch.call_args.args
        self.assertEqual((prompt, word, launch.call_args.kwargs["start"]), ("s", "stones", "tone"))
        self.assertEqual([s.kind for s in plan.steps], ["type", "enter"])

    def test_deletion_waits_for_captures_after_the_key_echo_delay(self):
        app, _ = make_app()
        app._last_frame = frame("stone")
        with patch.object(app, "_erase_suffix") as erase:
            app._clear_input("s")
            app._process_event("ERASED", (app._gen, "s", True))
            after = app._clear["after"]
            for offset in (0.01, 0.02, 0.03):
                app._check_clear(dict(frame("stone"), captured_at=after + offset), "ours", after + 1)
        erase.assert_called_once()

    def test_a_short_row_that_is_still_shrinking_remains_input(self):
        app, _ = make_app(("stone",))
        app._typing_prompt = app.watch.played = "s"
        state = dict(prompt="s", word="stone", unchanged=0, passes=3)
        app._clear = state
        app._erasing = app._needs_clear = True
        with patch.object(app, "_launch_typing") as launch:
            app._continue_clear(state, "st", time.monotonic())
        prompt, word, plan = launch.call_args.args
        self.assertEqual((prompt, word, launch.call_args.kwargs["start"]), ("s", "stone", "t"))
        self.assertEqual([s.key for s in plan.steps if s.kind == "type"], list("one"))
        app._start_typing.assert_not_called()

    def test_old_own_keystrokes_do_not_become_a_longer_prompt(self):
        app, _ = make_app(("stone", "stork", "stop"))
        app.typing = True
        app._typing_prompt = app.watch.played = "s"
        app._keys_now = "o"
        app._keys_sent = "too"
        now = time.monotonic()
        app._key_log.extend(((now - .3, "t"), (now - .2, "to"), (now - .1, "t"), (now, "o")))
        with patch.object(app, "_restart_for") as restart:
            for _ in range(3):
                self.assertFalse(app._watch_own_keys("sto", frame("sto")))
        restart.assert_not_called()
        self.assertEqual(app._typing_prompt, "s")

    def test_one_capture_cannot_confirm_a_new_prompt_twice(self):
        app, _ = make_app(("leech", "leetle"))
        app._typing_prompt = app.watch.played = "lee"
        app._keys_now = app._keys_sent = "ch"
        capture = frame("leetch")
        with patch.object(app, "_restart_for") as restart:
            self.assertFalse(app._watch_own_keys("leetch", capture))
            self.assertFalse(app._watch_own_keys("leetch", capture))
            self.assertTrue(app._watch_own_keys("leetch", frame("leetch")))
        restart.assert_called_once_with("leet", "leetch")

    def test_cancelling_a_correction_stops_all_remaining_keys(self):
        for shown, target in (("wrong", "right"), ("", "stone")):
            with self.subTest(shown=shown):
                app, _ = make_app()
                keys = []

                def tap(kind, key, hold):
                    keys.append(kind)
                    app._cancel_typing()

                with patch.object(app_module, "tap_key", side_effect=tap):
                    result = app._finish_suffix(shown, target)
                self.assertIsNone(result)
                self.assertEqual(len(keys), 1)

    def test_an_old_worker_cannot_start_a_correction_after_cancellation(self):
        app, _ = make_app()
        gen, cancel = app._gen, app._type_cancel
        app._cancel_typing()
        with patch.object(app_module, "tap_key") as tap:
            self.assertIsNone(app._finish_suffix("wrong", "right", gen=gen, cancel=cancel))
        tap.assert_not_called()

    def test_losing_focus_stops_a_correction_before_the_next_key(self):
        app, _ = make_app()
        with patch.object(app_module, "roblox_focused", side_effect=(True, True, False)), \
             patch.object(app_module, "tap_key") as tap:
            self.assertIsNone(app._finish_suffix("wrong", "right"))
        tap.assert_called_once()


if __name__ == "__main__":
    unittest.main()
