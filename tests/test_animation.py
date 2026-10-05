import tempfile
import json
import unittest
from pathlib import Path
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from lab_model_monitor.animation import PROMPT, VERSION, MAX_SITE_RUN_BYTES, extract_html, projection, site_snapshot
from lab_model_monitor.client import _decode_responses_sse
from lab_model_monitor.monitor import run_monitor
from lab_model_monitor.schedule import AIReasoningSchedule
from lab_model_monitor.site import build_reasoning_site_snapshot
from lab_model_monitor.store import RunStore

HTML = '<!doctype html><html><body><svg><circle r="2"/></svg></body></html>'


class AnimationTests(unittest.TestCase):
    @staticmethod
    def saved_run(index, samples):
        created = (datetime(2026, 10, 5, tzinfo=UTC) + timedelta(minutes=index)).isoformat()
        return {'run_id': str(uuid4()), 'created_at': created, 'ended_at': created, 'status': 'success',
                'contract': {'prompt_version': VERSION, 'reasoning_effort': 'medium', 'max_output_tokens': 32768},
                'samples': samples, 'result': {'success': True}}

    def test_twenty_recent_runs_keep_html_beyond_old_total_limit(self):
        from lab_model_monitor.artifacts import export_run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RunStore(root / 'db.sqlite')
            source = HTML.replace('</body>', '<!--' + 'x' * 95000 + '--></body>')
            samples = [{'requested_model': model, 'status': 'generated', 'response_text': source}
                       for model in ('astra', 'sol')]
            runs = [self.saved_run(index, samples) for index in range(21)]
            for run in runs:
                store.import_run(run)
                export_run(run, root / 'artifacts', renderer=lambda _, path:
                           path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 170000))
            # A newer running job must not displace completed history.
            store.start(runs[-1]['contract'], notify=False)
            snapshot = site_snapshot(store, now=datetime(2026, 10, 6, tzinfo=UTC))
            self.assertEqual([r['run_id'] for r in snapshot['runs']], [r['run_id'] for r in reversed(runs[1:])])
            self.assertGreater(len(json.dumps(snapshot).encode()), 2_000_000)
            self.assertTrue(all(s['html'] == source for r in snapshot['runs'] for s in r['samples']))
            self.assertTrue(all(len(json.dumps(r).encode()) <= MAX_SITE_RUN_BYTES for r in snapshot['runs']))
            self.assertEqual(store.get(runs[0]['run_id'])['samples'], samples)

    def test_large_images_are_removed_before_html_and_failed_history_stays(self):
        from lab_model_monitor.artifacts import export_run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RunStore(root / 'db.sqlite')
            source = HTML.replace('</body>', '<!--' + 'x' * 95000 + '--></body>')
            run = self.saved_run(1, [{'requested_model': f'model-{i}', 'status': 'generated',
                                      'response_text': source} for i in range(10)])
            failed = self.saved_run(0, [{'requested_model': 'model', 'status': 'api_error', 'response_text': ''}])
            failed['status'] = 'failed'
            store.import_run(run)
            store.import_run(failed)
            export_run(run, root / 'artifacts', renderer=lambda _, path:
                       path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 170000))
            snapshot = site_snapshot(store, now=datetime(2026, 10, 6, tzinfo=UTC))
            self.assertEqual(len(snapshot['runs']), 2)
            self.assertTrue(all(s['html'] == source for s in snapshot['runs'][0]['samples']))
            self.assertTrue(any(s['thumbnail'] is None for s in snapshot['runs'][0]['samples']))
            self.assertLessEqual(len(json.dumps(snapshot['runs'][0]).encode()), MAX_SITE_RUN_BYTES)
            self.assertEqual(snapshot['runs'][1]['samples'][0]['status'], 'api_error')

    def test_serialized_html_overflow_keeps_sample_metadata_and_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(Path(directory) / 'db.sqlite')
            # Escaping real newlines doubles their serialized size, despite
            # each original HTML remaining below its individual byte limit.
            source = HTML.replace('</body>', '<!--' + '\n' * 110000 + '--></body>')
            run = self.saved_run(0, [{'requested_model': f'model-{i}', 'status': 'generated',
                                      'response_text': source} for i in range(10)])
            store.import_run(run)
            snapshot = site_snapshot(store, now=datetime(2026, 10, 6, tzinfo=UTC))
            item = snapshot['runs'][0]
            self.assertEqual(len(item['samples']), 10)
            self.assertTrue(all(s['status'] == 'generated' and s['sha256'] for s in item['samples']))
            self.assertTrue(any(s['html'] is None for s in item['samples']))
            self.assertTrue(any(s['html'] == source for s in item['samples']))
            self.assertLessEqual(len(json.dumps(item).encode()), MAX_SITE_RUN_BYTES)
            self.assertEqual(store.get(run['run_id'])['samples'], run['samples'])

    def test_incomplete_stream_keeps_partial_artifact_without_promoting_success(self):
        events = [{'type': 'response.output_text.delta', 'delta': '<html><body>'},
                  {'type': 'response.incomplete', 'response': {'status': 'incomplete'}}]
        parsed = _decode_responses_sse('\n\n'.join('data: ' + json.dumps(event) for event in events))
        self.assertEqual(parsed['status'], 'incomplete')
        self.assertEqual(parsed['output_text'], '<html><body>')

    def test_extraction_preserves_code_and_rejects_partial(self):
        self.assertEqual(extract_html('```html\n' + HTML + '\n```'), HTML)
        self.assertIsNone(extract_html(HTML[:-7]))
        self.assertIsNone(extract_html('<html><body>no svg</body></html>'))

    def test_reuses_runner_once_per_model_and_keeps_candy_and_delivery_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RunStore(root / 'db.sqlite')
            schedule = AIReasoningSchedule(attempts_per_model=3).to_dict()
            calls = []
            def request(url, headers, body, timeout):
                calls.append(body)
                return {'output_text': HTML, 'status': 'completed' if len(calls) == 1 else 'incomplete'}
            result = run_monitor(settings={'api': {'base_url': 'https://relay.example', 'api_mode': 'responses'},
                                           'schedule': schedule}, credentials={'api_key': 'test'}, store=store,
                                 requester=request, lock_path=root / 'lock', animation_test=True)
            saved = store.get(result['run_id'])
            self.assertEqual(len(calls), len(schedule['models']))
            self.assertTrue(all(json.loads(body)['stream'] for body in calls))
            self.assertTrue(saved['contract']['stream'])
            self.assertEqual(saved['result']['method']['prompt'], PROMPT)
            self.assertEqual([s['status'] for s in saved['samples']], ['generated', 'incomplete'])
            self.assertEqual(saved['samples'][1]['response_text'], HTML)
            self.assertEqual(store.pending_deliveries(), [])
            display = projection(saved)
            self.assertEqual(display['samples'][0]['html'], HTML)
            self.assertIsNone(display['samples'][1]['html'])
            self.assertNotIn('base_url', str(display))
            self.assertEqual(build_reasoning_site_snapshot(store=store, schedule=schedule)['runs'], [])
