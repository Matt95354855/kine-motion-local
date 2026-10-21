import unittest
from dataclasses import replace

from packages.biomechanics.elbow import assess_elbow_trial
from packages.contracts.models import ElbowTrial, MeasurementStatus
from packages.harness.demo import synthetic_trial
from packages.harness.report import render_draft


class ElbowPipelineTests(unittest.TestCase):
    def test_synthetic_trial_has_traceable_apparent_angle(self) -> None:
        measurement = assess_elbow_trial(synthetic_trial())
        self.assertEqual(measurement.status, MeasurementStatus.VALID)
        self.assertAlmostEqual(measurement.value_deg, 90.0)
        self.assertEqual(measurement.side, "left")
        self.assertEqual(measurement.evidence_refs, ("trial_demo_001:frame:2",))
        self.assertIn("90,0°", render_draft(measurement))
        self.assertIn("BROUILLON NON VALIDÉ", render_draft(measurement))

    def test_occlusion_does_not_become_a_valid_measurement(self) -> None:
        trial = synthetic_trial()
        frames = (
            trial.frames[0],
            replace(trial.frames[1], wrist=None),
            trial.frames[2],
        )
        measurement = assess_elbow_trial(replace(trial, frames=frames))
        self.assertEqual(measurement.status, MeasurementStatus.REJECTED)
        self.assertIsNone(measurement.value_deg)
        self.assertIn("occlusion", measurement.quality_reasons)
        self.assertNotIn("°", render_draft(measurement))

    def test_minor_missing_frame_is_explicitly_limited(self) -> None:
        trial = synthetic_trial()
        frames = (
            trial.frames[0],
            trial.frames[1],
            replace(trial.frames[1], sequence=3, timestamp_ms=750, wrist=None),
            replace(trial.frames[2], sequence=4, timestamp_ms=1000),
            replace(trial.frames[2], sequence=5, timestamp_ms=1250),
        )
        measurement = assess_elbow_trial(replace(trial, frames=frames))
        self.assertEqual(measurement.status, MeasurementStatus.LIMITED)
        self.assertIn("occlusion", measurement.quality_reasons)
        self.assertIn("Estimation limitée", render_draft(measurement))

    def test_out_of_plane_or_stopped_trial_publishes_no_value(self) -> None:
        trial = synthetic_trial()
        invalid_view = replace(trial.frames[1], view_is_valid=False)
        for candidate in (
            replace(trial, frames=(trial.frames[0], invalid_view, trial.frames[2])),
            replace(trial, stopped=True),
        ):
            with self.subTest(candidate=candidate.stopped):
                measurement = assess_elbow_trial(candidate)
                self.assertEqual(measurement.status, MeasurementStatus.REJECTED)
                self.assertIsNone(measurement.value_deg)

    def test_unverified_capture_does_not_default_to_valid(self) -> None:
        trial = synthetic_trial()
        unknown_view = replace(trial.frames[1], view_is_valid=None)
        measurement = assess_elbow_trial(
            replace(trial, frames=(trial.frames[0], unknown_view, trial.frames[2]))
        )
        self.assertEqual(measurement.status, MeasurementStatus.REJECTED)
        self.assertEqual(measurement.quality_reasons, ("view_unverified",))
        self.assertIsNone(measurement.value_deg)

    def test_non_monotonic_capture_and_absent_trial_are_distinct(self) -> None:
        trial = synthetic_trial()
        out_of_order = replace(trial.frames[2], timestamp_ms=100)
        rejected = assess_elbow_trial(
            replace(trial, frames=(trial.frames[0], trial.frames[1], out_of_order))
        )
        self.assertEqual(rejected.status, MeasurementStatus.REJECTED)
        self.assertIn("invalid_timestamps", rejected.quality_reasons)

        absent = assess_elbow_trial(ElbowTrial("absent", "session_demo_001", "right", ()))
        self.assertEqual(absent.status, MeasurementStatus.NOT_PERFORMED)
        self.assertIsNone(absent.value_deg)
        self.assertIn("non réalisé", render_draft(absent))


if __name__ == "__main__":
    unittest.main()
