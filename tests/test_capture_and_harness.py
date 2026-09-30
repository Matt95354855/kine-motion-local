import json
import unittest

from packages.contracts.models import MeasurementStatus
from packages.harness.demo import synthetic_trial
from packages.harness.local_llm import LocalLLMClient
from packages.harness.runner import run_harness
from packages.harness.tools import ToolContext, ToolRegistry
from packages.biomechanics.elbow import assess_elbow_trial
from packages.pose.adapter import PoseObservation
from packages.contracts.models import Point2D
from services.api.state import SessionManager


class FakePoseEngine:
    def __init__(self) -> None:
        self.closed = False

    def detect(self, jpeg_bytes: bytes, timestamp_ms: int, side: str) -> PoseObservation:
        return PoseObservation(
            640, 480, Point2D(0.5, 0.25), Point2D(0.5, 0.5), Point2D(0.7, 0.5)
        )

    def close(self) -> None:
        self.closed = True


class FakeToolCallingLLM:
    def __init__(self, measurement_ref: str) -> None:
        self.measurement_ref = measurement_ref
        self.calls = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {
                "content": None,
                "tool_calls": [{
                    "id": "call_a",
                    "function": {"name": "get_capture_observation", "arguments": "{}"},
                }],
            }
        assert messages[-1]["role"] == "tool"
        assert "quality_reasons" in json.loads(messages[-1]["content"])
        return {"content": json.dumps({
            "measurement_ref": self.measurement_ref,
            "text": "Vue à vérifier par le professionnel.",
            "requires_professional_review": True,
        })}


class CaptureAndHarnessTests(unittest.TestCase):
    def test_frames_stay_in_memory_and_finish_requires_quality_confirmation(self) -> None:
        engine = FakePoseEngine()
        manager = SessionManager(lambda: engine)
        session = manager.start("left")
        for number in range(3):
            manager.add_frame(session.session_id, session.token, b"\xff\xd8test", number, number * 200)
        measurement = manager.finish(session.session_id, session.token, None, True)
        self.assertEqual(measurement.status, MeasurementStatus.REJECTED)
        self.assertEqual(measurement.quality_reasons, ("view_unverified",))
        self.assertIsNone(measurement.value_deg)
        self.assertEqual(session.frames, [])
        self.assertIsNone(session.keyframe_jpeg)
        self.assertTrue(engine.closed)

    def test_valid_trial_keeps_only_one_keyframe_until_revoked(self) -> None:
        manager = SessionManager(FakePoseEngine)
        session = manager.start("left")
        for number in range(3):
            manager.add_frame(session.session_id, session.token, b"\xff\xd8test", number, number * 200)
        measurement = manager.finish(session.session_id, session.token, True, True)
        self.assertEqual(measurement.status, MeasurementStatus.VALID)
        snapshot, keyframe = manager.completed_snapshot(session.session_id, session.token)
        self.assertEqual(snapshot.measurement_id, measurement.measurement_id)
        self.assertEqual(keyframe, b"\xff\xd8test")
        self.assertEqual(session.frames, [])
        manager.cancel(session.session_id, session.token)
        with self.assertRaises(PermissionError):
            manager.completed_snapshot(session.session_id, session.token)

    def test_previous_session_token_and_non_monotonic_frame_are_rejected(self) -> None:
        manager = SessionManager(FakePoseEngine)
        old = manager.start("left")
        current = manager.start("right")
        with self.assertRaises(PermissionError):
            manager.add_frame(old.session_id, old.token, b"\xff\xd8test", 0, 0)
        manager.add_frame(current.session_id, current.token, b"\xff\xd8test", 0, 0)
        with self.assertRaises(ValueError):
            manager.add_frame(current.session_id, current.token, b"\xff\xd8test", 0, 200)
        manager.close()

    def test_llm_can_read_only_current_session_and_note_stays_separate(self) -> None:
        measurement = assess_elbow_trial(synthetic_trial())
        context = ToolContext(measurement.session_id, measurement)
        model = FakeToolCallingLLM(measurement.measurement_id)
        result = run_harness(context, model)
        self.assertEqual(result.tool_names, ("get_capture_observation",))
        self.assertEqual(result.proposed_note, "Vue à vérifier par le professionnel.")
        self.assertNotIn(result.proposed_note, result.deterministic_draft)
        self.assertIsNone(result.fallback_reason)

        with self.assertRaises(ValueError):
            ToolContext("another_session", measurement)
        with self.assertRaises(ValueError):
            ToolRegistry().call("get_session_measurements", {"session_id": "another_session"}, context)

    def test_unlisted_tool_and_invented_number_fall_back(self) -> None:
        measurement = assess_elbow_trial(synthetic_trial())
        context = ToolContext(measurement.session_id, measurement)

        class InvalidTool:
            def complete(self, messages, tools):
                return {"tool_calls": [{
                    "id": "x", "function": {"name": "read_file", "arguments": "{}"}
                }]}

        self.assertIsNone(run_harness(context, InvalidTool()).proposed_note)

        class InventedNumber:
            def complete(self, messages, tools):
                return {"content": json.dumps({
                    "measurement_ref": measurement.measurement_id,
                    "text": "Angle de 150 degrés.",
                    "requires_professional_review": True,
                })}

        self.assertIsNone(run_harness(context, InventedNumber()).proposed_note)

    def test_remote_llm_address_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            LocalLLMClient("https://example.com", "model")

    def test_opt_in_visual_harness_sends_only_current_keyframe_to_local_model(self) -> None:
        measurement = assess_elbow_trial(synthetic_trial())
        context = ToolContext(measurement.session_id, measurement, b"\xff\xd8fake")

        class VisionModel:
            def complete(self, messages, tools):
                image = messages[1]["content"][1]["image_url"]["url"]
                assert image.startswith("data:image/jpeg;base64,")
                return {"content": json.dumps({
                    "measurement_ref": measurement.measurement_id,
                    "text": "La vue demande une vérification humaine.",
                    "requires_professional_review": True,
                })}

        result = run_harness(context, VisionModel(), allow_visual_evidence=True)
        self.assertEqual(result.tool_names, ("get_capture_keyframe",))
        self.assertIsNotNone(result.proposed_note)


if __name__ == "__main__":
    unittest.main()
