from types import SimpleNamespace
import unittest

from packages.pose.mediapipe_engine import observation_from_landmarks


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
        self.assertEqual(observation_from_landmarks(640, 480, [], "left").quality_reason, "degenerate_landmarks")
