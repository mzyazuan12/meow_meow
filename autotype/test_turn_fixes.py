"""Trap choice, turn clock, refusals and Enter timing."""
from __future__ import annotations

import random
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from autotype.featherine import edit_plan, plan_duration, turn_plan
from autotype.session import MatchSession, max_suffix_for
from autotype.test_regressions import app_module, frame, make_app
from autotype.timer import TurnClock, read_alert, read_clock
from dyoe2_engine import Dyoe2Engine, TrapPools

FIXTURES = Path(__file__).parent / "fixtures"


def session(words, **pools):
    engine = Dyoe2Engine(words, TrapPools(**pools), validate_giveable=False)
    engine.cancelled_prompts.clear()
    return MatchSession(engine)


class TrapChoiceTests(unittest.TestCase):
    def test_a_prefix_is_never_handed_over_more_times_than_it_has_solves(self):
        s = session(["preols", "preaols", "prebols", "prexabc", "preyabc", "prefoobar", "olsa", "olsb",
                     "abca", "abcb", "abcc"], casual_3=["ols", "abc"])
        # ols has two solves, abc three: fewest first.
        played = []
        for _ in range(5):
            word = s.choose("pre")[0]
            played.append(word)
            s.commit_play(word, "pre")
        self.assertTrue(played[0].endswith("ols"))
        self.assertEqual(played[-1], "prefoobar")
        # Giving ols again lowers it below abc, then two hand-overs exhaust it.
        self.assertEqual(played[1][-3:], "abc")
        self.assertEqual(sum(word.endswith("ols") for word in played), 2)
        self.assertEqual(s.given["ols"], 2)

    def test_a_trap_that_is_itself_an_unused_word_is_not_a_trap(self):
        s = session(["preols", "prexyz", "ols", "olsa", "xyza", "xyzb", "xyzc"], casual_3=["ols", "xyz"])
        self.assertEqual(s.choose("pre")[0], "prexyz")
        s.engine.mark_used("ols")
        self.assertEqual(s.choose("pre")[0], "preols")

    def test_pro_ranks_punctuation_traps_higher_and_never_uses_edge_punctuation(self):
        words = ["prea-b", "prexyz", "pre-ab", "preab-", "a-bc", "a-bd", "a-be",
                 "xyza", "xyzb", "-abx", "ab-x"]
        pools = {"casual_3": ["a-b", "xyz", "-ab", "ab-"], "pro_3": ["a-b", "xyz", "-ab", "ab-"]}
        s = session(words, **pools)
        s.set_mode("pro")
        self.assertEqual(s.choose("pre")[0], "prea-b")
        self.assertEqual(s._trap_pool(3).keys(), {"a-b", "xyz"})
        s.set_mode("casual")
        self.assertEqual(s.choose("pre")[0], "prexyz")

    def test_equal_solve_counts_prefer_the_trap_with_longer_solves(self):
        s = session(["preabc", "prexyz", "abcd", "xyzlongword"], casual_3=["abc", "xyz"])
        self.assertEqual(s.choose("pre")[0], "prexyz")

    def test_opponents_real_prompt_replaces_the_assumed_one(self):
        s = session(["abtone", "neat", "oneself"], casual_2=["ne"], casual_3=["one"])
        s.commit_play("abtone", "ab")
        self.assertEqual(s.given, {"ne": 1})
        s.note_given("one")
        self.assertEqual(s.given, {"ne": 0, "one": 1})
        s.note_given("ne")
        self.assertEqual(s.given, {"ne": 0, "one": 1})
        s.new_game()
        self.assertEqual(s.given, {})

    def test_short_clock_caps_answer_length_and_phase_one_limits_long_words(self):
        self.assertEqual(max_suffix_for(None, 3), 30)
        self.assertEqual(max_suffix_for(None, 1), 14)
        self.assertEqual(max_suffix_for(3.0, 3), 11)
        self.assertEqual(max_suffix_for(0.5, 3), 2)
        s = session(["preabcdefghijklmnxyz", "prest", "xyza"], casual_3=["xyz"])
        self.assertEqual(s.choose("pre")[0], "preabcdefghijklmnxyz")
        self.assertEqual(s.choose("pre", 2.5)[0], "prest")
        s = session(["a" + "b" * 20, "abcd"])
        self.assertEqual(s.choose("a")[0], "abcd")

    def test_spam_is_dyoe2_hybrid_endings_in_order_shortest_first_then_traps(self):
        s = session(["pring", "prinking", "pred", "prexyz", "prolong", "xyza"], casual_3=["xyz"])
        s.set_spam_suffixes("ing, ed")
        s.set_mode("spam")
        self.assertEqual(s.choices("pr", 5), ["pring", "prinking", "pred", "prexyz", "prolong"])
        self.assertEqual(s._choice_traps["pring"], "ing")
        self.assertEqual(s._choice_traps["prexyz"], "xyz")

    def test_refused_answer_moves_to_the_fewest_key_alternative(self):
        s = session(["ismailisms", "ismailism", "isms", "inestimableness", "inestimable", "inessive"])
        s.engine.mark_used("ismailisms")
        self.assertEqual(s.alternative("ism", "ismailisms"), ("ismailism", 1, ""))
        s.engine.mark_used("inestimableness")
        self.assertEqual(s.alternative("ines", "inestimableness"), ("inestimable", 4, ""))


