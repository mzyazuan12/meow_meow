from __future__ import annotations

import random
import unittest

from dyoe2_engine import Dyoe2Engine, TrapPools

from autotype.featherine import build_plan, featherine_plan, human_plan, live_plan
from autotype.tiles import settle_qo
from autotype.session import (
    BoardWatch,
    MatchSession,
    already_used_text,
    finished_word,
    names_match,
    phase_for_prompt,
    phase_for_round,
    speaker_from_header,
    sync_round_to_prefix,
)

class PhaseTests(unittest.TestCase):
    def test_phase_every_five_rounds(self) -> None:
        self.assertEqual([phase_for_round(n) for n in (1, 5, 6, 10, 11, 15, 16, 40)], [1, 1, 2, 2, 3, 3, 4, 4])

    def test_live_prefix_jumps_phase(self) -> None:
        self.assertEqual(phase_for_prompt(1, "s"), 1)
        self.assertEqual(phase_for_prompt(1, "sk"), 2)
        self.assertEqual(phase_for_prompt(2, "mens"), 4)
        self.assertEqual(sync_round_to_prefix(1, "mens"), 16)

    def test_header_name(self) -> None:
        header = "guga2323332, type an english word starting with:"
        self.assertEqual(speaker_from_header(header), "guga2323332")
        glued = "guga2323332,type an english word starting with:"
        self.assertEqual(speaker_from_header(glued), "guga2323332")
        self.assertTrue(names_match("guga2323332", "iga2323332"))
        self.assertTrue(names_match("gugugaga2323332", "uyugaga23233312"))
        self.assertFalse(names_match("guga2323332", "parker"))

    def test_finished_word_is_the_tiles_before_the_next_prefix(self) -> None:
        self.assertIsNone(finished_word("men", "menstrua"))
        self.assertEqual(finished_word("menstrual", "l"), "menstrual")
        self.assertIsNone(finished_word("m", "m"))

class BoardWatchTests(unittest.TestCase):
    def test_our_turn_plays_the_prefix_once_it_has_settled(self) -> None:
        watch = BoardWatch()
        self.assertEqual(watch.observe("sk", "ours", now=0)["play"], "")
        played = watch.observe("sk", "ours", now=0.8)
        self.assertEqual(played["play"], "sk")
        watch.played = "sk"
        self.assertEqual(watch.observe("sk", "ours", now=1.0)["play"], "")
        self.assertEqual(watch.observe("skate", "ours", now=1.1)["play"], "")
        self.assertEqual(watch.observe("u", "ours", now=2.0)["play"], "")
        self.assertEqual(watch.observe("u", "ours", now=2.0)["candidates"], [])

    def test_a_prefix_is_not_played_until_every_letter_has_landed(self) -> None:
        watch = BoardWatch()
        self.assertEqual(watch.observe("w", "ours", now=0.0)["play"], "")
        self.assertEqual(watch.observe("wo", "ours", now=0.25)["play"], "")
        self.assertEqual(watch.observe("wow", "ours", now=0.45)["play"], "")
        self.assertEqual(watch.observe("wow", "ours", now=0.9)["play"], "")
        self.assertEqual(watch.observe("wow", "ours", now=1.2)["play"], "wow")

    def test_an_unread_tile_keeps_the_prefix_from_settling(self) -> None:
        watch = BoardWatch()
        watch.observe("w", "ours", now=0.0, tiles=1)
        watch.observe("", "ours", now=0.6, complete=False, tiles=2)
        self.assertEqual(watch.observe("wo", "ours", now=0.7, tiles=2)["play"], "")
        self.assertEqual(watch.observe("wo", "ours", now=1.5, tiles=2)["play"], "wo")

    def test_their_prompt_is_not_typed_on_our_turn(self) -> None:
        watch = BoardWatch()
        watch.observe("sk", "ours", now=0.0)
        self.assertEqual(watch.observe("sk", "ours", now=0.8)["play"], "sk")
        watch.played = "sk"

        self.assertEqual(watch.observe("w", "ours", now=1.0)["play"], "")
        self.assertEqual(watch.observe("wow", "ours", now=1.4)["play"], "")
        self.assertEqual(watch.observe("wow", "ours", now=2.4)["play"], "")
        watch.observe("wow", "theirs", now=2.5)
        watch.observe("wonderful", "theirs", now=3.0)
        self.assertEqual(watch.observe("ab", "ours", now=3.2)["play"], "")
        self.assertEqual(watch.observe("ab", "ours", now=4.0)["play"], "ab")

    def test_a_cut_off_reading_is_kept_until_the_prompt_settles(self) -> None:
        watch = BoardWatch()
        watch.observe("nesti", "theirs", now=0.0)
        early = watch.observe("ing", "ours", now=0.2)
        self.assertEqual(early["play"], "")
        self.assertIn("nesti", early["partials"])
        settled = watch.observe("ing", "ours", now=1.1)
        self.assertEqual(settled["play"], "ing")
        self.assertIn("nesti", settled["partials"])

    def test_one_frame_of_their_word_is_stored_when_the_turn_flips(self) -> None:
        watch = BoardWatch()
        watch.observe("nectar", "theirs", now=0)
        stored = watch.observe("r", "ours", now=0.1)
        self.assertIn("nectar", stored["candidates"])
        self.assertEqual(stored["play"], "")
        self.assertEqual(watch.observe("r", "ours", now=0.9)["play"], "r")

    def test_a_growing_word_is_kept_in_full(self) -> None:
        watch = BoardWatch()
        watch.observe("n", "theirs", now=0)
        watch.observe("nec", "theirs", now=0.2)
        watch.observe("nectar", "theirs", now=0.4)
        stored = watch.observe("r", "ours", now=0.5)
        self.assertIn("nectar", stored["candidates"])
        self.assertEqual(stored["stored"], "nectar")
        self.assertEqual(stored["play"], "")

    def test_a_blank_frame_does_not_erase_the_word(self) -> None:
        watch = BoardWatch()
        watch.observe("nectar", "theirs", now=0)
        self.assertEqual(watch.observe("", "theirs", now=0.1)["stored"], "")
        self.assertEqual(watch.pending, "nectar")
        stored = watch.observe("r", "ours", now=0.2)
        self.assertIn("nectar", stored["candidates"])

    def test_our_word_is_accepted_when_the_tiles_become_its_ending(self) -> None:
        watch = BoardWatch()
        watch.observe("s", "ours")
        watch.played = "s"
        watch.typed = "stone"
        watch.observe("stone", "ours")
        accepted = watch.observe("e", "ours")
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["play"], "")
        self.assertEqual(accepted["candidates"], [])

