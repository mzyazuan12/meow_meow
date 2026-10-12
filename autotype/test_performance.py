from __future__ import annotations

import ctypes
import random
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from autotype import host
from autotype import tiles
from autotype.fast_reader import BubbleReader
from autotype.featherine import edit_plan, turn_plan
from autotype.session import BoardWatch, TrapStyle
from autotype.test_regressions import app_module, frame, make_app
from autotype.timer import TurnClock


class FinalWordTests(unittest.TestCase):
    """The key worker reads the row back before Enter, but never past the clock."""

    def pending(self):
        app, _ = make_app(("beating", "beatitude"))
        app._name = "player"
        app._typing_prompt = app.watch.played = "beat"
        app._keys_now = "ing"
        return app

    def live(self, app, extra, **kwargs):
        from autotype.test_live_fixes import SubmissionTests
        return SubmissionTests()._type_with_live_screen(app, "beating", "beat", extra, **kwargs)

    def check(self, app, after, frames, cancel=None):
        """Run the check before Enter; each wait shows the next of ``frames``."""
        frames = list(frames)

        class Clock:
            def is_set(self):
                return False

            def wait(self, seconds):
                if frames:
                    app._last_frame = frames.pop(0)
                return False

        with patch.object(app_module, "roblox_focused", return_value=True), \
             patch.object(app, "_finish_suffix", side_effect=lambda shown, target, **kwargs: target) as finish:
            result = app._repair_from_screen(app._gen, "beating", "ing", after, cancel or Clock())
        return result, finish

    def test_extra_g_is_never_submitted_and_is_repaired_from_the_screen(self):
        app, _ = make_app(("beating", "beatitude"))
        keys, text = self.live(app, "g")
        self.assertEqual(keys, list("ing") + ["\b", "ENTER"])
        self.assertEqual(text, "beating")
        self.assertEqual(app._typed_word, "beating")

    def test_a_capture_from_before_the_last_key_never_doubles_a_letter(self):
        # The game draws a key a few frames after it is sent, so a capture from
        # before the last key shows the row a letter short. Typing that letter
        # again is how "beatingg" was entered.
        app = self.pending()
        after = time.monotonic() - 0.2
        stale = dict(frame("beatin"), captured_at=after - 0.01)
        app._last_frame = stale
        result, finish = self.check(app, after, [stale] * 4 + [dict(frame("beating"), captured_at=time.monotonic())])
        self.assertEqual(result, "ing")
        finish.assert_not_called()

    def test_an_unreadable_row_waits_to_be_drawn_then_trusts_the_keys(self):
        app = self.pending()
        now = time.monotonic()
        blurred = dict(frame("beat???", full=False), captured_at=now)
        app._last_frame = blurred
        result, finish = self.check(app, now - 0.16, [blurred, dict(frame("beating"), captured_at=time.monotonic())])
        self.assertEqual(result, "ing")
        finish.assert_not_called()
        # Still unreadable long after the last key: Enter on what was typed.
        app._last_frame = dict(frame("beat???", full=False), captured_at=time.monotonic())
        result, finish = self.check(app, time.monotonic() - 0.5, [])
        self.assertEqual(result, "ing")
        finish.assert_not_called()

    def test_no_time_left_enters_without_reading_the_row(self):
        app = self.pending()
        app._last_frame = dict(frame("beatin"), captured_at=time.monotonic())
        with patch.object(app, "_time_left", return_value=0.2):
            result, finish = self.check(app, time.monotonic() - 0.2, [])
        self.assertEqual(result, "ing")
        finish.assert_not_called()

    def test_cancel_stops_the_check_without_enter(self):
        app = self.pending()
        app._last_frame = dict(frame("beatin"), captured_at=time.monotonic())

        class Cancel:
            def is_set(self):
                return False

            def wait(self, seconds):
                app._cancel_typing()
                return False

        result, finish = self.check(app, time.monotonic() - 0.2, [], cancel=Cancel())
        self.assertIsNone(result)
        finish.assert_not_called()

    def test_pause_while_finishing_a_word_clears_it_on_resume(self):
        app = self.pending()
        app.typing = True
        app._toggle_pause()
        self.assertTrue(app._needs_clear)
        app._toggle_pause()
        with patch.object(app, "_clear_input") as clear:
            app._handle_frame(frame("beatingg"))
        clear.assert_called_once_with("beat")

    def test_a_row_whose_fixes_keep_failing_is_still_entered(self):
        # Roblox dropping every Backspace must not cost the turn.
        app, _ = make_app(("beating",))
        keys, text = self.live(app, "g", drop_backspace=9)
        self.assertEqual(keys, list("ing") + ["\b"] * 3 + ["ENTER"])
        self.assertEqual(text, "beatingg")


