import time
import unittest
from dataclasses import replace

from packages.biomechanics.motion import summarize_motion
from packages.harness.demo import synthetic_trial
from packages.pose.jpeg import bounded_jpeg_dimensions
from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.state import SessionManager


def jpeg_header(width: int, height: int) -> bytes:
    return b"\xff\xd8\xff\xc0\x00\x0b\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x01\x01\x11\x00"


class MotionAndPrivacyTests(unittest.TestCase):
    def test_motion_keeps_source_time_and_missing_samples_without_interpolation(self):
        frames = synthetic_trial().frames
        frames = (replace(frames[0], timestamp_ms=1000),
                  replace(frames[1], timestamp_ms=1200, quality_reason="occlusion"),
                  replace(frames[2], timestamp_ms=2000))
        summary = summarize_motion(frames)
        self.assertEqual(summary["duration_ms"], 1000)
        self.assertEqual(summary["processed_frames"], 3)
        self.assertEqual(summary["usable_frames"], 2)
        self.assertEqual(summary["processing_rate_hz"], 2)
        self.assertIsNone(summary["samples"][1]["angle_deg"])
        self.assertEqual(summary["samples"][1]["quality_reason"], "occlusion")
        self.assertGreater(summary["observed_excursion_deg"], 0)

    def test_empty_motion_is_not_a_zero_degree_measurement(self):
        summary = summarize_motion(())
        self.assertEqual(summary["duration_ms"], 0)
        self.assertEqual(summary["processing_rate_hz"], 0)
        self.assertIsNone(summary["observed_excursion_deg"])

    def test_jpeg_dimensions_are_bounded_before_decode(self):
        self.assertEqual(bounded_jpeg_dimensions(jpeg_header(640, 480)), (640, 480))
        for width, height in ((20000, 10000), (640, 1081), (0, 0)):
            with self.assertRaises(ValueError):
                bounded_jpeg_dimensions(jpeg_header(width, height))
        for body in (b"not jpeg", b"\xff\xd8test", b"\xff\xd8\xff\xc0\x00\xff"):
            with self.assertRaises(ValueError):
                bounded_jpeg_dimensions(body)

    def test_completed_keyframe_expires_without_another_request(self):
        manager = SessionManager(SyntheticPoseEngine, ttl_seconds=0.15)
        self.addCleanup(manager.close)
        session = manager.start("left")
        for i in range(3):
            manager.add_frame(session.session_id, session.token, b"\xff\xd8test", i, i * 200)
        manager.finish(session.session_id, session.token, True, True)
        self.assertIsNotNone(session.keyframe_jpeg)
        deadline = time.monotonic() + 2
        while session.keyframe_jpeg is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertIsNone(session.keyframe_jpeg)
        self.assertIsNone(session.motion_summary)
        with self.assertRaises(PermissionError):
            manager.get(session.session_id, session.token)

    def test_foreign_token_cannot_read_evidence_or_motion(self):
        manager = SessionManager(SyntheticPoseEngine)
        self.addCleanup(manager.close)
        session = manager.start("right")
        for i in range(3):
            manager.add_frame(session.session_id, session.token, b"\xff\xd8test", i, i * 200)
        manager.finish(session.session_id, session.token, True, True)
        with self.assertRaises(PermissionError):
            manager.completed_snapshot(session.session_id, "foreign")
        details = manager.completed_details(session.session_id, session.token)
        self.assertIsNotNone(details["evidence_timestamp_ms"])
        self.assertEqual(details["motion"]["processed_frames"], 3)
        manager.start("left")
        self.assertIsNone(session.keyframe_jpeg)
        self.assertIsNone(session.motion_summary)

    def test_expired_active_engine_is_closed_and_frames_removed(self):
        class Engine(SyntheticPoseEngine):
            closed = False
            def close(self):
                self.closed = True
        engine = Engine()
        manager = SessionManager(lambda: engine)
        self.addCleanup(manager.close)
        session = manager.start("left")
        manager.add_frame(session.session_id, session.token, b"\xff\xd8test", 0, 0)
        session.expires_at = time.monotonic() - 1
        with self.assertRaises(PermissionError):
            manager.get(session.session_id, session.token)
        self.assertTrue(engine.closed)
        self.assertFalse(session.active)
        self.assertEqual(session.frames, [])


if __name__ == "__main__":
    unittest.main()
