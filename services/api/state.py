"""Séance éphémère : les JPEG ne sont jamais conservés par l'application."""

from dataclasses import dataclass, field, replace
from secrets import token_urlsafe
from threading import RLock
from time import monotonic
from typing import Callable
from uuid import uuid4

from packages.biomechanics.elbow import assess_elbow_trial
from packages.biomechanics.geometry import apparent_elbow_flexion_deg
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
    frames: list[PoseFrame] = field(default_factory=list)
    measurement: Measurement | None = None
    active: bool = True
    expires_at: float = field(default_factory=lambda: monotonic() + SESSION_TTL_SECONDS)
    keyframe_jpeg: bytes | None = None
    keyframe_sequence: int | None = None
    keyframe_angle: float = -1.0


class SessionManager:
    def __init__(self, engine_factory: Callable[[], PoseEngine]) -> None:
        self._engine_factory = engine_factory
        self._lock = RLock()
        self._session: CaptureSession | None = None

    def start(self, side: str) -> CaptureSession:
        if side not in ("left", "right"):
            raise ValueError("Côté anatomique requis")
        with self._lock:
            self._close_previous()
            session = CaptureSession(
                session_id=uuid4().hex,
                token=token_urlsafe(32),
                side=side,
                engine=self._engine_factory(),
            )
            self._session = session
            return session

    def _close_previous(self) -> None:
        if self._session is not None:
            if self._session.active:
                self._session.engine.close()
            self._session = None

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
            )
            session.frames.append(frame)
            if (
                observation.quality_reason is None
                and observation.shoulder is not None
                and observation.elbow is not None
                and observation.wrist is not None
            ):
                try:
                    angle = apparent_elbow_flexion_deg(
                        observation.shoulder,
                        observation.elbow,
                        observation.wrist,
                        observation.width_px,
                        observation.height_px,
                    )
                    if angle > session.keyframe_angle:
                        session.keyframe_angle = angle
                        session.keyframe_jpeg = jpeg
                        session.keyframe_sequence = sequence
                except ValueError:
                    pass
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
                measurement = assess_elbow_trial(trial)
            finally:
                session.active = False
                session.engine.close()
            session.measurement = measurement
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

    def completed_snapshot(self, session_id: str, token: str) -> tuple[Measurement, bytes | None]:
        with self._lock:
            measurement = self.completed_measurement(session_id, token)
            return measurement, self.get(session_id, token).keyframe_jpeg

    def cancel(self, session_id: str, token: str) -> None:
        with self._lock:
            self.get(session_id, token)
            self._close_previous()

    def close(self) -> None:
        with self._lock:
            self._close_previous()