class TimingAndRecoveryTests(unittest.TestCase):
    def test_frozen_timer_frame_does_not_grant_more_time(self):
        clock = TurnClock()
        clock.observe(3.0, .6, 10)
        clock.start_turn(10)
        for at in (10.2, 10.5, 11, 12):
            clock.observe(3.0, .6, at)
        self.assertAlmostEqual(clock.remaining(12.5), .5)
        self.assertLess(clock.remaining(13.1), 0)

    def test_deadline_survives_a_temporarily_unreadable_clock(self):
        clock = TurnClock()
        clock.observe(2, .2, 10)
        clock.start_turn(10)
        self.assertAlmostEqual(clock.remaining(12.2), -.2)

    def test_stable_full_prompt_can_correct_a_wrong_phase_without_stalling(self):
        watch = BoardWatch()
        watch.observe("a", "theirs", now=0)
        watch.observe("abcting", "theirs", now=.1)
        self.assertFalse(watch.observe("ting", "ours", now=1)["play"])
        self.assertEqual(watch.observe("ting", "ours", now=1.21)["play"], "ting")

    def test_idle_played_latch_does_not_leave_your_turn_without_choices(self):
        app, face = make_app(("stone",))
        app._name = "player"
        app.watch.played = app._typing_prompt = "st"
        with patch.object(app_module.time, "monotonic", return_value=10):
            app._handle_frame(frame("st"))
        with patch.object(app_module.time, "monotonic", return_value=10.16):
            app._handle_frame(frame("st"))
            app._handle_frame(frame("st"))
        self.assertEqual(face.values["C1"], "1  stone")
        app._start_typing.assert_called_with("st")

    def test_live_timer_shortens_the_answer_without_changing_key_pace(self):
        app, _ = make_app(("beating", "beatifications"))
        app._typing_prompt = "beat"
        app._keys_now = "i"
        app._typing_plan = turn_plan("ifications", "beat", 12, random.Random(2).random)
        with patch.object(app, "_time_left", return_value=1.0), patch.object(app, "_launch_typing") as launch:
            app._check_deadline(frame("beati"), time.monotonic())
        self.assertEqual(launch.call_args.args[1], "beating")


