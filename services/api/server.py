"""Serveur de démonstration local, sans stockage de captures."""

import argparse
import json
import os
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from packages.harness.local_llm import LocalLLMClient
from packages.harness.runner import run_harness
from packages.harness.tools import ToolContext
from packages.pose.mediapipe_engine import MediaPipePoseEngine
from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.state import MAX_JPEG_BYTES, SessionManager

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"


def make_handler(
    manager: SessionManager,
    llm_client=None,
    pose_mode: str = "experimental",
    llm_vision: bool = False,
):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args) -> None:
            # Évite d'inscrire le détail des séances ou des images dans les logs.
            pass

        def _headers(self, code: int, content_type: str, length: int) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(self), microphone=()")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()

        def _json(self, code: int, document: object) -> None:
            body = json.dumps(document, ensure_ascii=False).encode("utf-8")
            self._headers(code, "application/json; charset=utf-8", len(body))
            self.wfile.write(body)

        def _body(self, limit: int = 4096) -> bytes:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > limit:
                raise ValueError("Taille de requête invalide")
            return self.rfile.read(length)

        def _document(self) -> dict:
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("JSON requis")
            document = json.loads(self._body())
            if not isinstance(document, dict):
                raise ValueError("Objet JSON requis")
            return document

        def _check_local_request(self) -> None:
            host = self.headers.get("Host", "")
            if host not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"):
                raise PermissionError("Hôte non autorisé")
            origin = self.headers.get("Origin")
            if origin and origin not in (
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            ):
                raise PermissionError("Origine non autorisée")

        def do_GET(self) -> None:
            try:
                self._check_local_request()
                path = urlsplit(self.path).path
                if path == "/api/status":
                    self._json(200, {
                        "pose_mode": pose_mode,
                        "llm_configured": llm_client is not None,
                        "llm_vision": llm_vision,
                    })
                    return
                static = {
                    "/": ("index.html", "text/html; charset=utf-8"),
                    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                    "/style.css": ("style.css", "text/css; charset=utf-8"),
                }
                if path not in static:
                    self._json(404, {"error": "not_found"})
                    return
                filename, mime = static[path]
                body = (WEB / filename).read_bytes()
                self._headers(200, mime, len(body))
                self.wfile.write(body)
            except PermissionError:
                self._json(403, {"error": "forbidden"})

        def do_POST(self) -> None:
            try:
                self._check_local_request()
                path = urlsplit(self.path).path
                if path == "/api/session/start":
                    doc = self._document()
                    session = manager.start(doc.get("side"))
                    self._json(201, {"session_id": session.session_id, "token": session.token})
                elif path == "/api/frame":
                    if self.headers.get("Content-Type") != "image/jpeg":
                        raise ValueError("JPEG requis")
                    frame = manager.add_frame(
                        self.headers.get("X-Session-Id", ""),
                        self.headers.get("X-Session-Token", ""),
                        self._body(MAX_JPEG_BYTES),
                        int(self.headers.get("X-Sequence", "-1")),
                        int(self.headers.get("X-Timestamp-Ms", "-1")),
                    )
                    self._json(200, {"sequence": frame.sequence, "quality_reason": frame.quality_reason})
                elif path == "/api/session/finish":
                    doc = self._document()
                    measurement = manager.finish(
                        doc.get("session_id", ""),
                        doc.get("token", ""),
                        True if doc.get("view_confirmed") is True else None,
                        True if doc.get("camera_stable_confirmed") is True else None,
                        doc.get("stopped") is True,
                    )
                    from packages.harness.report import render_draft

                    self._json(200, {"measurement": asdict(measurement), "draft": render_draft(measurement)})
                elif path == "/api/session/cancel":
                    doc = self._document()
                    manager.cancel(doc.get("session_id", ""), doc.get("token", ""))
                    self._json(200, {"cancelled": True})
                elif path == "/api/harness/draft":
                    doc = self._document()
                    session_id, token = doc.get("session_id", ""), doc.get("token", "")
                    measurement, keyframe = manager.completed_snapshot(session_id, token)
                    result = run_harness(
                        ToolContext(session_id, measurement, keyframe if llm_vision else None),
                        llm_client,
                        allow_visual_evidence=llm_vision,
                    )
                    manager.get(session_id, token)  # Refuse une réponse pour une séance révoquée entre-temps.
                    self._json(200, asdict(result))
                else:
                    self._json(404, {"error": "not_found"})
            except PermissionError:
                self._json(403, {"error": "forbidden"})
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                self._json(400, {"error": "invalid_request"})
            except (RuntimeError, FileNotFoundError):
                self._json(503, {"error": "pose_engine_unavailable"})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Prototype de capture locale")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--pose-model", default=os.environ.get("KINE_POSE_MODEL"))
    parser.add_argument("--demo-pose", action="store_true", help="Pose fictive : n'analyse pas les pixels")
    parser.add_argument("--experimental-pose", action="store_true", help="Activer l'adaptateur MediaPipe non vérifié hors ligne")
    parser.add_argument("--llm-url", default=os.environ.get("KINE_LLM_URL"))
    parser.add_argument("--llm-model", default=os.environ.get("KINE_LLM_MODEL"))
    parser.add_argument("--llm-vision", action="store_true", help="Autoriser une image de preuve vers un VLM local")
    args = parser.parse_args()
    if not args.pose_model and not args.demo_pose:
        parser.error("Un modèle local --pose-model est requis ; aucun téléchargement automatique")
    if not args.demo_pose and not args.experimental_pose:
        parser.error("MediaPipe reste expérimental : ajouter --experimental-pose après examen du trafic réseau")
    client = None
    if args.llm_url and args.llm_model:
        client = LocalLLMClient(args.llm_url, args.llm_model)
    if args.llm_vision and client is None:
        parser.error("--llm-vision exige --llm-url et --llm-model")
    engine_factory = SyntheticPoseEngine if args.demo_pose else lambda: MediaPipePoseEngine(args.pose_model)
    manager = SessionManager(engine_factory)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(
            manager,
            client,
            "synthetic_demo" if args.demo_pose else "mediapipe_experimental",
            args.llm_vision,
        ),
    )
    print(f"Prototype local : http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    finally:
        manager.close()
        server.server_close()


if __name__ == "__main__":
    main()
