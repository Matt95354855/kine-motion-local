import time
import unittest
from dataclasses import replace

from packages.harness.demo import synthetic_trial
from packages.harness.window import MAX_IMAGES, MAX_SAMPLES, RollingCaptureWindow
from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.state import SessionManager


JPEG = b"\xff\xd8test"


class LiveWindowTests(unittest.TestCase):
    def frame(self, sequence, timestamp):
        return replace(synthetic_trial().frames[0], sequence=sequence, timestamp_ms=timestamp)

    def test_counts_and_source_time_are_bounded_without_retaining_whole_video(self):
        window = RollingCaptureWindow()
        window.set_image_consent(True)
        for i in range(100):
            window.append(self.frame(i, i * 200), JPEG + bytes([i]), i * 0.2)
        info = window.info("current", 19.8)
        self.assertEqual(info["sample_count"], MAX_SAMPLES)
        self.assertEqual(info["image_count"], MAX_IMAGES)
        self.assertGreaterEqual(info["start_timestamp_ms"], 15000)
        self.assertLess(info["end_timestamp_ms"] - info["start_timestamp_ms"], 5000)
        self.assertTrue(all(image.sequence >= 75 for image in window.images))

    def test_time_window_also_expires_without_new_source_frame(self):
        window = RollingCaptureWindow()
        window.set_image_consent(True)
        window.append(self.frame(0, 0), JPEG, 100)
        info = window.info("current", 105)
        self.assertEqual(info["sample_count"], 0)
        self.assertEqual(info["image_count"], 0)
        self.assertEqual(window.observation_samples(), ())

    def test_source_jump_evicts_old_images_even_if_arrivals_are_fast(self):
        window = RollingCaptureWindow()
        window.set_image_consent(True)
        window.append(self.frame(0, 0), JPEG, 100)
        window.append(self.frame(1, 10000), JPEG + b"new", 100.01)
        self.assertEqual(window.info("current", 100.01)["sample_count"], 1)
        self.assertEqual(tuple(image.sequence for image in window.images), (1,))

    def test_images_require_consent_and_are_cleared_on_revocation(self):
        window = RollingCaptureWindow()
        window.append(self.frame(0, 0), JPEG, 0)
        self.assertEqual(len(window.images), 0)
        window.set_image_consent(True)
        self.assertEqual(len(window.images), 0)  # Never backfill captures before consent.
        window.append(self.frame(1, 200), JPEG + b"consented", 0.2)
        window.append(self.frame(2, 400), JPEG + b"skip", 0.4)
        self.assertEqual(len(window.images), 1)
        window.set_image_consent(False)
        self.assertEqual(len(window.images), 0)
        window.append(self.frame(3, 600), JPEG, 0.6)
        self.assertEqual(len(window.images), 0)
        with self.assertRaises(ValueError):
            window.set_image_consent("true")

    def test_image_byte_limit_and_clear(self):
        window = RollingCaptureWindow()
        window.set_image_consent(True)
        with self.assertRaises(ValueError):
            window.append(self.frame(0, 0), b"\xff\xd8" + b"x" * 1_000_000, 0)
        self.assertEqual(len(window.samples), 0)
        window.clear()
        self.assertEqual(window.info("current", 1)["sample_count"], 0)
        self.assertFalse(window.image_consent)

    def test_missing_guide_points_do_not_mean_successful_tracking(self):
        window = RollingCaptureWindow()
        frame = replace(self.frame(0, 0), protocol_id="neck_rotation_guided", landmarks={})
        window.append(frame, JPEG, 0)
        self.assertIsNone(window.observation_samples()[0]["angle_deg"])
        self.assertEqual(window.observation_samples()[0]["quality_reason"], "occlusion")

    def test_manager_snapshot_is_independent_and_does_not_expose_tokens(self):
        manager = SessionManager(SyntheticPoseEngine)
        self.addCleanup(manager.close)
        session = manager.start("left")
        manager.add_frame(session.session_id, session.token, JPEG, 0, 0)
        snapshot = manager.live_snapshot(session.session_id, session.token, True)
        self.assertEqual(snapshot.images, ())
        manager.set_live_image_consent(session.session_id, session.token, True)
        manager.add_frame(session.session_id, session.token, JPEG + b"new", 1, 1000)
        with_images = manager.live_snapshot(session.session_id, session.token, True)
        self.assertEqual(with_images.images, (JPEG + b"new",))
        self.assertEqual(len(snapshot.samples), 1)
        self.assertNotIn(session.token, repr(snapshot))
        self.assertEqual(manager.live_snapshot(session.session_id, session.token).images, ())
        with self.assertRaises(PermissionError):
            manager.live_snapshot(session.session_id, "other", True)
        manager.cancel(session.session_id, session.token)
        self.assertEqual(session.live_window.info(session.session_id, 100)["sample_count"], 0)

    def test_finish_discards_live_memory_and_completed_capture_cannot_be_polled(self):
        manager = SessionManager(SyntheticPoseEngine)
        self.addCleanup(manager.close)
        session = manager.start("left")
        manager.set_live_image_consent(session.session_id, session.token, True)
        for i in range(3):
            manager.add_frame(session.session_id, session.token, JPEG, i, i * 1000)
        manager.finish(session.session_id, session.token, True, True)
        self.assertEqual(len(session.live_window.images), 0)
        self.assertEqual(len(session.live_window.samples), 0)
        with self.assertRaises(ValueError):
            manager.live_snapshot(session.session_id, session.token)
        self.assertIsNotNone(session.keyframe_jpeg)  # Existing final proof is a separate path.

    def test_idle_reaper_discards_expired_live_images_without_another_request(self):
        manager = SessionManager(SyntheticPoseEngine)
        self.addCleanup(manager.close)
        session = manager.start("left")
        manager.set_live_image_consent(session.session_id, session.token, True)
        manager.add_frame(session.session_id, session.token, JPEG, 0, 0)
        with manager._lock:
            window = session.live_window
            received_at, frame = window.samples[0]
            window.samples[0] = (received_at - 6, frame)
            window.images[0] = replace(window.images[0], received_at=received_at - 6)
        deadline = time.monotonic() + 2
        while window.samples and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(window.samples), 0)
        self.assertEqual(len(window.images), 0)
        self.assertEqual(len(session.frames), 1)  # Structured trial history is not the LLM buffer.