class FeatherineTests(unittest.TestCase):
    def test_featherine_uses_the_human_plan_at_her_tempo(self) -> None:
        plan = featherine_plan("stone", rng=random.Random(2).random)
        self.assertEqual(plan.rhythm, "human")
        self.assertEqual(plan.tempo, 0.72)
        self.assertEqual(plan.steps[-1].typed, "stone")
        self.assertGreater(plan.steps[0].delay, 0.1)
        self.assertGreater(plan.end_pause, 0.4)

    def test_suffix_excludes_the_prefix(self) -> None:
        traps = TrapPools(casual_2=["ne"], casual_3=["one"], casual_4=["tone"])
        engine = Dyoe2Engine(
            ["stone", "stony", "stop", "store"],
            traps=traps,
            validate_giveable=False,
        )
        session = MatchSession(engine)
        session.round = 6
        word, suffix, _trap, phase = session.choose("st")
        self.assertEqual(phase, 2)
        self.assertTrue(word.startswith("st"))
        self.assertEqual(suffix, word[2:])
        self.assertNotIn("st", suffix)
        session.commit_play(word)
        self.assertIn(word, engine.used_words)
        self.assertEqual(session.round, 7)

    def test_opponent_word_must_be_real_and_end_on_the_new_prefix(self) -> None:
        engine = Dyoe2Engine(
            ["stone", "nectar", "apple"],
            traps=TrapPools(),
            validate_giveable=False,
        )
        session = MatchSession(engine)
        self.assertFalse(session.note_opponent_word("ua"))
        self.assertFalse(session.note_opponent_bridge("nectar", "s", "e"))
        self.assertTrue(session.note_opponent_bridge("nectar", "n", "r"))
        self.assertIn("nectar", engine.used_words)

    def test_the_full_reading_wins_over_a_missed_letter(self) -> None:
        engine = Dyoe2Engine(
            ["nectar", "nectarine"],
            traps=TrapPools(),
            validate_giveable=False,
        )
        session = MatchSession(engine)
        kept = session.note_seen_words(["nectr", "nectar", "nect"])
        self.assertEqual(kept, "nectar")
        self.assertIn("nectar", engine.used_words)

    def test_a_cut_off_word_is_recovered_from_the_next_prompt(self) -> None:
        engine = Dyoe2Engine(
            ["nesting", "nestinging", "ingene", "stone"],
            traps=TrapPools(),
            validate_giveable=False,
        )
        session = MatchSession(engine)
        self.assertEqual(session.recover_partial(["n", "nes", "nesti"], "ing"), "nesting")
        self.assertIn("nesting", engine.used_words)
        self.assertTrue(already_used_text("This word is already used"))
        self.assertFalse(already_used_text("type an english word"))

    def test_an_ambiguous_fragment_is_not_stored(self) -> None:
        engine = Dyoe2Engine(
            ["wxyzaing", "wxyzbing"],
            traps=TrapPools(),
            validate_giveable=False,
        )
        session = MatchSession(engine)
        self.assertEqual(session.recover_partial(["wxyz"], "ing"), "")

    def test_spam_mode_types_words_that_end_with_the_prefixes(self) -> None:
        engine = Dyoe2Engine(
            ["stone", "stony", "store", "stellar"],
            traps=TrapPools(),
            validate_giveable=False,
        )
        session = MatchSession(engine)
        session.set_mode("spam")
        session.set_spam_suffixes("ne")
        word, suffix, _trap, phase = session.choose("st")
        self.assertEqual(phase, 5)
        self.assertEqual(word, "stone")
        self.assertTrue(word.endswith("ne"))
        self.assertEqual(suffix, word[2:])

