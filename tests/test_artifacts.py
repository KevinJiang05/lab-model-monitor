import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import urlopen

from lab_model_monitor.artifacts import capture_thumbnail, export_run, thumbnail_data
from lab_model_monitor.animation import VERSION


class ArtifactTests(unittest.TestCase):
    def test_blank_capture_retries_with_more_render_time_and_fresh_output(self):
        commands = []
        valid = b'\x89PNG\r\n\x1a\n' + b'x' * 3000

        def browser(command, **kwargs):
            commands.append(command)
            with urlopen(command[-1].replace('/preview.html', '/ready')):
                pass
            output = Path(next(arg.split('=', 1)[1] for arg in command if arg.startswith('--screenshot=')))
            self.assertFalse(output.exists(), 'A retry must not reuse the previous screenshot')
            output.write_bytes(b'\x89PNG\r\n\x1a\nblank' if len(commands) == 1 else valid)
            return Mock(returncode=0)

        with tempfile.TemporaryDirectory() as temp, patch('lab_model_monitor.artifacts.Path.is_file', return_value=True), \
                patch('lab_model_monitor.artifacts.subprocess.Popen', side_effect=browser):
            destination = Path(temp) / 'thumbnail.png'
            capture_thumbnail('<html><svg></svg></html>', destination)
            self.assertEqual(destination.read_bytes(), valid)
            self.assertEqual(len(commands), 2)
            self.assertIn('--timeout=10000', commands[0])
            self.assertIn('--timeout=20000', commands[1])
            profiles = [next(arg for arg in command if arg.startswith('--user-data-dir=')) for command in commands]
            self.assertNotEqual(*profiles)

    def test_failed_capture_cannot_reuse_old_output_or_replace_destination(self):
        calls = []

        def browser(command, **kwargs):
            calls.append(command)
            with urlopen(command[-1].replace('/preview.html', '/ready')):
                pass
            output = Path(next(arg.split('=', 1)[1] for arg in command if arg.startswith('--screenshot=')))
            self.assertFalse(output.exists())
            if len(calls) == 1:
                output.write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 3000)
            return Mock(returncode=1 if len(calls) == 1 else 0)

        with tempfile.TemporaryDirectory() as temp, patch('lab_model_monitor.artifacts.Path.is_file', return_value=True), \
                patch('lab_model_monitor.artifacts.subprocess.Popen', side_effect=browser):
            destination = Path(temp) / 'thumbnail.png'
            destination.write_bytes(b'previous valid destination')
            with self.assertRaisesRegex(RuntimeError, 'missing or invalid'):
                capture_thumbnail('<html><svg></svg></html>', destination)
            self.assertEqual(destination.read_bytes(), b'previous valid destination')
            self.assertEqual(len(calls), 2)

    def test_capture_timeout_kills_only_owned_process_then_retries(self):
        processes = []

        def browser(command, **kwargs):
            process = Mock(returncode=0, pid=12345)
            processes.append(process)
            if len(processes) == 1:
                process.wait.side_effect = [subprocess.TimeoutExpired(command, 45), 0]
            else:
                with urlopen(command[-1].replace('/preview.html', '/ready')):
                    pass
                output = Path(next(arg.split('=', 1)[1] for arg in command if arg.startswith('--screenshot=')))
                output.write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 3000)
            return process

        with tempfile.TemporaryDirectory() as temp, patch('lab_model_monitor.artifacts.Path.is_file', return_value=True), \
                patch('lab_model_monitor.artifacts.subprocess.Popen', side_effect=browser), \
                patch('lab_model_monitor.artifacts.subprocess.run') as terminate:
            destination = Path(temp) / 'thumbnail.png'
            capture_thumbnail('<html><svg></svg></html>', destination)
            self.assertIsNotNone(thumbnail_data(destination))
            self.assertEqual(len(processes), 2)
            self.assertEqual(terminate.call_args.args[0], ['taskkill', '/PID', '12345', '/T', '/F'])
            self.assertEqual(processes[0].wait.call_count, 2)

    def test_capture_requires_render_signal_before_accepting_an_image(self):
        def browser(command, **kwargs):
            output = Path(next(arg.split('=', 1)[1] for arg in command if arg.startswith('--screenshot=')))
            output.write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 3000)
            return Mock(returncode=0)

        with tempfile.TemporaryDirectory() as temp, patch('lab_model_monitor.artifacts.Path.is_file', return_value=True), \
                patch('lab_model_monitor.artifacts.subprocess.Popen', side_effect=browser):
            destination = Path(temp) / 'thumbnail.png'
            with self.assertRaisesRegex(RuntimeError, 'did not finish rendering'):
                capture_thumbnail('<html><svg></svg></html>', destination)
            self.assertFalse(destination.exists())

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
