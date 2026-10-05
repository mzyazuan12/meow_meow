from __future__ import annotations

import importlib.machinery
import importlib.util
import queue
import random
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from autotype.featherine import human_plan
from autotype.host import _fit_frame, _parse_frame, _shrink_rgba
from autotype.session import BoardWatch, MatchSession, header_is_ours, names_match, speaker_from_header
from dyoe2_engine import Dyoe2Engine, TrapPools

ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader('autotype_app_test', str(ROOT / 'autotype_app.pyw'))
spec = importlib.util.spec_from_loader(loader.name, loader)
app_module = importlib.util.module_from_spec(spec)
loader.exec_module(app_module)


class Face:
    def __init__(self):
        self.values = {}
    def send(self, key, value=''):
        self.values[key] = value


def make_app(words=('stone', 'star', 'mhorr', 'mhos', 'rabbit', 'nesting')):
    face = Face()
    with patch.object(app_module.AutotypeApp, '_load_text', side_effect=lambda path, default: default):
        app = app_module.AutotypeApp(face=face, start_services=False)
    app.engine.set_words(words, traps=TrapPools(), validate_giveable=False)
    app.engine.cancelled_prompts.clear()
    app.ready = True
    app._count = len(words)
    app._roblox = 'up'
    app.armed = True
    app._start_typing = unittest.mock.Mock()
    return app, face


def frame(board, speaker='player', full=True, error=''):
    return {'prompt': board, 'header': f'{speaker}, type an english word starting with:',
            'tiles': len(board), 'full': full, 'error': error}