class HumanTypingTests(unittest.TestCase):
    def test_the_first_key_has_no_lead_in(self) -> None:
        plan = human_plan("stone", "guga2323332", rng=random.Random(2).random)
        self.assertEqual(plan.steps[0].delay, 0)
        self.assertEqual(plan.steps[-1].typed, "stone")
        self.assertIn(plan.rhythm, ("human", "patient", "staccato"))
        gaps = [step.delay for step in plan.steps[1:]]
        self.assertTrue(gaps)
        self.assertGreater(max(gaps), 0.02)

    def test_featherine_still_hesitates_before_the_first_key(self) -> None:
        plan = build_plan("stone", human=True, rhythm="human", tempo=0.72, rng=random.Random(2).random)
        self.assertGreater(plan.steps[0].delay, 0.1)

    def test_live_typing_changes_pace_inside_the_word_and_spells_it(self) -> None:
        word = "nesslerising"
        plans = [live_plan(word, rng=random.Random(i).random) for i in range(24)]
        self.assertGreater(len({plan.rhythm for plan in plans}), 1)
        slower_opening = 0
        faster_opening = 0
        corrections = 0
        for plan in plans:
            self.assertEqual(plan.steps[-1].typed, word)
            delays = []
            for step in plan.steps:
                if step.kind == "type" and step.typed == word[: len(delays) + 1]:
                    delays.append(step.delay)
            self.assertEqual(len(delays), len(word))
            opening = sum(delays[:5]) / 5
            closing = sum(delays[-6:]) / 6
            if opening > closing * 1.4:
                slower_opening += 1
            if closing > opening * 1.4:
                faster_opening += 1
            if any(step.kind == "back" for step in plan.steps):
                corrections += 1
                self.assertEqual(plan.steps[-1].typed, word)
        self.assertGreater(slower_opening, 0)
        self.assertGreater(faster_opening, 0)
        self.assertGreater(corrections, 0)
        self.assertLess(corrections, len(plans))

def _glyph(width: int, height: int, oval: bool, tail: bool) -> bytes:
    raw = bytearray([255]) * (width * height * 3)
    cx, cy = width / 2, height * 0.42
    rx, ry = width * 0.22, height * 0.22

    def paint(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            i = (y * width + x) * 3
            raw[i : i + 3] = b"\x00\x00\x00"

    if oval:
        for y in range(height):
            for x in range(width):
                dx = (x - cx) / rx
                dy = (y - cy) / ry
                dist = (dx * dx + dy * dy) ** 0.5
                if 0.72 <= dist <= 1.02:
                    paint(x, y)
    if tail:
        for step in range(int(height * 0.34)):
            x = int(cx + rx * 0.55) + step // 3
            y = int(cy + ry) + step
            for dx in range(-1, 2):
                paint(x + dx, y)
    return bytes(raw)

class LetterShapeTests(unittest.TestCase):
    def test_q_tail_is_not_read_as_o(self) -> None:
        bowl = _glyph(96, 120, oval=True, tail=False)
        tailed = _glyph(96, 120, oval=True, tail=True)
        self.assertEqual(settle_qo(bowl, 96, 120, 3, "q"), "o")
        self.assertEqual(settle_qo(tailed, 96, 120, 3, "o"), "q")

if __name__ == "__main__":
    unittest.main()
