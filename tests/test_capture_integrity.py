from dataclasses import replace
import json
import unittest

from packages.biomechanics.protocols import assess_trial
from packages.contracts.models import MeasurementStatus
from packages.harness.control import ControlledChatClient, InferenceCancelled, InferenceControl
from packages.harness.demo import synthetic_trial
from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.capture_integrity import CaptureIntegrity, validate_capture_monitor
from services.api.state import SessionManager


def monitor(duration=400, last=400, interrupted=False):
    return {"schema_version": "1.0", "watchdog_timeout_ms": 3000,
            "expected_duration_ms": duration, "last_frame_elapsed_ms": last,
            "interrupted": interrupted}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class CaptureIntegrityTests(unittest.TestCase):
    def test_three_frames_then_freeze_is_persistent_even_after_fresh_frame(self):
        integrity = CaptureIntegrity(0)
        for now, timestamp in ((0, 0), (0.2, 200), (0.4, 400)):
            integrity.receive(now, timestamp)
        self.assertFalse(integrity.interrupted)
        integrity.observe(60)
        integrity.receive(60.1, 60100)
        result = integrity.finish(60.2, monitor(duration=60200, last=60100))
        self.assertTrue(result["interrupted"])
        self.assertEqual(result["reason"], "capture_interrupted")
        self.assertEqual(result["received_frame_count"], 4)

    def test_three_second_boundary_initial_delay_and_source_gap_fail_closed(self):
        for before in (False, True):
            integrity = CaptureIntegrity(0)
            if before:
                integrity.receive(0, 0)
            integrity.observe(2.999)
            self.assertFalse(integrity.interrupted)
            integrity.observe(3)
            self.assertTrue(integrity.interrupted)
        integrity = CaptureIntegrity(0)
        integrity.receive(0, 0)
        integrity.receive(0.1, 3000)
        self.assertTrue(integrity.interrupted)

    def test_short_clip_natural_end_has_no_minimum_duration(self):
        integrity = CaptureIntegrity(0)
        for now, timestamp in ((0, 0), (0.1, 100), (0.2, 200)):
            integrity.receive(now, timestamp)
        result = integrity.finish(0.3, monitor(duration=300, last=200))
        self.assertFalse(result["interrupted"])
        self.assertEqual(result["source_span_ms"], 200)

    def test_false_client_monitor_never_overrides_server_gap_or_explicit_interruption(self):
        integrity = CaptureIntegrity(0)
        integrity.receive(0, 0)
        self.assertTrue(integrity.finish(10, monitor(duration=0, last=0))["interrupted"])
        integrity = CaptureIntegrity(0)
        self.assertTrue(integrity.finish(0, monitor(), "capture_interrupted")["interrupted"])
        integrity = CaptureIntegrity(0)
        self.assertTrue(integrity.finish(0, monitor(duration=3000, last=None))["interrupted"])

    def test_monitor_contract_is_closed_finite_and_bounded(self):
        self.assertIsNone(validate_capture_monitor(None))
        self.assertEqual(validate_capture_monitor(monitor()), monitor())
        invalid = [[], {**monitor(), "private": "not allowed"}, {**monitor(), "watchdog_timeout_ms": 60000},
                   {**monitor(), "watchdog_timeout_ms": True}, {**monitor(), "interrupted": 1},
                   {**monitor(), "expected_duration_ms": True}, {**monitor(), "expected_duration_ms": float("nan")},
                   {**monitor(), "expected_duration_ms": float("inf")}, {**monitor(), "expected_duration_ms": -1},
                   {**monitor(), "expected_duration_ms": 135001}, {**monitor(), "last_frame_elapsed_ms": -1},
                   {**monitor(), "expected_duration_ms": 10 ** 1000},
                   {**monitor(), "last_frame_elapsed_ms": 10 ** 1000},
                   {**monitor(), "last_frame_elapsed_ms": 401}, {**monitor(), "last_frame_elapsed_ms": True}]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                validate_capture_monitor(candidate)


class ServerCaptureIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.manager = SessionManager(SyntheticPoseEngine, capture_clock=self.clock)
        self.session = self.manager.start("left")

    def tearDown(self):
        self.manager.close()

    def add_frames(self):
        for i in range(3):
            self.clock.now = i * 0.2
            self.manager.add_frame(self.session.session_id, self.session.token, b"\xff\xd8test", i, i * 200)

    def finish(self, **kwargs):
        return self.manager.finish(self.session.session_id, self.session.token, True, True, **kwargs)

    def test_normal_finish_after_silent_freeze_rejects_angle_and_jpeg_even_without_client_monitor(self):
        self.add_frames()
        self.clock.now = 60
        measurement = self.finish()
        self.assertEqual(measurement.status, MeasurementStatus.REJECTED)
        self.assertEqual(measurement.quality_reasons, ("capture_interrupted",))
        self.assertIsNone(measurement.value_deg)
        self.assertEqual(measurement.evidence_refs, ())
        details = self.manager.completed_details(self.session.session_id, self.session.token)
        self.assertTrue(details["capture_integrity"]["interrupted"])
        self.assertIsNone(details["evidence_sequence"])
        self.assertIsNone(self.session.keyframe_jpeg)

    def test_resumed_fresh_frame_cannot_hide_long_receipt_gap(self):
        self.add_frames()
        self.clock.now = 20
        frame = self.manager.add_frame(self.session.session_id, self.session.token, b"\xff\xd8fresh", 3, 600)
        self.assertEqual(frame.quality_reason, "capture_interrupted")
        self.assertIsNone(self.finish().value_deg)

    def test_slow_pose_return_does_not_make_the_old_received_image_fresh(self):
        self.add_frames()
        detect = self.session.engine.detect

        def slow(*args):
            result = detect(*args)
            self.clock.now += 3
            return result

        self.session.engine.detect = slow
        self.clock.now = 0.6
        frame = self.manager.add_frame(self.session.session_id, self.session.token, b"\xff\xd8test", 3, 600)
        self.assertEqual(frame.quality_reason, "capture_interrupted")
        self.assertIsNone(self.finish().value_deg)

    def test_failed_decoding_cannot_refresh_capture_or_preserve_old_angle(self):
        self.add_frames()

        def broken(*args):
            raise ValueError("Pixels illisibles")

        self.session.engine.detect = broken
        for i in range(3, 23):
            self.clock.now = i * 0.2
            with self.assertRaises(ValueError):
                self.manager.add_frame(self.session.session_id, self.session.token, b"\xff\xd8bad", i, i * 200)
        self.clock.now = 4.5
        measurement = self.finish()
        self.assertEqual(measurement.quality_reasons, ("capture_interrupted",))
        self.assertIsNone(measurement.value_deg)
        self.assertEqual(measurement.evidence_refs, ())
        self.assertIsNone(self.session.keyframe_jpeg)

    def test_invalid_pose_dimensions_fail_closed_before_new_capture(self):
        self.add_frames()
        detect = self.session.engine.detect
        self.session.engine.detect = lambda *args: replace(detect(*args), width_px=2000)
        self.clock.now = 0.6
        with self.assertRaises(ValueError):
            self.manager.add_frame(self.session.session_id, self.session.token, b"\xff\xd8test", 3, 600)
        self.assertIsNone(self.finish().value_deg)

    def test_current_short_capture_preserves_value_and_new_trial_resets_integrity(self):
        self.add_frames()
        self.clock.now = 0.5
        measurement = self.finish(capture_monitor=monitor(duration=500, last=400))
        self.assertEqual(measurement.status, MeasurementStatus.VALID)
        self.assertIsNotNone(measurement.value_deg)
        self.clock.now = 100
        new = self.manager.start("right")
        self.assertFalse(new.capture_integrity.interrupted)
        self.assertIsNone(self.session.capture_integrity)

    def test_explicit_client_interruption_rejects_all_protocols_before_manual_flags(self):
        trial = synthetic_trial()
        for protocol in ("elbow_flexion_active", "knee_flexion_active", "neck_rotation_guided"):
            frames = tuple(replace(frame, protocol_id=protocol) for frame in trial.frames)
            measurement = assess_trial(replace(trial, frames=frames, interruption_reason="capture_interrupted"), protocol)
            self.assertEqual(measurement.quality_reasons, ("capture_interrupted",))
            self.assertIsNone(measurement.value_deg)

    def test_llm_call_provenance_is_bounded_aggregated_and_cleared_with_session(self):
        self.manager.record_llm_completion(self.session.session_id, self.session.token, "qwen36", "live",
                                           {"id": "qwen36", "model_alias": "local-model"}, True, True)
        self.clock.now = 0.1
        self.manager.record_llm_completion(self.session.session_id, self.session.token, "qwen36", "live",
                                           {"id": "qwen36"}, False, False)
        details = self.manager.llm_usage_details(self.session.session_id, self.session.token)
        self.assertEqual(len(details["records"]), 1)
        self.assertEqual(details["records"][0]["completion_call_count"], 2)
        self.assertTrue(details["records"][0]["image_payload_attached"])
        self.assertEqual(details["records"][0]["last_call_elapsed_ms"], 100)
        self.assertNotIn(self.session.token, json.dumps(details))
        details["records"][0]["model"]["model_alias"] = "mutated"
        self.assertEqual(self.manager.llm_usage_details(self.session.session_id, self.session.token)["records"][0]["model"]["model_alias"], "local-model")
        for i in range(5):
            self.manager.record_llm_completion(self.session.session_id, self.session.token, f"test{i}", "live", {}, False, False)
        with self.assertRaises(ValueError):
            self.manager.record_llm_completion(self.session.session_id, self.session.token, "overflow", "live", {}, False, False)
        self.manager.cancel(self.session.session_id, self.session.token)
        self.assertEqual(self.session.llm_usage, {})

    def test_cancelled_control_never_records_or_starts_another_completion(self):
        calls = []
        control = InferenceControl()

        class Client:
            def complete(self, _messages, _tools):
                calls.append("client")
                return {}

        controlled = ControlledChatClient(Client(), control, lambda _messages: calls.append("record"))
        control.cancel()
        with self.assertRaises(InferenceCancelled):
            controlled.complete([], [])
        self.assertEqual(calls, [])

    def test_control_is_rechecked_after_recording_before_transport(self):
        calls = []
        control = InferenceControl()

        class Client:
            def complete(self, _messages, _tools):
                calls.append("client")
                return {}

        controlled = ControlledChatClient(Client(), control, lambda _messages: control.cancel())
        with self.assertRaises(InferenceCancelled):
            controlled.complete([], [])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
