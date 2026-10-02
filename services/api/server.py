"""Serveur de démonstration local, sans stockage de captures."""

import argparse
import json
import os
from base64 import b64encode
from dataclasses import asdict
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import timeout as SocketTimeout
from urllib.error import URLError
from urllib.parse import urlsplit

from packages.harness.local_llm import LocalLLMClient
from packages.harness.runner import run_harness
from packages.harness.tools import ToolContext
from packages.biomechanics.motion import frame_angle
from packages.pose.mediapipe_engine import MediaPipePoseEngine
from packages.pose.synthetic_engine import SyntheticPoseEngine
from services.api.state import MAX_JPEG_BYTES, SessionManager

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"


@dataclass(frozen=True)
class ModelBinding:
    label: str
    client: LocalLLMClient | None
    supports_images: bool = False
    image_enabled: bool = False


def configured_models(
    gpt_oss: LocalLLMClient | None = None,
    qwen36: LocalLLMClient | None = None,
    qwen_vision: bool = False,
) -> dict[str, ModelBinding]:
    return {
        "gpt_oss": ModelBinding("GPT-OSS", gpt_oss),
        "qwen36": ModelBinding("Qwen 3.6", qwen36, True, qwen_vision),
    }


def make_handler(
    manager: SessionManager,
    llm_client=None,
    pose_mode: str = "experimental",
    llm_vision: bool = False,
    model_bindings: dict[str, ModelBinding] | None = None,
):
    bindings = model_bindings or configured_models()
    if llm_client is not None:
        bindings = {**bindings, "custom": ModelBinding("Modèle local personnalisé", llm_client, llm_vision, llm_vision)}

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(15)

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
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Requête tronquée")
            return body

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
                        "capture_limits": {"max_frames": 600, "max_jpeg_bytes": MAX_JPEG_BYTES, "sampling_interval_ms": 200},
                        "llm_configured": any(item.client is not None for item in bindings.values()),
                        "llm_vision": any(item.image_enabled for item in bindings.values()),
                        "models": [
                            {
                                "id": key,
                                "label": item.label,
                                "configured": item.client is not None,
                                "supports_images": item.supports_images,
                                "image_enabled": item.image_enabled and item.client is not None,
                            }
                            for key, item in bindings.items()
                        ],
                    })
                    return
                static = {
                    "/": ("index.html", "text/html; charset=utf-8"),
                    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                    "/guide.js": ("guide.js", "text/javascript; charset=utf-8"),
                    "/capture-core.js": ("capture-core.js", "text/javascript; charset=utf-8"),
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
                    self._json(200, {"sequence": frame.sequence, "timestamp_ms": frame.timestamp_ms,
                                     "quality_reason": frame.quality_reason,
                                     "angle_deg": frame_angle(frame),
                                     "pose": {"width_px": frame.width_px, "height_px": frame.height_px,
                                              "shoulder": asdict(frame.shoulder) if frame.shoulder else None,
                                              "elbow": asdict(frame.elbow) if frame.elbow else None,
                                              "wrist": asdict(frame.wrist) if frame.wrist else None}})
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

                    self._json(200, {"measurement": asdict(measurement), "draft": render_draft(measurement),
                                     **manager.completed_details(doc.get("session_id", ""), doc.get("token", ""))})
                elif path == "/api/session/evidence":
                    doc = self._document()
                    measurement, keyframe = manager.completed_snapshot(doc.get("session_id", ""), doc.get("token", ""))
                    self._json(200, {"jpeg_base64": b64encode(keyframe).decode("ascii") if keyframe else None,
                                     "evidence_ref": measurement.evidence_refs[0] if keyframe else None})
                elif path == "/api/session/cancel":
                    doc = self._document()
                    manager.cancel(doc.get("session_id", ""), doc.get("token", ""))
                    self._json(200, {"cancelled": True})
                elif path == "/api/harness/draft":
                    doc = self._document()
                    model_id = doc.get("model_id")
                    if model_id is None:
                        model_id = "custom" if "custom" in bindings else "gpt_oss"
                    if model_id not in bindings:
                        raise ValueError("Modèle inconnu")
                    binding = bindings[model_id]
                    include_image = doc.get("include_image", False)
                    if not isinstance(include_image, bool) or (include_image and (not binding.image_enabled or binding.client is None)):
                        raise ValueError("Image non autorisée pour ce modèle")
                    session_id, token = doc.get("session_id", ""), doc.get("token", "")
                    measurement, keyframe = manager.completed_snapshot(session_id, token)
                    result = run_harness(
                        ToolContext(session_id, measurement, keyframe if include_image else None),
                        binding.client,
                        allow_visual_evidence=include_image,
                    )
                    manager.get(session_id, token)  # Refuse une réponse pour une séance révoquée entre-temps.
                    self._json(200, {**asdict(result), "model_id": model_id, "image_sent": include_image and binding.client is not None and keyframe is not None})
                elif path == "/api/models/check":
                    doc = self._document()
                    model_id = doc.get("model_id")
                    if model_id not in bindings:
                        raise ValueError("Modèle inconnu")
                    binding = bindings[model_id]
                    if binding.client is None:
                        self._json(200, {"model_id": model_id, "state": "not_configured"})
                    else:
                        try:
                            available = binding.client.check_model()
                            state = "ready" if available else "model_not_advertised"
                        except (OSError, URLError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                            state = "runtime_unreachable"
                        self._json(200, {"model_id": model_id, "state": state})
                else:
                    self._json(404, {"error": "not_found"})
            except PermissionError:
                self._json(403, {"error": "forbidden"})
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                self._json(400, {"error": "invalid_request"})
            except (RuntimeError, FileNotFoundError):
                self._json(503, {"error": "pose_engine_unavailable"})
            except SocketTimeout:
                self._json(408, {"error": "request_timeout"})

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
    parser.add_argument("--gpt-oss-url", default=os.environ.get("KINE_GPT_OSS_URL"))
    parser.add_argument("--gpt-oss-model", default=os.environ.get("KINE_GPT_OSS_MODEL", "gpt-oss-20b"))
    parser.add_argument("--qwen-url", default=os.environ.get("KINE_QWEN36_URL"))
    parser.add_argument("--qwen-model", default=os.environ.get("KINE_QWEN36_MODEL", "Qwen3.6-27B"))
    parser.add_argument("--qwen-vision", action="store_true", help="Permettre l'envoi explicite d'une image au serveur Qwen local")
    args = parser.parse_args()
    if not args.pose_model and not args.demo_pose:
        parser.error("Un modèle local --pose-model est requis ; aucun téléchargement automatique")
    if not args.demo_pose and not args.experimental_pose:
        parser.error("MediaPipe reste expérimental : ajouter --experimental-pose après examen du trafic réseau")
    client = None
    if bool(args.llm_url) != bool(args.llm_model):
        parser.error("--llm-url et --llm-model doivent être fournis ensemble")
    if args.llm_url and args.llm_model:
        client = LocalLLMClient(args.llm_url, args.llm_model)
    if args.llm_vision and client is None:
        parser.error("--llm-vision exige --llm-url et --llm-model")
    if args.qwen_vision and not args.qwen_url:
        parser.error("--qwen-vision exige --qwen-url")
    models = configured_models(
        LocalLLMClient(args.gpt_oss_url, args.gpt_oss_model) if args.gpt_oss_url else None,
        LocalLLMClient(args.qwen_url, args.qwen_model) if args.qwen_url else None,
        args.qwen_vision,
    )
    engine_factory = SyntheticPoseEngine if args.demo_pose else lambda: MediaPipePoseEngine(args.pose_model)
    manager = SessionManager(engine_factory)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(
            manager,
            client,
            "synthetic_demo" if args.demo_pose else "mediapipe_experimental",
            args.llm_vision,
            models,
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
