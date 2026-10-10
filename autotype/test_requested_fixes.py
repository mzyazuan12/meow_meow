"""Regression coverage for top-edge tiles, skills, selection and submission."""
import random
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import numpy as np
from autotype.glyphs import read_tile
from autotype.test_ocr import _TILES, _frame
from autotype.tiles import scan_rgba
from autotype.session import BoardWatch, MatchSession
from autotype.featherine import human_plan, turn_plan
from autotype.test_regressions import make_app, frame, app_module
from dyoe2_engine import Dyoe2Engine, TrapPools, normalize_hybrid_suffixes

class RequestedFixTests(unittest.TestCase):
    def test_top_edge_q_screenshot(self):
        source = Image.open(Path(__file__).parent / 'fixtures/top_edge_q.png').convert('RGBA')
        for width in (640, 924, 1600):
            im = source.resize((width, round(source.height * width / source.width)))
            result = scan_rgba(im.tobytes(), *im.size)
            self.assertEqual(result['prompt'], 'q')
            self.assertTrue(result['full'])

    def test_all_atlas_letters_and_punctuation_transformed(self):
        for char, im in _TILES.items():
            for size in (36, 60, 90):
                sample = np.asarray(Image.fromarray(im).resize((size, size), Image.Resampling.LANCZOS))
                for transformed in (sample, sample[::-1, ::-1], sample[:, ::-1], sample[::-1]):
                    self.assertEqual(read_tile(transformed), char)

    def test_reverse_only_when_forward_has_no_solves(self):
        s = MatchSession(Dyoe2Engine(['kingdom', 'gnikfoo'], validate_giveable=False))
        self.assertEqual(s.choose('gnik')[0], 'gnikfoo')
        s.engine.set_words(['kingdom'], validate_giveable=False)
        self.assertEqual(s.choose('gnik')[:2], ('kingdom', 'dom'))

    def test_opponent_ending_decides_a_mirrored_prompt(self):
        s = MatchSession(Dyoe2Engine(['telephone', 'telex', 'eletfoo'], validate_giveable=False))
        s.opponent_word = 'prevelet'
        self.assertEqual(s.resolve_prefix('tele'), 'elet')
        self.assertEqual(s.resolve_prefix('elet'), 'elet')
        self.assertEqual(s.choose('tele')[0], 'eletfoo')
        # Their word ended in tele, so a readable tele is not flipped. Their
        # word itself is used, so the other tele word answers it.
        s.opponent_word = 'telephone'
        self.assertEqual(s.resolve_prefix('tele'), 'tele')
        self.assertEqual(s.choose('tele')[0], 'telex')
        # No dictionary hit for elet must not undo an ending of elet.
        s.engine.set_words(['telephone', 'telex'], validate_giveable=False)
        s.opponent_word = 'prevelet'
        self.assertEqual(s.resolve_prefix('tele'), 'elet')
        s.opponent_word = ''
        self.assertEqual(s.resolve_prefix('tele'), 'tele')

    def test_garbled_tail_still_decides_direction_from_its_first_letters(self):
        s = MatchSession(Dyoe2Engine(['kickoffs', 'kicking', 'sfumato', 'fsfoo'], validate_giveable=False))
        # They typed kickoffs; the capture only saw kickkf. kick... can end in
        # fs but never in sf, so the sf on the board is the mirrored fs.
        s.opponent_word = 'kickkf'
        self.assertEqual(s.resolve_prefix('sf'), 'fs')
        # When the head can end in sf, the reading stays as it is.
        s.engine.set_words(['kicksf', 'sfumato', 'fsfoo'], validate_giveable=False)
        self.assertEqual(s.resolve_prefix('sf'), 'sf')
        # Both directions possible: nothing is decided from the head alone.
        s.engine.set_words(['kickoffs', 'kicksf', 'sfumato'], validate_giveable=False)
        self.assertEqual(s.resolve_prefix('sf'), 'sf')
        s.opponent_word = ''
        self.assertEqual(s.resolve_prefix('sf'), 'sf')

    def test_garbled_word_is_still_recovered_from_head_and_ending(self):
        s = MatchSession(Dyoe2Engine(['kickoffs', 'kicking'], validate_giveable=False))
        self.assertEqual(s.recover_partial(['kickkf'], 'fs', 'ki'), 'kickoffs')

    def test_mirrored_prompt_is_played_from_the_opponents_ending(self):
        app, _ = make_app(('eletfoo', 'telephone'))
        app._name = 'player'
        app._handle_frame(frame('prevelet', 'opponent'))
        app._handle_frame(frame('tele'))
        app._handle_frame(frame('tele'))
        app._start_typing.assert_called_with('elet')

    def test_only_their_words_ending_skips_the_second_read(self):
        w = BoardWatch()
        w.observe('prevelet', 'theirs', now=0)
        self.assertEqual(w.observe('elet', 'ours', now=0.1)['play'], 'elet')
        w = BoardWatch()
        w.observe('prevelet', 'theirs', now=0)
        self.assertEqual(w.observe('tele', 'ours', now=0.1)['play'], '')
        self.assertEqual(w.observe('tele', 'ours', now=0.2)['play'], 'tele')

    def test_opponent_word_follows_a_backspaced_correction(self):
        w = BoardWatch()
        for board in ('pre', 'prevelets', 'prevelet'):
            w.observe(board, 'theirs')
        self.assertEqual(w.opponent_word, 'prevelet')
        # The collapsed prompt while the header lags is not their word.
        w.observe('tele', 'theirs')
        self.assertEqual(w.opponent_word, 'prevelet')

    def test_self_solve_sometimes_and_enter_without_keys(self):
        s = MatchSession(Dyoe2Engine(['king', 'kingdom'], validate_giveable=False))
        with patch('autotype.session.random.random', return_value=0):
            self.assertEqual(s.choose('king')[:2], ('king', ''))
        with patch('autotype.session.random.random', return_value=0.9):
            self.assertEqual(s.choose('king')[0], 'kingdom')
        app, _ = make_app(('king',))
        app._name = 'player'
        app._typing_prompt = app.watch.played = 'king'
        with patch.object(app_module, 'press_enter') as enter:
            app._process_event('SUBMIT', (app._gen, 'king', 0))
            enter.assert_called_once()
        plan = turn_plan('', 'king', 5, random.Random(0).random)
        self.assertEqual([s.kind for s in plan.steps], ['enter'])

    def test_missing_letters_never_hold_back_enter_or_clear_the_answer(self):
        word = 'electroencephalographically'
        app, _ = make_app((word, 'enter'))
        app._name = 'player'
        app._typing_prompt = app.watch.played = 'e'
        reading = word[:8] + '?' + word[9:]
        with patch.object(app, '_clear_input') as clear, patch.object(app_module, 'press_enter') as enter:
            app._process_event('SUBMIT', (app._gen, word, len(word)-1))
            app._handle_frame(frame(reading, full=False))
            app._handle_frame(frame('', full=False))
            app._handle_frame(frame(reading, full=False))
            clear.assert_not_called()
            enter.assert_called_once()

    def test_fewest_solves_and_no_unused_self_solve(self):
        traps = TrapPools(casual_3=['abc', 'xyz'], pro_3=['abc', 'xyz'])
        words = ['preabc', 'prexyz', 'abc', 'abcd', 'xyza']
        for mode in ('casual', 'pro', 'spam'):
            s = MatchSession(Dyoe2Engine(words, traps, validate_giveable=False))
            s.set_mode(mode)
            self.assertEqual(s.choose('pre')[0], 'prexyz')

    def test_traps_before_cancel_before_remaining(self):
        words = ['ismafoo', 'ismafar', 'ismbfoo', 'ismbfar', 'ismcxyz', 'ismdbar']
        s = MatchSession(Dyoe2Engine(words, TrapPools(casual_3=['xyz']), validate_giveable=False))
        self.assertEqual(s.choose('ism')[0], 'ismcxyz')
        s.engine.mark_used('ismcxyz')
        self.assertEqual(s.choose('ism')[0], 'ismdbar')

    def test_brackets_punctuation_and_rhythm(self):
        self.assertEqual(normalize_hybrid_suffixes('[ing][ary] (ness), ous'), ('ing','ary','ness','ous'))
        s = MatchSession(Dyoe2Engine(["a-b'c"], validate_giveable=False))
        self.assertEqual(s.choose('a'), ('', '', None, 1))
        s.set_mode('pro')
        self.assertEqual(s.choose('a')[1], "-b'c")
        profiles = set()
        for seed in range(20):
            plan = human_plan("a-b'cdefgh", 'player', random.Random(seed).random)
            profiles.add(tuple(step.delay for step in plan.steps))
            self.assertEqual(plan.steps[-1].typed, "a-b'cdefgh")
            self.assertGreater(len(set(step.delay for step in plan.steps[1:])), 1)
        self.assertEqual(len(profiles), 20)

    def test_recover_without_final_capture_and_combine_unknowns(self):
        s = MatchSession(Dyoe2Engine(['extraordinarily'], validate_giveable=False))
        self.assertEqual(s.recover_partial(['ex'], 'ily', 'e'), 'extraordinarily')
        s.engine.clear_used()
        self.assertEqual(s.recover_partial(['extra?rdinarily', 'extrao?dinarily'], 'ily', 'e'), 'extraordinarily')

    def test_first_opponent_frame_after_enter_is_retained(self):
        app, _ = make_app(('stone', 'extraordinarily'))
        app._name = 'player'
        app._typing_prompt = app.watch.played = 's'
        app.watch.pending = app.watch.typed = app._typed_word = 'stone'
        # No intermediate opponent-prefix frame was captured.
        app._handle_frame(frame('extraordinarily', 'opponent'))
        app._handle_frame(frame('ily'))
        app._handle_frame(frame('ily'))
        self.assertEqual(app.engine.used_words, {'stone', 'extraordinarily'})
        app._start_typing.assert_called_with('ily')

    def test_clipped_row_is_not_a_reason_to_delete_long_word(self):
        word = 'electroencephalographically'
        app, _ = make_app((word,))
        app._name = 'player'
        app._typing_prompt = app.watch.played = 'e'
        app._process_event('SUBMIT', (app._gen, word, len(word) - 1, time.monotonic() - 2))
        with patch.object(app, '_clear_input') as clear:
            for _ in range(3):
                app._handle_frame(dict(frame('electro'), row_complete=False))
            clear.assert_not_called()

    def test_easy_plural_traps_come_after_harder_ones_until_those_run_out(self):
        pools = TrapPools(casual_3=['abc', 'xyz'], pro_3=['abc', 'xyz'])
        for mode in ('casual', 'pro'):
            s = MatchSession(Dyoe2Engine(['preabc', 'prexyz', 'abcs', 'xyza', 'xyzb'], pools, validate_giveable=False))
            s.set_mode(mode)
            self.assertEqual(s.choose('pre')[0], 'prexyz')
            # Two hand-overs of xyz have used both of its solves.
            s.given['xyz'] = 2
            self.assertEqual(s.choose('pre')[0], 'preabc')

    def test_trap_counts_exclude_the_word_we_are_about_to_use(self):
        pools = TrapPools(casual_3=['abc', 'xyz'])
        s = MatchSession(Dyoe2Engine(['abcabc', 'abcxyz', 'xyza'], pools, validate_giveable=False))
        # abc has only abcxyz left after abcabc is played; xyz has xyza.
        # The tie must no longer count abcabc as an opponent response.
        self.assertEqual(s.choices('abc', 2), ['abcabc', 'abcxyz'])

    def test_rhythms_change_for_the_same_username(self):
        rhythms = {human_plan('extraordinarily', 'player', random.Random(seed).random).rhythm
                   for seed in range(40)}
        self.assertGreaterEqual(len(rhythms), 3)

    def test_reverse_prefix_verifies_suffix_and_recovers_dropped_deletion(self):
        app, _ = make_app(('kingdom',))
        app._name = 'player'
        app._typing_prompt = app.watch.played = 'king'
        with patch.object(app_module, 'press_enter') as enter:
            app._process_event('SUBMIT', (app._gen, 'kingdom', 3))
            app._handle_frame(frame('gnikdom'))
            app._handle_frame(frame('gnikdom'))
            enter.assert_called_once()
        app._typed_word = app.watch.typed = ''
        app._clear = dict(gen=app._gen, prompt='king', word='kingdom', after=0,
                          read_at=0, board='', hits=0, working=False)
        app._erasing = app._needs_clear = True
        with patch.object(app, '_erase_suffix') as erase:
            app._handle_frame(frame('gnikd'))
            app._handle_frame(frame('gnikd'))
            erase.assert_called_once_with(app._gen, 'king', 1, app._type_cancel)

    def test_old_reverse_prefix_cannot_rewrite_opponents_word(self):
        app, _ = make_app(('absorb', 'bacteria'))
        app._name = 'player'
        app._typing_prompt = app.watch.played = 'ab'
        app.watch.pending = app.watch.typed = app._typed_word = 'absorb'
        app._handle_frame(frame('bacteria', 'opponent'))
        app._handle_frame(frame('ria'))
        app._handle_frame(frame('ria'))
        self.assertIn('bacteria', app.engine.used_words)

    def test_single_letter_never_submits_itself(self):
        s = MatchSession(Dyoe2Engine(['t', 'tree'], validate_giveable=False))
        with patch('autotype.session.random.random', return_value=0):
            self.assertEqual(s.choose('t')[:2], ('tree', 'ree'))
        s.engine.set_words(['t'], validate_giveable=False)
        self.assertEqual(s.choose('t')[0], '')

    def test_longest_word_is_entered_and_stored_though_its_tiles_are_clipped(self):
        word = 'taumatawhakatangihangakoauauotamateaturipukakapikimaungahoronukupokaiwhenuakitanatahu'
        image = _frame(word, 1600, 1000, 18)
        reading = scan_rgba(image.tobytes(), *image.size)
        self.assertTrue(reading['row_clipped'])
        self.assertIn('?', reading['prompt'])
        app, _ = make_app((word,))
        app._name = 'player'
        app._typing_prompt = app.watch.played = 't'
        reading['header'] = frame('t')['header']
        with patch.object(app_module, 'press_enter') as enter:
            app._process_event('SUBMIT', (app._gen, word, len(word) - 1))
            app._handle_frame(reading)
            app._handle_frame(reading)
            enter.assert_called_once()
        app._handle_frame(frame('ahu', 'opponent'))
        self.assertIn(word, app.engine.used_words)

    def test_no_early_enter_on_short_or_unrelated_partial_row(self):
        app, _ = make_app(('stone',))
        app._name = 'player'
        app._typing_prompt = app.watch.played = 's'
        app._process_event('SUBMIT', (app._gen, 'stone', 4, time.monotonic() - 2))
        with patch.object(app_module, 'press_enter') as enter:
            for _ in range(3):
                app._handle_frame(dict(frame('sto', full=False), row_clipped=True, row_complete=False))
            enter.assert_not_called()

    def test_longest_word_has_human_pace_and_correct_final_text(self):
        word = 'taumatawhakatangihangakoauauotamateaturipukakapikimaungahoronukupokaiwhenuakitanatahu'
        for seed in range(60):
            plan = human_plan(word, 'player', random.Random(seed).random)
            self.assertEqual(plan.steps[0].delay, 0)
            duration = sum(max(.022, step.delay) for step in plan.steps[1:]) + plan.end_pause
            self.assertGreaterEqual(duration, 9)
            self.assertLess(duration, 12.5)
            shown = ''
            for step in plan.steps:
                if step.kind == 'type':
                    shown += step.key
                elif step.kind == 'back':
                    shown = shown[:-1]
                self.assertEqual(shown, step.typed)
            self.assertEqual(shown, word)
            self.assertLessEqual(sum(step.kind == 'enter' for step in plan.steps), 1)

    def test_full_queue_retains_latest_turn_and_actions(self):
        app, _ = make_app()
        app._enqueue_roblox('up')
        for i in range(50):
            app._enqueue_frame(frame(f's{i}'))
        app._put_event('ACTION', ('CONFIRM', ''))
        events = list(app._queue.queue)
        self.assertLessEqual(len(events), app._queue.maxsize)
        self.assertIn(('ROBLOX', 'up'), events)
        self.assertEqual(events[-1], ('ACTION', ('CONFIRM', '')))
        self.assertEqual([item[1]['prompt'] for item in events if item[0] == 'FRAME'][-1], 's49')

    def test_unreadable_new_prompt_clears_stale_choices(self):
        app, face = make_app(('stone', 'nest'))
        app._name = 'player'
        app._handle_frame(frame('s'))
        self.assertIn('stone', face.values['C1'])
        app._handle_frame(frame('????', full=False))
        self.assertEqual(face.values['C1'], '—')
        app._handle_frame(frame('n'))
        self.assertIn('nest', face.values['C1'])

if __name__ == '__main__':
    unittest.main()
