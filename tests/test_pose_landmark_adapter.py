from dataclasses import asdict
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from packages.biomechanics.protocols import angle_and_reason
from packages.contracts.models import LandmarkDiagnostic, Point2D, PoseFrame
from packages.pose.adapter import PoseObservation
from packages.pose.mediapipe_engine import MediaPipePoseEngine, POSE_OPTIONS, observation_from_landmarks


class LandmarkAdapterTests(unittest.TestCase):
    def landmarks(self):
        return [SimpleNamespace(x=index / 33, y=.5, visibility=1, presence=1) for index in range(33)]

    def test_anatomical_indices_are_not_swapped_for_ears_arms_and_legs(self):
        source = self.landmarks()
        observation = observation_from_landmarks(640, 480, source, "right")
        for name, index in (("left_ear", 7), ("right_ear", 8), ("left_shoulder", 11), ("right_shoulder", 12),
                            ("left_hip", 23), ("right_hip", 24), ("left_knee", 25), ("right_knee", 26),
                            ("left_ankle", 27), ("right_ankle", 28)):
            self.assertEqual(observation.landmarks[name].x, source[index].x)
        self.assertEqual(observation.shoulder, observation.landmarks["right_shoulder"])
        self.assertEqual(observation.wrist, observation.landmarks["right_wrist"])

    def test_occlusion_and_non_finite_confidence_do_not_erase_unrelated_points(self):
        source = self.landmarks()
        source[15].visibility = .1
        source[7].presence = float("nan")
        source[8].x = float("nan")
        observation = observation_from_landmarks(640, 480, source, "left")
        self.assertIsNone(observation.wrist)
        self.assertIsNone(observation.landmarks["left_ear"])
        self.assertIsNone(observation.landmarks["right_ear"])
        self.assertIsNotNone(observation.landmarks["left_knee"])
        self.assertIsNone(observation.quality_reason)

    def test_incomplete_landmark_output_abstains(self):
        observation = observation_from_landmarks(640, 480, [], "left")
        self.assertEqual(observation.quality_reason, "degenerate_landmarks")
        self.assertEqual(len(observation.landmark_diagnostics), 14)
        self.assertTrue(all(item.reason == "missing_landmark" and not item.accepted
                            for item in observation.landmark_diagnostics.values()))

    def test_native_options_use_explicit_unchanged_thresholds_cpu_video_and_two_poses(self):
        base_options, pose_options = Mock(), Mock()
        base_options.Delegate.CPU = "cpu"
        landmarker = Mock()
        fake_mp = SimpleNamespace(tasks=SimpleNamespace(
            BaseOptions=base_options,
            vision=SimpleNamespace(PoseLandmarkerOptions=pose_options,
                                   RunningMode=SimpleNamespace(VIDEO="video"),
                                   PoseLandmarker=landmarker),
        ))
        with patch.dict("sys.modules", {"cv2": Mock(), "mediapipe": fake_mp, "numpy": Mock()}), \
             patch("packages.pose.mediapipe_engine.Path.is_file", return_value=True), \
             patch("packages.pose.mediapipe_engine.Path.mkdir"), patch.dict("os.environ", {}):
            engine = MediaPipePoseEngine("synthetic-model.task")
            engine.close()
        self.assertEqual(POSE_OPTIONS, {
            "num_poses": 2, "min_pose_detection_confidence": 0.5,
            "min_pose_presence_confidence": 0.5, "min_tracking_confidence": 0.5,
            "output_segmentation_masks": False,
        })
        base_options.assert_called_once_with(model_asset_path="synthetic-model.task", delegate="cpu")
        pose_options.assert_called_once_with(base_options=base_options.return_value,
                                             running_mode="video", **POSE_OPTIONS)
        landmarker.create_from_options.assert_called_once_with(pose_options.return_value)
        landmarker.create_from_options.return_value.close.assert_called_once()

    def test_threshold_decisions_and_scores_are_preserved_exactly(self):
        for visibility in (0, 0.499999, 0.5, 0.500001, 1):
            for presence in (0, 0.499999, 0.5, 0.500001, 1):
                with self.subTest(visibility=visibility, presence=presence):
                    source = self.landmarks()
                    source[15].visibility, source[15].presence = visibility, presence
                    observation = observation_from_landmarks(640, 480, source, "left")
                    diagnostic = observation.landmark_diagnostics["left_wrist"]
                    accepted = visibility >= 0.5 and presence >= 0.5
                    self.assertEqual(observation.wrist is not None, accepted)
                    self.assertEqual(diagnostic.accepted, accepted)
                    self.assertEqual(diagnostic.visibility, visibility)
                    self.assertEqual(diagnostic.presence, presence)
                    self.assertEqual(diagnostic.visibility_threshold, 0.5)
                    self.assertEqual(diagnostic.presence_threshold, 0.5)
                    expected = "accepted" if accepted else (
                        "low_visibility_and_presence" if visibility < 0.5 and presence < 0.5
                        else "low_visibility" if visibility < 0.5 else "low_presence"
                    )
                    self.assertEqual(diagnostic.reason, expected)

    def test_non_finite_scores_or_coordinates_remain_rejected_and_json_safe(self):
        for field in ("visibility", "presence", "x", "y"):
            for value in (float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, value=value):
                    source = self.landmarks()
                    setattr(source[15], field, value)
                    observation = observation_from_landmarks(640, 480, source, "left")
                    diagnostic = observation.landmark_diagnostics["left_wrist"]
                    self.assertIsNone(observation.wrist)
                    self.assertFalse(diagnostic.accepted)
                    self.assertEqual(diagnostic.reason, "non_finite_input")
                    self.assertEqual(diagnostic.non_finite_fields, (field,))
                    if field in ("visibility", "presence"):
                        self.assertIsNone(getattr(diagnostic, field))
                    else:
                        self.assertEqual(diagnostic.coordinate_status, "non_finite")
                    json.dumps(asdict(observation), allow_nan=False)

    def test_out_of_image_coordinates_are_retained_then_rejected_by_existing_geometry(self):
        for x, y in ((-0.1, 0.5), (1.1, 0.5), (0.5, -0.1), (0.5, 1.1)):
            with self.subTest(x=x, y=y):
                source = self.landmarks()
                source[15].x, source[15].y = x, y
                observation = observation_from_landmarks(640, 480, source, "left")
                diagnostic = observation.landmark_diagnostics["left_wrist"]
                self.assertEqual(observation.wrist, Point2D(x, y))
                self.assertTrue(diagnostic.accepted)
                self.assertEqual(diagnostic.reason, "accepted")
                self.assertEqual(diagnostic.coordinate_status, "out_of_frame")
                frame = PoseFrame(0, 0, 640, 480, observation.shoulder, observation.elbow,
                                  observation.wrist, landmarks=observation.landmarks,
                                  landmark_diagnostics=observation.landmark_diagnostics)
                self.assertEqual(angle_and_reason(frame), (None, "out_of_frame"))

    def test_missing_landmark_or_attribute_has_explicit_abstention(self):
        for landmark in (None, SimpleNamespace(x=0.5, y=0.5, visibility=1)):
            with self.subTest(landmark=landmark):
                source = self.landmarks()
                source[15] = landmark
                observation = observation_from_landmarks(640, 480, source, "left")
                self.assertIsNone(observation.wrist)
                self.assertEqual(observation.landmark_diagnostics["left_wrist"].reason, "missing_landmark")
                self.assertIsNotNone(observation.landmarks["left_knee"])
                json.dumps(asdict(observation), allow_nan=False)

    def test_optional_diagnostics_preserve_existing_observation_and_frame_constructors(self):
        observation = PoseObservation(640, 480, None, None, None)
        frame = PoseFrame(0, 0, 640, 480, None, None, None)
        self.assertEqual(observation.landmark_diagnostics, {})
        self.assertEqual(frame.landmark_diagnostics, {})
        source = {"left_wrist": LandmarkDiagnostic(1, 1, accepted=True, reason="accepted",
                                                   coordinate_status="in_frame")}
        observation = PoseObservation(640, 480, None, None, None, landmark_diagnostics=source)
        frame = PoseFrame(0, 0, 640, 480, None, None, None, landmark_diagnostics=source)
        source.clear()
        self.assertIn("left_wrist", observation.landmark_diagnostics)
        self.assertIn("left_wrist", frame.landmark_diagnostics)
        json.dumps(asdict(frame), allow_nan=False)

    def test_diagnostic_contract_rejects_unbounded_non_finite_or_arbitrary_payloads(self):
        for kwargs in ({"visibility": float("nan")}, {"presence_threshold": float("inf")},
                       {"reason": "personal-free-text"}, {"reason": []},
                       {"coordinate_status": "guess"}, {"coordinate_status": {}},
                       {"non_finite_fields": ("image",)}, {"non_finite_fields": ("x", "x")},
                       {"accepted": True}, {"accepted": False, "reason": "accepted"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                LandmarkDiagnostic(**kwargs)
        for value in ({str(i): LandmarkDiagnostic() for i in range(34)},
                      {"invalid-name": LandmarkDiagnostic()}, {"left_wrist": {"raw": "unvalidated"}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PoseObservation(640, 480, None, None, None, landmark_diagnostics=value)
            with self.assertRaises(ValueError):
                PoseFrame(0, 0, 640, 480, None, None, None, landmark_diagnostics=value)
