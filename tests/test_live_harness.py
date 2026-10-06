import json
import unittest

from packages.harness.live import LiveSnapshot, run_live_harness


def snapshot(samples=None, protocol_id="elbow_flexion_active", images=(), image_metadata=()):
    if samples is None:
        samples = ({"sequence": 0, "timestamp_ms": 0, "angle_deg": 45.0, "quality_reason": None},)
    return LiveSnapshot("session-a", "window-a", protocol_id, "left", 0, 1000, tuple(samples), images, image_metadata)


def answer(code="pose_visible", reference="window-a", **extra):
    return {"content": json.dumps({
        "window_ref": reference,
        "observation_code": code,
        "requires_professional_review": True,
        **extra,
    })}


def tool_call(name, arguments="{}", call_id="call-a"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []
        self.tools = []

    def complete(self, messages, tools):
        self.messages.append(json.loads(json.dumps(messages)))
        self.tools.append(json.loads(json.dumps(tools)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class LiveHarnessTests(unittest.TestCase):
    def test_snapshot_copies_input_samples_and_validates_bounds(self):
        sample = {"sequence": 0, "timestamp_ms": 0, "angle_deg": 45.0, "quality_reason": None}
        current = snapshot([sample])
        sample["angle_deg"] = 170.0
        self.assertEqual(current.samples[0]["angle_deg"], 45.0)
        with self.assertRaises(ValueError):
            snapshot([{"sequence": 0, "timestamp_ms": 0, "angle_deg": float("nan"), "quality_reason": None}])
        with self.assertRaises(ValueError):
            snapshot([{"sequence": i, "timestamp_ms": i, "angle_deg": 45, "quality_reason": None} for i in range(26)])
        with self.assertRaises(ValueError):
            snapshot(images=(b"\xff\xd8a", b"\xff\xd8b", b"\xff\xd8c"))
        with self.assertRaises(ValueError):
            snapshot(images=(b"not a jpeg",))

    def test_deterministic_observation_without_client_has_no_validated_measurement(self):
        result = run_live_harness(snapshot(), None)
        self.assertEqual(result["observation_code"], "pose_visible")
        self.assertEqual(result["observation_source"], "deterministic")
        self.assertEqual(result["fallback_reason"], "llm_unavailable")
        self.assertEqual(result["tool_names"], [])
        self.assertEqual(result["image_count"], 0)
        self.assertTrue(result["provisional"])
        self.assertTrue(result["requires_professional_review"])
        self.assertNotIn("value_deg", result)
        self.assertNotIn("measurement", result)
        self.assertIn("à vérifier", result["text"])
        json.dumps(result)

    def test_image_metadata_copies_and_requires_current_sample_positions(self):
        positions = ({"sequence": 0, "timestamp_ms": 0}, {"sequence": 1, "timestamp_ms": 200})
        samples = [
            {"sequence": 0, "timestamp_ms": 0, "angle_deg": 20, "quality_reason": None},
            {"sequence": 1, "timestamp_ms": 200, "angle_deg": 30, "quality_reason": None},
        ]
        current = snapshot(samples, images=(b"\xff\xd8a", b"\xff\xd8b"), image_metadata=positions)
        positions[0]["timestamp_ms"] = 999
        self.assertEqual(current.image_metadata[0]["timestamp_ms"], 0)
        invalid_metadata = (
            ({"sequence": 0, "timestamp_ms": 0},),
            ({"sequence": 0, "timestamp_ms": 0}, {"sequence": 0, "timestamp_ms": 0}),
            ({"sequence": 1, "timestamp_ms": 200}, {"sequence": 0, "timestamp_ms": 0}),
            ({"sequence": 0, "timestamp_ms": 1}, {"sequence": 1, "timestamp_ms": 200}),
            ({"sequence": 0, "timestamp_ms": 0, "extra": "untrusted"}, {"sequence": 1, "timestamp_ms": 200}),
        )
        for metadata in invalid_metadata:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                snapshot(samples, images=(b"\xff\xd8a", b"\xff\xd8b"), image_metadata=metadata)

    def test_deterministic_codes_follow_only_current_samples(self):
        cases = [
            ([], "awaiting_frames"),
            ([{"sequence": 0, "timestamp_ms": 0, "angle_deg": None, "quality_reason": "no_pose"}], "tracking_lost"),
            ([{"sequence": 0, "timestamp_ms": 0, "angle_deg": 20, "quality_reason": None},
              {"sequence": 1, "timestamp_ms": 200, "angle_deg": None, "quality_reason": "occlusion"}], "tracking_partial"),
        ]
        for samples, code in cases:
            with self.subTest(code=code):
                self.assertEqual(run_live_harness(snapshot(samples), None)["observation_code"], code)

    def test_guide_only_does_not_claim_visibility_on_missing_or_multiple_people(self):
        for reason in ("no_pose", "multiple_people", "occlusion"):
            with self.subTest(reason=reason):
                current = snapshot([
                    {"sequence": 0, "timestamp_ms": 0, "angle_deg": None, "quality_reason": reason}
                ], protocol_id="neck_rotation_guided")
                self.assertEqual(run_live_harness(current, None)["observation_code"], "tracking_lost")
        current = snapshot([
            {"sequence": 0, "timestamp_ms": 0, "angle_deg": None, "quality_reason": "rotation_not_measurable_2d"}
        ], protocol_id="neck_rotation_guided")
        self.assertEqual(run_live_harness(current, None)["observation_code"], "guide_only")

    def test_read_only_tools_success_and_rendered_text(self):
        model = FakeClient([
            {"tool_calls": [tool_call("get_live_observation"), tool_call("get_protocol_definition", call_id="call-b")]},
            answer(),
        ])
        result = run_live_harness(snapshot(), model)
        self.assertEqual(result["tool_names"], ["get_live_observation", "get_protocol_definition"])
        self.assertEqual(result["observation_source"], "llm")
        self.assertIsNone(result["fallback_reason"])
        observation = json.loads(model.messages[1][-2]["content"])
        protocol = json.loads(model.messages[1][-1]["content"])
        self.assertEqual(observation["window_ref"], "window-a")
        self.assertIsNone(observation["view_is_valid"])
        self.assertIsNone(observation["camera_stable"])
        self.assertFalse(observation["side_verified"])
        self.assertEqual(protocol["clinical_validation"], "not_established")
        self.assertEqual(protocol["mode"], "flexion")
        self.assertEqual(result["text"], run_live_harness(snapshot(), None)["text"])

    def test_malformed_envelopes_always_return_safe_fallback(self):
        responses = [[], None, "oops", {"tool_calls": {}}, {"tool_calls": [None]},
                     {"content": []}, {"content": None}, {"content": "not JSON"},
                     {"content": "[]"}, {"content": "x" * 1025}]
        for response in responses:
            with self.subTest(response=response):
                result = run_live_harness(snapshot(), FakeClient([response]))
                self.assertIsNotNone(result["fallback_reason"])
                self.assertEqual(result["observation_source"], "deterministic")
                self.assertEqual(result["observation_code"], "pose_visible")

    def test_wrong_reference_incompatible_code_and_unknown_code_are_rejected(self):
        cases = [
            (answer(reference="old-window"), "wrong_window_ref"),
            (answer(code="tracking_lost"), "incompatible_observation"),
            (answer(code="normal_range"), "unknown_observation_code"),
            (answer(requires_professional_review=False), "review_required"),
        ]
        for response, reason in cases:
            with self.subTest(reason=reason):
                result = run_live_harness(snapshot(), FakeClient([response]))
                self.assertEqual(result["fallback_reason"], reason)
                self.assertEqual(result["observation_source"], "deterministic")

    def test_free_text_and_clinical_fields_never_reach_result(self):
        for field, value in (
            ("text", "Diagnostic confirmé. Faites cent répétitions."),
            ("diagnosis", "tendinite"), ("exercise", "flexion"), ("value_deg", 150),
        ):
            with self.subTest(field=field):
                model = FakeClient([answer(**{field: value})])
                result = run_live_harness(snapshot(), model)
                self.assertEqual(result["fallback_reason"], "invalid_schema")
                self.assertNotIn(str(value), json.dumps(result, ensure_ascii=False))
                self.assertNotIn(field, result if field != "text" else {})

    def test_forbidden_tools_and_nonempty_arguments_are_rejected(self):
        cases = [
            (tool_call("read_file"), "forbidden_tool"),
            (tool_call("get_live_observation", '{"session_id":"other"}'), "forbidden_tool_arguments"),
            (tool_call("get_live_observation", "[]"), "forbidden_tool_arguments"),
            (tool_call("get_live_observation", None), "invalid_tool_arguments"),
        ]
        for call, reason in cases:
            with self.subTest(reason=reason):
                result = run_live_harness(snapshot(), FakeClient([{"tool_calls": [call]}]))
                self.assertEqual(result["fallback_reason"], reason)
                self.assertEqual(result["tool_names"], [])

    def test_tool_and_round_limits(self):
        calls = [tool_call("get_live_observation", call_id=f"call-{i}") for i in range(5)]
        self.assertEqual(run_live_harness(snapshot(), FakeClient([{"tool_calls": calls}]))["fallback_reason"], "tool_limit")
        model = FakeClient([{"tool_calls": [tool_call("get_live_observation", call_id=f"call-{i}")]} for i in range(4)])
        result = run_live_harness(snapshot(), model)
        self.assertEqual(result["fallback_reason"], "round_limit")
        self.assertEqual(len(model.messages), 4)

    def test_duplicate_tool_ids_are_rejected(self):
        model = FakeClient([
            {"tool_calls": [tool_call("get_live_observation")]},
            {"tool_calls": [tool_call("get_protocol_definition")]},
        ])
        result = run_live_harness(snapshot(), model)
        self.assertEqual(result["fallback_reason"], "invalid_tool_call")

    def test_tool_envelopes_cannot_echo_unbounded_extra_payload(self):
        for call in (
            {**tool_call("get_live_observation"), "extra": "large unsupported payload"},
            {"id": "call-a", "function": {"name": "get_live_observation", "arguments": "{}", "extra": []}},
        ):
            with self.subTest(call=call):
                model = FakeClient([{"tool_calls": [call]}])
                result = run_live_harness(snapshot(), model)
                self.assertEqual(result["fallback_reason"], "invalid_tool_call")
                self.assertEqual(len(model.messages), 1)

    def test_visual_opt_in_sends_at_most_two_current_images_never_in_result(self):
        current = snapshot(images=(b"\xff\xd8current-a", b"\xff\xd8current-b"))
        model = FakeClient([
            {"tool_calls": [tool_call("get_recent_capture_images"), tool_call("get_live_observation", call_id="call-b")]},
            answer(),
        ])
        result = run_live_harness(current, model, allow_visual_evidence=True)
        self.assertEqual(result["image_count"], 2)
        self.assertIsNone(result["fallback_reason"])
        sequence = model.messages[1]
        self.assertEqual([item["role"] for item in sequence[-4:]], ["assistant", "tool", "tool", "user"])
        parts = sequence[-1]["content"]
        self.assertEqual(len([part for part in parts if part["type"] == "image_url"]), 2)
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertNotIn("data:image", json.dumps(result))
        self.assertNotIn("image_url", result)

    def test_visual_tool_is_absent_without_opt_in_or_without_images(self):
        for current, enabled in ((snapshot(images=(b"\xff\xd8current",)), False), (snapshot(), True)):
            with self.subTest(enabled=enabled, has_images=bool(current.images)):
                model = FakeClient([{"tool_calls": [tool_call("get_recent_capture_images")]}])
                result = run_live_harness(current, model, allow_visual_evidence=enabled)
                self.assertEqual(result["fallback_reason"], "forbidden_tool")
                self.assertEqual(result["image_count"], 0)
                self.assertNotIn("data:image", json.dumps(model.messages))
                self.assertNotIn("get_recent_capture_images", json.dumps(model.tools))

    def test_visual_tools_and_parts_preserve_image_chronology(self):
        current = snapshot([
            {"sequence": 2, "timestamp_ms": 200, "angle_deg": 20, "quality_reason": None},
            {"sequence": 3, "timestamp_ms": 400, "angle_deg": 30, "quality_reason": None},
        ], images=(b"\xff\xd8a", b"\xff\xd8b"), image_metadata=(
            {"sequence": 2, "timestamp_ms": 200}, {"sequence": 3, "timestamp_ms": 400},
        ))
        model = FakeClient([{"tool_calls": [tool_call("get_recent_capture_images")]}, answer()])
        result = run_live_harness(current, model, allow_visual_evidence=True)
        tool_output = json.loads(model.messages[1][-2]["content"])
        self.assertTrue(tool_output["chronology_available"])
        self.assertEqual(tool_output["images"], [
            {"image_ref": "window-a:image:0", "sequence": 2, "timestamp_ms": 200},
            {"image_ref": "window-a:image:1", "sequence": 3, "timestamp_ms": 400},
        ])
        parts = model.messages[1][-1]["content"]
        self.assertEqual([part["type"] for part in parts], ["text", "text", "image_url", "text", "image_url"])
        self.assertEqual(json.loads(parts[1]["text"])["timestamp_ms"], 200)
        self.assertEqual(json.loads(parts[3]["text"])["timestamp_ms"], 400)
        self.assertEqual(result["image_count"], 2)
        self.assertNotIn("data:image", json.dumps(result))

    def test_repeated_visual_tool_reuses_references_without_duplicating_images(self):
        current = snapshot(images=(b"\xff\xd8a", b"\xff\xd8b"))
        model = FakeClient([
            {"tool_calls": [tool_call("get_recent_capture_images", call_id=f"call-{index}")]}
            for index in range(3)
        ] + [answer()])
        result = run_live_harness(current, model, allow_visual_evidence=True)
        self.assertIsNone(result["fallback_reason"])
        self.assertEqual(result["image_count"], 2)
        for payload in model.messages:
            image_parts = [
                part
                for message in payload if isinstance(message.get("content"), list)
                for part in message["content"] if part.get("type") == "image_url"
            ]
            self.assertLessEqual(len(image_parts), 2)
        last_payload = model.messages[-1]
        self.assertEqual(sum(
            part.get("type") == "image_url"
            for message in last_payload if isinstance(message.get("content"), list)
            for part in message["content"]
        ), 2)
        repeated_tool_outputs = [
            json.loads(message["content"])
            for message in last_payload if message["role"] == "tool"
        ]
        self.assertEqual(len(repeated_tool_outputs), 3)
        self.assertTrue(all(output["image_refs"] == ["window-a:image:0", "window-a:image:1"]
                            for output in repeated_tool_outputs))

    def test_last_round_image_request_without_followup_is_not_counted_as_sent(self):
        model = FakeClient([
            {"tool_calls": [tool_call("get_live_observation", call_id=f"call-{index}")]}
            for index in range(3)
        ] + [{"tool_calls": [tool_call("get_recent_capture_images", call_id="call-last")]}])
        result = run_live_harness(snapshot(images=(b"\xff\xd8a",)), model, allow_visual_evidence=True)
        self.assertEqual(result["fallback_reason"], "round_limit")
        self.assertEqual(result["image_count"], 0)
        self.assertNotIn("data:image", json.dumps(model.messages))

    def test_images_remain_private_until_read_tool_is_requested(self):
        model = FakeClient([answer()])
        result = run_live_harness(snapshot(images=(b"\xff\xd8current",)), model, allow_visual_evidence=True)
        self.assertEqual(result["image_count"], 0)
        self.assertNotIn("data:image", json.dumps(model.messages))

    def test_cancellation_before_call_and_after_response_blocks_publication(self):
        model = FakeClient([answer()])
        result = run_live_harness(snapshot(), model, should_continue=lambda: False)
        self.assertEqual(result["fallback_reason"], "cancelled")
        self.assertEqual(model.messages, [])
        checks = iter([True, True, False])
        model = FakeClient([answer()])
        result = run_live_harness(snapshot(), model, should_continue=lambda: next(checks))
        self.assertEqual(result["fallback_reason"], "cancelled")
        self.assertEqual(result["observation_source"], "deterministic")
        self.assertEqual(len(model.messages), 1)

    def test_cancellation_between_tool_rounds_prevents_next_inference(self):
        checks = iter([True, True, True, False])
        model = FakeClient([{"tool_calls": [tool_call("get_live_observation")]}, answer()])
        result = run_live_harness(snapshot(), model, should_continue=lambda: next(checks))
        self.assertEqual(result["fallback_reason"], "cancelled")
        self.assertEqual(len(model.messages), 1)

    def test_client_failure_does_not_leak_external_error_or_generated_data(self):
        for error in (AttributeError("private data"), TimeoutError("private URL"), ValueError("private capture")):
            with self.subTest(error=type(error).__name__):
                result = run_live_harness(snapshot(), FakeClient([error]))
                self.assertEqual(result["fallback_reason"], "llm_error")
                self.assertNotIn("private", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
