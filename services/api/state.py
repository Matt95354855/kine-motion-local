"""Séance éphémère : les JPEG ne sont jamais conservés par l'application."""

from dataclasses import dataclass, field, replace
from secrets import token_urlsafe
from threading import Event, RLock, Thread
from time import monotonic
from typing import Callable
from uuid import uuid4

from packages.biomechanics.protocols import angle_and_reason, assess_trial, get_protocol
from packages.biomechanics.motion import summarize_motion
from packages.contracts.models import ElbowTrial, Measurement, PoseFrame
from packages.pose.adapter import PoseEngine

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


class SessionManager:
    def __init__(self, engine_factory: Callable[[], PoseEngine], ttl_seconds: float = SESSION_TTL_SECONDS) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Expiration positive requise")
        self._engine_factory = engine_factory
        self._ttl_seconds = ttl_seconds
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
            observation = session.engine.detect(jpeg, timestamp_ms, session.side)
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
                quality_reason=observation.quality_reason,
                landmarks=dict(observation.landmarks),
                protocol_id=session.protocol_id,
                side=session.side,
            )
            angle, reason = angle_and_reason(frame, session.side)
            if reason != "rotation_not_measurable_2d":
                frame = replace(frame, quality_reason=reason)
            session.frames.append(frame)
            if angle is not None and angle > session.keyframe_angle:
                session.keyframe_angle = angle
                session.keyframe_jpeg = jpeg
                session.keyframe_sequence = sequence
                session.keyframe_timestamp_ms = timestamp_ms
            return frame

    def finish(
        self,
        session_id: str,
        token: str,
        view_confirmed: bool | None,
        camera_stable_confirmed: bool | None,
        stopped: bool = False,
    ) -> Measurement:
        with self._lock:
            session = self.get(session_id, token)
            if not session.active:
                raise ValueError("Séance déjà terminée")
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
            )
            try:
                measurement = assess_trial(trial, session.protocol_id)
            finally:
                session.active = False
                session.engine.close()
            session.measurement = measurement
            session.motion_summary = summarize_motion(frames)
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
                    "evidence_sequence": session.keyframe_sequence,
                    "evidence_timestamp_ms": session.keyframe_timestamp_ms if session.keyframe_jpeg else None}

    def completed_snapshot(self, session_id: str, token: str) -> tuple[Measurement, bytes | None]:
        with self._lock:
            measurement = self.completed_measurement(session_id, token)
            return measurement, self.get(session_id, token).keyframe_jpeg

    def cancel(self, session_id: str, token: str) -> None:
        with self._lock:
            self.get(session_id, token)
            self._close_previous()

    def close(self) -> None:
        self._shutdown.set()
        with self._lock:
            self._close_previous()
        self._reaper.join(timeout=2)
