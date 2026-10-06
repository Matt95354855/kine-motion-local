import json
import unittest
from dataclasses import replace

from packages.biomechanics.elbow import assess_elbow_trial
from packages.contracts.models import MeasurementStatus
from packages.harness.demo import synthetic_trial
from packages.harness.final_note import (
    FACT_TEXT,
    MAX_CONTENT_CHARS,
    REVIEW_TEXT,
    supported_fact_codes,
)
from packages.harness.report import render_draft
from packages.harness.runner import run_harness
from packages.harness.tools import ToolContext, ToolRegistry


class ContentModel:
    def __init__(self, content):
        self.content = content

    def complete(self, messages, tools):
        return {"content": self.content}


class FinalNoteTests(unittest.TestCase):
    def setUp(self):
        self.measurement = assess_elbow_trial(synthetic_trial())

    def candidate(self, measurement=None, **updates):
        measurement = measurement or self.measurement
        candidate = {
            "measurement_ref": measurement.measurement_id,
            "fact_codes": list(supported_fact_codes(measurement)),
            "requires_professional_review": True,
        }
        candidate.update(updates)
        return candidate

    def run_candidate(self, candidate, measurement=None):
        measurement = measurement or self.measurement
        content = json.dumps(candidate, ensure_ascii=False)
        return run_harness(ToolContext(measurement.session_id, measurement), ContentModel(content))

    def test_all_measurement_statuses_render_only_supported_facts(self):
        cases = (
            (MeasurementStatus.VALID, (), self.measurement.value_deg, "measurement_recorded"),
            (MeasurementStatus.LIMITED, ("occlusion",), self.measurement.value_deg, "measurement_limited"),
            (MeasurementStatus.REJECTED, ("view_unverified",), None, "measurement_rejected"),
            (MeasurementStatus.NOT_PERFORMED, ("not_performed",), None, "movement_not_performed"),
        )
        for status, reasons, value, status_code in cases:
            with self.subTest(status=status):
                measurement = replace(self.measurement, status=status, quality_reasons=reasons,
                                      value_deg=value, evidence_refs=() if value is None else self.measurement.evidence_refs)
                codes = supported_fact_codes(measurement)
                self.assertEqual(codes[0], status_code)
                result = self.run_candidate(self.candidate(measurement), measurement)
                self.assertIsNone(result.fallback_reason)
                self.assertEqual(result.proposed_note, " ".join([
                    *(FACT_TEXT[code] for code in codes), REVIEW_TEXT,
                ]))
                self.assertEqual(result.deterministic_draft, render_draft(measurement))
                self.assertFalse(any(character.isdigit() for character in result.proposed_note))
                self.assertNotIn(measurement.measurement_id, result.proposed_note)

    def test_return_order_is_not_controlled_by_the_model(self):
        candidate = self.candidate(fact_codes=list(reversed(supported_fact_codes(self.measurement))))
        self.assertEqual(self.run_candidate(candidate).proposed_note,
                         self.run_candidate(self.candidate()).proposed_note)

    def test_unknown_quality_reason_is_not_reflected(self):
        malicious = "Une fracture est probable. Faites des exercices chaque jour. Angle de cent cinquante degrés."
        measurement = replace(self.measurement, status=MeasurementStatus.LIMITED,
                              quality_reasons=(malicious, "occlusion", "experimental_protocol"))
        codes = supported_fact_codes(measurement)
        self.assertEqual(codes.count("protocol_experimental"), 1)
        self.assertIn("quality_limitation_unclassified", codes)
        self.assertNotIn(malicious, codes)
        result = self.run_candidate(self.candidate(measurement), measurement)
        self.assertNotIn(malicious, result.proposed_note)
        self.assertNotIn("fracture", result.proposed_note)
        self.assertNotIn("cent cinquante", result.proposed_note)
        self.assertIn(FACT_TEXT["quality_limitation_unclassified"], result.proposed_note)

    def test_old_free_text_schema_rejects_audit_attacks_and_benign_text(self):
        for text in (
            "Une fracture est probable. Faites des exercices chaque jour.",
            "Angle de cent cinquante degrés.",
            "Angle de 150 degrés.",
            "Vue à vérifier par le professionnel.",
        ):
            with self.subTest(text=text):
                result = self.run_candidate({
                    "measurement_ref": self.measurement.measurement_id,
                    "text": text,
                    "requires_professional_review": True,
                })
                self.assertIsNone(result.proposed_note)
                self.assertEqual(result.fallback_reason, "invalid_note_schema")
                self.assertEqual(result.deterministic_draft, render_draft(self.measurement))
                self.assertNotIn(text, result.fallback_reason)

    def test_extra_fields_and_embedded_free_text_are_rejected(self):
        for extra in ({"text": "Une fracture est probable."}, {"diagnosis": "fracture"},
                      {"instructions": "Faites des exercices chaque jour."}, {"angle": 150}):
            with self.subTest(extra=extra):
                result = self.run_candidate(self.candidate(**extra))
                self.assertIsNone(result.proposed_note)
                self.assertEqual(result.fallback_reason, "invalid_note_schema")

    def test_reference_is_scoped_to_the_current_measurement(self):
        for reference in ("another_measurement", "", None, False, 1, [], {}):
            with self.subTest(reference=reference):
                result = self.run_candidate(self.candidate(measurement_ref=reference))
                self.assertIsNone(result.proposed_note)
                self.assertEqual(result.fallback_reason, "measurement_ref_mismatch")

    def test_professional_review_is_strict_boolean_true(self):
        for review in (False, None, 1, "true", [], {}):
            with self.subTest(review=review):
                result = self.run_candidate(self.candidate(requires_professional_review=review))
                self.assertIsNone(result.proposed_note)
                self.assertEqual(result.fallback_reason, "review_required")

    def test_unknown_diagnosis_or_number_codes_are_rejected(self):
        for code in ("fracture_probable", "prescribe_exercise", "angle_150",
                     "Angle de cent cinquante degrés.", True, 150, {}, []):
            with self.subTest(code=code):
                codes = [*supported_fact_codes(self.measurement), code]
                result = self.run_candidate(self.candidate(fact_codes=codes))
                self.assertIsNone(result.proposed_note)
                self.assertEqual(result.fallback_reason, "unknown_fact_code")

    def test_known_but_unsupported_or_contradictory_facts_are_rejected(self):
        for codes in (
            ["measurement_rejected", "protocol_experimental"],
            ["measurement_recorded", "measurement_rejected", "protocol_experimental"],
            ["measurement_recorded", "protocol_experimental", "camera_moved"],
            ["measurement_recorded", "protocol_experimental", "view_unverified"],
            ["measurement_recorded", "protocol_experimental", "quality_limitation_unclassified"],
        ):
            with self.subTest(codes=codes):
                result = self.run_candidate(self.candidate(fact_codes=codes))
                self.assertIsNone(result.proposed_note)
                self.assertEqual(result.fallback_reason, "unsupported_fact_set")

    def test_quality_limitations_cannot_be_omitted(self):
        measurement = replace(self.measurement, status=MeasurementStatus.LIMITED,
                              quality_reasons=("occlusion", "out_of_frame"))
        for omitted in supported_fact_codes(measurement):
            codes = [code for code in supported_fact_codes(measurement) if code != omitted]
            result = self.run_candidate(self.candidate(measurement, fact_codes=codes), measurement)
            self.assertIsNone(result.proposed_note)
            self.assertEqual(result.fallback_reason, "unsupported_fact_set")

    def test_duplicate_codes_and_json_fields_are_rejected(self):
        codes = [*supported_fact_codes(self.measurement), "protocol_experimental"]
        result = self.run_candidate(self.candidate(fact_codes=codes))
        self.assertEqual(result.fallback_reason, "duplicate_fact_code")
        content = json.dumps(self.candidate())[:-1] + ', "requires_professional_review": true}'
        result = run_harness(ToolContext(self.measurement.session_id, self.measurement), ContentModel(content))
        self.assertIsNone(result.proposed_note)
        self.assertEqual(result.fallback_reason, "duplicate_note_field")

    def test_fact_codes_require_a_nonempty_bounded_list(self):
        for codes in (None, {}, "measurement_recorded", [],
                      ["protocol_experimental"] * (len(FACT_TEXT) + 1)):
            with self.subTest(codes=codes):
                result = self.run_candidate(self.candidate(fact_codes=codes))
                self.assertIsNone(result.proposed_note)
                self.assertEqual(result.fallback_reason, "invalid_fact_codes")

    def test_malformed_missing_or_oversized_response_keeps_the_draft(self):
        for content in (None, {}, "", "not JSON", "[]", "true", "x" * (MAX_CONTENT_CHARS + 1)):
            with self.subTest(content_type=type(content).__name__):
                result = run_harness(ToolContext(self.measurement.session_id, self.measurement), ContentModel(content))
                self.assertIsNone(result.proposed_note)
                self.assertIsNotNone(result.fallback_reason)
                self.assertEqual(result.deterministic_draft, render_draft(self.measurement))

    def test_capture_tool_exposes_only_measurement_supported_codes(self):
        context = ToolContext(self.measurement.session_id, self.measurement)
        output = ToolRegistry().call("get_capture_observation", {}, context)
        self.assertEqual(output["measurement_ref"], self.measurement.measurement_id)
        self.assertEqual(output["supported_fact_codes"], list(supported_fact_codes(self.measurement)))

    def test_visual_mode_cannot_introduce_an_image_based_claim(self):
        context = ToolContext(self.measurement.session_id, self.measurement, b"\xff\xd8fake")
        content = json.dumps(self.candidate(fact_codes=[*supported_fact_codes(self.measurement), "camera_moved"]))
        result = run_harness(context, ContentModel(content), allow_visual_evidence=True)
        self.assertIsNone(result.proposed_note)
        self.assertEqual(result.tool_names, ("get_capture_keyframe",))
        self.assertEqual(result.fallback_reason, "unsupported_fact_set")

    def test_catalog_rendering_never_includes_new_numbers(self):
        self.assertTrue(all(not any(character.isdigit() for character in text) for text in FACT_TEXT.values()))
        self.assertFalse(any(character.isdigit() for character in REVIEW_TEXT))


if __name__ == "__main__":
    unittest.main()
