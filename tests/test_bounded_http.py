import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch

from packages.harness.control import InferenceCancelled, InferenceControl
from packages.harness.runner import HarnessResult, run_harness
from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.server import configured_models, make_handler
from services.api.state import SessionManager


class CooperativeModel:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.calls = 0
        self.measurement_ref = ""
        self.call_delay = 0
        self.loop_tools = False

    def complete_controlled(self, messages, tools, control):
        self.calls += 1
        self.entered.set()
        try:
            while not self.release.wait(0.005):
                control.check()
            until = time.monotonic() + self.call_delay
            while time.monotonic() < until:
                control.check()
                time.sleep(0.005)
            control.check()
        except InferenceCancelled:
            self.cancelled.set()
            raise
        if self.loop_tools:
            return {"tool_calls": [{"id": f"call_{self.calls}", "function": {
                "name": "get_capture_observation", "arguments": "{}",
            }}]}
        try:
            observation = json.loads(messages[1]["content"])
        except (ValueError, TypeError):
            observation = {"measurement_ref": self.measurement_ref,
                           "supported_fact_codes": ["measurement_recorded", "protocol_experimental"]}
        if "measurement_ref" in observation:
            return {"content": json.dumps({
                "measurement_ref": observation["measurement_ref"],
                "fact_codes": observation["supported_fact_codes"],
                "requires_professional_review": True,
            })}
        return {"content": json.dumps({
            "window_ref": observation["window_ref"],
            "observation_code": observation["supported_observation_code"],
            "requires_professional_review": True,
        })}


