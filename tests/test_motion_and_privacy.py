import time
import unittest
import json
from dataclasses import replace
from math import cos, radians, sin
from unittest.mock import patch

from packages.biomechanics.elbow import assess_elbow_trial
from packages.biomechanics.motion import MAX_INVALID_INTERVALS, summarize_motion
from packages.contracts.models import ElbowTrial, MeasurementStatus, Point2D, PoseFrame
from packages.harness.demo import synthetic_trial
from packages.pose.jpeg import bounded_jpeg_dimensions
from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.state import SessionManager


def jpeg_header(width: int, height: int) -> bytes:
    return b"\xff\xd8\xff\xc0\x00\x0b\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x01\x01\x11\x00"


class MotionAndPrivacyTests(unittest.TestCase):
    def frame(self, sequence, timestamp_ms, angle=30, reason=None, width=640, height=480):
        # Repères synthétiques en pixels, puis normalisés ; aucune vidéo réelle.
        radius = height / 4
        joint_x, joint_y = width / 2, height / 2
        return PoseFrame(
            sequence, timestamp_ms, width, height,
            Point2D(joint_x / width, (joint_y - radius) / height),
            Point2D(joint_x / width, joint_y / height),
            Point2D((joint_x + radius * sin(radians(angle))) / width,
                    (joint_y + radius * cos(radians(angle))) / height),
            view_is_valid=True, camera_stable=True, quality_reason=reason,
        )

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
        diagnostics = summary["robustness"]
        self.assertIsNone(diagnostics["raw_peak"])
        self.assertEqual(diagnostics["invalid_intervals"], [])
        self.assertEqual(diagnostics["longest_invalid_observed_duration_ms"], 0)
        self.assertIsNone(diagnostics["max_adjacent_sample_gap_ms"])
        self.assertTrue(all(value is None for value in diagnostics["analyzed_image_dimensions"].values()))

    def test_technical_diagnostics_leave_legacy_sample_contract_and_measurement_unchanged(self):
        frames = tuple(self.frame(index, index * 200, angle) for index, angle in enumerate((10, 100, 20)))
        trial = ElbowTrial("raw-peak", "session", "left", frames)
        before = assess_elbow_trial(trial)
        summary = summarize_motion(frames)
        after = assess_elbow_trial(trial)
        self.assertEqual(before, after)
        self.assertEqual(before.status, MeasurementStatus.VALID)
        self.assertAlmostEqual(before.value_deg, 100)
        self.assertEqual(before.evidence_refs, ("raw-peak:frame:1",))
        for sample in summary["samples"]:
            self.assertEqual(set(sample), {"sequence", "timestamp_ms", "angle_deg", "quality_reason"})
        peak = summary["robustness"]["raw_peak"]
        self.assertEqual(peak["sequence"], 1)
        self.assertEqual(peak["temporal_context"], "before_and_after")
        # Un écart très grand reste descriptif : aucune correction, probabilité
        # de support ou décision clinique n'est dérivée des deux voisins.
        self.assertEqual(peak["before"]["delta_deg"], 90)
        self.assertEqual(peak["after"]["delta_deg"], 80)

    def test_peak_ties_keep_first_maximum_and_show_consecutive_neighbors(self):
        frames = tuple(self.frame(index, index * 200, angle) for index, angle in enumerate((10, 80, 80, 30)))
        summary = summarize_motion(frames)
        peak = summary["robustness"]["raw_peak"]
        self.assertEqual(peak["sequence"], 1)
        self.assertEqual(peak["timestamp_ms"], 200)
        self.assertEqual(peak["temporal_context"], "before_and_after")
        self.assertEqual(peak["after"]["delta_deg"], 0)
        self.assertEqual(peak["neighbor_gap_limit_ms"], 1000)

    def test_peak_does_not_jump_over_occlusion_to_find_distant_valid_samples(self):
        frames = tuple(self.frame(index, index * 200, angle, reason) for index, (angle, reason) in enumerate((
            (10, None), (20, "occlusion"), (80, None), (70, "no_pose"), (30, None),
        )))
        diagnostics = summarize_motion(frames)["robustness"]
        peak = diagnostics["raw_peak"]
        self.assertEqual(peak["temporal_context"], "isolated")
        self.assertIsNone(peak["before"])
        self.assertIsNone(peak["after"])
        self.assertEqual(peak["before_unavailable_reason"], "invalid_sample")
        self.assertEqual(peak["after_unavailable_reason"], "invalid_sample")
        self.assertEqual(diagnostics["invalid_reason_counts"], {"no_pose": 1, "occlusion": 1})
        self.assertEqual(diagnostics["invalid_interval_count"], 2)
        self.assertEqual(diagnostics["longest_invalid_observed_duration_ms"], 0)

    def test_peak_neighborhood_uses_time_limit_and_sequence_continuity(self):
        frames = (self.frame(0, 0, 10), self.frame(1, 1000, 80), self.frame(2, 2200, 30))
        diagnostics = summarize_motion(frames)["robustness"]
        peak = diagnostics["raw_peak"]
        self.assertEqual(peak["temporal_context"], "before_only")
        self.assertEqual(peak["before"]["gap_ms"], 1000)
        self.assertIsNone(peak["after"])
        self.assertEqual(peak["after_unavailable_reason"], "time_gap")
        self.assertEqual(diagnostics["max_adjacent_sample_gap_ms"], 1200)
        gap_frames = (self.frame(0, 0, 10), self.frame(2, 200, 80), self.frame(3, 400, 30))
        peak = summarize_motion(gap_frames)["robustness"]["raw_peak"]
        self.assertEqual(peak["temporal_context"], "after_only")
        self.assertEqual(peak["before_unavailable_reason"], "sequence_gap")

    def test_largest_adjacent_change_is_signed_raw_difference_away_from_peak(self):
        angles = (130, 95, 100, 34.8, 40)
        timestamps = (0, 200, 400, 601, 800)
        frames = tuple(self.frame(index, timestamp, angle)
                       for index, (angle, timestamp) in enumerate(zip(angles, timestamps)))
        trial = ElbowTrial("unchanged", "session", "left", frames)
        original = assess_elbow_trial(trial)
        diagnostics = summarize_motion(frames)["robustness"]
        self.assertEqual(diagnostics["raw_peak"]["sequence"], 0)
        self.assertEqual(diagnostics["largest_adjacent_angle_change"], {
            "start_sequence": 2, "end_sequence": 3,
            "start_timestamp_ms": 400, "end_timestamp_ms": 601,
            "gap_ms": 201, "delta_deg": -65.2,
        })
        self.assertEqual(assess_elbow_trial(trial), original)
        self.assertNotIn("outlier", json.dumps(diagnostics))

    def test_largest_change_skips_invalid_samples_sequence_holes_and_large_time_gaps(self):
        frames = (
            self.frame(0, 0, 10), self.frame(1, 200, 50, reason="occlusion"),
            self.frame(2, 400, 90), self.frame(4, 600, 0),
            self.frame(5, 1601, 100), self.frame(6, 1801, 90),
        )
        change = summarize_motion(frames)["robustness"]["largest_adjacent_angle_change"]
        self.assertEqual(change, {
            "start_sequence": 5, "end_sequence": 6,
            "start_timestamp_ms": 1601, "end_timestamp_ms": 1801,
            "gap_ms": 200, "delta_deg": -10,
        })

    def test_largest_change_keeps_first_absolute_tie_and_zero_without_clinical_threshold(self):
        frames = tuple(self.frame(index, index * 1000) for index in range(3))
        for angles, expected_delta in (((50, 40, 50), -10), ((30, 30, 30), 0)):
            with self.subTest(angles=angles), \
                    patch("packages.biomechanics.motion.frame_angle", side_effect=angles):
                change = summarize_motion(frames)["robustness"]["largest_adjacent_angle_change"]
                self.assertEqual(change["start_sequence"], 0)
                self.assertEqual(change["end_sequence"], 1)
                self.assertEqual(change["gap_ms"], 1000)
                self.assertEqual(change["delta_deg"], expected_delta)
        for bad_frames in (
            (), frames[:1],
            (self.frame(0, 0), self.frame(1, 0)),
            (self.frame(0, 1000), self.frame(1, 200)),
            tuple(replace(frame, protocol_id="neck_rotation_guided") for frame in frames),
        ):
            with self.subTest(frame_count=len(bad_frames)):
                change = summarize_motion(bad_frames)["robustness"]["largest_adjacent_angle_change"]
                self.assertIsNone(change)

    def test_invalid_intervals_use_received_source_times_without_extending_to_valid_frames(self):
        frames = (
            self.frame(0, 0), self.frame(1, 100, reason="occlusion"),
            self.frame(2, 400, reason="no_pose"), self.frame(3, 900, reason="occlusion"),
            self.frame(4, 1500), self.frame(5, 2000, reason="occlusion"),
        )
        diagnostics = summarize_motion(frames)["robustness"]
        self.assertEqual(diagnostics["usable_frames"], 2)
        self.assertEqual(diagnostics["unusable_frames"], 4)
        self.assertEqual(diagnostics["invalid_reason_counts"], {"no_pose": 1, "occlusion": 3})
        self.assertEqual(diagnostics["longest_invalid_observed_duration_ms"], 800)
        self.assertEqual(diagnostics["invalid_intervals"][0], {
            "start_sequence": 1, "end_sequence": 3,
            "start_timestamp_ms": 100, "end_timestamp_ms": 900,
            "observed_duration_ms": 800, "frame_count": 3,
            "reasons": ["no_pose", "occlusion"],
        })
        self.assertEqual(diagnostics["invalid_intervals"][1]["observed_duration_ms"], 0)

    def test_invalid_intervals_are_bounded_while_total_counts_remain_exact(self):
        frames = tuple(self.frame(index, index * 200, reason="occlusion" if index % 2 else None)
                       for index in range(150))
        diagnostics = summarize_motion(frames)["robustness"]
        self.assertEqual(len(diagnostics["invalid_intervals"]), MAX_INVALID_INTERVALS)
        self.assertEqual(diagnostics["invalid_interval_count"], 75)
        self.assertTrue(diagnostics["invalid_intervals_truncated"])
        self.assertEqual(diagnostics["invalid_reason_counts"], {"occlusion": 75})

    def test_derived_geometry_reasons_do_not_change_raw_sample_quality_reason(self):
        base = self.frame(0, 0)
        frames = (replace(base, wrist=None),
                  replace(base, sequence=1, timestamp_ms=200, wrist=Point2D(1.1, 0.5)),
                  replace(base, sequence=2, timestamp_ms=400, wrist=base.elbow))
        summary = summarize_motion(frames)
        self.assertTrue(all(sample["quality_reason"] is None for sample in summary["samples"]))
        self.assertEqual(summary["robustness"]["invalid_reason_counts"], {
            "degenerate_landmarks": 1, "occlusion": 1, "out_of_frame": 1,
        })
        self.assertIsNone(summary["robustness"]["raw_peak"])

    def test_actual_analyzed_image_dimensions_are_reported_without_pixels(self):
        frames = (self.frame(0, 0, width=640, height=480),
                  self.frame(1, 200, width=320, height=180),
                  self.frame(2, 400, width=1920, height=1080))
        diagnostics = summarize_motion(frames)["robustness"]
        self.assertEqual(diagnostics["analyzed_image_dimensions"], {
            "min_width_px": 320, "max_width_px": 1920,
            "min_height_px": 180, "max_height_px": 1080,
        })
        self.assertNotIn("jpeg", json.dumps(diagnostics))
        self.assertNotIn("landmarks", json.dumps(diagnostics))

    def test_bad_timestamp_order_has_no_negative_duration_or_supported_context(self):
        frames = (self.frame(0, 100, 80), self.frame(1, 100, reason="occlusion"),
                  self.frame(2, 50, reason="occlusion"))
        diagnostics = summarize_motion(frames)["robustness"]
        self.assertFalse(diagnostics["timestamps_strictly_increasing"])
        self.assertIsNone(diagnostics["max_adjacent_sample_gap_ms"])
        self.assertIsNone(diagnostics["longest_invalid_observed_duration_ms"])
        self.assertIsNone(diagnostics["invalid_intervals"][0]["observed_duration_ms"])
        self.assertEqual(diagnostics["raw_peak"]["temporal_context"], "isolated")
        self.assertEqual(diagnostics["raw_peak"]["after_unavailable_reason"], "timestamp_order")

    def test_nonfinite_angles_are_not_used_by_technical_peak_diagnostic(self):
        frames = tuple(self.frame(index, index * 200) for index in range(3))
        with patch("packages.biomechanics.motion.frame_angle", side_effect=(float("nan"), float("inf"), 30)):
            diagnostics = summarize_motion(frames)["robustness"]
        self.assertEqual(diagnostics["usable_frames"], 1)
        self.assertEqual(diagnostics["invalid_reason_counts"], {"nonfinite_angle": 2})
        self.assertEqual(diagnostics["raw_peak"]["sequence"], 2)
        self.assertEqual(diagnostics["raw_peak"]["temporal_context"], "isolated")
        self.assertIsNone(diagnostics["largest_adjacent_angle_change"])
        json.dumps(diagnostics, allow_nan=False)
        for invalid_time in (float("nan"), float("inf"), -1):
            with self.subTest(timestamp_ms=invalid_time), self.assertRaises(ValueError):
                replace(frames[0], timestamp_ms=invalid_time)

    def test_guide_only_absent_angle_is_not_reported_as_tracking_loss(self):
        frames = tuple(replace(self.frame(index, index * 200), protocol_id="neck_rotation_guided")
                       for index in range(3))
        diagnostics = summarize_motion(frames)["robustness"]
        self.assertFalse(diagnostics["quantified_protocol"])
        self.assertEqual(diagnostics["usable_frames"], 0)
        self.assertEqual(diagnostics["nonquantified_frames"], 3)
        self.assertEqual(diagnostics["invalid_reason_counts"], {})
        self.assertEqual(diagnostics["invalid_intervals"], [])
        self.assertIsNone(diagnostics["raw_peak"])
        with_loss = frames[:1] + (replace(frames[1], quality_reason="no_pose"),) + frames[2:]
        diagnostics = summarize_motion(with_loss)["robustness"]
        self.assertEqual(diagnostics["nonquantified_frames"], 2)
        self.assertEqual(diagnostics["invalid_reason_counts"], {"no_pose": 1})
        self.assertEqual(diagnostics["invalid_interval_count"], 1)

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