class TurnRegressionTests(unittest.TestCase):
    def test_exact_short_and_split_names_and_ocr_confusions(self):
        self.assertTrue(names_match('ab', 'ab'))
        self.assertEqual(speaker_from_header('guga2323332,type an engIish word starting with:'), 'guga2323332')
        self.assertEqual(speaker_from_header('f g _p _ ga2323332, type an english word starting with:'), 'ga2323332')
        self.assertTrue(header_is_ours('QY_player101', 'OV_playerl0l, type an english word starting with:'))
        self.assertFalse(names_match('player123456', 'enemy123456'))
        self.assertFalse(names_match('playername', 'play'))
        self.assertFalse(names_match('player1', 'player2'))
        self.assertEqual(speaker_from_header('60,610 | player, type an english word starting with:'), 'player')

    def test_no_timer_delay_and_no_duplicate_play(self):
        watch = BoardWatch()
        self.assertFalse(watch.observe('st', 'ours', tiles=2, now=0)['play'])
        self.assertEqual(watch.observe('st', 'ours', tiles=2, now=0.016)['play'], 'st')
        watch.played = 'st'
        self.assertFalse(watch.observe('st', 'ours', tiles=2, now=0.032)['play'])

    def test_complete_tile_count_required(self):
        watch = BoardWatch()
        watch.observe('w', 'ours', tiles=1)
        self.assertFalse(watch.observe('wo', 'ours', tiles=3)['play'])
        self.assertFalse(watch.observe('wo?', 'ours', tiles=3, complete=False)['play'])
        self.assertFalse(watch.observe('wow', 'ours', tiles=3)['play'])
        self.assertEqual(watch.observe('wow', 'ours', tiles=3)['play'], 'wow')

    def test_short_word_does_not_become_prompt_during_header_transition(self):
        watch = BoardWatch()
        watch.observe('c', 'theirs')
        watch.observe('cat', 'theirs')
        for _ in range(3):
            self.assertFalse(watch.observe('cat', 'ours')['play'])
        watch.observe('t', 'ours')
        event = watch.observe('t', 'ours')
        self.assertEqual(event['play'], 't')
        self.assertIn('cat', event['partials'])

    def test_multiletter_prefix_plays_when_header_lags_the_tiles(self):
        # Their prefix was one letter. The next prefix "is" is already up
        # while the header still names them. That must type without a key.
        watch = BoardWatch()
        watch.observe('a', 'theirs')
        watch.observe('apple', 'theirs')
        watch.observe('is', 'theirs')
        self.assertFalse(watch.observe('is', 'ours')['play'])
        self.assertEqual(watch.observe('is', 'ours')['play'], 'is')

    def test_settled_multiletter_prefix_plays_without_a_longer_word(self):
        watch = BoardWatch()
        watch.observe('a', 'theirs')
        watch.observe('is', 'theirs')
        self.assertFalse(watch.observe('is', 'ours', now=10)['play'])
        self.assertFalse(watch.observe('is', 'ours', now=10.1)['play'])
        self.assertEqual(watch.observe('is', 'ours', now=10.3)['play'], 'is')

    def test_growing_prefix_replaces_the_shorter_latch(self):
        watch = BoardWatch()
        watch.observe('i', 'ours')
        self.assertEqual(watch.observe('i', 'ours')['play'], 'i')
        watch.played = 'i'
        self.assertFalse(watch.observe('is', 'ours')['play'])
        self.assertEqual(watch.observe('is', 'ours')['play'], 'is')

    def test_unknown_header_never_types(self):
        watch = BoardWatch()
        for _ in range(3):
            self.assertFalse(watch.observe('s', '')['play'])

    def test_multiletter_prefix_types_when_the_header_lags(self):
        app, _ = make_app()
        app._name = 'player'
        app._handle_frame(frame('a', 'opponent'))
        app._handle_frame(frame('apple', 'opponent'))
        app._handle_frame(frame('is', 'opponent'))
        app._handle_frame(frame('is'))
        app._handle_frame(frame('is'))
        app._start_typing.assert_called_once_with('is')

    def test_aborted_multiletter_prompt_survives_a_missed_tile(self):
        app, _ = make_app()
        app._name = 'player'
        app.watch.turn = 'ours'
        app.watch.pending = 'is'
        app._shown = 'is'
        app._aborted_prompt = 'is'
        app._typing_prompt = 'is'
        app._handle_frame(frame('i'))
        app._start_typing.assert_not_called()
        self.assertEqual(app._aborted_prompt, 'is')
        app._handle_frame(frame('is'))
        app._start_typing.assert_called_once_with('is')

    def test_manual_name_edit_rechecks_current_frame_immediately(self):
        app, face = make_app()
        app._handle_frame(frame('s'))
        self.assertIn('THEIR TURN', face.values['TURN'])
        app.handle('NAME', 'player')
        self.assertEqual(face.values['TURN'], 'YOUR TURN')
        app._start_typing.assert_called_once_with('s')

    def test_confirmation_learns_username_for_this_session(self):
        app, face = make_app()
        app._handle_frame(frame('s', 'p1ayer'))
        app.handle('CONFIRM', '')
        self.assertEqual(app._name, 'p1ayer')
        self.assertEqual(face.values['NAME'], 'p1ayer')
        self.assertEqual(face.values['TURN'], 'YOUR TURN')
        app._start_typing.assert_called_once_with('s')
        fresh, _ = make_app()
        self.assertEqual(fresh._name, '')
        self.assertFalse(fresh._aliases)

    def test_acceptance_while_typing_finishes_is_not_missed(self):
        app, _ = make_app()
        app._name = 'player'
        app.watch.pending = 's'
        app.watch.played = 's'
        app.typing = True
        app._current_turn = 'ours'
        with patch.object(app_module, 'roblox_focused', return_value=True), patch.object(app_module, 'press_enter'):
            app._process_event('SUBMIT', (app._gen, 'stone', 4))
        app._handle_frame(frame('e', 'opponent'))
        self.assertEqual(app.engine.used_words, {'stone'})
        self.assertEqual(app.session.round, 2)
        app._handle_frame(frame('e', 'opponent'))
        self.assertEqual(app.session.round, 2)

    def test_the_same_prefix_can_be_played_on_the_next_turn(self):
        watch = BoardWatch()
        watch.observe('s', 'ours')
        watch.observe('s', 'ours')
        watch.played, watch.typed = 's', 'stones'
        self.assertTrue(watch.observe('s', 'theirs')['accepted'])
        watch.observe('s', 'theirs')
        watch.observe('stars', 'theirs')
        watch.observe('s', 'ours')
        self.assertEqual(watch.observe('s', 'ours')['play'], 's')

    def test_roblox_loss_cancels_active_keys_and_disarms(self):
        app, face = make_app()
        app.typing = True
        cancel = app._type_cancel
        app._apply_roblox('down')
        self.assertTrue(cancel.is_set())
        self.assertFalse(app.typing)
        self.assertFalse(app.armed)
        self.assertEqual(face.values['STATUS'], "ROBLOX ISN'T AVAILABLE")

    def test_permission_failure_is_visible_and_does_not_retry_forever(self):
        app, face = make_app()
        app.typing = True
        app._process_event('TYPE_DONE', (app._gen, False, 0, 'Typing failed: Allow Accessibility'))
        self.assertFalse(app.armed)
        self.assertFalse(app.typing)
        self.assertEqual(face.values['STATUS'], "KEYBOARD CONTROL ISN'T AVAILABLE")
        app._handle_frame(frame('s'))
        app._handle_frame(frame('s'))
        app._start_typing.assert_not_called()

    def test_retry_excludes_only_the_rejected_attempt(self):
        app, _ = make_app()
        app.watch.played = app._shown = 's'
        app.watch.typed = app._typed_word = 'stone'
        with patch.object(app, '_clear_input') as clear:
            app._schedule_retry('stone', used=False)
        clear.assert_called_once_with('s')
        self.assertIn('stone', app.engine.rejected_words)
        self.assertNotIn('stone', app.engine.used_words)
        self.assertFalse(app._typed_word)

    def test_already_used_error_is_added_to_used_words(self):
        app, _ = make_app()
        app.watch.played = app._shown = 's'
        with patch.object(app, '_clear_input'):
            app._schedule_retry('stone', used=True)
        self.assertIn('stone', app.engine.used_words)

    def test_capture_queue_does_not_drop_status_or_accepted_word(self):
        app, _ = make_app()
        app._enqueue_roblox('up')
        for reading in ('m', 'mho', 'mhorr', 'r'):
            app._enqueue_frame(frame(reading))
        self.assertEqual(app._queue.get_nowait(), ('ROBLOX', 'up'))
        self.assertEqual([app._queue.get_nowait()[1]['prompt'] for _ in range(4)], ['m', 'mho', 'mhorr', 'r'])
        self.assertLessEqual(app._queue.maxsize, 128)


