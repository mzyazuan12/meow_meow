"""Opponent handoffs, genuine shuffles, and immediate complete prompt reads."""
from __future__ import annotations

import random
import unittest
from unittest.mock import patch

from autotype.featherine import turn_plan
from autotype.session import PARTIAL_PROMPT_HOLD, BoardWatch
from autotype.test_regressions import app_module, frame, make_app

TURN_STALL = app_module.TURN_STALL


class HandoffTests(unittest.TestCase):
    def app(self, words):
        app, face = make_app(words)
        app._name = "player"
        return app, face

    def test_size_is_a_clean_fragment_even_when_vmsize_was_clipped(self):
        app, _ = self.app(("vmsize", "zeuhl", "sizeable"))
        for seen in ("vms", "vmsi", "vmsiz", "vmsize"):
            with self.subTest(seen=seen):
                self.assertEqual(app.session.descramble_prompt("size", seen, "vm", [seen]), "")

    def test_clipped_vmsize_waits_for_ze_without_false_glitch_or_early_ranking(self):
        app, _ = self.app(("vmsize", "zeuhl", "zebra", "sizeable"))
        with patch.object(app, "_note") as note, patch.object(app, "_present", wraps=app._present) as present:
            for board in ("vm", "vmsi"):
                app._handle_frame(frame(board, "opponent"))
            for _ in range(4):
                app._handle_frame(frame("size"))
            app._start_typing.assert_not_called()
            present.assert_not_called()
            app._handle_frame(frame("ze"))
            app._handle_frame(frame("ze"))
            app._start_typing.assert_called_once_with("ze")
            logs = [c.args[0] for c in note.call_args_list]
        self.assertFalse(any("GLITCHED" in line for line in logs), logs)
        self.assertIn("vmsize", app.engine.used_words)
        self.assertEqual(app.session.opponent_word, "vmsize")
        app.watch.played = "ze"
        app._handle_frame(frame("ze"))
        self.assertEqual(app.session.opponent_word, "vmsize")
        self.assertLess(logs.index("THEIRS  vmsize"), next(i for i, line in enumerate(logs) if line.startswith("ze  →")))

    def test_opponent_frames_are_recorded_without_unglitching_them(self):
        app, _ = self.app(("vmsize", "zeuhl"))
        with patch.object(app, "_unglitch", wraps=app._unglitch) as unglitch:
            for board in ("vm", "vmsi", "size", "vmsize", "ze"):
                app._handle_frame(frame(board, "opponent"))
            unglitch.assert_not_called()
        self.assertEqual(app.watch.opponent_word, "vmsize")
        app._handle_frame(frame("ze"))
        app._start_typing.assert_called_once_with("ze")

    def test_transition_tail_does_not_replace_the_last_opponent_fragment(self):
        watch = BoardWatch()
        for board in ("vm", "vmsi", "size", "ze"):
            watch.observe(board, "theirs")
        self.assertEqual(watch.opponent_word, "vmsi")

    def test_final_word_on_first_our_frame_is_captured_before_correction(self):
        app, _ = self.app(("vmsize", "zeuhl"))
        for board in ("vm", "vmsi"):
            app._handle_frame(frame(board, "opponent"))
        contexts = []
        original = app._unglitch
        def inspect(board):
            contexts.append(app.watch.opponent_word)
            return original(board)
        with patch.object(app, "_unglitch", side_effect=inspect):
            app._handle_frame(frame("vmsize"))
        self.assertEqual(contexts, ["vmsize"])
        app._handle_frame(frame("ze"))
        app._start_typing.assert_called_once_with("ze")

    def test_a_used_zeuhl_is_excluded_before_ranking_the_new_prompt(self):
        app, face = self.app(("vmsize", "zeuhl", "zebra"))
        app.engine.mark_used("zeuhl")
        for board in ("vm", "vmsi"):
            app._handle_frame(frame(board, "opponent"))
        app._handle_frame(frame("ze"))
        app._handle_frame(frame("ze"))
        self.assertEqual(face.values["C1"], "1  zebra")
        self.assertEqual(app.session.choose("ze", resolve=False)[0], "zebra")

    def test_gnign_uses_kinging_and_starts_on_the_first_complete_capture(self):
        app, _ = self.app(("kinging", "ginger"))
        for board in ("king", "kingi", "kinging"):
            app._handle_frame(frame(board, "opponent"))
        with patch.object(app, "_note") as note:
            app._handle_frame(frame("gnign"))
        app._start_typing.assert_called_once_with("ging")
        self.assertIn("kinging", app.engine.used_words)
        self.assertIn("GLITCHED PROMPT  gnign → ging", [c.args[0] for c in note.call_args_list])

    def test_a_mirror_is_logged_as_a_mirror(self):
        app, _ = self.app(("capsulation", "tional"))
        for board in ("cap", "capsulation"):
            app._handle_frame(frame(board, "opponent"))
        with patch.object(app, "_note") as note:
            app._handle_frame(frame("noit"))
        self.assertIn("MIRRORED PROMPT  noit → tion", [c.args[0] for c in note.call_args_list])
        app._start_typing.assert_called_once_with("tion")

    def test_recovered_word_still_corrects_a_different_shuffle_after_it_is_marked_used(self):
        app, _ = self.app(("kinging", "ginger"))
        for board in ("king", "kingin"):
            app._handle_frame(frame(board, "opponent"))
        app._handle_frame(frame("gnign"))
        app._handle_frame(frame("gnign"))
        self.assertIn("kinging", app.engine.used_words)
        self.assertEqual(app.watch.opponent_word, "kinging")
        self.assertEqual(app._unglitch("gnigk"), "ging")

    def test_partial_tile_metadata_cannot_be_erased_by_a_glitch_fix(self):
        for flags in ({"tiles": 6}, {"row_complete": False}, {"full": False}):
            with self.subTest(flags=flags):
                app, _ = self.app(("kinging", "ginger"))
                for board in ("king", "kinging"):
                    app._handle_frame(frame(board, "opponent"))
                with patch.object(app, "_unglitch", wraps=app._unglitch) as unglitch:
                    for _ in range(3):
                        app._handle_frame(dict(frame("gnign"), **flags))
                    unglitch.assert_not_called()
                app._start_typing.assert_not_called()
                app._handle_frame(frame("gnign"))
                app._start_typing.assert_called_once_with("ging")

    def test_bil_waits_for_bils_even_if_partial_tiles_repeat_for_a_long_time(self):
        for floor in (3, 4):
            with self.subTest(floor=floor):
                watch = BoardWatch()
                watch.floor = floor
                watch.observe("gerbils"[:floor], "theirs", now=0)
                watch.observe("gerbils", "theirs", now=0.1)
                for now in (1.0, 1.02, 1.35, 1.6):
                    self.assertFalse(watch.observe("bil", "ours", now=now)["play"])
                self.assertEqual(watch.observe("bils", "ours", now=1.61)["play"], "bils")

    def test_a_letter_they_deleted_cannot_hold_our_prompt_forever(self):
        # They typed "elishas" and deleted the s before Enter, between two
        # captures. "sha" sits inside the remembered word, not at its end.
        watch = BoardWatch()
        watch.floor = 3
        watch.observe("eli", "theirs", now=0)
        watch.observe("elishas", "theirs", now=0.1)
        times = [1.0 + i * 0.05 for i in range(40)]
        played = [watch.observe("sha", "ours", now=now)["play"] for now in times]
        self.assertIn("sha", played)
        waited = times[played.index("sha")] - times[0]
        self.assertGreaterEqual(waited, PARTIAL_PROMPT_HOLD)
        self.assertLess(waited, PARTIAL_PROMPT_HOLD + 0.2)

    def test_a_prompt_left_on_our_turn_is_answered_though_one_letter_flickers(self):
        app, _ = self.app(("slate", "skate"))
        times = [100 + i * 0.05 for i in range(30)]
        reads = ["sla", "ska", "sla"] * 10
        fired = [app._turn_stalled(board, "ours", True, now) for board, now in zip(reads, times)]
        first = next(i for i, prompt in enumerate(fired) if prompt)
        self.assertEqual(fired[first], "sla")
        self.assertGreaterEqual(times[first] - times[0], TURN_STALL)
        app.typing = True
        self.assertEqual(app._turn_stalled("sla", "ours", True, 200), "")
        app.typing = False
        self.assertEqual(app._turn_stalled("sla", "ours", True, 201), "")

    def test_the_app_types_a_prompt_that_nothing_else_acted_on(self):
        app, _ = self.app(("slate",))
        clock = [100.0]
        blank = app.watch._blank
        with patch.object(app_module.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(app.watch, "observe", side_effect=lambda *args, **kwargs: blank()):
            for i in range(25):
                clock[0] = 100 + i * 0.05
                app._handle_frame(frame("sla"))
                if i * 0.05 < TURN_STALL - 0.05:
                    app._start_typing.assert_not_called()
        app._start_typing.assert_called_once_with("sla")

    def test_internal_transition_fragments_are_not_new_prompts(self):
        watch = BoardWatch()
        watch.observe("vm", "theirs", now=0)
        watch.observe("vmsize", "theirs", now=0.1)
        for index, board in enumerate(("size", "siz", "siz", "si", "si")):
            self.assertFalse(watch.observe(board, "ours", now=1 + index * 0.1)["play"])
        self.assertEqual(watch.observe("ze", "ours", now=1.6)["play"], "ze")

    def test_bils_does_not_rank_or_type_bil_at_the_app_level(self):
        app, _ = self.app(("gerbils", "bilberry", "bilsted"))
        for board in ("gerb", "gerbils"):
            app._handle_frame(frame(board, "opponent"))
        with patch.object(app, "_present", wraps=app._present) as present:
            for _ in range(4):
                app._handle_frame(frame("bil"))
            present.assert_not_called()
            app._start_typing.assert_not_called()
            app._handle_frame(frame("bils"))
            present.assert_called_once_with("bils")
        app._start_typing.assert_called_once_with("bils")

    def test_four_slots_with_only_three_read_letters_never_confirm(self):
        app, _ = self.app(("bilberry", "bilsted"))
        for _ in range(3):
            app._handle_frame(dict(frame("bil"), tiles=4))
        app._start_typing.assert_not_called()
        app._handle_frame(frame("bils"))
        app._handle_frame(frame("bils"))
        app._start_typing.assert_called_once_with("bils")

    def test_used_word_is_stored_before_choices_are_computed(self):
        app, _ = self.app(("telephone", "oneself"))
        for board in ("tel", "telephone"):
            app._handle_frame(frame(board, "opponent"))
        with patch.object(app, "_present", side_effect=lambda _: self.assertIn("telephone", app.engine.used_words)):
            app._handle_frame(frame("one"))
        app._start_typing.assert_called_once_with("one")


class ImmediateTypingTests(unittest.TestCase):
    def test_immediate_plans_start_the_answer_without_fidgets_or_a_pause(self):
        for seed in range(100):
            plan = turn_plan("ailism", "ism", 12, random.Random(seed).random, immediate=True)
            self.assertEqual(plan.fidgets, 0)
            first = plan.steps[0]
            self.assertEqual((first.kind, first.key, first.delay), ("type", "a", 0))
            self.assertEqual(plan.steps[-1].typed, "ailism")

    def test_live_app_requests_an_immediate_plan(self):
        app, _ = make_app(("bilsted",))
        app._start_typing = app_module.AutotypeApp._start_typing.__get__(app)
        with patch.object(app, "_launch_typing") as launch:
            app._start_typing("bils")
        plan = launch.call_args.args[2]
        self.assertEqual(plan.fidgets, 0)
        self.assertEqual((plan.steps[0].key, plan.steps[0].delay), ("t", 0))


if __name__ == "__main__":
    unittest.main()
