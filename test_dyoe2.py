"""Unit tests for DYOE2.0 engine."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dyoe2_engine import (
    BLACKLISTED_TRAP_PREFIXES,
    Dyoe2Engine,
    TrapPools,
    analyze_cancel,
    build_giveable_via_reversed,
    build_trap_pools,
    filter_giveable_pools,
    load_prefixes_from_lines,
    merge_prefix_tiers,
    normalize_hybrid_suffixes,
    word_has_punctuation,
)


class PriorityAndBlacklistTests(unittest.TestCase):
    def test_bj_is_blacklisted_constant(self) -> None:
        self.assertIn("bj", BLACKLISTED_TRAP_PREFIXES)
        for prefix in ("rk", "ls", "tion", "ishes", "oo", "ng", "-",
                       "bb", "cc", "dd", "gg", "hh", "ll", "rr", "ss",
                       "rb", "rc", "rd", "rf", "rk", "rl", "rm", "rn", "rp", "rt", "ry",
                       "bs", "cs", "ds", "gs", "ks", "ls", "ms", "ns", "ts", "ws", "ys", "zs"):
            self.assertIn(prefix, BLACKLISTED_TRAP_PREFIXES)

    def test_bj_removed_from_built_pools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            casual = root / "casual.txt"
            traps = root / "traps.txt"
            special = root / "special.txt"
            no_plural = root / "noplural.txt"
            casual.write_text("#\nbt\t3\t1\t1\t-\n", encoding="utf-8")
            trap_lines = ["#"] * 8 + ["bj\t1\tx - y", "bz\t1\tx - y"]
            traps.write_text("\n".join(trap_lines) + "\n", encoding="utf-8")
            special.write_text("#\n", encoding="utf-8")
            no_plural.write_text("#\n", encoding="utf-8")
            pools = build_trap_pools(
                casual_path=casual,
                traps_path=traps,
                special_path=special,
                no_plural_path=no_plural,
            )
            self.assertNotIn("bj", pools.pro_2)
            self.assertIn("bz", pools.pro_2)

    def test_priority_order_moves_trap_to_front(self) -> None:
        traps = TrapPools(pro_2=["aa", "ee", "ff"], casual_2=["aa", "ee"])
        engine = Dyoe2Engine(
            ["xaa", "xee", "xff", "prefix"],
            traps=traps,
            validate_giveable=False,
        )
        engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        engine.set_casual_mode(False)
        engine.set_phase(2)
        engine.set_priority_order(2, ["ff", "aa"], casual=False, persist=True)
        ordered = engine.get_ordered_traps(2, casual=False)
        self.assertEqual(ordered[:3], ["ff", "aa", "ee"])
        ranked = engine.ranked_words("x")
        self.assertEqual(ranked[0], "xff")

    def test_priority_never_reintroduces_bj(self) -> None:
        traps = TrapPools(pro_2=["aa", "ee"])
        engine = Dyoe2Engine(["xaa", "xee"], traps=traps, validate_giveable=False)
        ordered = engine.apply_priority_order(["aa", "ee"], ["bj", "ee", "aa"])
        self.assertNotIn("bj", ordered)
        self.assertEqual(ordered, ["ee", "aa"])

    def test_used_trap_moves_to_end_so_others_get_chance(self) -> None:
        traps = TrapPools(casual_2=["aa", "ee", "ff"])
        words = ["zaa", "zee", "zff", "zaalong", "giveaa", "giveee", "giveff"]
        engine = Dyoe2Engine(words, traps=traps, validate_giveable=False)
        engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        engine.set_casual_mode(True)
        engine.set_phase(2)
        engine.reset_queue_from_rank("z", size=3)
        front, _, _ = engine.get_display_words("z")
        self.assertTrue(front.endswith("aa"), front)
        next_front, _, _ = engine.already_used("z")
        self.assertEqual(engine.last_decayed_trap, "aa")
        ordered = engine.get_ordered_traps(2, casual=True)
        self.assertEqual(ordered[-1], "aa")
        self.assertEqual(ordered[0], "ee")
        # The visible queue must immediately rebuild from the new order.
        self.assertTrue(next_front.endswith("ee"), next_front)

    def test_hybrid_custom_suffix_priority_stays_fixed_after_use(self) -> None:
        traps = TrapPools(casual_4=["tone"])
        words = [
            "stary",
            "stlongary",
            "stbee",
            "stone",
            "giveary",
            "givebee",
        ]
        engine = Dyoe2Engine(words, traps=traps, validate_giveable=False)
        engine.set_casual_mode(True)
        engine.set_phase(5)
        engine.set_hybrid_suffixes("ary bee")
        engine.reset_queue_from_rank("st", size=3)
        front, _, _ = engine.get_display_words("st")
        # Hybrid custom endings prefer the shortest matching word first.
        self.assertEqual(front, "stary")
        next_front, _, _ = engine.already_used("st")
        self.assertIsNone(engine.last_decayed_trap)
        self.assertEqual(engine.hybrid_suffixes, ("ary", "bee"))
        # Another ary word still beats bee because custom priority never moves.
        self.assertEqual(next_front, "stlongary")
        engine.rotate_for_new_game(casual=True, persist=False)
        self.assertEqual(engine.hybrid_suffixes, ("ary", "bee"))

    def test_used_trap_decays_only_inside_its_source_tier(self) -> None:
        traps = TrapPools(
            pro_3=["s-a", "s-b", "nzz", "nbb", "gzz", "gbb"],
            source_tiers={
                "pro:3": [
                    ["s-a", "s-b"],
                    ["nzz", "nbb"],
                    ["gzz", "gbb"],
                ]
            },
        )
        words = ["xs-a", "xs-b", "xnzz", "xnbb", "xgzz", "xgbb"]
        engine = Dyoe2Engine(words, traps=traps, validate_giveable=False)
        engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        engine.set_casual_mode(False)
        engine.set_phase(3)

        self.assertTrue(engine.deprioritize_trap(3, "s-a", persist=False))
        tiers = engine.get_ordered_trap_tiers(3, casual=False)
        self.assertEqual(tiers[0], ["s-b", "s-a"])
        self.assertEqual(tiers[1], ["nzz", "nbb"])
        self.assertEqual(tiers[2], ["gzz", "gbb"])
        self.assertEqual(
            engine.get_ordered_traps(3, casual=False),
            ["s-b", "s-a", "nzz", "nbb", "gzz", "gbb"],
        )

    def test_cross_tier_drag_cannot_break_source_hierarchy(self) -> None:
        traps = TrapPools(
            pro_3=["s-a", "s-b", "nzz", "nbb", "gzz", "gbb"],
            source_tiers={
                "pro:3": [
                    ["s-a", "s-b"],
                    ["nzz", "nbb"],
                    ["gzz", "gbb"],
                ]
            },
        )
        engine = Dyoe2Engine(
            ["xs-a", "xs-b", "xnzz", "xnbb", "xgzz", "xgbb"],
            traps=traps,
            validate_giveable=False,
        )
        engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        engine.set_priority_order(
            3,
            ["gbb", "nbb", "s-b", "gzz", "nzz", "s-a"],
            casual=False,
            persist=False,
        )
        # Requested order is honored within each tier only.
        self.assertEqual(
            engine.get_ordered_traps(3, casual=False),
            ["s-b", "s-a", "nbb", "nzz", "gbb", "gzz"],
        )

    def test_new_game_rotates_each_tier_without_crossing_tiers(self) -> None:
        traps = TrapPools(
            pro_3=["s-a", "s-b", "nzz", "nbb", "gzz", "gbb"],
            source_tiers={
                "pro:3": [
                    ["s-a", "s-b"],
                    ["nzz", "nbb"],
                    ["gzz", "gbb"],
                ]
            },
        )
        engine = Dyoe2Engine(
            ["xs-a", "xs-b", "xnzz", "xnbb", "xgzz", "xgbb"],
            traps=traps,
            validate_giveable=False,
        )
        engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        engine.rotate_for_new_game(casual=False, persist=False)
        self.assertEqual(
            engine.get_ordered_trap_tiers(3, casual=False),
            [["s-b", "s-a"], ["nbb", "nzz"], ["gbb", "gzz"]],
        )
        self.assertEqual(
            engine.get_ordered_traps(3, casual=False),
            ["s-b", "s-a", "nbb", "nzz", "gbb", "gzz"],
        )


class ParseHelpersTests(unittest.TestCase):
    def test_load_prefixes_line_ranges_are_1_indexed_inclusive(self) -> None:
        lines = [
            "# header",
            "aa\t1\tx - y",
            "bb\t1\tx - y",
            "cc\t1\tx - y",
            "ddd\t1\tx - y",
        ]
        self.assertEqual(
            load_prefixes_from_lines(lines, start_line=2, end_line=3),
            ["aa", "bb"],
        )
        self.assertEqual(
            load_prefixes_from_lines(lines, start_line=5, end_line=5),
            ["ddd"],
        )

    def test_merge_keeps_first_tier_priority(self) -> None:
        merged = merge_prefix_tiers(["a-b", "zzz"], ["zzz", "plain"], ["a-b", "later"])
        self.assertEqual(merged, ["a-b", "zzz", "plain", "later"])

    def test_hybrid_suffix_normalization(self) -> None:
        self.assertEqual(
            normalize_hybrid_suffixes(" ary, bee; Cee  ary "),
            ("ary", "bee", "cee"),
        )

    def test_punctuation_detector(self) -> None:
        self.assertTrue(word_has_punctuation("e-mail"))
        self.assertTrue(word_has_punctuation("i'll"))
        self.assertFalse(word_has_punctuation("email"))


class GiveableTests(unittest.TestCase):
    def test_giveable_requires_word_ending_with_suffix(self) -> None:
        words = ["alpha", "sub-i", "hello"]
        found = build_giveable_via_reversed(words, ["pha", "b-i", "zzz", "lo"])
        self.assertEqual(found, {"pha", "b-i", "lo"})

    def test_filter_drops_non_giveable_traps(self) -> None:
        pools = TrapPools(
            casual_2=["aa", "zz"],
            casual_3=["aaa"],
            casual_4=[],
            pro_2=["aa"],
            pro_3=["b-i"],
            pro_4=["zzzz"],
        )
        filtered = filter_giveable_pools(pools, {"aa", "b-i"})
        self.assertEqual(filtered.casual_2, ["aa"])
        self.assertEqual(filtered.casual_3, [])
        self.assertEqual(filtered.pro_3, ["b-i"])
        self.assertEqual(filtered.pro_4, [])


class RankingTests(unittest.TestCase):
    def setUp(self) -> None:
        # Words starting with "st":
        # - longest: staaaaaaaa
        # - ends with trap "xy": stickyxy / shortxy
        # - ends with hyphen trap "e-m": stale-m
        # - punctuation word for casual filter: st-hello
        self.words = [
            "staaaaaaaa",
            "stickyxy",
            "stoutxy",
            "stale-m",
            "st-hello",
            "stone",
            "star",
            "other",
            "prefixxy",  # does not start with st
            "giveablexy",  # makes xy giveable as ending
            "source-m",  # makes e-m giveable
        ]
        self.traps = TrapPools(
            casual_2=["xy", "ne"],
            casual_3=["one"],
            casual_4=["tone"],
            pro_2=["xy"],
            pro_3=["e-m", "zzz"],
            pro_4=["tone", "aaaa"],
        )
        self.engine = Dyoe2Engine(
            self.words, traps=self.traps, validate_giveable=True
        )
        self.engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        self.engine.priority_orders = {}

    def test_phase1_prefers_longest(self) -> None:
        self.engine.set_casual_mode(True)
        self.engine.set_phase(1)
        ranked = self.engine.ranked_words("st")
        self.assertEqual(ranked[0], "staaaaaaaa")

    def test_casual_excludes_hyphen_and_apostrophe_words(self) -> None:
        self.engine.set_casual_mode(True)
        self.engine.set_phase(1)
        ranked = self.engine.ranked_words("st")
        self.assertNotIn("st-hello", ranked)
        self.assertNotIn("stale-m", ranked)

    def test_pro_allows_punctuation_words(self) -> None:
        self.engine.set_casual_mode(False)
        self.engine.set_phase(1)
        ranked = self.engine.ranked_words("st")
        self.assertIn("st-hello", ranked)
        self.assertIn("stale-m", ranked)

    def test_phase2_prefers_words_ending_with_trap(self) -> None:
        self.engine.set_casual_mode(True)
        self.engine.set_phase(2)
        ranked = self.engine.ranked_words("st")
        # stickyxy and stoutxy end with xy trap; longest trap-match first
        self.assertEqual(ranked[0], "stickyxy")
        self.assertEqual(ranked[1], "stoutxy")

    def test_pro_phase3_special_trap_outranks_others(self) -> None:
        self.engine.set_casual_mode(False)
        self.engine.set_phase(3)
        ranked = self.engine.ranked_words("st")
        self.assertEqual(ranked[0], "stale-m")

    def test_hybrid_custom_suffix_has_highest_priority(self) -> None:
        self.engine.set_casual_mode(True)
        self.engine.set_phase(5)
        self.engine.set_hybrid_suffixes("ary, one")
        # stone ends with "one" custom; should beat xy-trap words
        ranked = self.engine.ranked_words("st")
        self.assertEqual(ranked[0], "stone")

    def test_hybrid_custom_suffix_prefers_shortest_word(self) -> None:
        self.words.extend(["stary", "stlongary", "stverylongary"])
        self.engine = Dyoe2Engine(
            self.words, traps=self.traps, validate_giveable=True
        )
        self.engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        self.engine.priority_orders = {}
        self.engine.set_casual_mode(True)
        self.engine.set_phase(5)
        self.engine.set_hybrid_suffixes("ary")
        ranked = self.engine.ranked_words("st", limit=4)
        ary = [w for w in ranked if w.endswith("ary")]
        self.assertEqual(ary[:3], ["stary", "stlongary", "stverylongary"])
        # Fallback traps still prefer longest after customs are exhausted.
        self.assertTrue(all(w.endswith("ary") for w in ranked[:3]))

    def test_hybrid_fills_all_custom_before_fallback_traps(self) -> None:
        # Multiple custom matches must outrank any phase-trap word.
        self.words.extend(["stxyzary", "stabcary", "stdefary"])
        self.engine = Dyoe2Engine(
            self.words, traps=self.traps, validate_giveable=True
        )
        self.engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        self.engine.priority_orders = {}
        self.engine.set_casual_mode(True)
        self.engine.set_phase(5)
        self.engine.set_hybrid_suffixes("ary")
        ranked = self.engine.ranked_words("st", limit=5)
        custom = [w for w in ranked if w.endswith("ary")]
        self.assertGreaterEqual(len(custom), 3)
        # First three should all be custom ary endings (shortest first among them)
        self.assertTrue(all(w.endswith("ary") for w in ranked[:3]))
        self.assertEqual(ranked[0], "stabcary")
        self.assertNotEqual(ranked[0], "stickyxy")

    def test_hybrid_falls_back_to_phase_traps(self) -> None:
        self.engine.set_casual_mode(True)
        self.engine.set_phase(5)
        self.engine.set_hybrid_suffixes("zzznotfound")
        ranked = self.engine.ranked_words("st")
        # No custom match → casual 4→3→2 traps; "tone" (phase4) beats "xy" (phase2)
        self.assertEqual(ranked[0], "stone")

    def test_side_promote_swaps_without_marking_used(self) -> None:
        self.engine.set_casual_mode(True)
        self.engine.set_phase(2)
        self.engine.reset_queue_from_rank("st", size=3)
        front, top, bottom = self.engine.get_display_words("st")
        self.assertIsNotNone(front)
        self.assertIsNotNone(top)
        new_front, new_top, _ = self.engine.promote_side("st", "top")
        self.assertEqual(new_front, top)
        self.assertEqual(new_top, front)
        self.assertEqual(self.engine.used_words, set())

    def test_already_used_advances_queue(self) -> None:
        self.engine.set_casual_mode(True)
        self.engine.set_phase(2)
        self.engine.reset_queue_from_rank("st", size=3)
        first, second, third = self.engine.get_display_words("st")
        front, top, bottom = self.engine.already_used("st")
        self.assertIn(first, self.engine.used_words)
        # Used trap (xy) is moved to the end, so the next front may change
        # relative to the pre-decay second slot — still must be unused & valid.
        self.assertIsNotNone(front)
        self.assertNotEqual(front, first)
        self.assertNotIn(front, self.engine.used_words)
        self.assertEqual(self.engine.last_decayed_trap, "xy")

    def test_exact_trap_word_preferred_over_longer_ending(self) -> None:
        # skas itself must beat alaskas/modjeskas so the opponent can't
        # self-solve by typing the trap word after you dump a longer *skas.
        words = [
            "alaskas",
            "modjeskas",
            "skas",
            "skasely",
            "skafoo",
            "other",
        ]
        traps = TrapPools(
            pro_4=["skas"],
            source_tiers={"pro:4": [["skas"]]},
        )
        engine = Dyoe2Engine(words, traps=traps, validate_giveable=False)
        engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        engine.set_casual_mode(False)
        engine.set_phase(4)
        ranked = engine.ranked_words("sk")
        self.assertEqual(ranked[0], "skas")
        self.assertNotEqual(ranked[0], "alaskas")

    def test_skip_longer_trap_ending_while_exact_trap_unused(self) -> None:
        # Prompt "alas" matches alaskas but not skas — do not dump skas via
        # alaskas while skas is still available for the opponent to self-solve.
        words = ["alaskas", "skas", "alaskaite", "alastrims"]
        traps = TrapPools(
            pro_4=["skas"],
            source_tiers={"pro:4": [["skas"]]},
        )
        engine = Dyoe2Engine(words, traps=traps, validate_giveable=False)
        engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        engine.set_casual_mode(False)
        engine.set_phase(4)
        matches = engine._matching_trap_words("alas", "skas", seen=set())
        self.assertEqual(matches, [])

    def test_longer_trap_ending_ok_after_exact_trap_used(self) -> None:
        words = ["alaskas", "skas", "alaskaite", "modjeskas"]
        traps = TrapPools(
            pro_4=["skas"],
            source_tiers={"pro:4": [["skas"]]},
        )
        engine = Dyoe2Engine(words, traps=traps, validate_giveable=False)
        engine.priority_path = Path(tempfile.mkdtemp()) / "prio.json"
        engine.set_casual_mode(False)
        engine.set_phase(4)
        engine.mark_used("skas")
        ranked = engine.ranked_words("alas")
        self.assertEqual(ranked[0], "alaskas")


class TrapPoolFileTests(unittest.TestCase):
    def test_build_trap_pools_from_temp_files_respects_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            casual = root / "casual.txt"
            traps = root / "traps.txt"
            special = root / "special.txt"
            no_plural = root / "noplural.txt"

            casual.write_text(
                "# hdr\nbt\t3\t1\t1\t-\nabc\t3\t1\t1\t-\nzzrd\t4\t1\t1\t-\n",
                encoding="utf-8",
            )
            # lines 1-8 header padding, 9-10 phase2, 11+ phase3 sample
            trap_lines = ["#"] * 8 + [
                "bj\t1\tx - y",  # line 9
                "bz\t1\tx - y",  # line 10
            ]
            # pad to line 57 for a phase-3 entry
            while len(trap_lines) < 56:
                trap_lines.append("# pad")
            trap_lines.append("aan\t1\tx - y")  # line 57
            while len(trap_lines) < 711:
                trap_lines.append("# pad")
            trap_lines.append("zzzz\t1\tx - y")  # line 712 phase4
            traps.write_text("\n".join(trap_lines) + "\n", encoding="utf-8")

            special_lines = ["#"] * 10
            special_lines.append("b-i\t1\tx - y")  # 11
            while len(special_lines) < 24:
                special_lines.append("# pad")
            special_lines.append("n-r\t1\tx - y")  # 25
            while len(special_lines) < 30:
                special_lines.append("# pad")
            special_lines.append("d-be\t1\tx - y")  # 31
            special.write_text("\n".join(special_lines) + "\n", encoding="utf-8")

            np_lines = ["#"] * 13
            np_lines.append("aoh\t1\tdyoe_giveable=yes\taoh\t1\tx - y")  # 14
            while len(np_lines) < 141:
                np_lines.append("# pad")
            np_lines.append("zzzz\t1\tdyoe_giveable=yes\tzzzz\t1\tx - y")  # 142
            no_plural.write_text("\n".join(np_lines) + "\n", encoding="utf-8")

            pools = build_trap_pools(
                casual_path=casual,
                traps_path=traps,
                special_path=special,
                no_plural_path=no_plural,
            )
            self.assertEqual(pools.casual_2, ["bt"])
            self.assertEqual(pools.casual_3, ["abc"])
            self.assertEqual(pools.casual_4, ["zzrd"])
            self.assertEqual(pools.pro_2, ["bz"])  # bj is blacklisted
            self.assertEqual(pools.pro_3[0], "b-i")
            self.assertIn("n-r", pools.pro_3)
            self.assertIn("aoh", pools.pro_3)
            self.assertIn("aan", pools.pro_3)
            self.assertEqual(pools.pro_4[0], "d-be")
            self.assertIn("zzzz", pools.pro_4)


class QueueIntegrationTests(unittest.TestCase):
    def test_three_word_display_and_bottom_promote(self) -> None:
        words = [f"aa{i:03d}" for i in range(10)]  # aa000.. longest-ish equal
        # Make distinct lengths for phase1 ordering
        words = ["aaaaaaaaaa", "aaaaaaaaa", "aaaaaaaa", "aaaaaaa", "aaaaaa"]
        engine = Dyoe2Engine(words, traps=TrapPools(), validate_giveable=False)
        engine.set_phase(1)
        engine.set_casual_mode(True)
        engine.reset_queue_from_rank("aa", size=3)
        front, top, bottom = engine.get_display_words("aa")
        self.assertEqual(front, "aaaaaaaaaa")
        self.assertEqual(top, "aaaaaaaaa")
        self.assertEqual(bottom, "aaaaaaaa")
        front, top, bottom = engine.promote_side("aa", "bottom")
        self.assertEqual(front, "aaaaaaaa")
        self.assertEqual(bottom, "aaaaaaaaaa")


class CancelLawTests(unittest.TestCase):
    def test_analyze_cancel_keeps_two_largest_groups(self) -> None:
        words = [
            "like",
            "likeable",
            "likeness",
            "likewake",
            "likewakes",
            "likewalk",
            "likewalks",
            "likeways",
            "likewise",
            "likewisely",
            "likewiseness",
            "likelier",
            "likeliest",
            "likelihood",
            "likelihoods",
            "likelihead",
            "likeliness",
            "likelinesses",
            "likely",
        ]
        analysis = analyze_cancel("like", words)
        self.assertEqual(set(analysis.kept_keys), {"l", "w"})
        self.assertEqual(len(analysis.groups["w"]), 8)
        self.assertEqual(len(analysis.groups["l"]), 8)
        self.assertIn("likeable", analysis.cancel_words)
        self.assertIn("likeness", analysis.cancel_words)
        self.assertIn("like", analysis.cancel_words)
        self.assertNotIn("likewise", analysis.cancel_words)
        self.assertNotIn("likely", analysis.cancel_words)

    def test_cancelled_prompt_surfaces_cancel_words_first_in_casual(self) -> None:
        words = [
            "ely",
            "elychnious",
            "elydoric",
            "elymi",
            "elymoclavine",
            "elymoclavines",
            "elymus",
            "elys",
            "elysian",
            "elysium",
            "elysiums",
            "elysia",
            "elytra",
            "elytral",
            "elytriform",
            "elytrin",
            "elytro-",  # punctuation ignored by cancel source
        ]
        # pad t-group so it stays a kept group
        words.extend(
            [
                "elytrum",
                "elytrons",
                "elytron",
                "elytrous",
                "elytroid",
                "elytropolyp",
                "elytropolypous",
                "elytroplastic",
                "elytroplasty",
                "elytrosis",
                "elytrocele",
                "elytrocyst",
                "elytrocysts",
                "elytroidal",
                "elytroids",
                "elytromorphous",
                "elytrorrhaphy",
                "elytroptosis",
                "elytroptoses",
            ]
        )
        engine = Dyoe2Engine(words, traps=TrapPools(), validate_giveable=False)
        engine.cancelled_prompts_path = Path(tempfile.mkdtemp()) / "cancel.json"
        engine.load_cancelled_prompts()
        engine.set_casual_mode(True)
        engine.set_phase(1)
        analysis = engine.analyze_cancel("ely")
        self.assertTrue(analysis.cancel_words)
        self.assertTrue(engine.toggle_prompt_cancelled("ely", persist=True))
        ranked = engine.ranked_words("ely")
        self.assertEqual(ranked[: len(analysis.cancel_words)], list(analysis.cancel_words))
        # Kept-group solves follow after every cancel word.
        for word in analysis.kept_words:
            if word in ranked:
                self.assertGreaterEqual(
                    ranked.index(word),
                    len(analysis.cancel_words),
                    word,
                )

    def test_cancel_priority_ignored_in_pro_mode(self) -> None:
        words = ["zaa", "zbb", "zcc", "zdd", "zee", "zff"]
        engine = Dyoe2Engine(words, traps=TrapPools(), validate_giveable=False)
        engine.cancelled_prompts_path = Path(tempfile.mkdtemp()) / "cancel.json"
        engine.load_cancelled_prompts()
        engine.set_prompt_cancelled("z", True, persist=True)
        engine.set_casual_mode(False)
        engine.set_phase(1)
        ranked_pro = engine.ranked_words("z")
        engine.set_casual_mode(True)
        ranked_casual = engine.ranked_words("z")
        self.assertNotEqual(ranked_pro[0], ranked_casual[0])


if __name__ == "__main__":
    unittest.main()