class PerformanceTests(unittest.TestCase):
    def test_switch_is_persisted_and_does_not_change_the_typing_plan(self):
        app, face = make_app(("stone",))
        app._start_typing = app_module.AutotypeApp._start_typing.__get__(app)
        with patch.object(app, "_save_text") as save, patch.object(app, "_launch_typing"), \
             patch.object(app_module, "turn_plan", return_value=edit_plan("", "one")) as plan:
            app._start_typing("st")
            before = plan.call_args
            app.handle("PERFORMANCE", "")
            app._start_typing("st")
            self.assertEqual(plan.call_args, before)
            save.assert_called_with(app_module.PERFORMANCE_PATH, "on")
        self.assertEqual(face.values["PERFORMANCE"], "1")

    def test_real_accepted_word_bubble_is_read(self):
        path = Path(__file__).parent / "fixtures" / "accepted_clock.jpg"
        rgb = np.asarray(Image.open(path).convert("RGB"))
        words = BubbleReader().read(rgb)
        self.assertEqual([b["word"] for b in words], ["pox"])
        self.assertGreater(words[0]["confidence"], .9)

    def capture(self, grabs, high=False):
        """Run the capture loop over ``grabs``; returns frames and refresh requests."""
        grabs, frames, refreshes = list(grabs), [], []
        stop = threading.Event()

        def grab(refresh):
            refreshes.append(refresh)
            if not grabs:
                stop.set()
                return host.SAME_FRAME
            return grabs.pop(0)

        with patch.object(host, "_grab", side_effect=grab), patch.object(host.sys, "platform", "darwin"):
            host._run_portable(stop, frames.append, lambda status: None, lambda: "player",
                               performance_fn=lambda: high)
        return frames, refreshes

    def test_a_frame_is_never_read_twice_and_keeps_its_capture_time(self):
        image = Image.open(Path(__file__).parent / "fixtures" / "accepted_clock.jpg").convert("RGBA")
        shown = (image.tobytes(), *image.size, 41.5)
        frames, refreshes = self.capture([shown, host.SAME_FRAME, host.SAME_FRAME, shown])
        self.assertEqual(len(frames), 2)
        self.assertEqual([f["captured_at"] for f in frames], [41.5, 41.5])
        self.assertEqual(frames[0]["prompt"], "pox")
        self.assertNotIn("word_bubbles", frames[0])
        # Right after a read the same frame is not asked for again.
        self.assertEqual(refreshes[:2], [True, False])

    def test_high_performance_reads_like_the_base_reader_and_adds_speech_boxes(self):
        for path in sorted((Path(__file__).parent / "fixtures").glob("*")):
            with self.subTest(path=path.name):
                image = Image.open(path).convert("RGBA")
                image.thumbnail((1600, 1600))
                raw = image.tobytes()
                frames, _ = self.capture([(raw, *image.size, 7.0)], high=True)
                expected = tiles.scan_rgba(raw, *image.size, "player")
                for key in ("prompt", "tiles", "full", "header", "timer", "timer_frac", "alert"):
                    self.assertEqual(frames[0][key], expected[key], key)
                self.assertIn("word_bubbles", frames[0])
                if path.name == "accepted_clock.jpg":
                    self.assertEqual([b["word"] for b in frames[0]["word_bubbles"]], ["pox"])

    def test_busy_capture_queue_preserves_controls_and_final_opponent_word(self):
        app, _ = make_app(("kinging",))
        app._high_performance = True
        app._put_event("ACTION", ("PAUSE", ""))
        for count in range(1, 8):
            app._enqueue_frame(frame("kinging"[:count], "opponent"))
        for _ in range(16):
            app._enqueue_frame(frame("ging"))
        pending = list(app._queue.queue)
        self.assertIn(("ACTION", ("PAUSE", "")), pending)
        self.assertTrue(any(kind == "FRAME" and data["prompt"] == "kinging" for kind, data in pending))
        self.assertLessEqual(len(pending), 8)

    def test_bubble_completes_clipped_opponent_before_unscrambling(self):
        app, _ = make_app(("kinging", "ginger"))
        app._name = "player"
        app._high_performance = True
        for word in ("king", "kingin"):
            app._handle_frame(frame(word, "opponent"))
        evidence = [dict(word="kinging", confidence=.95, box=(1, 2, 3, 4))]
        app._handle_frame(dict(frame("gnign"), word_bubbles=evidence))
        app._handle_frame(dict(frame("gnign"), word_bubbles=evidence))
        app._start_typing.assert_called_with("ging")
        self.assertIn("kinging", app.engine.used_words)

    def test_a_misread_speech_box_letter_still_names_the_word(self):
        # A small Q reads best as O; G and Q score about as well.
        app, _ = make_app(("obsequy", "obsess"))
        options = (("o", "g"), ("b",), ("s",), ("e",), ("o", "g", "q"), ("u",), ("y",))
        self.assertEqual(app._bubble_words(dict(word="obseouy", options=options)), ["obsequy"])
        stray = tuple((c,) for c in "obse") + (("-", ""),) + tuple((c,) for c in "quy")
        self.assertEqual(app._bubble_words(dict(word="obse-quy", options=stray)), ["obsequy"])

    def test_their_speech_box_settles_the_word_they_entered(self):
        # They typed "elishas" and deleted the s; the corrected row was on
        # screen for less than a frame, but the box shows what was accepted.
        app, _ = make_app(("elisha", "elishas", "shadow"))
        app._name = "player"
        app._high_performance = True
        for board in ("eli", "elishas"):
            app._handle_frame(dict(frame(board, "opponent"), word_bubbles=[]))
        box = [dict(word="elisha", confidence=.95, options=tuple((c,) for c in "elisha"))]
        app._handle_frame(dict(frame("elishas", "opponent"), word_bubbles=box))
        app._handle_frame(dict(frame("sha", "opponent"), word_bubbles=box))
        self.assertEqual(app.watch.opponent_word, "elisha")
        # "sha" ends their word, so no wait for more tiles.
        app._handle_frame(frame("sha"))
        app._start_typing.assert_called_once_with("sha")

    def test_unrelated_or_preexisting_bubble_does_not_mark_a_word_used(self):
        app, _ = make_app(("kinging", "ginger", "walking"))
        app._name = "player"
        app._high_performance = True
        bubble = [dict(word="walking", confidence=.99)]
        app._handle_frame(dict(frame("king", "opponent"), word_bubbles=bubble))
        app._handle_frame(frame("kingin", "opponent"))
        for _ in range(3):
            app._handle_frame(dict(frame("ging"), word_bubbles=bubble))
        self.assertNotIn("walking", app.engine.used_words)

    def test_equal_strength_traps_rotate_across_games(self):
        app, _ = make_app(("preabc", "prexyz", "abca", "xyza"))
        s = app.session
        s.set_mode("pro")
        fixed = TrapStyle(123, "sharp", .75, 1, "short", 4)
        with patch.object(TrapStyle, "roll", return_value=fixed):
            s.new_game()
            first = s.choose("pre")[0]
            s.commit_play(first, "pre")
            s.new_game()
            second = s.choose("pre")[0]
        self.assertNotEqual(first, second)


