from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path
from unittest.mock import patch

from lab_model_monitor.client import GPTAPIError, GPTClientConfig, OpenAICompatibleClient, _decode_responses_sse
from lab_model_monitor.delivery import deliver, send_feishu
from lab_model_monitor.monitor import _contract, execution_lock, grade_candy_answer, run_monitor
from lab_model_monitor.schedule import AIReasoningSchedule
from lab_model_monitor.site import _NoRedirect, build_reasoning_site_snapshot, sync_reasoning_site, validate_site_url
from lab_model_monitor.store import RunStore


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = RunStore(self.root / "monitor.sqlite3")
        self.schedule = AIReasoningSchedule(enabled=True, attempts_per_model=1).to_dict()
        self.settings = {"api": {"base_url": "https://relay.example/v1", "model": "unused", "api_mode": "responses"},
                         "schedule": self.schedule, "site_url": "https://site.example", "feishu_enabled": True}
        self.credentials = {"api_key": "test-secret", "site_token": "site-secret", "feishu_app_id": "test-app",
                            "feishu_app_secret": "feishu-secret", "feishu_chat_id": "test-chat"}

    def run_monitor(self, requester=None, **kwargs):
        return run_monitor(settings=self.settings, credentials=self.credentials, store=self.store,
                           lock_path=self.root / "lock", requester=requester or (lambda *_: {"output_text": "21", "status": "completed"}), **kwargs)

    def test_strict_first_line(self):
        for text, expected in (("21\nproof", ("passed", 21)), ("29\n21", ("wrong_answer", 29)),
                               ("21颗", ("format_error", None)), ("\n21", ("format_error", None)),
                               ("**21**", ("format_error", None)), (" 21", ("format_error", None))):
            with self.subTest(text=text):
                self.assertEqual(grade_candy_answer(text), expected)

    def test_shape_control_guarantee_and_lower_bound(self):
        failure_sizes = set()
        for hand in product(*(range(cap + 1) for cap in (7, 9, 8, 7, 6, 4))):
            if not ((hand[0] and hand[4]) or (hand[1] and hand[3])):
                failure_sizes.add((sum(hand[:3]), sum(hand[3:])))
        winners = [(r + s, r, s) for r in range(25) for s in range(18) if (r, s) not in failure_sizes]
        self.assertEqual(min(winners), (21, 9, 12))
        self.assertEqual(max(r + s for r, s in failure_sizes) + 1, 29)

    def test_protocol_settings_no_tools_and_no_hidden_retry(self):
        for mode in ("responses", "chat_completions"):
            calls = []
            def request(url, headers, body, timeout):
                calls.append(json.loads(body))
                self.assertTrue(headers["User-Agent"].startswith("LabModelMonitor/"))
                self.assertNotIn("tools", calls[-1])
                return {"output_text": "21", "status": "completed"} if mode == "responses" else {"choices": [{"message": {"content": "21"}, "finish_reason": "stop"}]}
            client = OpenAICompatibleClient(api_key="test", config=GPTClientConfig("https://relay.example", "model", mode), requester=request, retry_stream_failures=False)
            self.assertEqual(client.generate_text(instructions="solve", input_text="puzzle", reasoning_effort="high", max_output_tokens=32768).text, "21")
            self.assertEqual(calls[0].get("max_output_tokens", calls[0].get("max_completion_tokens")), 32768)
        client = OpenAICompatibleClient(api_key="test", config=GPTClientConfig("https://relay.example", "model"),
            requester=lambda *_: (_ for _ in ()).throw(GPTAPIError("stream failed server_error")), retry_stream_failures=False)
        with self.assertRaises(GPTAPIError):
            client.generate_text(instructions="solve", input_text="puzzle")

    def test_failed_samples_preserve_statuses_and_do_not_retry(self):
        self.schedule["attempts_per_model"] = 3
        replies = [ {"output_text": "29"}, {"output_text": "**21**"}, {"output_text": "21", "status": "incomplete"},
                    GPTAPIError("TimeoutError"), GPTAPIError("HTTP 524 test-secret"), {"output_text": "21"}]
        calls = []
        def request(*args):
            calls.append(args)
            value = replies.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        result = self.run_monitor(request)
        saved = self.store.get(result["run_id"])
        self.assertEqual(len(calls), 6)
        self.assertEqual([item["status"] for item in saved["samples"]], ["wrong_answer", "format_error", "incomplete", "timeout", "api_error", "passed"])
        self.assertNotIn("test-secret", json.dumps(saved))
        self.assertFalse(result["success"])

    def test_contract_windows_and_no_double_count(self):
        self.run_monitor()
        result = self.run_monitor()
        self.assertTrue(all(item["seven_day_attempts"] == 2 for item in result["models"]))
        self.schedule["reasoning_effort"] = "high"
        result = self.run_monitor()
        self.assertTrue(all(item["seven_day_attempts"] == 1 for item in result["models"]))

    def test_daily_uniqueness_and_no_early_requests(self):
        morning = datetime(2026, 10, 5, 7, 59, tzinfo=UTC)
        evening = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
        self.assertEqual(self.run_monitor(scheduled=True, now=morning)["status"], "not_due")
        first = self.run_monitor(scheduled=True, now=evening)
        second = self.run_monitor(scheduled=True, now=evening + timedelta(hours=1))
        self.assertEqual(second["status"], "already_run")
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(len(self.store.recent()), 1)

    def test_disabled_schedule_makes_no_calls(self):
        self.schedule["enabled"] = False
        self.assertEqual(self.run_monitor(scheduled=True)["status"], "disabled")
        self.assertEqual(self.store.recent(), [])

    def test_missing_key_fails_before_recording_or_requests(self):
        self.credentials["api_key"] = ""
        with self.assertRaises(ValueError):
            self.run_monitor()
        self.assertEqual(self.store.recent(), [])

    def test_exclusive_lock_rejects_overlapping_execution(self):
        with execution_lock(self.root / "lock"):
            with self.assertRaises(OSError):
                self.run_monitor()

    def test_interrupted_day_is_finalized_without_retesting(self):
        contract = _contract(self.settings["api"], AIReasoningSchedule.from_mapping(self.schedule))
        run_id = self.store.start(contract, schedule_day="2026-10-05")
        self.assertEqual(self.run_monitor(scheduled=True, now=datetime(2026, 10, 5, 9, tzinfo=UTC))["status"], "already_run")
        self.assertEqual(self.store.get(run_id)["status"], "failed")
        self.assertEqual(self.store.get(run_id)["samples"], [])

    def test_legacy_import_is_exact_idempotent_and_never_resends(self):
        result = self.run_monitor()
        run = self.store.get(result["run_id"])
        imported = RunStore(self.root / "import.sqlite3")
        self.assertTrue(imported.import_run(run))
        self.assertFalse(imported.import_run(run))
        self.assertEqual(imported.get(run["run_id"])["samples"], run["samples"])
        self.assertEqual(imported.pending_deliveries(), [])
        run["created_at"] = "2000-01-01T00:00:00+00:00"
        with self.assertRaises(ValueError):
            imported.import_run(run)

    def test_projection_omits_endpoint_errors_and_preserves_unknown_usage(self):
        result = self.run_monitor(lambda *_: (_ for _ in ()).throw(GPTAPIError("HTTP 524 PRIVATE")))
        snapshot = build_reasoning_site_snapshot(store=self.store, schedule=self.schedule)
        serialized = json.dumps(snapshot)
        self.assertNotIn("PRIVATE", serialized)
        self.assertNotIn("relay.example", serialized)
        self.assertNotIn("base_url", serialized)
        self.assertEqual(snapshot["runs"][0]["run_id"], result["run_id"])
        self.assertEqual(snapshot["runs"][0]["samples"][0]["http_status"], 524)
        self.assertIsNone(snapshot["runs"][0]["samples"][0]["total_tokens"])

    def test_same_public_contract_different_endpoint_separates_chart(self):
        self.run_monitor()
        self.settings["api"]["base_url"] = "https://other.example/v1"
        self.run_monitor()
        runs = build_reasoning_site_snapshot(store=self.store, schedule=self.schedule)["runs"]
        self.assertNotEqual(runs[0]["contract_id"], runs[1]["contract_id"])

    def test_invalid_destination_and_redirect_block(self):
        for url in ("http://site.example", "https://user:secret@site.example", "https://site.example/path", "https://site.example?key=x", "https://site.example:1234"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_site_url(url)
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", None, "https://other.example"))

    def test_sync_payload_and_authorization(self):
        self.run_monitor()
        requests = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, *_): return b'{"success":true}'
        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                return Response()
        with patch("lab_model_monitor.site.build_opener", lambda _: Opener()):
            result = sync_reasoning_site(settings=self.settings, credentials=self.credentials, store=self.store)
        self.assertTrue(result["success"])
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer site-secret")
        self.assertNotIn("api_key", requests[0].data.decode())

    def test_feishu_same_uuid_and_missing_credentials(self):
        result = self.run_monitor()
        run = self.store.get(result["run_id"])
        payloads = []
        def requester(url, payload, token=""):
            if "auth/v3" in url:
                return {"code": 0, "tenant_access_token": "test-token"}
            payloads.append(payload)
            return {"code": 0, "data": {"message_id": "test"}}
        self.assertTrue(send_feishu(run, self.credentials, requester=requester)["success"])
        self.assertTrue(send_feishu(run, self.credentials, requester=requester)["success"])
        self.assertEqual(payloads[0]["uuid"], payloads[1]["uuid"])
        self.assertEqual(send_feishu(run, {})["status"], "missing_feishu_credential")

    def test_delivery_failure_does_not_change_grade_and_retry_uses_no_models(self):
        result = self.run_monitor()
        delivered = []
        def sender(run, *_args, **_kwargs):
            delivered.append(run["run_id"])
            return {"success": True, "status": "delivered"}
        def failing(**_):
            return {"success": False, "status": "http_error", "http_status": 503}
        first = deliver(store=self.store, settings=self.settings, credentials=self.credentials, run_id=result["run_id"], sender=sender, syncer=failing)
        second = deliver(store=self.store, settings=self.settings, credentials=self.credentials, sender=sender, syncer=failing)
        self.assertFalse(first["success"])
        self.assertFalse(second["success"])
        self.assertEqual(delivered, [result["run_id"]])
        self.assertEqual(self.store.get(result["run_id"])["status"], "success")

    def test_sse_completed_and_incomplete_contract(self):
        payload = _decode_responses_sse('event: response.completed\ndata: {"type":"response.completed","response":{"status":"completed","output_text":"21"}}\n\n')
        self.assertEqual(payload["output_text"], "21")

    def test_invalid_schedule_settings(self):
        for value in ({"daily_time": "25:00"}, {"attempts_per_model": 0}, {"models": ["a", "a"]}, {"max_output_tokens": 100}, {"enabled": "yes"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AIReasoningSchedule.from_mapping(value)


if __name__ == "__main__":
    unittest.main()
