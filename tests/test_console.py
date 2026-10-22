from __future__ import annotations

import copy
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from lab_model_monitor import config
from lab_model_monitor.client import GPTAPIError, GPTResponse, OpenAICompatibleClient
from lab_model_monitor.console import MAX_REQUEST, make_server
from lab_model_monitor.control import BusyError, ControlService, WindowsScheduler, public_run
from lab_model_monitor.delivery import send_feishu
from lab_model_monitor.monitor import CANDY_PROMPT_SHA256, _contract, execution_lock, run_monitor
from lab_model_monitor.schedule import AIReasoningSchedule
from lab_model_monitor.site import build_reasoning_site_snapshot, sync_reasoning_site
from lab_model_monitor.store import RunStore


class FakeScheduler:
    def __init__(self):
        self.state = "Disabled"
        self.applied = []
        self.fail_next = False

    def status(self):
        return {"state": self.state, "task_name": "LabModelMonitor-Daily", "next_run": "2026-10-05T16:00:00"}

    def apply(self, settings):
        self.applied.append(copy.deepcopy(settings))
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Simulated schedule failure")
        self.state = "Ready" if settings["schedule"]["enabled"] else "Disabled"
        return self.status()


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        state_patch = patch.object(config, "STATE", self.root)
        state_patch.start()
        self.addCleanup(state_patch.stop)
        env_patch = patch.dict(os.environ, {key: "" for key in config.CREDENTIAL_ENVS.values()})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.settings = config.validate_settings({"api": {"base_url": "https://relay.example", "model": "m1"},
            "schedule": {"enabled": False, "models": ["m1", "m2"], "attempts_per_model": 1}, "feishu_enabled": False})
        config.write_json(self.root / "settings.json", self.settings)
        config.update_credentials({"api_key": "fake-model-secret", "site_token": "fake-site-secret"})
        self.store = RunStore(self.root / "monitor.sqlite3")
        self.scheduler = FakeScheduler()
        self.service = ControlService(scheduler=self.scheduler, store=self.store)

    def http_server(self):
        server = make_server(0, service=self.service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def request(self, server, path="/api/state", payload=None, *, origin=True, host=None, size=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
        self.addCleanup(connection.close)
        headers = {}
        if host:
            headers["Host"] = host
        body = None
        if payload is not None:
            body = json.dumps(payload)
            headers["Content-Type"] = "application/json"
            if origin:
                headers["Origin"] = f"http://127.0.0.1:{server.server_port}"
            if size:
                headers["Content-Length"] = str(size)
        connection.request("POST" if payload is not None else "GET", path, body, headers)
        response = connection.getresponse()
        return response.status, response.read().decode()

    def test_loopback_and_static_assets_and_no_secret_echo(self):
        server = self.http_server()
        self.assertEqual(server.server_address[0], "127.0.0.1")
        original = (self.root / "settings.json").read_bytes()
        with patch.object(OpenAICompatibleClient, "generate_text", side_effect=AssertionError("Unexpected model call")):
            for path in ("/", "/console.js", "/console.css", "/api/health", "/api/state"):
                code, body = self.request(server, path)
                self.assertEqual(code, 200, path)
                self.assertNotIn("fake-model-secret", body)
                self.assertNotIn("fake-site-secret", body)
        self.assertEqual((self.root / "settings.json").read_bytes(), original)
        self.assertEqual(self.store.recent(), [])
        self.assertEqual(self.scheduler.applied, [])
        self.assertEqual(self.request(server, host="external.example")[0], 403)

    def test_local_post_requires_same_origin_json_and_bounded_body(self):
        server = self.http_server()
        payload = {"settings": self.settings}
        self.assertEqual(self.request(server, "/api/settings", payload, origin=False)[0], 403)
        self.assertEqual(self.request(server, "/api/settings", payload, size=MAX_REQUEST + 1)[0], 413)
        self.assertEqual(self.request(server, "/api/settings", [1])[0], 400)
        payload["settings"]["schedule"]["daily_time"] = "25:00"
        self.assertEqual(self.request(server, "/api/settings", payload)[0], 400)
        self.assertEqual(config.load_settings()["schedule"]["daily_time"], "16:00")

    def test_blank_preserves_secret_explicit_clear_and_environment_precedence(self):
        result = self.service.save({"settings": self.settings, "credentials": {"api_key": ""}})
        self.assertTrue(result["credentials"]["api_key"]["configured"])
        self.assertEqual(config.load_credentials()["api_key"], "fake-model-secret")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-environment-key"}):
            result = self.service.save({"settings": self.settings, "clear_credentials": ["api_key"]})
            self.assertEqual(result["credentials"]["api_key"]["source"], "environment")
            self.assertNotIn("fake-environment-key", json.dumps(result))
        self.assertFalse(config.credential_status()["api"])

    def test_enable_pause_time_changes_apply_existing_scheduler(self):
        self.settings["schedule"].update(enabled=True, daily_time="17:15")
        result = self.service.save({"settings": self.settings})
        self.assertEqual(result["scheduler"]["state"], "Ready")
        self.assertEqual(self.scheduler.applied[-1]["schedule"]["daily_time"], "17:15")
        self.service.save({"settings": self.settings})
        self.assertEqual(len(self.scheduler.applied), 1)
        self.settings["schedule"]["enabled"] = False
        result = self.service.save({"settings": self.settings})
        self.assertEqual(result["scheduler"]["state"], "Disabled")
        self.assertEqual(len(self.scheduler.applied), 2)

    def test_reconcile_external_task_state(self):
        self.scheduler.state = "Ready"
        self.service.save({"settings": self.settings})
        self.assertEqual(self.scheduler.state, "Disabled")
        self.settings["schedule"]["enabled"] = True
        config.write_json(self.root / "settings.json", self.settings)
        self.scheduler.state = "not_installed"
        self.service.save({"settings": self.settings})
        self.assertEqual(self.scheduler.state, "Ready")

    def test_quick_pause_changes_only_saved_schedule_even_during_operation(self):
        self.settings['schedule']['enabled'] = True
        config.write_json(self.root / 'settings.json', self.settings)
        self.service.job = {'id': 'active', 'state': 'running', 'action': 'animation'}
        with execution_lock(self.root / 'job.lock'):
            result = self.service.set_schedule_enabled(False)
        self.assertFalse(result['settings']['schedule']['enabled'])
        self.assertEqual(result['scheduler']['state'], 'Disabled')
        expected = copy.deepcopy(self.settings)
        expected['schedule']['enabled'] = False
        self.assertEqual(config.load_settings(), expected)
        self.assertFalse(self.service.stop_event.is_set())
        with self.assertRaises(ValueError):
            self.service.set_schedule_enabled('false')

    def test_quick_schedule_failure_restores_previous_intent(self):
        previous = config.load_settings()
        self.scheduler.fail_next = True
        with self.assertRaises(RuntimeError):
            self.service.set_schedule_enabled(True)
        self.assertEqual(config.load_settings(), previous)
        self.assertEqual(self.scheduler.state, 'Disabled')

    def test_console_routes_all_manual_actions_to_shared_runner(self):
        for action in ('run', 'animation', 'run-all', 'sync'):
            self.service.job = {'id': action, 'state': 'running', 'action': action}
            with patch('lab_model_monitor.__main__.execute_command', return_value={'success': True}) as command:
                self.service._worker(action, action)
            command.assert_called_once_with(action, stop_event=self.service.stop_event)
            self.assertEqual(self.service.job['state'], 'success')

    def test_stop_preserves_stream_evidence_and_prevents_further_samples(self):
        calls = []
        self.service.job = {'id': 'owned', 'state': 'running', 'action': 'run'}
        def generate(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                return GPTResponse(text='21', model='m1', response_id='first', completion_status='completed')
            self.service.stop()
            kwargs['on_progress']({'response_text': 'partial answer', 'last_event': 'response.output_text.delta', 'terminal': False})
            self.fail('Cancelled progress must stop reading')
        with patch.object(OpenAICompatibleClient, 'generate_text', side_effect=generate):
            result = run_monitor(settings=self.settings, credentials={'api_key': 'fake'}, store=self.store,
                lock_path=self.root / 'sample.lock', stop_event=self.service.stop_event)
        self.assertEqual(result['status'], 'cancelled')
        samples = self.store.get(result['run_id'])['samples']
        self.assertEqual([s['status'] for s in samples], ['passed', 'incomplete'])
        self.assertEqual(samples[1]['response_text'], 'partial answer')
        self.assertEqual(samples[1]['completion_status'], 'client_cancelled')
        self.assertTrue(public_run(self.store.get(result['run_id']))['cancelled'])
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.service.job['stop_requested'])
        for action in ('sync', 'models'):
            self.service.job = {'state': 'running', 'action': action}
            with self.assertRaises(ValueError):
                self.service.stop()

    def test_schedule_and_stop_http_routes_do_not_issue_model_requests(self):
        server = self.http_server()
        with patch.object(OpenAICompatibleClient, 'generate_text', side_effect=AssertionError('Unexpected model call')):
            code, body = self.request(server, '/api/schedule', {'enabled': True})
            self.assertEqual(code, 200)
            self.assertTrue(json.loads(body)['settings']['schedule']['enabled'])
            self.assertEqual(self.request(server, '/api/schedule', {'enabled': 'false'})[0], 400)
            self.assertEqual(self.request(server, '/api/actions', {'action': 'stop'})[0], 400)
            self.service.job = {'id': 'owned', 'state': 'running', 'action': 'animation'}
            code, body = self.request(server, '/api/actions', {'action': 'stop'})
            self.assertEqual(code, 202)
            self.assertTrue(json.loads(body)['job']['stop_requested'])
        self.assertEqual(self.store.recent(), [])

    def test_stop_at_completion_keeps_completed_answer_and_skips_next_model(self):
        calls = []
        self.service.job = {'id': 'owned', 'state': 'running', 'action': 'run'}
        def generate(**kwargs):
            calls.append(1)
            self.service.stop()
            kwargs['on_progress']({'response_text': '21', 'last_event': 'response.completed', 'terminal': True})
            return GPTResponse(text='21', model='m1', response_id='complete', completion_status='completed')
        with patch.object(OpenAICompatibleClient, 'generate_text', side_effect=generate):
            result = run_monitor(settings=self.settings, credentials={'api_key': 'fake'}, store=self.store,
                lock_path=self.root / 'sample.lock', stop_event=self.service.stop_event)
        samples = self.store.get(result['run_id'])['samples']
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(samples[0]['status'], 'passed')
        self.assertEqual(samples[0]['completion_status'], 'completed')

    def test_failure_diagnosis_is_useful_without_returning_raw_error(self):
        from lab_model_monitor.control import sample_diagnosis
        self.assertIn('服务链路', sample_diagnosis({'status': 'api_error', 'error': 'fake-model-secret'}, 502))
        self.assertIn('服务端失败', sample_diagnosis({'status': 'api_error', 'last_event': 'error'}, None))
        self.assertIn('本地停止', sample_diagnosis({'status': 'incomplete', 'completion_status': 'client_cancelled'}, None))
        self.assertNotIn('fake-model-secret', sample_diagnosis({'status': 'api_error', 'error': 'fake-model-secret'}, None))

    def test_failure_restores_config_credentials_and_task_intent(self):
        previous = config.load_settings()
        self.settings["schedule"].update(enabled=True, daily_time="17:00")
        self.scheduler.fail_next = True
        with self.assertRaises(RuntimeError):
            self.service.save({"settings": self.settings, "credentials": {"api_key": "new-fake-key"}})
        self.assertEqual(config.load_settings(), previous)
        self.assertEqual(config.load_credentials()["api_key"], "fake-model-secret")
        self.assertEqual(self.scheduler.applied[-1], previous)
        self.assertEqual(self.scheduler.state, "Disabled")

    def test_invalid_credential_or_missing_required_channel_leaves_no_changes(self):
        before = (self.root / "settings.json").read_bytes()
        with self.assertRaises(ValueError):
            self.service.save({"settings": self.settings, "credentials": {"unknown": "value"}})
        self.assertEqual((self.root / "settings.json").read_bytes(), before)
        self.settings.update(feishu_enabled=True)
        self.settings["schedule"]["enabled"] = True
        with self.assertRaises(ValueError):
            self.service.save({"settings": self.settings, "credentials": {"api_key": "new-fake-key"}})
        self.assertEqual((self.root / "settings.json").read_bytes(), before)
        self.assertEqual(config.load_credentials()["api_key"], "fake-model-secret")
        self.assertEqual(self.scheduler.applied, [])

    def test_external_lock_blocks_save_actions_and_does_not_grow(self):
        with execution_lock(self.root / "job.lock"):
            self.assertTrue(self.service.snapshot()["busy"])
            for operation in (lambda: self.service.save({"settings": self.settings}), lambda: self.service.start("sync")):
                with self.assertRaises(BusyError):
                    operation()
        for _ in range(20):
            self.assertFalse(self.service.snapshot()["busy"])
        self.assertEqual((self.root / "job.lock").stat().st_size, 1)

    def test_async_operation_prevents_overlap_and_reports_result(self):
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        def cli(action):
            self.assertEqual(action, "sync")
            entered.set()
            self.assertTrue(release.wait(3))
            return {"success": True, "site": {"status": "synced"}}
        original_worker = self.service._worker
        def worker(*args):
            try:
                original_worker(*args)
            finally:
                done.set()
        with patch.object(self.service, "_cli", side_effect=cli), patch.object(self.service, "_worker", side_effect=worker):
            self.assertEqual(self.service.start("sync")["state"], "running")
            self.assertTrue(entered.wait(2))
            with self.assertRaises(BusyError):
                self.service.save({"settings": self.settings})
            with self.assertRaises(BusyError):
                self.service.start("run")
            release.set()
            self.assertTrue(done.wait(3))
        self.assertEqual(self.service.snapshot()["job"]["state"], "success")
        self.assertEqual(self.store.recent(), [])

    def test_connection_action_only_lists_models_and_sanitizes_failure(self):
        self.service.job = {"id": "fake", "state": "running"}
        with patch.object(OpenAICompatibleClient, "list_models", return_value=[{"id": "m1"}]) as list_models, patch.object(OpenAICompatibleClient, "generate_text", side_effect=AssertionError):
            self.service._worker("fake", "models")
        list_models.assert_called_once()
        self.assertEqual(self.service.job["result"]["models"], [{"id": "m1"}])
        self.service.job = {"id": "error", "state": "running"}
        with patch.object(OpenAICompatibleClient, "list_models", side_effect=GPTAPIError("HTTP 403 fake-model-secret")):
            self.service._worker("error", "models")
        self.assertEqual(self.service.job["result"]["http_status"], 403)
        self.assertNotIn("fake-model-secret", json.dumps(self.service.job))

    def monitor(self, answer="21"):
        return run_monitor(settings=self.settings, credentials={"api_key": "fake"}, store=self.store,
            lock_path=self.root / "monitor.lock", requester=lambda *_: {"output_text": answer, "status": "completed"})

    def test_default_contract_unchanged_custom_method_is_persisted_and_windows_separate(self):
        original = _contract(self.settings["api"], AIReasoningSchedule.from_mapping(self.settings["schedule"]))
        self.assertEqual(original["prompt_sha256"], CANDY_PROMPT_SHA256)
        old = self.monitor()
        old_record = self.store.get(old["run_id"])
        self.settings["test"] = {"instructions": "计算并在首行只写整数", "prompt": "6×7=?", "expected_answer": 42}
        custom = self.monitor("42\n解释")
        record = self.store.get(custom["run_id"])
        self.assertEqual(record["result"]["method"], self.settings["test"])
        self.assertEqual(record["contract"]["expected_answer"], 42)
        self.assertNotEqual(record["contract"]["prompt_sha256"], original["prompt_sha256"])
        self.assertTrue(all(item["seven_day_attempts"] == 1 for item in custom["models"]))
        self.assertEqual(self.store.get(old["run_id"]), old_record)
        self.settings["test"] = config.default_test()
        restored = self.monitor()
        self.assertTrue(all(item["seven_day_attempts"] == 2 for item in restored["models"]))

    def test_custom_records_never_replace_candy_projection_or_upload(self):
        standard = self.monitor()
        self.settings["test"] = {"instructions": "整数", "prompt": "6×7=?", "expected_answer": 42}
        for _ in range(3):
            self.monitor("42")
        snapshot = build_reasoning_site_snapshot(store=self.store, schedule=self.settings["schedule"])
        self.assertEqual([run["run_id"] for run in snapshot["runs"]], [standard["run_id"]])
        with patch("lab_model_monitor.site.build_opener", side_effect=AssertionError("Custom prompt uploaded")):
            self.assertEqual(sync_reasoning_site(store=self.store, settings=self.settings, credentials={})["status"], "custom_test_local_only")
        self.assertEqual(self.store.recent(limit=1, prompt_version="candy-shape-selection-v1")[0]["run_id"], standard["run_id"])

    def test_detail_returns_original_method_and_http_code_without_error_text(self):
        result = self.monitor()
        row = self.store.get(result["run_id"])
        row["samples"][0]["error"] = "HTTP 524 fake-model-secret"
        item = public_run(row, detailed=True)
        self.assertEqual(item["samples"][0]["http_status"], 524)
        self.assertNotIn("fake-model-secret", json.dumps(item))
        self.assertNotIn("base_url", item["contract"])
        self.assertEqual(item["method"], config.default_test())
        server = self.http_server()
        code, body = self.request(server, "/api/runs/" + result["run_id"])
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["run"]["run_id"], result["run_id"])
        self.assertEqual(self.request(server, "/api/runs/not-a-uuid")[0], 400)

    def test_interrupted_custom_run_keeps_its_original_prompt(self):
        method = {"instructions": "整数", "prompt": "6×7=?", "expected_answer": 42}
        contract = _contract(self.settings["api"], AIReasoningSchedule.from_mapping(self.settings["schedule"]), method)
        identity = self.store.start(contract, method=method)
        self.monitor()
        row = self.store.get(identity)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(public_run(row, detailed=True)["method"], method)

    def test_missing_delivery_credentials_allow_disabled_or_custom_local_mode(self):
        self.settings["schedule"]["enabled"] = True
        self.settings["site_url"] = "https://board.example"
        config.update_credentials({}, ["site_token"])
        with self.assertRaises(ValueError):
            self.service.save({"settings": self.settings})
        self.settings["test"] = {"instructions": "整数", "prompt": "6×7=?", "expected_answer": 42}
        self.assertTrue(self.service.save({"settings": self.settings})["settings"]["schedule"]["enabled"])

    def test_custom_feishu_does_not_link_to_candy_board(self):
        self.settings["test"] = {"instructions": "整数", "prompt": "6×7=?", "expected_answer": 42}
        result = self.monitor("42")
        requests = []
        def request(url, payload, token=""):
            requests.append(payload)
            return {"code": 0, "tenant_access_token": "fake-token"}
        credentials = {"feishu_app_id": "fake", "feishu_app_secret": "fake", "feishu_chat_id": "fake"}
        self.assertTrue(send_feishu(self.store.get(result["run_id"]), credentials, site_url="https://board.example", requester=request)["success"])
        self.assertNotIn("board.example", requests[-1]["content"])
        self.assertIn("自定义测试", requests[-1]["content"])

    def test_scheduler_adapter_uses_existing_script_not_new_detector(self):
        scheduler = WindowsScheduler()
        fake = type("ProcessResult", (), {"returncode": 0, "stdout": '{"state":"Ready"}'})()
        with patch("lab_model_monitor.control.os.name", "nt"), patch("lab_model_monitor.control.subprocess.run", return_value=fake) as run:
            scheduler.apply({"schedule": {"enabled": True}})
        self.assertIn("Install", run.call_args.args[0])
        self.assertIn(str(config.ROOT / "scripts" / "schedule.ps1"), run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
