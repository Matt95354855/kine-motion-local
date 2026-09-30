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
                self.assertEqual(json.load(response)["sequence"], index)

        finished = self.post_json(
            "/api/session/finish",
            {**session, "view_confirmed": True, "camera_stable_confirmed": True},
        )
        self.assertEqual(finished["measurement"]["status"], "valid")
        self.assertIn("BROUILLON NON VALIDÉ", finished["draft"])
        llm = self.post_json("/api/harness/draft", session)
        self.assertEqual(llm["fallback_reason"], "llm_unavailable")
        self.assertIsNone(llm["proposed_note"])

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
                    "text": "La vue demande une vérification professionnelle.",
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
            self.assertIsInstance(gpt.messages[0][1]["content"], str)

            qwen_text = post("/api/harness/draft", {**session, "model_id": "qwen36"})
            self.assertFalse(qwen_text["image_sent"])
            self.assertIsInstance(qwen.messages[0][1]["content"], str)
            qwen_visual = post("/api/harness/draft", {**session, "model_id": "qwen36", "include_image": True})
            self.assertTrue(qwen_visual["image_sent"])
            self.assertEqual(qwen.messages[1][1]["content"][1]["type"], "image_url")
        finally:
            server.shutdown()
            server.server_close()
            manager.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
