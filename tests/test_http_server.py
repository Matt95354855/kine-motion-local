import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.server import configured_models, make_handler
from services.api.state import SessionManager


class LocalHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manager = SessionManager(SyntheticPoseEngine)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.manager, None, "synthetic_demo"))
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = build_opener(ProxyHandler({}))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.manager.close()
        cls.thread.join(timeout=2)

    def post_json(self, path: str, document: dict) -> dict:
        request = Request(
            self.base + path,
            data=json.dumps(document).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": self.base},
            method="POST",
        )
        with self.opener.open(request, timeout=3) as response:
            return json.load(response)

    def test_static_app_and_local_frame_flow(self) -> None:
        with self.opener.open(self.base + "/", timeout=3) as response:
            self.assertIn("Analyse de mouvement", response.read().decode("utf-8"))
        with self.opener.open(self.base + "/api/status", timeout=3) as response:
            status = json.load(response)
        self.assertEqual(status["provenance"]["pose_engine"], "synthetic_demo")
        self.assertIsNone(status["provenance"]["pose_model"]["hash_verified"])

        session = self.post_json("/api/session/start", {"side": "left"})
        for index in range(3):
            request = Request(
                self.base + "/api/frame",
                data=b"\xff\xd8test",
                headers={
                    "Content-Type": "image/jpeg",
                    "Origin": self.base,
                    "X-Session-Id": session["session_id"],
                    "X-Session-Token": session["token"],
                    "X-Sequence": str(index),
                    "X-Timestamp-Ms": str(index * 200),
                },
                method="POST",
            )
            with self.opener.open(request, timeout=3) as response:
                observed = json.load(response)
                self.assertEqual(observed["sequence"], index)
                self.assertEqual(observed["analyzed_image"], {"width_px": 640, "height_px": 480})
                self.assertEqual(observed["landmark_diagnostics"], {})

        finished = self.post_json(
            "/api/session/finish",
            {**session, "view_confirmed": True, "camera_stable_confirmed": True},
        )
        self.assertEqual(finished["measurement"]["status"], "valid")
        self.assertEqual(finished["motion"]["duration_ms"], 400)
        self.assertEqual(finished["motion"]["pose_diagnostics"]["available_frame_count"], 0)
        self.assertEqual(finished["motion"]["robustness"]["usable_frames"], 3)
        self.assertIn("ne jugent pas l'exécution du geste", finished["draft"])
        self.assertFalse(finished["capture_integrity"]["interrupted"])
        self.assertEqual(finished["llm_usage"]["records"], [])
        evidence = self.post_json("/api/session/evidence", session)
        self.assertIsNotNone(evidence["jpeg_base64"])
        self.assertEqual(evidence["evidence_ref"], finished["measurement"]["evidence_refs"][0])
        self.assertIn("BROUILLON NON VALIDÉ", finished["draft"])
        llm = self.post_json("/api/harness/draft", session)
        self.assertEqual(llm["fallback_reason"], "llm_unavailable")
        self.assertIsNone(llm["proposed_note"])
        self.post_json("/api/session/cancel", session)
        with self.assertRaises(HTTPError) as captured:
            self.post_json("/api/session/evidence", session)
        self.assertEqual(captured.exception.code, 403)
        captured.exception.close()

    def test_foreign_origin_is_blocked_before_session_creation(self) -> None:
        request = Request(
            self.base + "/api/session/start",
            data=b'{"side":"left"}',
            headers={"Content-Type": "application/json", "Origin": "https://other.example"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as captured:
            self.opener.open(request, timeout=3)
        self.assertEqual(captured.exception.code, 403)
        captured.exception.close()

    def test_new_protocol_flow_has_selected_landmarks_and_does_not_call_elbow_harness(self) -> None:
        with self.opener.open(self.base + "/api/status", timeout=3) as response:
            status = json.load(response)
        self.assertEqual(len(status["protocols"]), 7)
        self.assertEqual(status["topology"]["camera"], "browser_client")
        for protocol_id, count in (("knee_flexion_active", 3), ("neck_lateral_inclination", 4), ("neck_rotation_guided", 4)):
            session = self.post_json("/api/session/start", {"side": "right", "protocol_id": protocol_id})
            for index in range(3):
                request = Request(self.base + "/api/frame", data=b"\xff\xd8test", method="POST", headers={
                    "Content-Type": "image/jpeg", "Origin": self.base,
                    "X-Session-Id": session["session_id"], "X-Session-Token": session["token"],
                    "X-Sequence": str(index), "X-Timestamp-Ms": str(index * 200),
                })
                with self.opener.open(request, timeout=3) as response:
                    observation = json.load(response)
                self.assertEqual(len(observation["pose"]["points"]), count)
                self.assertEqual(observation["pose"]["protocol_id"], protocol_id)
                if protocol_id == "neck_rotation_guided":
                    self.assertIsNone(observation["angle_deg"])
            finished = self.post_json("/api/session/finish", {**session, "view_confirmed": True, "camera_stable_confirmed": True})
            self.assertEqual(finished["measurement"]["protocol_id"], protocol_id)
            self.assertNotIn("coude", finished["draft"])
            with self.assertRaises(HTTPError) as captured:
                self.post_json("/api/harness/draft", session)
            self.assertEqual(captured.exception.code, 409)
            captured.exception.close()
            self.post_json("/api/session/cancel", session)

    def test_model_selection_and_visual_consent_are_enforced(self) -> None:
        class RecordingModel:
            def __init__(self) -> None:
                self.measurement_ref = ""
                self.messages = []

            def check_model(self) -> bool:
                return True

            def complete(self, messages, tools):
                self.messages.append(messages)
                return {"content": json.dumps({
                    "measurement_ref": self.measurement_ref,
                    "fact_codes": ["measurement_recorded", "protocol_experimental"],
                    "requires_professional_review": True,
                })}

        gpt, qwen = RecordingModel(), RecordingModel()
        manager = SessionManager(SyntheticPoseEngine)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(manager, pose_mode="synthetic_demo", model_bindings=configured_models(gpt, qwen, True)),
        )
        base = f"http://127.0.0.1:{server.server_port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def post(path, doc):
            request = Request(
                base + path,
                data=json.dumps(doc).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": base},
                method="POST",
            )
            with self.opener.open(request, timeout=3) as response:
                return json.load(response)

        try:
            with self.opener.open(base + "/api/status", timeout=3) as response:
                status = json.load(response)
            self.assertEqual([item["id"] for item in status["models"]], ["gpt_oss", "qwen36"])
            self.assertFalse(status["models"][0]["supports_images"])
            self.assertTrue(status["models"][1]["image_enabled"])
            self.assertEqual(post("/api/models/check", {"model_id": "qwen36"})["state"], "ready")

            session = post("/api/session/start", {"side": "left"})
            for index in range(3):
                frame = Request(
                    base + "/api/frame",
                    data=b"\xff\xd8test",
                    headers={
                        "Content-Type": "image/jpeg", "Origin": base,
                        "X-Session-Id": session["session_id"], "X-Session-Token": session["token"],
                        "X-Sequence": str(index), "X-Timestamp-Ms": str(index * 200),
                    },
                    method="POST",
                )
                with self.opener.open(frame, timeout=3):
                    pass
            finished = post("/api/session/finish", {**session, "view_confirmed": True, "camera_stable_confirmed": True})
            gpt.measurement_ref = qwen.measurement_ref = finished["measurement"]["measurement_id"]

            request = Request(
                base + "/api/harness/draft",
                data=json.dumps({**session, "model_id": "gpt_oss", "include_image": True}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": base},
                method="POST",
            )
            with self.assertRaises(HTTPError) as captured:
                self.opener.open(request, timeout=3)
            self.assertEqual(captured.exception.code, 400)
            captured.exception.close()
            self.assertEqual(gpt.messages, [])

            text_result = post("/api/harness/draft", {**session, "model_id": "gpt_oss"})
            self.assertFalse(text_result["image_sent"])
            self.assertEqual(text_result["model_id"], "gpt_oss")
            self.assertIsNotNone(text_result["proposed_note"])
            self.assertIsNone(text_result["fallback_reason"])
            self.assertIsInstance(gpt.messages[0][1]["content"], str)
            gpt_trace = text_result["llm_usage"]["records"]
            self.assertEqual(len(gpt_trace), 1)
            self.assertEqual(gpt_trace[0]["model_id"], "gpt_oss")
            self.assertEqual(gpt_trace[0]["kind"], "draft")
            self.assertEqual(gpt_trace[0]["completion_call_count"], 1)
            self.assertFalse(gpt_trace[0]["image_payload_attached"])

            qwen_text = post("/api/harness/draft", {**session, "model_id": "qwen36"})
            self.assertFalse(qwen_text["image_sent"])
            self.assertIsInstance(qwen.messages[0][1]["content"], str)
            qwen_visual = post("/api/harness/draft", {**session, "model_id": "qwen36", "include_image": True})
            self.assertTrue(qwen_visual["image_sent"])
            self.assertIsNotNone(qwen_visual["proposed_note"])
            self.assertEqual(qwen.messages[1][1]["content"][1]["type"], "image_url")
            usage = {item["model_id"]: item for item in qwen_visual["llm_usage"]["records"]}
            self.assertEqual(usage["qwen36"]["completion_call_count"], 2)
            self.assertTrue(usage["qwen36"]["image_authorized"])
            self.assertTrue(usage["qwen36"]["image_payload_attached"])
            self.assertIsNone(usage["qwen36"]["model"]["quantization_verified"])
            self.assertNotIn(session["token"], json.dumps(qwen_visual["llm_usage"]))
        finally:
            server.shutdown()
            server.server_close()
            manager.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
