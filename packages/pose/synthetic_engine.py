"""Moteur de démonstration : ignore les pixels et génère une pose fictive."""

from math import sin

from packages.contracts.models import Point2D
from packages.pose.adapter import PoseObservation


class SyntheticPoseEngine:
    def detect(self, jpeg_bytes: bytes, timestamp_ms: int, side: str) -> PoseObservation:
        # Ce moteur sert seulement à vérifier le transport et le parcours UI.
        bend = abs(sin(timestamp_ms / 600.0))
        wrist = Point2D(0.5 + 0.18 * bend, 0.75 - 0.25 * bend)
        landmarks = {}
        for name, offset in (("left", -0.04), ("right", 0.04)):
            landmarks.update({
                f"{name}_ear": Point2D(0.5 + offset, 0.13 + offset * bend),
                f"{name}_shoulder": Point2D(0.5 + offset, 0.25),
                f"{name}_elbow": Point2D(0.5 + offset, 0.5),
                f"{name}_wrist": Point2D(wrist.x + offset, wrist.y),
                f"{name}_hip": Point2D(0.5 + offset, 0.57),
                f"{name}_knee": Point2D(0.5 + offset + 0.1 * bend, 0.75),
                f"{name}_ankle": Point2D(0.5 + offset, 0.94 - 0.12 * bend),
            })
        return PoseObservation(
            width_px=640,
            height_px=480,
            shoulder=Point2D(0.5, 0.25),
            elbow=Point2D(0.5, 0.5),
            wrist=wrist,
            landmarks=landmarks,
        )

    def close(self) -> None:
        pass
