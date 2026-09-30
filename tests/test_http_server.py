import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.server import make_handler
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


if __name__ == "__main__":
    unittest.main()
