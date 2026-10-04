import tempfile
import json
import unittest
from pathlib import Path

from lab_model_monitor.animation import PROMPT, extract_html, projection
from lab_model_monitor.client import _decode_responses_sse
from lab_model_monitor.monitor import run_monitor
from lab_model_monitor.schedule import AIReasoningSchedule
from lab_model_monitor.site import build_reasoning_site_snapshot
from lab_model_monitor.store import RunStore

HTML = '<!doctype html><html><body><svg><circle r="2"/></svg></body></html>'


class AnimationTests(unittest.TestCase):
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