class PlanTests(unittest.TestCase):
    def spell(self, plan):
        shown = ""
        for step in plan.steps:
            if step.kind == "type":
                shown += step.key
            elif step.kind == "back":
                shown = shown[:-1]
            self.assertEqual(shown, step.typed)
        return shown

    def test_human_turns_are_varied_correct_and_end_with_an_immediate_enter(self):
        fidgets = typos = 0
        for seed in range(300):
            plan = turn_plan("ailism", "ism", 12, random.Random(seed).random, lambda w: False)
            self.assertEqual(self.spell(plan), "ailism")
            self.assertEqual(plan.steps[-1].kind, "enter")
            self.assertLessEqual(plan.steps[-1].delay, 0.05)
            # A fidget erases back to the bare prompt; a typo never does.
            fidget = any(s.kind == "back" and not s.typed for s in plan.steps)
            fidgets += fidget
            typos += not fidget and any(s.kind == "type" and not "ailism".startswith(s.typed)
                                        for s in plan.steps)
            gaps = [s.delay for s in plan.steps[1:] if s.kind == "type"]
            self.assertGreaterEqual(min(gaps), 0.055)
        self.assertTrue(35 < fidgets < 110, fidgets)
        self.assertTrue(30 < typos < 100, typos)

    def test_no_fidget_or_typo_when_time_is_short_and_the_plan_fits(self):
        for seed in range(100):
            plan = turn_plan("ailism", "ism", 1.2, random.Random(seed).random)
            self.assertLessEqual(plan_duration(plan.steps), 1.25)
            self.assertEqual([s.kind for s in plan.steps], ["type"] * 6 + ["enter"])

    def test_edit_plan_deletes_only_the_difference(self):
        plan = edit_plan("timableness", "timable", 5, random.Random(0).random)
        self.assertEqual([s.kind for s in plan.steps], ["back"] * 4 + ["enter"])
        self.assertEqual(plan.steps[-1].typed, "timable")


class ClockTests(unittest.TestCase):
    def scaled(self, name, width):
        with Image.open(FIXTURES / name) as source:
            image = source.convert("RGB")
        return np.asarray(image.resize((width, round(image.height * width / image.width)), Image.LANCZOS))

    def test_clock_arc_digits_and_banner_from_screenshots(self):
        for width in (1024, 1600):
            accepted = self.scaled("accepted_clock.jpg", width)
            used = self.scaled("already_used.jpg", width)
            self.assertAlmostEqual(read_clock(accepted)["timer_frac"], 13.2 / 15, delta=0.03)
            self.assertAlmostEqual(read_clock(used)["timer_frac"], 11.1 / 15, delta=0.03)
            self.assertFalse(read_alert(accepted))
            self.assertTrue(read_alert(used))
        for width in (960, 1600):
            turn = read_clock(self.scaled("fullscreen_turn.png", width))
            self.assertEqual(turn["timer"], 9.7)
            self.assertAlmostEqual(turn["timer_frac"], 9.7 / 15, delta=0.03)
            self.assertFalse(read_alert(self.scaled("fullscreen_turn.png", width)))
        # A clock cut off by the window edge is not read at all.
        self.assertEqual(read_clock(self.scaled("top_edge_q.png", 924)), {"timer": None, "timer_frac": None})

    def test_yellow_low_time_digits(self):
        with Image.open(FIXTURES / "yellow_clock.png") as source:
            clock = source.convert("RGB").resize((100, 86), Image.LANCZOS)
        canvas = Image.new("RGB", (1024, 540), (230, 30, 40))
        canvas.paste(clock, (462, 370))
        self.assertEqual(read_clock(np.asarray(canvas))["timer"], 7.1)

    def test_turn_clock_learns_the_stage_from_the_shrinking_arc(self):
        clock = TurnClock()
        for i in range(8):
            clock.observe(None, 1.0 - i * 0.02, 100 + i * 0.1)
        self.assertEqual(clock.total, 5.0)
        self.assertAlmostEqual(clock.remaining(100.7), 0.86 * 5, delta=0.05)
        clock.start_turn(200)
        self.assertAlmostEqual(clock.remaining(203), 2.0, delta=0.01)
        clock.observe(3.0, None, 205)
        self.assertAlmostEqual(clock.remaining(205.5), 2.5, delta=0.01)


class AppTurnTests(unittest.TestCase):
    def test_typing_budget_and_answer_follow_the_turn_clock(self):
        app, _ = make_app(("preabcdefghijklmnopqrstuvwxyz", "prest"))
        app._start_typing = app_module.AutotypeApp._start_typing.__get__(app)
        budgets = []
        with patch.object(app, "_time_left", return_value=3.0), \
             patch.object(app_module, "turn_plan", side_effect=lambda s, p, b, is_word=None: budgets.append((s, b))
                          or edit_plan("", s)), \
             patch.object(app, "_launch_typing"):
            app._start_typing("pre")
        self.assertEqual(budgets, [("st", 3.0 - app_module.SUBMIT_MARGIN)])

    def test_opponents_starting_prompt_is_recorded_as_given(self):
        app, _ = make_app(("abtone", "oneself", "neat"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "ab"
        with patch.object(app_module, "press_enter"):
            app._process_event("SUBMIT", (app._gen, "abtone", 4))
        app._handle_frame(frame("one", "opponent"))
        self.assertIn("abtone", app.engine.used_words)
        self.assertEqual(app.session.given.get("one"), 1)
        self.assertFalse(app.session.given.get("ne"))

    def test_a_word_entered_by_hand_on_our_turn_is_stored(self):
        app, _ = make_app(("stone", "star"))
        app._name = "player"
        app._handle_frame(frame("s"))
        app._handle_frame(frame("s"))
        app._handle_frame(frame("stone"))
        app._handle_frame(frame("ne", "opponent"))
        self.assertIn("stone", app.engine.used_words)


if __name__ == "__main__":
    unittest.main()
