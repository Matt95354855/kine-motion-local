"""Séance éphémère : aucune capture sur disque, mémoire live courte et bornée."""

from dataclasses import asdict, dataclass, field, replace
from secrets import token_urlsafe
from threading import Event, RLock, Thread
from time import monotonic
from typing import Callable
from uuid import uuid4
from copy import deepcopy

from packages.biomechanics.protocols import angle_and_reason, assess_trial, get_protocol
from packages.biomechanics.motion import summarize_motion
from packages.contracts.models import ElbowTrial, Measurement, PoseFrame
from packages.pose.adapter import PoseEngine
from packages.harness.live import LiveSnapshot
from packages.harness.window import RollingCaptureWindow
from services.api.capture_integrity import CaptureIntegrity

MAX_FRAMES = 600
MAX_JPEG_BYTES = 1_000_000
SESSION_TTL_SECONDS = 15 * 60


@dataclass
class CaptureSession:
    session_id: str
    token: str
    side: str
    engine: PoseEngine
    protocol_id: str = "elbow_flexion_active"
    frames: list[PoseFrame] = field(default_factory=list)
    measurement: Measurement | None = None
    active: bool = True
    expires_at: float = field(default_factory=lambda: monotonic() + SESSION_TTL_SECONDS)
    keyframe_jpeg: bytes | None = None
    keyframe_sequence: int | None = None
    keyframe_angle: float = -1.0
    keyframe_timestamp_ms: int | None = None
    motion_summary: dict | None = None
    live_window: RollingCaptureWindow = field(default_factory=RollingCaptureWindow)
    live_control_version: int = -1
    live_enabled: bool = False
    capture_integrity: CaptureIntegrity | None = None
    capture_summary: dict | None = None
    llm_usage: dict = field(default_factory=dict)


