import hashlib
import tempfile
import unittest
from pathlib import Path

from lab_model_monitor.artifacts import export_run, thumbnail_data
from lab_model_monitor.animation import VERSION


class ArtifactTests(unittest.TestCase):
    def test_export_is_exact_cached_and_thumbnail_failure_is_recoverable(self):
        source = '<html><svg></svg></html>'
        run = {'run_id': '12345678-1234-1234-1234-123456789abc', 'created_at': '2026-10-05T00:00:00Z',
               'contract': {'prompt_version': VERSION, 'reasoning_effort': 'medium', 'max_output_tokens': 32768},
               'samples': [{'requested_model': 'model', 'status': 'generated', 'response_text': source}]}
        calls = []
        def failing(*args):
            calls.append(1)
            raise TimeoutError()
        def renderer(html, path):
            calls.append(1)
            self.assertEqual(html, source)
            path.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            failed = export_run(run, root, renderer=failing)
            self.assertFalse(failed['success'])
            self.assertEqual(failed['samples'][0]['html'], 'saved')
            exported = root / run['run_id'] / 'model-1.html'
            self.assertEqual(exported.read_bytes(), source.encode())
            self.assertTrue(export_run(run, root, renderer=renderer)['success'])
            self.assertTrue(export_run(run, root, renderer=failing)['success'])
            self.assertEqual(len(calls), 2)
            thumb = root / run['run_id'] / (hashlib.sha256(source.encode()).hexdigest() + '.png')
            self.assertTrue(thumbnail_data(thumb).startswith('data:image/png;base64,'))
            self.assertEqual(run['samples'][0]['status'], 'generated')

    def test_failed_sample_does_not_create_html_or_invoke_browser(self):
        run = {'run_id': '12345678-1234-1234-1234-123456789abc', 'created_at': '2026-10-05T00:00:00Z',
               'contract': {'prompt_version': VERSION, 'reasoning_effort': 'medium', 'max_output_tokens': 32768},
               'samples': [{'requested_model': 'model', 'status': 'incomplete', 'response_text': '<html>'}]}
        with tempfile.TemporaryDirectory() as temp:
            result = export_run(run, Path(temp), renderer=lambda *_: self.fail('Must not render incomplete HTML'))
            self.assertTrue(result['success'])
            self.assertEqual(list(Path(temp).rglob('*.html')), [])
