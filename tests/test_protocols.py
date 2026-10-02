from dataclasses import replace
from math import atan, degrees
import unittest

from packages.biomechanics.protocols import angle_and_reason, assess_trial, get_protocol, protocol_catalog, render_protocol_draft
from packages.contracts.models import ElbowTrial, MeasurementStatus, Point2D, PoseFrame
from packages.pose.adapter import PoseObservation
from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.state import SessionManager


def frame(protocol_id, landmarks, sequence=0, side="left", width=1000, height=1000):
    return PoseFrame(sequence, sequence * 200, width, height,
                     landmarks.get(f"{side}_shoulder"), landmarks.get(f"{side}_elbow"), landmarks.get(f"{side}_wrist"),
                     True, True, landmarks=landmarks, protocol_id=protocol_id, side=side)


class ProtocolTests(unittest.TestCase):
    def test_catalog_is_explicit_and_rotation_never_promises_quantification(self):
        catalog = protocol_catalog()
        self.assertEqual(len(catalog), 7)
        self.assertEqual(sum(item["quantified"] for item in catalog), 6)
        self.assertFalse(catalog[-1]["quantified"])
        self.assertEqual([item["id"] for item in catalog if item["harness_supported"]], ["elbow_flexion_active"])
        with self.assertRaises(ValueError):
            get_protocol("imaginary_clinical_test")

    def test_joint_triplets_have_the_correct_convention(self):
        for protocol_id in ("elbow_flexion_active", "knee_flexion_active", "shoulder_abduction_active", "hip_flexion_active"):
            with self.subTest(protocol=protocol_id):
                names = get_protocol(protocol_id).names("left")
                landmarks = dict(zip(names, (Point2D(.5, .2), Point2D(.5, .5), Point2D(.8, .5))))
                self.assertAlmostEqual(angle_and_reason(frame(protocol_id, landmarks))[0], 90)
                straight = dict(zip(names, (Point2D(.5, .2), Point2D(.5, .5), Point2D(.5, .8))))
                expected = 180 if protocol_id == "shoulder_abduction_active" else 0
                self.assertAlmostEqual(angle_and_reason(frame(protocol_id, straight))[0], expected)

    def test_head_proxy_uses_pixel_aspect_and_is_mirror_invariant(self):
        landmarks = {"left_ear": Point2D(.3, .1), "right_ear": Point2D(.5, .3),
                     "left_shoulder": Point2D(.3, .5), "right_shoulder": Point2D(.7, .5)}
        original = frame("neck_lateral_inclination", landmarks, width=1000, height=500)
        self.assertAlmostEqual(angle_and_reason(original)[0], degrees(atan(.5)))
        mirrored = replace(original, landmarks={key: Point2D(1 - point.x, point.y) for key, point in landmarks.items()})
        self.assertAlmostEqual(angle_and_reason(mirrored)[0], angle_and_reason(original)[0])

    def test_trunk_proxy_uses_midpoints_relative_to_image_vertical(self):
        landmarks = {"left_shoulder": Point2D(.55, .2), "right_shoulder": Point2D(.75, .2),
                     "left_hip": Point2D(.4, .7), "right_hip": Point2D(.6, .7)}
        self.assertAlmostEqual(angle_and_reason(frame("trunk_lateral_inclination", landmarks, width=1000, height=500))[0], degrees(atan(.6)))

    def test_right_side_is_not_silently_computed_from_left_landmarks(self):
        landmarks = {"left_hip": Point2D(.4, .3), "left_knee": Point2D(.4, .5), "left_ankle": Point2D(.4, .8),
                     "right_hip": Point2D(.6, .3), "right_knee": Point2D(.6, .5), "right_ankle": Point2D(.8, .5)}
        self.assertAlmostEqual(angle_and_reason(frame("knee_flexion_active", landmarks, side="right"), "right")[0], 90)

    def test_occluded_arm_does_not_reject_a_knee_trial(self):
        landmarks = {"left_hip": Point2D(.4, .3), "left_knee": Point2D(.4, .5), "left_ankle": Point2D(.7, .5)}
        class Engine:
            def detect(self, *_args):
                return PoseObservation(640, 480, None, None, None, landmarks=landmarks)
            def close(self):
                pass
        manager = SessionManager(Engine)
        try:
            session = manager.start("left", "knee_flexion_active")
            for index in range(3):
                observation = manager.add_frame(session.session_id, session.token, b"\xff\xd8test", index, index * 200)
                self.assertIsNone(observation.quality_reason)
            result = manager.finish(session.session_id, session.token, True, True)
            self.assertEqual(result.status, MeasurementStatus.LIMITED)
            self.assertIn("experimental_protocol", result.quality_reasons)
            self.assertAlmostEqual(result.value_deg, 90)
            self.assertNotIn("coude", render_protocol_draft(result))
        finally:
            manager.close()

    def test_missing_out_of_frame_and_degenerate_points_abstain(self):
        protocol = "neck_lateral_inclination"
        self.assertEqual(angle_and_reason(frame(protocol, {})), (None, "occlusion"))
        landmarks = dict(zip(get_protocol(protocol).names("left"), (Point2D(-.1, .2), Point2D(.7, .2), Point2D(.3, .4), Point2D(.7, .4))))
        self.assertEqual(angle_and_reason(frame(protocol, landmarks)), (None, "out_of_frame"))
        landmarks["left_ear"] = landmarks["right_ear"]
        self.assertEqual(angle_and_reason(frame(protocol, landmarks)), (None, "degenerate_landmarks"))

    def test_new_trials_require_manual_checks_and_enough_coverage(self):
        protocol = "knee_flexion_active"
        landmarks = dict(zip(get_protocol(protocol).names("left"), (Point2D(.5, .2), Point2D(.5, .5), Point2D(.8, .5))))
        frames = tuple(frame(protocol, landmarks, i) for i in range(3))
        trial = ElbowTrial("trial", "session", "left", frames)
        self.assertEqual(assess_trial(trial, protocol).status, MeasurementStatus.LIMITED)
        for attribute in ("view_is_valid", "camera_stable"):
            result = assess_trial(replace(trial, frames=tuple(replace(f, **{attribute: None}) for f in frames)), protocol)
            self.assertIsNone(result.value_deg)
        result = assess_trial(replace(trial, frames=(frames[0], frames[1], replace(frames[2], landmarks={}))), protocol)
        self.assertIn("insufficient_coverage", result.quality_reasons)
        self.assertIsNone(result.value_deg)
        self.assertIsNone(assess_trial(replace(trial, stopped=True), protocol).value_deg)

    def test_all_protocols_complete_without_inventing_a_rotation_angle(self):
        manager = SessionManager(SyntheticPoseEngine)
        try:
            for item in protocol_catalog():
                with self.subTest(protocol=item["id"]):
                    session = manager.start("left", item["id"])
                    for index in range(3):
                        manager.add_frame(session.session_id, session.token, b"\xff\xd8test", index, index * 200)
                    result = manager.finish(session.session_id, session.token, True, True)
                    self.assertEqual(result.protocol_id, item["id"])
                    report = render_protocol_draft(result)
                    self.assertIn("BROUILLON NON VALIDÉ", report)
                    if item["quantified"]:
                        self.assertIsNotNone(result.value_deg)
                        self.assertIsNotNone(manager.completed_snapshot(session.session_id, session.token)[1])
                    else:
                        self.assertIsNone(result.value_deg)
                        self.assertEqual(result.quality_reasons, ("rotation_not_measurable_2d",))
                        self.assertIsNone(manager.completed_snapshot(session.session_id, session.token)[1])
                        self.assertTrue(all(s["angle_deg"] is None for s in session.motion_summary["samples"]))
        finally:
            manager.close()
