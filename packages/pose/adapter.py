"""Interface de perception : aucun moteur externe n'est imposé au harness."""

from dataclasses import dataclass
from typing import Protocol

from packages.contracts.models import Point2D


@dataclass(frozen=True)
class PoseObservation:
    width_px: int
    height_px: int
    shoulder: Point2D | None
    elbow: Point2D | None
    wrist: Point2D | None
    quality_reason: str | None = None


class PoseEngine(Protocol):
    def detect(self, jpeg_bytes: bytes, timestamp_ms: int, side: str) -> PoseObservation: ...

    def close(self) -> None: ...
