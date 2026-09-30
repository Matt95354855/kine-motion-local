"""Moteur de démonstration : ignore les pixels et génère une pose fictive."""

from math import sin

from packages.contracts.models import Point2D
from packages.pose.adapter import PoseObservation


class SyntheticPoseEngine:
    def detect(self, jpeg_bytes: bytes, timestamp_ms: int, side: str) -> PoseObservation:
        # Ce moteur sert seulement à vérifier le transport et le parcours UI.
        bend = abs(sin(timestamp_ms / 600.0))
        wrist = Point2D(0.5 + 0.18 * bend, 0.75 - 0.25 * bend)
        return PoseObservation(
            width_px=640,
            height_px=480,
            shoulder=Point2D(0.5, 0.25),
            elbow=Point2D(0.5, 0.5),
            wrist=wrist,
        )

    def close(self) -> None:
        pass
