import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.server import configured_models, make_handler
from services.api.state import SessionManager


class BlockingModel:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        self.entered.set()
        self.release.wait(2)
        observation = json.loads(messages[1]["content"])
        return {"content": json.dumps({
            "window_ref": observation["window_ref"],
            "observation_code": observation["supported_observation_code"],
            "requires_professional_review": True,
        })}


class LiveHttpTests(unittest.TestCase):
    def setUp(self):
        self.model = BlockingModel()
        self.manager = SessionManager(SyntheticPoseEngine)
        self.handler = make_handler(self.manager, pose_mode="synthetic_demo",
                                    model_bindings=configured_models(self.model, self.model, True))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = build_opener(ProxyHandler({}))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.model.release.set()
        self.handler.live_coordinator.close()
        self.server.shutdown()
        self.server.server_close()
        self.manager.close()
        self.thread.join(timeout=2)

    def post(self, path, document):
        request = Request(self.base + path, data=json.dumps(document).encode(), method="POST",
                          headers={"Content-Type": "application/json", "Origin": self.base})
        with self.opener.open(request, timeout=3) as response:
            return json.load(response)

    def frame(self, session, sequence, timestamp):
        request = Request(self.base + "/api/frame", data=b"\xff\xd8test", method="POST", headers={
            "Content-Type": "image/jpeg", "Origin": self.base,
            "X-Session-Id": session["session_id"], "X-Session-Token": session["token"],
            "X-Sequence": str(sequence), "X-Timestamp-Ms": str(timestamp),
        })
        with self.opener.open(request, timeout=3) as response:
            return json.load(response)

    def start(self, protocol="elbow_flexion_active"):
        session = self.post("/api/session/start", {"side": "left", "protocol_id": protocol})
        for i in range(3):
            self.frame(session, i, i * 200)
        return session

    def assert_error(self, code, path, document):
        with self.assertRaises(HTTPError) as caught:
            self.post(path, document)
        self.assertEqual(caught.exception.code, code)
        caught.exception.close()

    def test_poll_is_nonblocking_and_pose_keeps_working_while_llm_runs(self):
        session = self.start("knee_flexion_active")
        before = time.monotonic()
        response = self.post("/api/harness/live/poll", {**session, "model_id": "gpt_oss", "control_version": 1})
        self.assertLess(time.monotonic() - before, 1)
        self.assertEqual(response["state"], "running")
        self.assertIsNone(response["result"])
        self.assertTrue(self.model.entered.wait(1))
        self.assertEqual(self.frame(session, 3, 600)["sequence"], 3)
        self.post("/api/harness/live/poll", {**session, "model_id": "gpt_oss", "control_version": 1})
        self.assertEqual(self.model.calls, 1)
        self.model.release.set()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            response = self.post("/api/harness/live/poll", {**session, "model_id": "gpt_oss", "control_version": 1})
            if response["result"]:
                break
            time.sleep(0.01)
        self.assertEqual(response["state"], "ready")
        self.assertTrue(response["result"]["provisional"])
        self.assertEqual(response["result"]["observation_source"], "llm")
        self.assertNotIn("jpeg", json.dumps(response))
        finished = self.post("/api/session/finish", {**session, "view_confirmed": True, "camera_stable_confirmed": True})
        self.assertNotIn("observation_code", json.dumps(finished))
        self.assert_error(400, "/api/harness/live/poll", {**session, "model_id": "gpt_oss", "control_version": 1})

    def test_image_permission_double_consent_and_stale_poll_cannot_reactivate(self):
        session = self.start()
        self.assert_error(400, "/api/harness/live/poll", {
            **session, "model_id": "gpt_oss", "include_image": True, "control_version": 1,
        })
        self.assert_error(400, "/api/harness/live/poll", {**session, "model_id": "qwen36", "include_image": "yes", "control_version": 1})
        self.assert_error(400, "/api/harness/live/poll", {**session, "model_id": "qwen36"})
        self.post("/api/harness/live/poll", {**session, "model_id": "qwen36", "include_image": True, "control_version": 2})
        self.assertEqual(self.manager.live_window_info(**session)["image_count"], 0)
        self.frame(session, 3, 1000)
        self.frame(session, 4, 2000)
        self.assertEqual(self.manager.live_window_info(**session)["image_count"], 2)
        self.post("/api/harness/live/stop", {**session, "control_version": 3})
        self.assertEqual(self.manager.live_window_info(**session)["image_count"], 0)
        for version in (2, 3):
            self.assert_error(403, "/api/harness/live/poll", {
                **session, "model_id": "qwen36", "include_image": True, "control_version": version,
            })
        self.assertEqual(self.manager.live_window_info(**session)["image_count"], 0)
        self.model.release.set()
        self.post("/api/harness/live/poll", {**session, "model_id": "qwen36", "include_image": False, "control_version": 4})
        self.assert_error(403, "/api/harness/live/stop", {**session, "control_version": 3})
        self.assertTrue(self.manager.live_is_current(session["session_id"], session["token"], 4))

    def test_token_and_window_are_scoped_and_replacement_cannot_return_old_result(self):
        old = self.start()
        self.post("/api/harness/live/poll", {**old, "model_id": "gpt_oss", "control_version": 1})
        self.assert_error(403, "/api/harness/live/poll", {**old, "token": "other", "model_id": "gpt_oss", "control_version": 2})
        current = self.start("neck_rotation_guided")
        self.model.release.set()
        self.assert_error(403, "/api/harness/live/poll", {**old, "model_id": "gpt_oss", "control_version": 2})
        response = self.post("/api/harness/live/poll", {**current, "model_id": "qwen36", "control_version": 1})
        self.assertNotIn(old["session_id"], json.dumps(response))
        self.assertIn(current["session_id"], response["window"]["window_ref"])

    def test_status_advertises_short_memory_not_video_streaming(self):
        with self.opener.open(self.base + "/api/status", timeout=3) as response:
            status = json.load(response)
        self.assertEqual(status["live_harness"]["window_ms"], 5000)
        self.assertEqual(status["live_harness"]["max_samples"], 25)
        self.assertEqual(status["live_harness"]["max_images"], 2)
        self.assertEqual(status["capture_limits"]["max_frames"], 600)