class WordRegressionTests(unittest.TestCase):
    def setUp(self):
        engine = Dyoe2Engine(['mho', 'mhos', 'mhorr', 'mhorrs', 'cat', 'at', 'nesting', 'nectarine',
                             'wxyzaing', 'wxyzbing'], traps=TrapPools(), validate_giveable=False)
        self.session = MatchSession(engine)

    def test_mho_completed_from_the_next_prefix(self):
        self.assertEqual(self.session.recover_partial(['m', 'mh', 'mho'], 'r', 'm'), 'mhorr')
        self.assertEqual(self.session.engine.used_words, {'mhorr'})

    def test_short_accepted_words_are_kept(self):
        watch = BoardWatch()
        watch.observe('a', 'theirs')
        watch.observe('at', 'theirs')
        watch.observe('t', 'ours')
        event = watch.observe('t', 'ours')
        self.assertEqual(self.session.recover_partial(event['partials'], event['ending'], event['given']), 'at')

    def test_attach_mid_turn_keeps_a_short_complete_word(self):
        watch = BoardWatch()
        watch.observe('cat', 'theirs')
        watch.observe('t', 'ours')
        event = watch.observe('t', 'ours')
        self.assertEqual(self.session.recover_partial(event['partials'], event['ending'], event['given']), 'cat')

    def test_missing_slots_do_not_shift_or_discard_the_rest_of_the_word(self):
        watch = BoardWatch()
        watch.observe('n', 'theirs')
        watch.observe('nectar?ne', 'theirs', tiles=9, complete=False)
        watch.observe('ne', 'ours')
        event = watch.observe('ne', 'ours')
        self.assertEqual(self.session.recover_partial(event['partials'], event['ending'], event['given']), 'nectarine')

    def test_shorter_valid_fragment_is_not_stored_instead_of_full_word(self):
        self.assertEqual(self.session.recover_partial(['mho', 'mhorr'], 'r', 'm'), 'mhorr')
        self.assertNotIn('mho', self.session.engine.used_words)

    def test_both_prefixes_must_fit(self):
        self.assertEqual(self.session.recover_partial(['mho'], 'r', 'n'), '')
        self.assertEqual(self.session.recover_partial(['mhorr'], 't', 'm'), '')
        self.assertFalse(self.session.engine.used_words)

    def test_ambiguous_completion_stays_unresolved(self):
        self.assertEqual(self.session.recover_partial(['wxyz'], 'ing', 'w'), '')

    def test_app_recovers_opponent_before_selecting_our_word(self):
        app, _ = make_app()
        app._name = 'player'
        for board in ('m', 'mho'):
            app._handle_frame(frame(board, 'opponent'))
        app._handle_frame(frame('r'))
        app._handle_frame(frame('r'))
        self.assertEqual(app.engine.used_words, {'mhorr'})
        app._start_typing.assert_called_once_with('r')

    def test_rejected_word_is_excluded_but_not_counted_as_used(self):
        engine = self.session.engine
        engine.mark_rejected('mhorr')
        self.assertFalse(engine.used_words)
        self.assertNotIn('mhorr', engine.prefix_candidates('m'))
        engine.clear_used()
        self.assertIn('mhorr', engine.prefix_candidates('m'))

    def test_spam_rotates_used_words_and_obeys_endings(self):
        self.session.set_mode('spam')
        self.session.set_spam_suffixes('r, s')
        one = self.session.choose('m')[0]
        self.session.engine.mark_used(one)
        two = self.session.choose('m')[0]
        self.assertNotEqual(one, two)
        self.assertTrue(one.endswith(('r', 's')))
        self.assertTrue(two.endswith(('r', 's')))


