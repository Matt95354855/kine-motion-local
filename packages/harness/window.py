"""Mémoire de travail courte ; aucun média sur disque ni historique LLM."""

from collections import deque
from dataclasses import dataclass

from packages.biomechanics.motion import frame_angle
from packages.biomechanics.protocols import get_protocol, selected_points
from packages.contracts.models import PoseFrame

WINDOW_MS = 5000
MAX_SAMPLES = 25
MAX_IMAGES = 2
IMAGE_INTERVAL_MS = 1000
MAX_IMAGE_BYTES = 1_000_000


@dataclass(frozen=True)
class RecentImage:
    sequence: int
    timestamp_ms: float
    received_at: float
    jpeg: bytes


class RollingCaptureWindow:
    """Borne indépendante en temps source, temps serveur, nombre et octets.

    Les JPEG ne sont retenus qu'après consentement live explicite. Le buffer de
    poses reste distinct des données structurées de l'essai (au plus 600 poses)
    et de son unique image de preuve. Purger libère les références, sans promettre
    une zéroisation de la mémoire ni des copies d'une inférence déjà en vol.
    """

    def __init__(self) -> None:
        self.samples: deque[tuple[float, PoseFrame]] = deque(maxlen=MAX_SAMPLES)
        self.images: deque[RecentImage] = deque(maxlen=MAX_IMAGES)
        self.image_consent = False

    def purge(self, now: float) -> None:
        latest = self.samples[-1][1].timestamp_ms if self.samples else None
        while self.samples and (
            now - self.samples[0][0] >= WINDOW_MS / 1000
            or latest - self.samples[0][1].timestamp_ms >= WINDOW_MS
        ):
            self.samples.popleft()
        first_sequence = self.samples[0][1].sequence if self.samples else None
        while self.images and (
            first_sequence is None
            or self.images[0].sequence < first_sequence
            or now - self.images[0].received_at >= WINDOW_MS / 1000
        ):
            self.images.popleft()

    def set_image_consent(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("Consentement visuel booléen requis")
        if enabled != self.image_consent:
            self.images.clear()
        self.image_consent = enabled

    def append(self, frame: PoseFrame, jpeg: bytes, now: float) -> None:
        if self.image_consent and (not 4 <= len(jpeg) <= MAX_IMAGE_BYTES or not jpeg.startswith(b"\xff\xd8")):
            raise ValueError("JPEG live invalide ou trop volumineux")
        self.samples.append((now, frame))
        self.purge(now)
        if self.image_consent and (
            not self.images or frame.timestamp_ms - self.images[-1].timestamp_ms >= IMAGE_INTERVAL_MS
        ):
            self.images.append(RecentImage(frame.sequence, frame.timestamp_ms, now, bytes(jpeg)))

    def info(self, session_id: str, now: float) -> dict:
        self.purge(now)
        frames = [entry[1] for entry in self.samples]
        first, last = (frames[0], frames[-1]) if frames else (None, None)
        return {
            "window_ref": f"{session_id}:live:{first.sequence}:{last.sequence}" if frames else f"{session_id}:live:empty",
            "start_timestamp_ms": int(first.timestamp_ms) if first else 0,
            "end_timestamp_ms": int(last.timestamp_ms) if last else 0,
            "sample_count": len(frames),
            "image_count": len(self.images),
            "latest_sample_age_ms": round(max(0, now - self.samples[-1][0]) * 1000) if frames else None,
        }

    def observation_samples(self) -> tuple[dict, ...]:
        observations = []
        for _, frame in self.samples:
            reason = frame.quality_reason
            # Le guide de rotation n'a pas d'angle : vérifier les repères plutôt
            # que de confondre absence d'angle et personne correctement suivie.
            if get_protocol(frame.protocol_id).mode == "guide_only" and reason is None:
                if any(point is None for point in selected_points(frame, frame.side)):
                    reason = "occlusion"
            observations.append({"sequence": frame.sequence, "timestamp_ms": frame.timestamp_ms,
                                 "angle_deg": frame_angle(frame), "quality_reason": reason})
        return tuple(observations)

    def clear(self) -> None:
        self.samples.clear()
        self.images.clear()
        self.image_consent = False
