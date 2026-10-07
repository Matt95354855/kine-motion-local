import hashlib
import json
from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from packages.biomechanics.elbow import assess_elbow_trial
from packages.biomechanics.motion import summarize_motion
from packages.biomechanics.protocols import assess_trial
from packages.contracts.models import LandmarkDiagnostic, MeasurementStatus
from packages.harness.demo import synthetic_trial
from packages.harness.final_note import render_verified_note, supported_fact_codes
from packages.harness.report import render_capture_diagnostics, render_draft
from packages.pose.adapter import PoseObservation
from services.api.provenance import IMPLEMENTATION_FILES, analysis_provenance
from services.api.state import SessionManager


class AnalysisDiagnosticsTests(unittest.TestCase):
    def test_tracking_limits_do_not_claim_bad_execution_or_proven_occlusion(self):
        trial = synthetic_trial()
        frames = tuple(replace(trial.frames[min(i, 2)], sequence=i, timestamp_ms=i * 200)
                       for i in range(6))
        frames = (*frames[:3], replace(frames[3], wrist=None), *frames[4:])
        measurement = assess_elbow_trial(replace(trial, frames=frames))
        self.assertEqual(measurement.status, MeasurementStatus.LIMITED)
        draft = render_draft(measurement) + render_capture_diagnostics(measurement, summarize_motion(frames))
        self.assertIn("pic brut 2D", draft)
        self.assertIn("5/6 images reçues", draft)
        self.assertIn("1 image(s) : repère requis indisponible", draft)
        self.assertIn("0.60–0.60 s", draft)
        self.assertIn("ne juge pas la bonne exécution", draft)
        self.assertNotIn("repère masqué", draft)
        self.assertIn("ne valident ni le pic", draft)
        note = render_verified_note(json.dumps({
            "measurement_ref": measurement.measurement_id,
            "fact_codes": list(supported_fact_codes(measurement)),
            "requires_professional_review": True,
        }), measurement)
        self.assertIn("sous le seuil", note)
        self.assertNotIn("masqué", note)

    def test_rejected_measurement_never_recovers_an_angle_from_peak_diagnostics(self):
        trial = synthetic_trial()
        frames = tuple(replace(frame, view_is_valid=None) for frame in trial.frames)
        measurement = assess_elbow_trial(replace(trial, frames=frames))
        motion = summarize_motion(frames)
        self.assertIsNotNone(motion["robustness"]["raw_peak"])
        self.assertIsNone(measurement.value_deg)
        diagnostics = render_capture_diagnostics(measurement, motion)
        self.assertNotIn("°", diagnostics)
        self.assertNotIn("Contexte du pic", diagnostics)
        self.assertIn("3/3 images reçues", diagnostics)

    def test_diagnostics_missing_is_explicit_not_a_success(self):
        measurement = assess_elbow_trial(synthetic_trial())
        self.assertIn("indisponible", render_capture_diagnostics(measurement, {}))

    def test_guide_only_does_not_hide_real_tracking_loss(self):
        trial = synthetic_trial()
        frames = tuple(replace(frame, protocol_id="neck_rotation_guided", quality_reason="no_pose")
                       for frame in trial.frames)
        measurement = assess_trial(replace(trial, frames=frames), "neck_rotation_guided")
        diagnostics = render_capture_diagnostics(measurement, summarize_motion(frames))
        self.assertIn("absence d'angle attendue", diagnostics)
        self.assertIn("3 image(s) : pose non retournée", diagnostics)
        self.assertIn("Suivi non exploitable", diagnostics)
        self.assertNotIn("Angle calculable", diagnostics)
        self.assertNotIn("°", diagnostics)

    def test_only_required_landmark_diagnostics_survive_completion_and_are_revoked(self):
        frame = synthetic_trial().frames[0]
        accepted = LandmarkDiagnostic(visibility=0.9, presence=0.8, accepted=True,
                                      reason="accepted", coordinate_status="in_frame")

        class Engine:
            def detect(self, _jpeg, _time, _side):
                return PoseObservation(640, 480, frame.shoulder, frame.elbow, frame.wrist,
                                       landmark_diagnostics={"left_wrist": accepted, "right_ear": accepted})

            def close(self):
                pass

        manager = SessionManager(Engine)
        try:
            session = manager.start("left")
            for i in range(3):
                pose = manager.add_frame(session.session_id, session.token, b"\xff\xd8synthetic", i, i * 200)
                self.assertEqual(pose.landmark_diagnostics["left_wrist"].visibility, 0.9)
            measurement = manager.finish(session.session_id, session.token, True, True)
            details = manager.completed_details(session.session_id, session.token)
            diagnostics = details["motion"]["pose_diagnostics"]
            self.assertEqual(diagnostics["available_frame_count"], 3)
            self.assertEqual(set(diagnostics["samples"][0]["landmarks"]), {"left_wrist"})
            self.assertEqual(details["motion"]["robustness"]["raw_peak"]["sequence"], details["evidence_sequence"])
            self.assertIsNotNone(measurement.value_deg)
            serialized = json.dumps(details, allow_nan=False)
            self.assertNotIn(session.token, serialized)
            self.assertNotIn("jpeg", serialized)
            self.assertNotIn("right_ear", serialized)
            manager.cancel(session.session_id, session.token)
            self.assertIsNone(session.motion_summary)
            self.assertEqual(session.frames, [])
        finally:
            manager.close()