class WindowsInputTests(unittest.TestCase):
    def api(self, scan):
        api = Mock()
        api.GetForegroundWindow.return_value = 11
        api.GetWindowThreadProcessId.return_value = 22
        api.GetKeyboardLayout.return_value = 33
        api.VkKeyScanExW.return_value = scan
        api.MapVirtualKeyExW.return_value = 0
        return api

    def test_punctuation_uses_game_layout_and_all_modifier_bits(self):
        api = self.api(0x600 | 0xBD)
        with patch.object(host, "_win_api", return_value=(api, None, None)), patch.object(host, "_win_send") as send:
            host._win_key("-", 0)
        api.VkKeyScanExW.assert_called_once_with("-", 33)
        self.assertEqual([c.args for c in send.call_args_list], [(0x11, False), (0x12, False),
                         (0xBD, False), (0xBD, True), (0x12, True), (0x11, True)])

    def test_dead_apostrophe_uses_literal_character_instead_of_an_accent(self):
        api = self.api(0xDE)
        api.MapVirtualKeyExW.return_value = 0x80000027
        with patch.object(host, "_win_api", return_value=(api, None, None)), patch.object(host, "_win_unicode") as literal:
            host._win_key("'", .022)
        literal.assert_called_once_with("'", .022)

    def test_modifier_is_released_when_key_down_fails(self):
        api = self.api(0x100 | 0xBD)
        events = []
        def send(key, up):
            events.append((key, up))
            if key == 0xBD and not up:
                raise OSError("key rejected")
        with patch.object(host, "_win_api", return_value=(api, None, None)), patch.object(host, "_win_send", side_effect=send):
            with self.assertRaises(OSError):
                host._win_key("-", 0)
        self.assertEqual(events[-1], (0x10, True))

    def test_windows_input_structure_has_the_native_abi_size(self):
        self.assertEqual(ctypes.sizeof(host._win_input_type()), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


class LinuxInputTests(unittest.TestCase):
    def test_punctuation_in_active_layout_uses_shift_and_altgr(self):
        for symbol, level in (("-", 1), ("'", 2), ("'", 3)):
            with self.subTest(symbol=symbol, level=level):
                x11, xtst = Mock(), Mock()
                def state(_display, _device, ptr):
                    ctypes.cast(ptr, ctypes.POINTER(host._XkbState)).contents.group = 1
                    return 0
                x11.XkbGetState.side_effect = state
                x11.XKeysymToKeycode.side_effect = lambda _d, s: {0xFFE1: 50, 0xFE03: 108}.get(s, 20)
                x11.XkbKeycodeToKeysym.side_effect = lambda _d, c, g, n: ord(symbol) if (c, g, n) == (48, 1, level) else 0
                xtst.XTestFakeKeyEvent.return_value = 1
                with patch.object(host, "_linux_display", return_value=(x11, 11)), \
                     patch.object(host.ctypes, "CDLL", return_value=xtst):
                    host._linux_key(symbol, 0)
                downs = ([108] if level >= 2 else []) + ([50] if level % 2 else []) + [48]
                self.assertEqual([(c.args[1], c.args[2]) for c in xtst.XTestFakeKeyEvent.call_args_list],
                                 [(c, True) for c in downs] + [(c, False) for c in reversed(downs)])
                x11.XCloseDisplay.assert_called_once_with(11)


@unittest.skipUnless(sys.platform == "darwin", "macOS keyboard events")
class MacInputTests(unittest.TestCase):
    def test_typed_keys_carry_their_character_whatever_the_layout(self):
        from autotype import mac_input
        sent = []

        def text(_event, count, chars):
            sent.append("".join(chr(chars[i]) for i in range(count)))

        with patch.object(mac_input._CG, "CGPreflightPostEventAccess", return_value=True, create=True), \
             patch.object(mac_input._CG, "CGEventCreateKeyboardEvent", return_value=1), \
             patch.object(mac_input._CG, "CGEventPost"), \
             patch.object(mac_input._CG, "CGEventKeyboardSetUnicodeString", side_effect=text), \
             patch.object(mac_input._CF, "CFRelease"), patch.object(mac_input.time, "sleep"):
            for ch in "-'a":
                mac_input.tap_key("type", ch, 0)
            mac_input.tap_key("back", "", 0)
        # Down and up for each character; Backspace is a key, not text.
        self.assertEqual(sent, ["-", "-", "'", "'", "a", "a"])


if __name__ == "__main__":
    unittest.main()
