import unittest

from packages.biomechanics.geometry import apparent_elbow_flexion_deg, internal_angle_deg
from packages.contracts.models import Point2D


class GeometryTests(unittest.TestCase):
    def test_right_angle_survives_translation_rotation_and_mirror(self) -> None:
        variants = (
            ((0, -1), (0, 0), (1, 0)),
            ((10, 9), (10, 10), (11, 10)),
            ((1, 0), (0, 0), (0, 1)),
            ((0, -1), (0, 0), (-1, 0)),
        )
        for a, b, c in variants:
            with self.subTest(points=(a, b, c)):
                self.assertAlmostEqual(internal_angle_deg(a, b, c), 90.0)

    def test_non_square_image_uses_pixel_coordinates(self) -> None:
        width, height = 640, 480
        shoulder = Point2D(320 / width, 240 / height)
        elbow = Point2D(320 / width, 360 / height)
        wrist = Point2D(440 / width, 480 / height)
        self.assertAlmostEqual(
            apparent_elbow_flexion_deg(shoulder, elbow, wrist, width, height), 45.0
        )

    def test_degenerate_and_non_finite_geometry_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            internal_angle_deg((0, 0), (0, 0), (1, 0))
        with self.assertRaises(ValueError):
            internal_angle_deg((float("nan"), 0), (0, 0), (1, 0))
        with self.assertRaises(ValueError):
            apparent_elbow_flexion_deg(
                Point2D(-0.1, 0.5), Point2D(0.5, 0.5), Point2D(0.7, 0.5), 640, 480
            )


if __name__ == "__main__":
    unittest.main()