class TypingRegressionTests(unittest.TestCase):
    def test_website_rhythm_starts_immediately_and_spells_every_word(self):
        corrected = 0
        for seed in range(60):
            plan = human_plan('nesslerising', 'player', rng=random.Random(seed).random)
            self.assertEqual(plan.steps[0].delay, 0)
            shown = ''
            for step in plan.steps:
                shown = shown[:-1] if step.kind == 'back' else shown + step.key
                self.assertEqual(shown, step.typed)
            self.assertEqual(shown, 'nesslerising')
            self.assertGreater(plan.end_pause, 0.2)
            corrected += any(step.kind == 'back' for step in plan.steps)
        self.assertGreater(corrected, 0)
        self.assertLess(corrected, 60)

    def test_cancelling_interrupts_a_human_pause(self):
        app, _ = make_app()
        app._name = 'player'
        cancel = threading.Event()
        cancel.set()
        with patch.object(app_module, 'tap_key') as tap, patch.object(app_module, 'press_enter') as enter:
            app._type_suffix(app._gen, 'stone', 'tone', cancel)
        tap.assert_not_called()
        enter.assert_not_called()

    def test_first_key_arrives_before_any_pause(self):
        app, _ = make_app()
        app._name = 'player'
        app._current_turn = 'ours'
        events = []
        class Clock:
            def is_set(self): return False
            def wait(self, seconds):
                events.append(('wait', seconds))
                return False
        with patch.object(app_module, 'focus_roblox', return_value=True), \
             patch.object(app_module, 'roblox_focused', return_value=True), \
             patch.object(app_module, 'tap_key', side_effect=lambda kind, key, hold: events.append(('key', key))), \
             patch.object(app_module, 'press_enter', side_effect=lambda: events.append(('enter', None))):
            app._type_suffix(app._gen, 'stone', 'tone', Clock())
            while not app._queue.empty():
                app._process_event(*app._queue.get_nowait())
        self.assertEqual(events[:2], [('wait', 0.0), ('key', 't')])
        self.assertEqual(events[-1][0], 'enter')

    def test_focus_loss_prevents_the_next_key_and_enter(self):
        app, _ = make_app()
        app._name = 'player'
        class Clock:
            def is_set(self): return False
            def wait(self, seconds): return False
        with patch.object(app_module, 'focus_roblox', return_value=True), \
             patch.object(app_module, 'roblox_focused', side_effect=[True, False]), \
             patch.object(app_module, 'tap_key') as tap, patch.object(app_module, 'press_enter') as enter:
            app._type_suffix(app._gen, 'stone', 'tone', Clock())
        self.assertEqual(tap.call_count, 1)
        enter.assert_not_called()


class CaptureRegressionTests(unittest.TestCase):
    def test_scaling_preserves_aspect_and_bounds_portrait_and_retina_memory(self):
        for width, height in [(1281, 720), (3840, 2160), (1080, 5000), (900, 600)]:
            _, w, h = _fit_frame(width, height)
            self.assertLessEqual(max(w, h), 1600)
            self.assertLessEqual(w*h*4, 10_240_000)
            self.assertAlmostEqual(w/h, width/height, delta=0.01)
        self.assertEqual(_fit_frame(1281, 720)[1], 1281)

    def test_wire_keeps_missing_letter_positions(self):
        parsed = _parse_frame('PROMPT\tmh?rr\tHEADER\tplayer,type an english word\tTILES\t5\tMS\t1\tFULL\t0\tERROR\t\n')
        self.assertEqual(parsed['prompt'], 'mh?rr')
        self.assertFalse(parsed['full'])


if __name__ == '__main__':
    unittest.main()
