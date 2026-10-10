from __future__ import annotations

import unittest

from autotype.session import BoardWatch, MatchSession, prompt_lengths
from autotype.test_regressions import frame, make_app

WORDS = ('kinging', 'kingdom', 'kings', 'kingship', 'gingham', 'ginger', 'stone', 'star')


def session(words=WORDS):
    app, _ = make_app(words)
    return app.session


class DescrambleTests(unittest.TestCase):
    def test_phase_is_the_given_prefix_length(self):
        self.assertEqual(prompt_lengths(4), [4])
        self.assertEqual(prompt_lengths(3), [3, 4])
        self.assertEqual(prompt_lengths(0, 2), [2, 3])
        self.assertEqual(prompt_lengths(0, 5), [])

    def test_extra_letter_and_shuffled_order_resolve_to_the_ending(self):
        s = session()
        self.assertEqual(s.descramble_prompt('gnigk', 'kinging', 'king'), 'ging')
        self.assertEqual(s.descramble_prompt('kgnig', 'kinging', 'king'), 'ging')
        self.assertEqual(s.descramble_prompt('gnig', 'kinging', 'king'), 'ging')
        self.assertEqual(s.descramble_prompt('gnigkx', 'kinging', 'king'), 'ging')

    def test_the_phase_picks_the_length(self):
        s = session()
        # Phase 3 (prefix "kin") expects a 3 letter ending, not "ging".
        self.assertEqual(s.descramble_prompt('gnigk', 'kinging', 'kin'), 'ing')
        # Only one letter of the 4 letter ending is available, so it is not it.
        self.assertEqual(s.descramble_prompt('gniab', 'kinging', 'king'), '')

    def test_clean_reads_are_never_touched(self):
        s = session()
        self.assertEqual(s.descramble_prompt('ging', 'kinging', 'king'), '')
        self.assertEqual(s.descramble_prompt('kingi', 'kinging', 'king'), '')
        self.assertEqual(s.descramble_prompt('kinging', 'kinging', 'king'), '')
        self.assertEqual(s.descramble_prompt('king', '', 'king'), '')

    def test_unrelated_letters_are_not_forced_into_an_ending(self):
        s = session()
        self.assertEqual(s.descramble_prompt('zzqxy', 'kinging', 'king'), '')
        self.assertEqual(s.descramble_prompt('gnigk', '', ''), '')

    def test_clipped_word_is_completed_from_the_dictionary(self):
        s = session()
        # The capture only ever saw "kingin" before the board shuffled.
        self.assertEqual(s.descramble_prompt('gnigk', 'kingin', 'king', ['kingi', 'kingin']), 'ging')

    def test_used_words_are_not_candidates_for_a_clipped_word(self):
        s = session()
        s.engine.mark_used('kinging')
        self.assertEqual(s.descramble_prompt('gnigk', 'kingin', 'king', ['kingin']), '')

    def test_ambiguous_clipped_word_is_left_alone(self):
        s = session(('kingdom', 'kingmod', 'kingship'))
        self.assertEqual(s.descramble_prompt('odmxx', 'king', 'king', ['kingd']), '')


class WatchTests(unittest.TestCase):
    def test_glitched_read_does_not_replace_their_word(self):
        watch = BoardWatch()
        watch.observe('king', 'theirs')
        watch.observe('kingi', 'theirs')
        watch.observe('kinging', 'theirs')
        watch.observe('gnigk', 'theirs')
        self.assertEqual(watch.opponent_word, 'kinging')
        self.assertEqual(watch.scramble_context(), ('kinging', 'king', ['king', 'kingi', 'kinging']))

    def test_no_context_between_turns(self):
        self.assertIsNone(BoardWatch().scramble_context())


class AppTests(unittest.TestCase):
    def play(self, board_after_word):
        app, _ = make_app(WORDS)
        app._name = 'player'
        for board in ('king', 'kingi', 'kinging'):
            app._handle_frame(frame(board, 'opponent'))
        app._handle_frame(frame(board_after_word, 'player'))
        app._handle_frame(frame(board_after_word, 'player'))
        return app

    def test_glitched_prompt_is_solved_and_typed(self):
        app = self.play('gnigk')
        app._start_typing.assert_called_with('ging')
        self.assertEqual(app.watch.opponent_word, 'kinging')
        self.assertIn('kinging', app.engine.used_words)

    def test_shuffled_same_length_prompt_is_solved_too(self):
        app = self.play('gnig')
        app._start_typing.assert_called_with('ging')

    def test_a_clean_prompt_still_works(self):
        app = self.play('ging')
        app._start_typing.assert_called_with('ging')

    def test_glitch_while_the_header_still_names_them(self):
        app, _ = make_app(WORDS)
        app._name = 'player'
        for board in ('king', 'kingi', 'kinging', 'gnigk', 'gnigk'):
            app._handle_frame(frame(board, 'opponent'))
        self.assertEqual(app.watch.opponent_word, 'kinging')
        app._handle_frame(frame('ging', 'player'))
        app._handle_frame(frame('ging', 'player'))
        app._start_typing.assert_called_with('ging')


if __name__ == '__main__':
    unittest.main()
