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


class DynamicTrapTests(unittest.TestCase):
    def test_a_trap_is_found_from_the_dictionary_without_any_list(self):
        s = session(["preqzk", "prefoobar", "qzkaaaaaaa"])  # no trap lists at all
        self.assertEqual(s.choose("pre")[0], "preqzk")
        self.assertEqual(s._choice_traps["preqzk"], "qzk")

    def test_few_and_long_beats_many_and_short(self):
        words = ["preabc", "prexyz", "abcd", "abce", "abcf", "abcg", "xyzqqqqqqqq"]
        s = session(words)
        self.assertEqual(s.choose("pre")[0], "prexyz")

    def test_a_blacklisted_ending_is_never_a_trap(self):
        s = session(["prebj", "bjaaaaaaaa", "prexyq", "xyqaa"])
        self.assertEqual(s.choose("pre")[0], "prexyq")
        self.assertNotIn("bj", s._choice_traps.values())

    def test_every_new_game_rolls_a_different_style_and_stays_deadly(self):
        words = [f"pre{a}{b}{c}" for a in "klmnpqrstvz" for b in "aeiouy" for c in "bdfgkx"]
        words += [f"{a}{b}{c}" + "t" * n for a in "klmnpqrstvz" for b in "aeiouy" for c in "bdfgkx"
                  for n in (2, 5)]
        s = session(words)
        seen, firsts = set(), set()
        for _ in range(10):
            s.new_game()
            seen.add(s.style.signature)
            word = s.choose("pre")[0]
            firsts.add(word)
            trap = s._choice_traps.get(word)
            self.assertTrue(trap, word)
            remaining = [w for w in s.engine.prefix_candidates(trap) if w != word]
            self.assertLessEqual(len(remaining), 2, (word, trap))
        self.assertGreater(len(seen), 4)
        self.assertGreater(len(firsts), 1)

    def test_search_does_not_disturb_the_live_turn(self):
        s = session(["stone", "stoke", "stow"])
        s.last_prefix, s.last_word = "xx", "xxyy"
        found = s.search("st")
        self.assertEqual(found["prefix"], "st")
        self.assertEqual(set(found["words"]), {"stone", "stoke", "stow"})
        self.assertEqual((s.last_prefix, s.last_word), ("xx", "xxyy"))
        self.assertIsNone(s.search("   "))


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

    def test_casual_never_types_a_hyphen_or_an_apostrophe(self):
        words = ["prea-b", "preab's", "prexyz", "a-bc", "ab'sx"]
        s = session(words, casual_3=["a-b", "xyz"], pro_3=["a-b", "xyz"])
        s.set_mode("casual")
        picked = s.choices("pre", 12)
        self.assertEqual(picked, ["prexyz"])
        self.assertTrue(all("-" not in word and "'" not in word for word in picked))
        only = session(["prea-b", "preab's"])
        only.set_mode("casual")
        self.assertEqual(only.choose("pre")[0], "")
        only.set_mode("pro")
        self.assertTrue(any(mark in only.choose("pre")[0] for mark in "-'"))

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

    def test_spam_tries_the_typed_endings_first_then_deadly_traps(self):
        s = session(["xpring", "xprinking", "xpred", "xprexyz", "xprolong", "xyzaa"],
                    casual_3=["xyz"])
        s.set_spam_suffixes("ing, ed")
        s.set_mode("spam")
        self.assertEqual(s.choices("xpr", 5)[:4], ["xpring", "xprinking", "xpred", "xprexyz"])
        self.assertEqual(s._choice_traps["xpring"], "ing")
        self.assertEqual(s._choice_traps["xprexyz"], "xyz")
        # "ing" on a 2-letter prompt hands "ng", which is blacklisted.
        blocked = session(["pring", "prsafeq", "safeqaa"])
        blocked.set_spam_suffixes("ing")
        blocked.set_mode("spam")
        self.assertNotIn("pring", blocked.choices("pr", 5))
        self.assertEqual(blocked.choose("pr")[0], "prsafeq")

    def test_spam_follows_casual_or_pro_under_the_typed_endings(self):
        s = session(["preing", "prea-b", "a-bc", "a-bd"])
        s.set_spam_suffixes("ing")
        s.set_mode("spam")
        s.set_spam_base("casual")
        self.assertEqual(s.choose("pre")[0], "preing")
        s.set_spam_suffixes("")
        s.set_spam_base("casual")
        self.assertNotIn("-", s.choose("pre")[0])
        s.set_spam_base("pro")
        self.assertIn("-", s.choose("pre")[0])

    def test_a_blacklisted_ending_is_never_handed_over(self):
        s = session(["spark", "spaqz", "rkaaaaaa", "qzaaaaaaaa"])
        self.assertEqual(s.choose("sp")[0], "spaqz")
        self.assertNotIn("rk", {word[-2:] for word in s.choices("sp", 12)})
        doubled = session(["starr", "stazz", "rraaaaaa", "azzaaaaa"])
        self.assertEqual(doubled.choose("st")[0], "stazz")
        self.assertNotIn("rr", {word[-2:] for word in doubled.choices("st", 12)})
        longer = session(["xxxxtion", "xxxxqzkz", "tionaaaa", "qzkzaaaa"])
        self.assertEqual(longer.choose("xxxx")[0], "xxxxqzkz")

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

    def _fidget_bursts(self, plan):
        return sum(1 for s in plan.steps if s.kind == "back" and not s.typed)

    def _suffix_gaps(self, plan, suffix):
        gaps = [None] * len(suffix)
        for step in plan.steps:
            if step.kind == "type" and step.typed and suffix.startswith(step.typed):
                gaps[len(step.typed) - 1] = step.delay
        return gaps

    def _clean_gaps(self, plan, suffix):
        """Gaps of the letters of a turn with nothing but the word in it."""
        if any(s.kind in ("back", "early") for s in plan.steps):
            return None
        return [s.delay for s in plan.steps if s.kind == "type"][1:]

    def test_human_turns_are_varied_correct_and_end_with_an_immediate_enter(self):
        paces, spreads, steady, styles = [], [], 0, set()
        end_enters = mistakes = clean = 0
        for seed in range(600):
            plan = turn_plan("ailism", "ism", 12, random.Random(seed).random, lambda w: False)
            self.assertEqual(self.spell(plan), "ailism")
            self.assertEqual(plan.steps[-1].kind, "enter")
            self.assertEqual(sum(s.kind == "enter" for s in plan.steps), 1)
            self.assertLessEqual(plan.steps[-1].delay, 0.05)
            self.assertLessEqual(plan.fidgets, 3)
            end_enters += any(s.kind == "early" and s.typed and not "ailism".startswith(s.typed)
                              for s in plan.steps)
            mistakes += plan.mistakes > 0
            clean += plan.mistakes == 0
            gaps = self._clean_gaps(plan, "ailism")
            if gaps is None or plan.fidgets:
                continue
            self.assertGreaterEqual(min(gaps), 0.045)
            paces.append(12.0 / (sum(gaps) / len(gaps)))
            spreads.append(max(gaps) / min(gaps))
            steady += all(a <= b for a, b in zip(gaps, gaps[1:])) or all(a >= b for a, b in zip(gaps, gaps[1:]))
            styles.add(tuple(round(g, 3) for g in gaps))
        # Pace differs a lot between turns, but is never robotic-fast.
        self.assertGreater(max(paces) - min(paces), 60)
        self.assertLess(max(paces), 175)
        self.assertGreater(min(paces), 35)
        self.assertGreater(sum(p < 65 for p in paces), 10)
        self.assertGreater(sum(p > 105 for p in paces), 40)
        # Inside one word the keys are uneven, and never a steady ramp.
        self.assertGreater(sum(s > 1.6 for s in spreads), len(spreads) * 0.9)
        self.assertLess(steady, len(spreads) * 0.02)
        self.assertGreater(len(styles), len(spreads) * 0.9)
        # Mistakes come and go.
        self.assertTrue(120 < mistakes < 330, mistakes)
        self.assertGreater(clean, 250)
        self.assertGreater(end_enters, 0)
        self.assertLess(end_enters, 120)

    def test_mistakes_take_several_forms_and_are_fixed_at_a_varied_speed(self):
        forms, fix_gaps, late = set(), [], 0
        for seed in range(800):
            plan = turn_plan("sessionary", "ses", 12, random.Random(seed).random, lambda w: False)
            self.assertEqual(self.spell(plan), "sessionary")
            if not plan.mistakes or plan.fidgets:
                continue
            typed = [s for s in plan.steps if s.kind == "type"]
            wrong_at = next(i for i, s in enumerate(plan.steps)
                            if s.kind == "type" and not "sessionary".startswith(s.typed))
            first_back = next(i for i, s in enumerate(plan.steps) if s.kind == "back" and i > wrong_at)
            gone = first_back - wrong_at          # letters typed before it was noticed
            late += gone > 1
            forms.add(("dup" if plan.steps[wrong_at].typed[-2:-1] == plan.steps[wrong_at].typed[-1:]
                       else "other", min(gone, 3)))
            fix_gaps.append(plan.steps[first_back].delay)
        self.assertGreater(len(forms), 4)
        self.assertGreater(late, 15)
        self.assertGreater(max(fix_gaps) - min(fix_gaps), 0.2)
        self.assertLess(sorted(fix_gaps)[len(fix_gaps) // 2], 0.3)

    def test_short_prefixes_fidget_up_to_three_times_longer_ones_rarely_do(self):
        counts = {1: {}, 3: {}}
        pauses = set()
        for seed in range(1200):
            one = turn_plan("ailism", "i", 12, random.Random(seed).random, lambda w: False)
            three = turn_plan("ailism", "ism", 12, random.Random(seed + 4000).random, lambda w: False)
            self.assertEqual(self.spell(one), "ailism")
            self.assertEqual(self.spell(three), "ailism")
            counts[1][one.fidgets] = counts[1].get(one.fidgets, 0) + 1
            counts[3][three.fidgets] = counts[3].get(three.fidgets, 0) + 1
            if one.fidgets >= 2:
                # the pause that follows a fidget (its last erase) varies a lot
                empties = [i for i, s in enumerate(one.steps) if s.kind == "back" and not s.typed]
                pauses.update(round(one.steps[i + 1].delay, 1) for i in empties[:-1]
                              if i + 1 < len(one.steps))
        self.assertEqual(max(counts[1]), 3)
        self.assertLessEqual(max(counts[3]), 2)
        self.assertGreater(counts[1].get(2, 0), 40)
        self.assertGreater(counts[1].get(3, 0), 10)
        short = 1200 - counts[1][0]
        longer = 1200 - counts[3][0]
        self.assertGreater(short, longer * 2)
        self.assertLess(longer, 1200 * 0.14)
        self.assertGreater(len(pauses), 4)

    def test_fidgets_differ_in_style_and_speed(self):
        shapes, first_erase = set(), []
        for seed in range(600):
            plan = turn_plan("ailism", "i", 12, random.Random(seed).random, lambda w: False)
            if plan.fidgets != 1:
                continue
            end = next(i for i, s in enumerate(plan.steps) if s.kind == "back" and not s.typed)
            act = plan.steps[:end + 1]
            shapes.add("".join("t" if s.kind == "type" else "b" for s in act))
            first_erase.append(next(s.delay for s in act if s.kind == "back"))
        self.assertGreaterEqual(len(shapes), 5)
        self.assertGreater(max(first_erase) - min(first_erase), 0.25)

    def test_pace_drifts_across_a_game(self):
        random.seed(5)
        means = [turn_plan("ailismable", "i", 12).tempo for _ in range(300)]
        self.assertGreater(max(means) / min(means), 2.0)
        runs = sum(1 for a, b, c in zip(means, means[1:], means[2:]) if a < b < c or a > b > c)
        self.assertLess(runs, 120)

    def test_no_fidget_or_typo_when_time_is_short_and_the_plan_fits(self):
        for seed in range(100):
            plan = turn_plan("ailism", "ism", 1.2, random.Random(seed).random)
            self.assertLessEqual(plan_duration(plan.steps), 1.25)
            self.assertEqual([s.kind for s in plan.steps], ["type"] * 6 + ["enter"])

    def test_turns_start_quickly_and_do_not_repeat_the_same_fidget(self):
        first = []
        end_slips = 0
        for seed in range(200):
            plan = turn_plan("ailism", "i", 12, random.Random(seed).random, lambda w: False)
            self.assertEqual(self.spell(plan), "ailism")
            self.assertLessEqual(plan.steps[0].delay, 0.12)
            first.append(plan.steps[0].delay)
            end_slips += any(s.kind == "early" and s.typed and not "ailism".startswith(s.typed)
                             for s in plan.steps)
        self.assertLess(sum(first) / len(first), 0.055)
        self.assertGreater(end_slips, 0)
        self.assertLess(end_slips, 30)

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


class SearchBoxTests(unittest.TestCase):
    def test_search_shows_choices_and_the_live_turn_gives_the_screen_back(self):
        app, face = make_app(("stone", "stoke", "stow", "tonal"))
        app.handle("SEARCH", "  ST ")
        self.assertEqual(face.values["PROMPT"], "st")
        self.assertTrue(face.values["C1"].startswith("1  sto"))
        self.assertNotEqual(face.values["TYPE"], "—")
        # A live prompt must not overwrite what was searched for.
        app._shown = "to"
        app._present("to")
        app._show_prompt("to")
        self.assertEqual(face.values["PROMPT"], "st")
        # Typing a word marks it used and refreshes the results.
        app.engine.mark_used(face.values["C1"].split()[-1])
        app._refresh_used()
        self.assertNotEqual(face.values["C1"].split()[-1], "")
        app.handle("SEARCH", "")
        self.assertEqual(face.values["PROMPT"], "to")
        self.assertTrue(face.values["C1"].startswith("1  to"))

    def test_search_with_no_answers_is_empty_not_an_error(self):
        app, face = make_app(("stone",))
        app.handle("SEARCH", "zzq")
        self.assertEqual(face.values["C1"], "—")


if __name__ == "__main__":
    unittest.main()