class SessionManager:
    def __init__(self, engine_factory: Callable[[], PoseEngine], ttl_seconds: float = SESSION_TTL_SECONDS,
                 capture_clock: Callable[[], float] = monotonic) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Expiration positive requise")
        self._engine_factory = engine_factory
        self._ttl_seconds = ttl_seconds
        self._capture_clock = capture_clock
        self._lock = RLock()
        self._session: CaptureSession | None = None
        self._shutdown = Event()
        self._reaper = Thread(target=self._expire_idle, daemon=True)
        self._reaper.start()

    def _expire_idle(self) -> None:
        while not self._shutdown.wait(min(1.0, self._ttl_seconds)):
            with self._lock:
                if self._session and monotonic() > self._session.expires_at:
                    self._close_previous()
                elif self._session:
                    self._session.live_window.purge(monotonic())
                    if self._session.active:
                        self._session.capture_integrity.observe(self._capture_clock())
                        if self._session.capture_integrity.interrupted:
                            self._session.live_enabled = False
                            self._session.live_window.clear()

    def start(self, side: str, protocol_id: str = "elbow_flexion_active") -> CaptureSession:
        if side not in ("left", "right"):
            raise ValueError("Côté anatomique requis")
        get_protocol(protocol_id)
        with self._lock:
            self._close_previous()
            session = CaptureSession(
                session_id=uuid4().hex,
                token=token_urlsafe(32),
                side=side,
                engine=self._engine_factory(),
                protocol_id=protocol_id,
                expires_at=monotonic() + self._ttl_seconds,
            )
            session.capture_integrity = CaptureIntegrity(self._capture_clock())
            self._session = session
            return session

    def _close_previous(self) -> None:
        if self._session is not None:
            previous = self._session
            self._session = None
            try:
                if previous.active:
                    previous.engine.close()
            finally:
                previous.active = False
                previous.frames.clear()
                previous.keyframe_jpeg = None
                previous.keyframe_sequence = None
                previous.keyframe_timestamp_ms = None
                previous.measurement = None
                previous.motion_summary = None
                previous.capture_summary = None
                previous.capture_integrity = None
                previous.llm_usage.clear()
                previous.live_window.clear()
                previous.live_enabled = False

    def get(self, session_id: str, token: str) -> CaptureSession:
        with self._lock:
            if (
                self._session is None
                or self._session.session_id != session_id
                or self._session.token != token
            ):
                raise PermissionError("Séance inconnue ou expirée")
            if monotonic() > self._session.expires_at:
                self._close_previous()
                raise PermissionError("Séance expirée")
            return self._session

    def completed_measurement(self, session_id: str, token: str) -> Measurement:
        with self._lock:
            session = self.get(session_id, token)
            if session.active or session.measurement is None:
                raise ValueError("Terminer l'essai avant la rédaction")
            return session.measurement

    def add_frame(
        self, session_id: str, token: str, jpeg: bytes, sequence: int, timestamp_ms: int
    ) -> PoseFrame:
        with self._lock:
            session = self.get(session_id, token)
            if not session.active:
                raise ValueError("Séance terminée")
            if not 4 <= len(jpeg) <= MAX_JPEG_BYTES or not jpeg.startswith(b"\xff\xd8"):
                raise ValueError("JPEG invalide ou trop volumineux")
            if len(session.frames) >= MAX_FRAMES:
                raise ValueError("Limite d'images atteinte")
            if sequence < 0 or timestamp_ms < 0:
                raise ValueError("Séquence ou temps invalide")
            if session.frames and (
                sequence <= session.frames[-1].sequence
                or timestamp_ms <= session.frames[-1].timestamp_ms
            ):
                raise ValueError("Images non monotones")
            received_at = self._capture_clock()
            session.capture_integrity.receive(received_at, timestamp_ms)
            try:
                observation = session.engine.detect(jpeg, timestamp_ms, session.side)
                # Un retour lent n'efface pas l'âge de l'image lors de sa réception.
                session.capture_integrity.observe(self._capture_clock())
                if not (0 < observation.width_px <= 1920 and 0 < observation.height_px <= 1080):
                    raise ValueError("Dimensions d'image hors limite")
                frame = PoseFrame(
                    sequence=sequence,
                    timestamp_ms=timestamp_ms,
                    width_px=observation.width_px,
                    height_px=observation.height_px,
                    shoulder=observation.shoulder,
                    elbow=observation.elbow,
                    wrist=observation.wrist,
                    quality_reason="capture_interrupted" if session.capture_integrity.interrupted else observation.quality_reason,
                    landmarks=dict(observation.landmarks),
                    landmark_diagnostics=dict(observation.landmark_diagnostics),
                    protocol_id=session.protocol_id,
                    side=session.side,
                )
                angle, reason = angle_and_reason(frame, session.side)
            except Exception:
                # Des JPEG reçus mais non traités ne rendent pas une capture complète.
                # Sans ceci, des erreurs répétées pourraient garder un ancien pic valide.
                session.capture_integrity.interrupted = True
                session.live_enabled = False
                session.live_window.clear()
                session.keyframe_jpeg = None
                raise
            if reason != "rotation_not_measurable_2d":
                frame = replace(frame, quality_reason=reason)
            session.frames.append(frame)
            if not session.capture_integrity.interrupted:
                session.live_window.append(frame, jpeg, monotonic())
            else:
                session.live_enabled = False
                session.live_window.clear()
            if angle is not None and angle > session.keyframe_angle:
                session.keyframe_angle = angle
                session.keyframe_jpeg = jpeg
                session.keyframe_sequence = sequence
                session.keyframe_timestamp_ms = timestamp_ms
            return frame

    def _live_session(self, session_id: str, token: str) -> CaptureSession:
        session = self.get(session_id, token)
        if not session.active or session.capture_integrity.interrupted:
            raise ValueError("Observation live réservée à un essai en cours")
        return session

    def set_live_image_consent(self, session_id: str, token: str, enabled: bool) -> None:
        with self._lock:
            self._live_session(session_id, token).live_window.set_image_consent(enabled)

    @staticmethod
    def _check_live_version(control_version: int) -> None:
        if type(control_version) is not int or not 0 <= control_version <= 1_000_000_000:
            raise ValueError("Version de contrôle live invalide")

    def configure_live(self, session_id: str, token: str, control_version: int, include_images: bool) -> None:
        """Une vieille requête ne peut réactiver un consentement révoqué."""
        self._check_live_version(control_version)
        if type(include_images) is not bool:
            raise ValueError("Consentement visuel booléen requis")
        with self._lock:
            session = self._live_session(session_id, token)
            if control_version < session.live_control_version or (
                control_version == session.live_control_version and not session.live_enabled
            ):
                raise PermissionError("Contrôle live révoqué")
            session.live_control_version = control_version
            session.live_enabled = True
            session.live_window.set_image_consent(include_images)

    def stop_live(self, session_id: str, token: str, control_version: int) -> None:
        self._check_live_version(control_version)
        with self._lock:
            session = self.get(session_id, token)
            if control_version < session.live_control_version:
                raise PermissionError("Ancien contrôle live")
            session.live_control_version = control_version
            session.live_enabled = False
            session.live_window.set_image_consent(False)

    def live_is_current(self, session_id: str, token: str, control_version: int) -> bool:
        with self._lock:
            session = self.get(session_id, token)
            return (session.active and not session.capture_integrity.interrupted
                    and session.live_enabled and session.live_control_version == control_version)

    def live_window_info(self, session_id: str, token: str) -> dict:
        with self._lock:
            session = self._live_session(session_id, token)
            return session.live_window.info(session_id, monotonic())

    def live_snapshot(self, session_id: str, token: str, include_images: bool = False) -> LiveSnapshot:
        with self._lock:
            session = self._live_session(session_id, token)
            window = session.live_window
            info = window.info(session_id, monotonic())
            images = tuple(item.jpeg for item in window.images) if include_images and window.image_consent else ()
            image_metadata = tuple({"sequence": item.sequence, "timestamp_ms": int(item.timestamp_ms)}
                                   for item in window.images) if images else ()
            return LiveSnapshot(
                session_id=session_id, window_ref=info["window_ref"], protocol_id=session.protocol_id,
                side=session.side, start_timestamp_ms=info["start_timestamp_ms"],
                end_timestamp_ms=info["end_timestamp_ms"], samples=window.observation_samples(), images=images,
                image_metadata=image_metadata,
            )

    def finish(
        self,
        session_id: str,
        token: str,
        view_confirmed: bool | None,
        camera_stable_confirmed: bool | None,
        stopped: bool = False,
        interruption_reason: str | None = None,
        capture_monitor: dict | None = None,
    ) -> Measurement:
        with self._lock:
            session = self.get(session_id, token)
            if not session.active:
                raise ValueError("Séance déjà terminée")
            capture_summary = session.capture_integrity.finish(
                self._capture_clock(), capture_monitor, interruption_reason)
            frames = tuple(
                replace(
                    frame,
                    view_is_valid=view_confirmed,
                    camera_stable=camera_stable_confirmed,
                )
                for frame in session.frames
            )
            trial = ElbowTrial(
                trial_id=f"{session_id}:trial:1",
                session_id=session_id,
                side=session.side,
                frames=frames,
                stopped=stopped,
                interruption_reason="capture_interrupted" if capture_summary["interrupted"] else None,
            )
            try:
                measurement = assess_trial(trial, session.protocol_id)
            finally:
                session.active = False
                session.live_enabled = False
                session.live_window.clear()
                session.engine.close()
            session.measurement = measurement
            session.capture_summary = capture_summary
            session.motion_summary = summarize_motion(frames)
            # Diagnostics séparés : les quatre clés des échantillons utilisés
            # par le harness live ne changent pas. Aucun pixel supplémentaire.
            diagnostics = []
            for frame in frames:
                names = get_protocol(frame.protocol_id).names(frame.side)
                diagnostics.append({
                    "sequence": frame.sequence, "timestamp_ms": frame.timestamp_ms,
                    "landmarks": {name: asdict(frame.landmark_diagnostics[name])
                                  for name in names if name in frame.landmark_diagnostics},
                })
            session.motion_summary["pose_diagnostics"] = {
                "schema_version": "1.0", "scope": "protocol_required_landmarks",
                "score_interpretation": "detector_internal_not_angular_accuracy",
                "available_frame_count": sum(bool(item["landmarks"]) for item in diagnostics),
                "samples": diagnostics,
            }
            session.frames.clear()
            if (
                measurement.value_deg is None
                or not measurement.evidence_refs
                or session.keyframe_sequence is None
                or not measurement.evidence_refs[0].endswith(f":frame:{session.keyframe_sequence}")
            ):
                session.keyframe_jpeg = None
                session.keyframe_sequence = None
            return measurement

    def completed_details(self, session_id: str, token: str) -> dict:
        with self._lock:
            self.completed_measurement(session_id, token)
            session = self.get(session_id, token)
            return {"motion": session.motion_summary,
                    "capture_integrity": session.capture_summary,
                    "llm_usage": self.llm_usage_details(session_id, token),
                    "evidence_sequence": session.keyframe_sequence,
                    "evidence_timestamp_ms": session.keyframe_timestamp_ms if session.keyframe_jpeg else None}

    def completed_snapshot(self, session_id: str, token: str) -> tuple[Measurement, bytes | None]:
        with self._lock:
            measurement = self.completed_measurement(session_id, token)
            return measurement, self.get(session_id, token).keyframe_jpeg

    def record_llm_completion(self, session_id: str, token: str, model_id: str, kind: str,
                              model: dict, image_authorized: bool, image_payload_attached: bool) -> None:
        """Compteur borné d'appels commencés, sans prompt, réponse ou pixels."""
        if kind not in ("live", "draft") or not isinstance(model_id, str) or not 1 <= len(model_id) <= 64:
            raise ValueError("Provenance d'appel invalide")
        with self._lock:
            session = self.get(session_id, token)
            if kind == "live" and (not session.active or session.capture_integrity.interrupted):
                raise PermissionError("Capture révoquée pour l'analyse")
            if kind == "draft" and session.active:
                raise ValueError("Terminer la capture avant la note")
            key = (model_id, kind)
            if key not in session.llm_usage and len(session.llm_usage) >= 6:
                raise ValueError("Limite de provenance LLM atteinte")
            elapsed = round(max(0.0, self._capture_clock() - session.capture_integrity.started_at) * 1000, 1)
            if key not in session.llm_usage:
                session.llm_usage[key] = {
                    "model_id": model_id, "kind": kind, "completion_call_count": 0,
                    "first_call_elapsed_ms": elapsed, "last_call_elapsed_ms": elapsed,
                    "image_authorized": False, "image_payload_attached": False, "model": deepcopy(model),
                }
            record = session.llm_usage[key]
            record["completion_call_count"] += 1
            record["last_call_elapsed_ms"] = elapsed
            record["image_authorized"] = record["image_authorized"] or image_authorized
            record["image_payload_attached"] = record["image_payload_attached"] or image_payload_attached

    def llm_usage_details(self, session_id: str, token: str) -> dict:
        with self._lock:
            session = self.get(session_id, token)
            return {
                "schema_version": "1.0",
                "meaning": "completion_attempts_started_not_proof_of_network_success_or_gpu_release",
                "records": deepcopy(list(session.llm_usage.values())),
            }

    def cancel(self, session_id: str, token: str) -> None:
        with self._lock:
            self.get(session_id, token)
            self._close_previous()

    def close(self) -> None:
        self._shutdown.set()
        with self._lock:
            self._close_previous()
        self._reaper.join(timeout=2)