class AnalysisProvenanceTests(unittest.TestCase):
    def test_hash_matches_selected_pose_asset_without_exposing_its_path(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "infra").mkdir()
            model = root / "private-test.task"
            model.write_bytes(b"synthetic model asset")
            digest = hashlib.sha256(model.read_bytes()).hexdigest()
            (root / "infra" / "pose-model.json").write_text(json.dumps({"sha256": digest}))
            with patch("services.api.provenance._git", side_effect=["a" * 40, " M private-name.py"]), \
                 patch("services.api.provenance.version", return_value="0.10.21"):
                provenance = analysis_provenance(root, "mediapipe_experimental", str(model))
            self.assertTrue(provenance["pose_model"]["hash_verified"])
            self.assertEqual(provenance["pose_model"]["sha256"], digest)
            self.assertTrue(provenance["working_tree_dirty"])
            self.assertEqual(provenance["pose_settings"]["running_mode"], "VIDEO")
            self.assertEqual(provenance["pose_settings"]["landmark_visibility_threshold"], 0.5)
            self.assertNotIn(str(root), json.dumps(provenance))
            self.assertNotIn("private-name", json.dumps(provenance))
            model.write_bytes(b"changed synthetic model asset")
            with patch("services.api.provenance._git", return_value=None):
                changed = analysis_provenance(root, "mediapipe_experimental", str(model))
            self.assertFalse(changed["pose_model"]["hash_verified"])

    def test_missing_tools_and_assets_remain_unknown(self):
        with TemporaryDirectory() as temporary, patch("services.api.provenance._git", return_value=None):
            provenance = analysis_provenance(Path(temporary), "mediapipe_experimental", "absent.task")
        for key in ("git_commit", "working_tree_dirty", "implementation_sha256"):
            self.assertIsNone(provenance[key])
        self.assertIsNone(provenance["pose_model"]["sha256"])
        self.assertIsNone(provenance["pose_model"]["hash_verified"])

    def test_synthetic_mode_does_not_inspect_or_claim_real_model_configuration(self):
        with TemporaryDirectory() as temporary, patch("services.api.provenance._git", return_value=""), \
             patch("services.api.provenance.version") as query:
            provenance = analysis_provenance(Path(temporary), "synthetic_demo", "private-asset.task")
        self.assertIsNone(provenance["pose_settings"])
        self.assertIsNone(provenance["pose_model"]["hash_verified"])
        query.assert_not_called()

    def test_implementation_hash_changes_with_uncommitted_pipeline_content(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in IMPLEMENTATION_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic source")
            with patch("services.api.provenance._git", return_value=None):
                original = analysis_provenance(root, "synthetic_demo")["implementation_sha256"]
                (root / "packages/biomechanics/elbow.py").write_bytes(b"changed synthetic source")
                changed = analysis_provenance(root, "synthetic_demo")["implementation_sha256"]
            self.assertEqual(len(original), 64)
            self.assertNotEqual(original, changed)


if __name__ == "__main__":
    unittest.main()