class BoundedHttpTests(unittest.TestCase):
    def setUp(self):
        self.model = CooperativeModel()
        self.manager = SessionManager(SyntheticPoseEngine)
        self.handler = make_handler(self.manager, pose_mode="synthetic_demo",
                                    model_bindings=configured_models(self.model),
                                    live_budget_seconds=0.5, draft_budget_seconds=0.25)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = build_opener(ProxyHandler({}))
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self):
        self.model.release.set()
        self.handler.live_coordinator.close()
        self.handler.inference_gate.cancel_all()
        self.server.shutdown()
        self.server.server_close()
        self.manager.close()
        self.server_thread.join(timeout=2)

    def post(self, path, document):
        request = Request(self.base + path, data=json.dumps(document).encode(), method="POST",
                          headers={"Content-Type": "application/json", "Origin": self.base})
        with self.opener.open(request, timeout=3) as response:
            return json.load(response)

    def capture(self, completed=False):
        session = self.post("/api/session/start", {"side": "left"})
        for i in range(3):
            self.manager.add_frame(session["session_id"], session["token"], b"\xff\xd8test", i, i * 200)
        if completed:
            response = self.post("/api/session/finish", {**session, "view_confirmed": True, "camera_stable_confirmed": True})
            self.model.measurement_ref = response["measurement"]["measurement_id"]
        return session

    def run_background_post(self, path, document, wait_for_model=True):
        results = []
        def run():
            try:
                results.append(self.post(path, document))
            except HTTPError as error:
                results.append({"http_error": error.code})
                error.close()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        if wait_for_model:
            self.assertTrue(self.model.entered.wait(1))
        return worker, results

    def test_duplicate_final_notes_are_refused_immediately_without_extra_calls(self):
        session = self.capture(completed=True)
        worker, results = self.run_background_post("/api/harness/draft", {**session, "model_id": "gpt_oss"})
        started = time.monotonic()
        with self.assertRaises(HTTPError) as caught:
            self.post("/api/harness/draft", {**session, "model_id": "gpt_oss"})
        self.assertEqual(caught.exception.code, 409)
        self.assertEqual(json.load(caught.exception)["error"], "analysis_busy")
        caught.exception.close()
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(self.model.calls, 1)
        self.model.release.set()
        worker.join(timeout=1)
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["fallback_reason"])
        self.assertFalse(self.handler.inference_gate.is_busy())

    def test_final_note_has_one_total_budget_across_tool_rounds(self):
        session = self.capture(completed=True)
        self.model.release.set()
        self.model.call_delay = 0.1
        self.model.loop_tools = True
        started = time.monotonic()
        response = self.post("/api/harness/draft", {**session, "model_id": "gpt_oss"})
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertEqual(response["fallback_reason"], "inference_deadline_exceeded")
        self.assertIsNone(response["proposed_note"])
        self.assertIn("BROUILLON NON VALIDÉ", response["deterministic_draft"])
        self.assertLess(self.model.calls, 4)
        self.assertFalse(self.handler.inference_gate.is_busy())

    def test_session_cancel_interrupts_inflight_note_and_refuses_its_late_result(self):
        session = self.capture(completed=True)
        worker, results = self.run_background_post("/api/harness/draft", {**session, "model_id": "gpt_oss"})
        self.post("/api/session/cancel", session)
        worker.join(timeout=1)
        self.assertTrue(self.model.cancelled.is_set())
        self.assertEqual(results, [{"http_error": 403}])
        self.assertFalse(self.handler.inference_gate.is_busy())

    def test_live_stop_interrupts_worker_without_stopping_pose_capture(self):
        session = self.capture()
        self.post("/api/harness/live/poll", {**session, "model_id": "gpt_oss", "control_version": 1})
        self.assertTrue(self.model.entered.wait(1))
        self.post("/api/harness/live/stop", {**session, "control_version": 2})
        self.assertTrue(self.model.cancelled.wait(1))
        self.assertTrue(self.manager.get(**session).active)
        self.manager.add_frame(session["session_id"], session["token"], b"\xff\xd8test", 3, 600)
        deadline = time.monotonic() + 1
        while self.handler.inference_gate.is_busy() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(self.handler.inference_gate.is_busy())
        self.assertFalse(self.manager.live_is_current(session["session_id"], session["token"], 1))

    def test_cancel_signals_llm_before_waiting_for_pose_manager_lock(self):
        session = self.capture()
        self.post("/api/harness/live/poll", {**session, "model_id": "gpt_oss", "control_version": 1})
        self.assertTrue(self.model.entered.wait(1))
        before_manager, release_manager = threading.Event(), threading.Event()
        original_stop = self.handler.live_coordinator.stop

        def blocked_manager_stop(*args, **kwargs):
            before_manager.set()
            if not release_manager.wait(2):
                raise TimeoutError("test_manager_lock_timeout")
            return original_stop(*args, **kwargs)

        with patch.object(self.handler.live_coordinator, "stop", side_effect=blocked_manager_stop):
            worker, results = self.run_background_post("/api/session/cancel", session, wait_for_model=False)
            try:
                self.assertTrue(before_manager.wait(1))
                # L'HTTP cancel est encore en attente du gestionnaire, mais le
                # contrôle du transport a déjà été révoqué, sans autre modèle.
                self.assertTrue(self.model.cancelled.wait(0.2))
                self.assertTrue(worker.is_alive())
                release_manager.set()
                worker.join(timeout=1)
                self.assertEqual(results, [{"cancelled": True}])
            finally:
                release_manager.set()
                worker.join(timeout=2)

    def test_finish_cancels_live_call_acquired_before_capture_transition(self):
        session = self.capture()
        before_finish, resume_finish = threading.Event(), threading.Event()
        allow_worker_exit = threading.Event()
        original_finish = self.manager.finish
        original_completion = self.model.complete_controlled

        def delayed_finish(*args, **kwargs):
            before_finish.set()
            if not resume_finish.wait(2):
                raise TimeoutError("test_finish_transition_timeout")
            return original_finish(*args, **kwargs)

        def cooperative_completion(*args, **kwargs):
            try:
                return original_completion(*args, **kwargs)
            except InferenceCancelled:
                # Le transport coopératif a observé l'annulation, mais son
                # worker n'est pas encore sorti : sa réservation doit rester.
                if not allow_worker_exit.wait(2):
                    raise TimeoutError("test_cancelled_worker_exit_timeout")
                raise

        # Ce budget distingue la révocation testée d'une expiration ordinaire.
        with patch.object(self.manager, "finish", side_effect=delayed_finish), \
                patch.object(self.model, "complete_controlled", side_effect=cooperative_completion), \
                patch.object(self.handler.live_coordinator, "_budget", 2):
            worker, results = self.run_background_post(
                "/api/session/finish", {**session, "view_confirmed": True, "camera_stable_confirmed": True},
                wait_for_model=False,
            )
            try:
                self.assertTrue(before_finish.wait(1))
                self.assertFalse(self.handler.inference_gate.is_busy())
                # Le dernier cancel préalable a déjà eu lieu. Un nouveau poll
                # réserve un slot tant que la capture est encore active.
                self.post("/api/harness/live/poll", {**session, "model_id": "gpt_oss", "control_version": 1})
                self.assertTrue(self.model.entered.wait(1))
                self.assertTrue(self.handler.inference_gate.is_busy())
                self.assertEqual(self.model.calls, 1)
                self.assertFalse(self.model.cancelled.is_set())
                resume_finish.set()
                worker.join(timeout=1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(len(results), 1)
                self.assertIn("measurement", results[0])
                self.assertFalse(self.manager.get(**session).active)
                self.assertTrue(self.model.cancelled.wait(0.5))
                self.assertTrue(self.handler.inference_gate.is_busy())
                self.assertIsNone(self.handler.live_coordinator._result)
                allow_worker_exit.set()
                deadline = time.monotonic() + 1
                while self.handler.inference_gate.is_busy() and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertFalse(self.handler.inference_gate.is_busy())
                self.assertIsNone(self.handler.live_coordinator._result)
                self.assertEqual(self.model.calls, 1)
            finally:
                resume_finish.set()
                allow_worker_exit.set()
                worker.join(timeout=2)

    def test_status_exposes_budgets_and_no_queue_without_internal_tokens(self):
        with self.opener.open(self.base + "/api/status", timeout=3) as response:
            status = json.load(response)
        self.assertEqual(status["analysis_limits"], {
            "live_budget_ms": 500, "draft_budget_ms": 250,
            "max_concurrent": 1, "queue_capacity": 0, "transport_cancellation": True,
        })
        self.assertNotIn("token", json.dumps(status))

    def test_old_snapshot_cannot_start_note_after_session_replacement(self):
        session = self.capture(completed=True)
        gate = self.handler.inference_gate
        original_acquire = gate.try_acquire
        before_acquire, resume_acquire = threading.Event(), threading.Event()

        def delayed_acquire(*args, **kwargs):
            before_acquire.set()
            if not resume_acquire.wait(2):
                raise TimeoutError("test_acquire_timeout")
            return original_acquire(*args, **kwargs)

        with patch.object(gate, "try_acquire", side_effect=delayed_acquire):
            worker, results = self.run_background_post(
                "/api/harness/draft", {**session, "model_id": "gpt_oss"},
                wait_for_model=False,
            )
            try:
                self.assertTrue(before_acquire.wait(1))
                current = self.post("/api/session/start", {"side": "right"})
                self.assertFalse(gate.is_busy())
                resume_acquire.set()
                worker.join(timeout=1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results, [{"http_error": 403}])
                self.assertEqual(self.model.calls, 0)
                self.assertFalse(self.model.entered.is_set())
                self.assertFalse(gate.is_busy())
                self.assertTrue(self.manager.get(**current).active)
            finally:
                resume_acquire.set()
                worker.join(timeout=2)

    def test_deadline_after_harness_validation_discards_valid_candidate_note(self):
        session = self.capture(completed=True)
        clock = [0.0]
        control = InferenceControl(timeout_seconds=0.25, clock=lambda: clock[0])

        def late_harness(context, client, **kwargs):
            if client is None:
                return run_harness(context, None, **kwargs)
            clock[0] += 0.3
            return HarnessResult("Ancien brouillon", "Cette note arrive trop tard.", (), None)

        with patch("services.api.server.InferenceControl", return_value=control) as created, \
                patch("services.api.server.run_harness", side_effect=late_harness):
            response = self.post("/api/harness/draft", {**session, "model_id": "gpt_oss"})
        created.assert_called_once()
        self.assertEqual(response["fallback_reason"], "inference_deadline_exceeded")
        self.assertIsNone(response["proposed_note"])
        self.assertIn("BROUILLON NON VALIDÉ", response["deterministic_draft"])
        self.assertNotIn("Cette note arrive trop tard", json.dumps(response))
        self.assertFalse(self.handler.inference_gate.is_busy())

    def test_deeply_nested_model_json_returns_fallback_without_leaking_slot(self):
        session = self.capture(completed=True)
        nested = "[" * 1500 + "0" + "]" * 1500
        replies = [
            {"content": nested},
            {"tool_calls": [{"id": "nested", "function": {
                "name": "get_capture_observation", "arguments": nested,
            }}]},
        ]
        for reply in replies:
            with self.subTest(reply_type=next(iter(reply))), \
                    patch.object(self.model, "complete_controlled", return_value=reply):
                response = self.post("/api/harness/draft", {**session, "model_id": "gpt_oss"})
                self.assertEqual(response["fallback_reason"], "RecursionError")
                self.assertIsNone(response["proposed_note"])
                self.assertIn("BROUILLON NON VALIDÉ", response["deterministic_draft"])
                self.assertFalse(self.handler.inference_gate.is_busy())

    def test_context_validation_failure_releases_reserved_slot(self):
        session = self.capture(completed=True)
        with patch("services.api.server.ToolContext", side_effect=ValueError("invalid_context")), \
                self.assertRaises(HTTPError) as caught:
            self.post("/api/harness/draft", {**session, "model_id": "gpt_oss"})
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        self.assertEqual(self.model.calls, 0)
        self.assertFalse(self.handler.inference_gate.is_busy())

    def test_cancel_also_interrupts_note_acquired_before_manager_revocation(self):
        session = self.capture(completed=True)
        before_revocation, resume_revocation = threading.Event(), threading.Event()
        original_cancel = self.manager.cancel

        def delayed_cancel(*args, **kwargs):
            before_revocation.set()
            if not resume_revocation.wait(2):
                raise TimeoutError("test_revoke_timeout")
            original_cancel(*args, **kwargs)

        # Un budget assez large isole l'annulation testée de l'expiration.
        with patch.object(self.manager, "cancel", side_effect=delayed_cancel), \
                patch("services.api.server.InferenceControl", side_effect=lambda timeout_seconds: InferenceControl(2)):
            cancel_worker, cancel_results = self.run_background_post(
                "/api/session/cancel", session, wait_for_model=False,
            )
            draft_worker = None
            try:
                self.assertTrue(before_revocation.wait(1))
                self.assertFalse(self.handler.inference_gate.is_busy())
                draft_worker, draft_results = self.run_background_post(
                    "/api/harness/draft", {**session, "model_id": "gpt_oss"},
                )
                self.assertTrue(self.handler.inference_gate.is_busy())
                self.assertEqual(self.model.calls, 1)
                resume_revocation.set()
                cancel_worker.join(timeout=1)
                draft_worker.join(timeout=1)
                self.assertFalse(cancel_worker.is_alive())
                self.assertFalse(draft_worker.is_alive())
                self.assertEqual(cancel_results, [{"cancelled": True}])
                self.assertEqual(draft_results, [{"http_error": 403}])
                self.assertTrue(self.model.cancelled.is_set())
                self.assertFalse(self.handler.inference_gate.is_busy())
            finally:
                resume_revocation.set()
                cancel_worker.join(timeout=2)
                if draft_worker is not None:
                    draft_worker.join(timeout=2)
