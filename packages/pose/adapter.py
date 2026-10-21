"""Interface de perception : aucun moteur externe n'est imposé au harness."""

from dataclasses import dataclass, field
from typing import Protocol

from packages.contracts.models import LandmarkDiagnostic, Point2D, copy_landmark_diagnostics


@dataclass(frozen=True)
class PoseObservation:
    width_px: int
    height_px: int
    shoulder: Point2D | None
    elbow: Point2D | None
    wrist: Point2D | None
    quality_reason: str | None = None
    landmarks: dict[str, Point2D | None] = field(default_factory=dict)
    landmark_diagnostics: dict[str, LandmarkDiagnostic] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "landmark_diagnostics", copy_landmark_diagnostics(self.landmark_diagnostics))


class PoseEngine(Protocol):
    def detect(self, jpeg_bytes: bytes, timestamp_ms: int, side: str) -> PoseObservation: ...

    def close(self) -> None: ...
