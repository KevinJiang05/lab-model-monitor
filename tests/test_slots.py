import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from lab_model_monitor.animation import site_snapshot
from lab_model_monitor.monitor import run_monitor
from lab_model_monitor.schedule import AIReasoningSchedule
from lab_model_monitor.store import RunStore

HTML = '<html><body><svg></svg></body></html>'


class SlotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = RunStore(self.root / 'db.sqlite')
        self.settings = {'api': {'base_url': 'https://example.test', 'api_mode': 'responses'},
                         'schedule': AIReasoningSchedule(enabled=True, daily_times=('15:00', '20:00')).to_dict()}
        self.calls = []

    def run_slot(self, hour, animation=False, requester=None):
        def request(url, headers, body, timeout):
            self.calls.append(json.loads(body))
            return {'output_text': HTML if animation else '21', 'status': 'completed'}
        return run_monitor(settings=self.settings, credentials={'api_key': 'test'}, store=self.store,
                           lock_path=self.root / 'lock', requester=requester or request,
                           scheduled=True, animation_test=animation, now=datetime(2026, 10, 5, hour, tzinfo=UTC))

    def test_two_slots_both_test_types_are_independent_and_idempotent(self):
        self.assertEqual(self.run_slot(6)['status'], 'not_due')
        for hour in (7, 12):
            for animation in (False, True):
                first = self.run_slot(hour, animation)
                second = self.run_slot(hour, animation)
                self.assertTrue(first['success'])
                self.assertEqual(second['status'], 'already_run')
                self.assertEqual(first['run_id'], second['run_id'])
        self.assertEqual(len(self.calls), 16)  # 2 slots * (6 candy + 2 animation).
        self.assertEqual(len(self.store.recent()), 4)

    def test_animation_retries_only_unsuccessful_models_and_keeps_failures(self):
        attempts = {}
        def request(url, headers, body, timeout):
            model = json.loads(body)['model']
            attempts[model] = attempts.get(model, 0) + 1
            return {'output_text': HTML if model.endswith('astra') or attempts[model] == 2 else 'bad', 'status': 'completed'}
        result = self.run_slot(7, True, request)
        self.assertTrue(result['success'])
        self.assertEqual(sorted(attempts.values()), [1, 2])
        self.assertEqual([s['status'] for s in self.store.get(result['run_id'])['samples']], ['generated', 'format_error', 'generated'])
        snapshot = site_snapshot(self.store)
        self.assertEqual(len(snapshot['runs'][0]['samples']), 3)
        self.assertNotIn('base_url', json.dumps(snapshot))
        self.assertNotIn('api_key', json.dumps(snapshot))

    def test_animation_failure_stops_at_three_and_reentry_does_not_retry(self):
        calls = []
        def request(*args):
            calls.append(1)
            return {'output_text': 'partial', 'status': 'incomplete'}
        self.assertFalse(self.run_slot(7, True, request)['success'])
        self.assertEqual(self.run_slot(7, True, request)['status'], 'already_run')
        self.assertEqual(len(calls), 6)

    def test_cli_runs_animation_even_when_candy_fails_and_reuses_slot_timestamp(self):
        from lab_model_monitor.__main__ import main
        with patch('sys.argv', ['monitor', 'scheduled-run']), patch('lab_model_monitor.__main__.RunStore', return_value=self.store), \
             patch('lab_model_monitor.__main__.load_settings', return_value=self.settings), \
             patch('lab_model_monitor.__main__.load_credentials', return_value={'api_key': 'test'}), \
             patch('lab_model_monitor.__main__.STATE', self.root), \
             patch('lab_model_monitor.__main__.run_monitor', side_effect=[{'success': False, 'status': 'failed'}, {'success': True, 'status': 'success'}]) as runner, \
             patch('lab_model_monitor.__main__.deliver', return_value={'success': True}), patch('builtins.print'):
            self.assertEqual(main(), 1)
        self.assertEqual(runner.call_count, 2)
        self.assertTrue(runner.call_args_list[1].kwargs['animation_test'])
        self.assertEqual(runner.call_args_list[0].kwargs['now'], runner.call_args_list[1].kwargs['now'])

    def test_invalid_multiple_times(self):
        for times in (['15:00', '15:00'], ['25:00'], '15:00,20:00'):
            with self.assertRaises(ValueError):
                AIReasoningSchedule.from_mapping({'daily_times': times})
