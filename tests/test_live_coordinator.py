"""Coordination testée avec horloge et clients locaux simulés, sans réseau."""

import json
import time
import unittest
from threading import Event, Thread, current_thread
from types import SimpleNamespace
from unittest.mock import patch

from packages.harness.live import LiveSnapshot
from packages.harness.control import ControlledChatClient, InferenceControl
from services.api.inference import InferenceGate
from services.api.live import LiveHarnessCoordinator


class ManualClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeManager:
    def __init__(self):
        self.session = SimpleNamespace(session_id="first", token="secret", active=True)
        self.revision = 0
        self.sample_count = 3
        self.snapshot_count = 0
        self.image_options = []
        self.control_version = 0
        self.enabled = True
        self.latest_sample_age_ms = 0

    def get(self, session_id, token):
        if (session_id, token) != (self.session.session_id, self.session.token):
            raise PermissionError("invalid_session")
        return self.session

    def live_is_current(self, session_id, token, control_version):
        session = self.get(session_id, token)
        return session.active and self.enabled and control_version == self.control_version

    def live_window_info(self, session_id, token):
        session = self.get(session_id, token)
        if not session.active:
            raise ValueError("inactive")
        return {
            "window_ref": f"{session_id}:window:{self.revision}",
            "start_timestamp_ms": self.revision * 200,
            "end_timestamp_ms": (self.revision + max(0, self.sample_count - 1)) * 200,
            "sample_count": self.sample_count,
            "image_count": 2 if self.sample_count else 0,
            "latest_sample_age_ms": self.latest_sample_age_ms,
        }

    def live_snapshot(self, session_id, token, include_images=False):
        self.snapshot_count += 1
        self.image_options.append(include_images)
        info = self.live_window_info(session_id, token)
        samples = tuple({
            "sequence": self.revision + index,
            "timestamp_ms": (self.revision + index) * 200,
            "angle_deg": 30.0,
            "quality_reason": None,
        } for index in range(self.sample_count))
        return LiveSnapshot(
            session_id, info["window_ref"], "elbow_flexion_active", "left",
            info["start_timestamp_ms"], info["end_timestamp_ms"], samples,
            (b"\xff\xd8one", b"\xff\xd8two") if include_images else (),
        )

    def replace_session(self):
        self.session.active = False
        self.session = SimpleNamespace(session_id="second", token="new-secret", active=True)
        self.revision = 0


class FakeClient:
    def __init__(self, blocked=False):
        self.calls = 0
        self.started = Event()
        self.release = Event()
        if not blocked:
            self.release.set()

    def complete(self, messages, tools):
        self.calls += 1
        self.started.set()
        if not self.release.wait(3):
            raise TimeoutError("fake_timeout")
        observation = json.loads(messages[1]["content"])
        return {"content": json.dumps({
            "window_ref": observation["window_ref"],
            "observation_code": observation["supported_observation_code"],
            "requires_professional_review": True,
        })}


class LiveCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.manager = FakeManager()
        self.clock = ManualClock()
        self.coordinator = LiveHarnessCoordinator(self.manager, clock=self.clock)
        self.clients = []

    def tearDown(self):
        self.coordinator.close()
        for client in self.clients:
            client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)

    def client(self, blocked=False):
        client = FakeClient(blocked)
        self.clients.append(client)
        return client

    def poll(self, client=None, model="gpt-oss", include_image=False):
        return self.coordinator.poll(
            self.manager.session.session_id, self.manager.session.token,
            model, client, include_image,
        )

    def wait_until(self, condition):
        deadline = time.monotonic() + 2
        while not condition():
            if time.monotonic() >= deadline:
                self.fail("Le worker simulé n'a pas terminé")
            time.sleep(0.001)

    def test_minimum_frames_and_invalid_token_never_create_snapshot(self):
        self.manager.sample_count = 2
        client = self.client()
        response = self.poll(client)
        self.assertEqual(response["state"], "warming_up")
        self.assertIsNone(response["result"])
        self.assertEqual(self.manager.snapshot_count, 0)
        self.assertEqual(client.calls, 0)
        with self.assertRaises(PermissionError):
            self.coordinator.poll("first", "wrong", "gpt-oss", client)
        self.manager.session.active = False
        with self.assertRaises(ValueError):
            self.poll(client)

    def test_no_client_returns_deterministic_observation_without_worker(self):
        with patch("services.api.live.Thread") as thread:
            response = self.poll()
        thread.assert_not_called()
        self.assertEqual(response["state"], "ready")
        self.assertEqual(response["result"]["observation_source"], "deterministic")
        self.assertEqual(response["result"]["fallback_reason"], "llm_unavailable")
        self.assertEqual(response["result_age_ms"], 0)
        self.assertIsNone(self.coordinator._job)
        self.assertEqual(self.manager.image_options, [False])
        self.poll()
        self.assertEqual(self.manager.snapshot_count, 1)

    def test_llm_poll_is_immediate_and_busy_polls_create_no_more_snapshots(self):
        client = self.client(blocked=True)
        started = time.monotonic()
        response = self.poll(client)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(response["state"], "running")
        self.assertTrue(client.started.wait(1))
        for _ in range(5):
            self.manager.revision += 1
            self.poll(client)
        self.assertEqual(self.manager.snapshot_count, 1)
        self.assertEqual(client.calls, 1)
        client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        response = self.poll(client)
        self.assertEqual(response["state"], "ready")
        self.assertEqual(response["result"]["window_ref"], "first:window:0")

    def test_stopped_slow_worker_keeps_global_slot_and_cannot_publish(self):
        old = self.client(blocked=True)
        new = self.client()
        self.poll(old)
        self.assertTrue(old.started.wait(1))
        started = time.monotonic()
        self.coordinator.stop("first", "secret")
        self.assertLess(time.monotonic() - started, 0.5)
        self.manager.revision += 1
        self.clock.advance(3)
        response = self.poll(new, model="qwen")
        self.assertIsNone(response["result"])
        self.assertEqual(new.calls, 0)
        self.assertEqual(self.manager.snapshot_count, 1)
        old.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        self.poll(new, model="qwen")
        self.assertTrue(new.started.wait(1))
        self.wait_until(lambda: self.coordinator._job is None)
        result = self.poll(new, model="qwen")["result"]
        self.assertEqual(result["window_ref"], "first:window:1")

    def test_finished_capture_suppresses_result_without_blocking_stop(self):
        client = self.client(blocked=True)
        self.poll(client)
        self.assertTrue(client.started.wait(1))
        self.manager.session.active = False
        self.coordinator.stop("first", "secret")
        client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        self.assertIsNone(self.coordinator._result)

    def test_session_replacement_cannot_expose_previous_result(self):
        client = self.client(blocked=True)
        self.poll(client)
        self.assertTrue(client.started.wait(1))
        self.manager.replace_session()
        self.coordinator.invalidate()
        self.clock.advance(3)
        response = self.poll()
        self.assertIsNone(response["result"])
        self.assertEqual(self.manager.snapshot_count, 1)
        client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        result = self.poll()["result"]
        self.assertEqual(result["window_ref"], "second:window:0")

    def test_configuration_changes_hide_result_and_do_not_reuse_same_window(self):
        first = self.poll()
        self.assertIsNotNone(first["result"])
        response = self.poll(model="qwen", include_image=True)
        self.assertIsNone(response["result"])
        self.assertEqual(self.manager.snapshot_count, 1)
        self.manager.revision += 1
        response = self.poll(model="qwen", include_image=True)
        self.assertIsNotNone(response["result"])
        self.assertEqual(self.manager.image_options, [False, True])
        with self.assertRaises(ValueError):
            self.poll(include_image="true")

    def test_model_and_visual_consent_change_invalidate_running_job(self):
        client = self.client(blocked=True)
        self.poll(client)
        self.assertTrue(client.started.wait(1))
        self.poll(client, model="qwen", include_image=True)
        client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        self.assertIsNone(self.coordinator._result)
        self.assertEqual(client.calls, 1)

    def test_completed_results_expire_from_snapshot_not_completion(self):
        client = self.client(blocked=True)
        self.poll(client)
        self.assertTrue(client.started.wait(1))
        self.clock.advance(11)
        client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        response = self.poll(client)
        self.assertEqual(response["state"], "stale")
        self.assertIsNone(response["result"])
        self.assertEqual(response["result_age_ms"], 11000)
        self.assertEqual(client.calls, 1)

    def test_new_windows_are_throttled_globally_and_not_queued(self):
        client = self.client()
        self.poll(client)
        self.wait_until(lambda: self.coordinator._job is None)
        self.manager.revision += 1
        self.poll(client)
        self.assertEqual(client.calls, 1)
        self.assertEqual(self.manager.snapshot_count, 1)
        self.clock.advance(3)
        self.poll(client)
        self.wait_until(lambda: self.coordinator._job is None)
        self.assertEqual(client.calls, 2)
        self.assertEqual(self.manager.snapshot_count, 2)
        self.poll(client)
        self.assertEqual(client.calls, 2)

    def test_revocation_and_close_prevent_late_worker_publication(self):
        client = self.client(blocked=True)
        self.poll(client)
        self.assertTrue(client.started.wait(1))
        self.coordinator.close()
        self.assertIsNotNone(self.coordinator._job)
        client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        self.assertIsNone(self.coordinator._result)
        with self.assertRaises(RuntimeError):
            self.poll(client)

    def test_control_version_rejects_old_poll_and_revokes_worker(self):
        client = self.client(blocked=True)
        self.coordinator.poll("first", "secret", "gpt-oss", client, control_version=0)
        self.assertTrue(client.started.wait(1))
        self.manager.control_version += 1
        self.manager.enabled = False
        with self.assertRaises(ValueError):
            self.coordinator.poll("first", "secret", "gpt-oss", client, control_version=0)
        client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        self.assertIsNone(self.coordinator._result)
        self.assertEqual(self.manager.snapshot_count, 1)

    def test_expired_window_prevents_followup_model_turn(self):
        client = self.client(blocked=True)
        original_complete = client.complete

        def requests_tool(messages, tools):
            original_complete(messages, tools)
            return {"content": None, "tool_calls": [{
                "id": "next", "function": {"name": "get_live_observation", "arguments": "{}"},
            }]}

        client.complete = requests_tool
        self.poll(client)
        self.assertTrue(client.started.wait(1))
        self.clock.advance(10)
        client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        self.assertEqual(client.calls, 1)
        response = self.poll(client)
        self.assertEqual(response["state"], "stale")
        self.assertIsNone(response["result"])

    def test_capture_age_is_included_before_inference_starts(self):
        client = self.client(blocked=True)
        self.manager.latest_sample_age_ms = 4000
        self.poll(client)
        self.assertTrue(client.started.wait(1))
        self.clock.advance(7)
        client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        response = self.poll(client)
        self.assertEqual(response["state"], "stale")
        self.assertEqual(response["result_age_ms"], 11000)
        self.assertIsNone(response["result"])

    def test_capture_age_does_not_bypass_start_interval(self):
        client = self.client()
        self.manager.latest_sample_age_ms = 4000
        self.poll(client)
        self.wait_until(lambda: self.coordinator._job is None)
        self.manager.revision += 1
        self.clock.advance(1)
        self.poll(client)
        self.assertEqual(client.calls, 1)
        self.clock.advance(2)
        self.poll(client)
        self.wait_until(lambda: self.coordinator._job is None)
        self.assertEqual(client.calls, 2)

    def test_delayed_versioned_stop_does_not_revoke_newer_job(self):
        client = self.client(blocked=True)
        stop_checked, finish_stop = Event(), Event()
        original_get = self.manager.get
        errors = []

        def delayed_get(session_id, token):
            session = original_get(session_id, token)
            if current_thread().name == "delayed-stop":
                stop_checked.set()
                if not finish_stop.wait(2):
                    raise TimeoutError("stop_test_timeout")
            return session

        def old_stop():
            try:
                self.coordinator.stop("first", "secret", control_version=2)
            except Exception as exc:
                errors.append(exc)

        self.manager.control_version, self.manager.enabled = 2, False
        thread = Thread(target=old_stop, name="delayed-stop")
        with patch.object(self.manager, "get", side_effect=delayed_get):
            thread.start()
            try:
                self.assertTrue(stop_checked.wait(1))
                self.manager.control_version, self.manager.enabled = 3, True
                self.coordinator.poll("first", "secret", "qwen", client, control_version=3)
                self.assertTrue(client.started.wait(1))
                job, generation = self.coordinator._job, self.coordinator._generation
                finish_stop.set()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertIs(self.coordinator._job, job)
                self.assertEqual(self.coordinator._generation, generation)
                self.assertTrue(self.coordinator._continues(job))
            finally:
                finish_stop.set()
                thread.join(2)
        client.release.set()
        self.wait_until(lambda: self.coordinator._job is None)
        response = self.coordinator.poll("first", "secret", "qwen", client, control_version=3)
        self.assertIsNotNone(response["result"])

    def test_old_poll_validated_before_new_poll_cannot_roll_back_configuration(self):
        client = self.client(blocked=True)
        old_checked, finish_old = Event(), Event()
        original_info = self.manager.live_window_info
        errors = []

        def delayed_info(session_id, token):
            if current_thread().name == "old-poll":
                old_checked.set()
                if not finish_old.wait(2):
                    raise TimeoutError("poll_test_timeout")
            return original_info(session_id, token)

        def old_poll():
            try:
                self.coordinator.poll("first", "secret", "gpt-oss", client, control_version=1)
            except Exception as exc:
                errors.append(exc)

        self.manager.control_version = 1
        thread = Thread(target=old_poll, name="old-poll")
        with patch.object(self.manager, "live_window_info", side_effect=delayed_info):
            thread.start()
            try:
                self.assertTrue(old_checked.wait(1))
                self.manager.control_version = 3
                self.coordinator.poll("first", "secret", "qwen", client, control_version=3)
                self.assertTrue(client.started.wait(1))
                job, generation = self.coordinator._job, self.coordinator._generation
                finish_old.set()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], PermissionError)
                self.assertEqual(self.coordinator._configuration.control_version, 3)
                self.assertEqual(self.coordinator._generation, generation)
                self.assertIs(self.coordinator._job, job)
                self.assertTrue(self.coordinator._continues(job))
                self.assertEqual(self.manager.snapshot_count, 1)
            finally:
                finish_old.set()
                thread.join(2)

    def test_stopped_version_watermark_survives_empty_configuration(self):
        for old_version in (1, 2):
            with self.subTest(old_version=old_version):
                manager = FakeManager()
                coordinator = LiveHarnessCoordinator(manager, clock=self.clock)
                manager.control_version = old_version
                old_checked, finish_old = Event(), Event()
                original_info = manager.live_window_info
                errors = []

                def delayed_info(session_id, token):
                    old_checked.set()
                    if not finish_old.wait(2):
                        raise TimeoutError("poll_test_timeout")
                    return original_info(session_id, token)

                def old_poll():
                    try:
                        coordinator.poll("first", "secret", "gpt-oss", None,
                                         control_version=old_version)
                    except Exception as exc:
                        errors.append(exc)

                thread = Thread(target=old_poll)
                with patch.object(manager, "live_window_info", side_effect=delayed_info):
                    thread.start()
                    try:
                        self.assertTrue(old_checked.wait(1))
                        manager.control_version, manager.enabled = 2, False
                        coordinator.stop("first", "secret", control_version=2)
                        self.assertIsNone(coordinator._configuration)
                        finish_old.set()
                        thread.join(1)
                        self.assertFalse(thread.is_alive())
                        self.assertEqual(len(errors), 1)
                        self.assertIsInstance(errors[0], PermissionError)
                        self.assertIsNone(coordinator._configuration)
                        self.assertIsNone(coordinator._job)
                        self.assertEqual(manager.snapshot_count, 0)
                    finally:
                        finish_old.set()
                        thread.join(2)
                        coordinator.close()

    def test_old_poll_cannot_publish_new_configuration_result(self):
        old_computed, finish_old = Event(), Event()
        original_execute = self.coordinator._execute
        errors, responses = [], []

        def delayed_execute(job, snapshot, client):
            original_execute(job, snapshot, client)
            if current_thread().name == "old-result":
                old_computed.set()
                if not finish_old.wait(2):
                    raise TimeoutError("result_test_timeout")

        def old_poll():
            try:
                responses.append(self.coordinator.poll(
                    "first", "secret", "gpt-oss", None, control_version=1
                ))
            except Exception as exc:
                errors.append(exc)

        self.manager.control_version = 1
        thread = Thread(target=old_poll, name="old-result")
        with patch.object(self.coordinator, "_execute", side_effect=delayed_execute):
            thread.start()
            try:
                self.assertTrue(old_computed.wait(1))
                self.manager.control_version = 3
                self.manager.revision += 1
                response = self.coordinator.poll(
                    "first", "secret", "qwen", None, control_version=3
                )
                self.assertEqual(response["result"]["window_ref"], "first:window:1")
                finish_old.set()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(responses, [])
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], PermissionError)
                self.assertEqual(self.coordinator._configuration.control_version, 3)
                self.assertEqual(self.coordinator._result["window_ref"], "first:window:1")
            finally:
                finish_old.set()
                thread.join(2)

    def test_unexpected_worker_error_is_unavailable_without_error_details(self):
        class BrokenClient:
            def complete(self, messages, tools):
                raise RuntimeError("private-prompt-or-server-secret")

        self.poll(BrokenClient())
        self.wait_until(lambda: self.coordinator._job is None)
        response = self.poll(BrokenClient())
        self.assertEqual(response["state"], "unavailable")
        self.assertIsNone(response["result"])
        self.assertNotIn("secret", json.dumps(response))

    def test_shared_draft_slot_refuses_live_before_snapshot_or_worker(self):
        gate = InferenceGate()
        self.coordinator.close()
        self.coordinator = LiveHarnessCoordinator(
            self.manager, clock=self.clock, inference_gate=gate
        )
        control = InferenceControl(clock=self.clock)
        lease = gate.try_acquire(control, "first", "secret", "draft")
        client = self.client()
        with patch("services.api.live.Thread") as thread:
            for _ in range(5):
                response = self.poll(client)
        thread.assert_not_called()
        self.assertEqual(response["state"], "busy")
        self.assertEqual(response["analysis_state"], "busy")
        self.assertEqual(response["busy_reason"], "analysis_busy")
        self.assertIsNone(response["budget_remaining_ms"])
        self.assertEqual(self.manager.snapshot_count, 0)
        self.assertEqual(client.calls, 0)
        self.assertNotIn("secret", json.dumps(response))
        gate.release(lease)
        self.poll(client)
        self.assertTrue(client.started.wait(1))
        self.wait_until(lambda: self.coordinator._job is None)
        self.assertFalse(gate.is_busy())

    def test_uncooperative_cancelled_worker_retains_shared_global_slot(self):
        gate = InferenceGate()
        self.coordinator.close()
        self.coordinator = LiveHarnessCoordinator(
            self.manager, clock=self.clock, inference_gate=gate
        )
        client = self.client(blocked=True)
        self.poll(client)
        self.assertTrue(client.started.wait(1))
        job = self.coordinator._job
        self.coordinator.stop("first", "secret")
        self.assertTrue(job.control.cancelled)
        self.assertFalse(job.active)
        self.assertTrue(gate.is_busy())
        response = self.poll(client, model="qwen")
        self.assertEqual(response["analysis_state"], "cancelling")
        self.assertEqual(response["budget_remaining_ms"], 0)
        other = LiveHarnessCoordinator(self.manager, clock=self.clock, inference_gate=gate)
        try:
            for _ in range(5):
                response = other.poll("first", "secret", "qwen", None)
                self.assertEqual(response["analysis_state"], "busy")
            self.assertEqual(self.manager.snapshot_count, 1)
            self.assertEqual(client.calls, 1)
            client.release.set()
            self.wait_until(lambda: self.coordinator._job is None)
            self.assertFalse(gate.is_busy())
            self.assertIsNone(self.coordinator._result)
            response = other.poll("first", "secret", "qwen", None)
            self.assertIsNotNone(response["result"])
            self.assertEqual(response["analysis_state"], "idle")
        finally:
            other.close()

    def test_one_budget_is_shared_across_all_model_turns(self):
        self.coordinator.close()
        self.coordinator = LiveHarnessCoordinator(
            self.manager, clock=self.clock, analysis_budget_seconds=3,
        )
        clock = self.clock

        class ToolClient:
            calls = 0

            def complete(self, messages, tools):
                self.calls += 1
                clock.advance(2)
                return {"content": None, "tool_calls": [{
                    "id": f"turn-{self.calls}", "function": {
                        "name": "get_live_observation", "arguments": "{}",
                    },
                }]}

        client = ToolClient()
        self.poll(client)
        self.wait_until(lambda: self.coordinator._job is None)
        self.assertEqual(client.calls, 2)
        response = self.poll(client)
        self.assertEqual(response["state"], "unavailable")
        self.assertEqual(response["analysis_state"], "idle")
        self.assertIsNone(response["result"])
        self.assertEqual(self.manager.snapshot_count, 1)

    def test_age_reduces_budget_and_adapter_is_created_once(self):
        client = self.client(blocked=True)
        self.manager.latest_sample_age_ms = 4000
        with patch("services.api.live.ControlledChatClient", wraps=ControlledChatClient) as adapter:
            response = self.poll(client)
            self.assertTrue(client.started.wait(1))
            self.assertEqual(response["budget_remaining_ms"], 6000)
            self.assertEqual(response["analysis_state"], "running")
            self.assertEqual(adapter.call_count, 1)
            job = self.coordinator._job
            self.assertIs(adapter.call_args.args[1], job.control)
            self.clock.advance(6)
            response = self.poll(client)
            self.assertEqual(response["analysis_state"], "cancelling")
            self.assertEqual(response["budget_remaining_ms"], 0)
            self.assertFalse(self.coordinator._continues(job))
            client.release.set()
            self.wait_until(lambda: self.coordinator._job is None)
            self.assertIsNone(self.coordinator._result)
            self.assertEqual(adapter.call_count, 1)

    def test_snapshot_copy_time_counts_against_budget_before_thread_start(self):
        original_snapshot = self.manager.live_snapshot

        def delayed_snapshot(*args, **kwargs):
            result = original_snapshot(*args, **kwargs)
            self.clock.advance(10)
            return result

        client = self.client()
        with patch.object(self.manager, "live_snapshot", side_effect=delayed_snapshot), \
                patch("services.api.live.Thread") as thread:
            response = self.poll(client)
        thread.assert_not_called()
        self.assertEqual(client.calls, 0)
        self.assertEqual(response["state"], "stale")
        self.assertEqual(response["analysis_state"], "idle")
        self.assertIsNone(response["result"])
        self.assertFalse(self.coordinator._inference_gate.is_busy())

    def test_worker_start_failure_releases_shared_slot(self):
        with patch("services.api.live.Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("thread_unavailable")
            response = self.poll(self.client())
        self.assertEqual(response["state"], "unavailable")
        self.assertEqual(response["analysis_state"], "idle")
        self.assertIsNone(self.coordinator._job)
        self.assertFalse(self.coordinator._inference_gate.is_busy())

    def test_invalid_analysis_budget_is_refused(self):
        for budget in (0, -1, float("nan"), float("inf")):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                LiveHarnessCoordinator(self.manager, analysis_budget_seconds=budget)


if __name__ == "__main__":
    unittest.main()
