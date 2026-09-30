"""Contrats minimaux pour le protocole synthétique de flexion du coude.

Ces objets ne contiennent aucune identité patient et ne constituent pas un dossier clinique.
"""

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class MeasurementStatus(str, Enum):
    VALID = "valid"
    LIMITED = "limited"
    REJECTED = "rejected"
    NOT_PERFORMED = "not_performed"


class MeasurementSource(str, Enum):
    ALGORITHM = "algorithm"
    MANUAL = "manual"
    PATIENT_REPORTED = "patient_reported"


@dataclass(frozen=True)
class Point2D:
    """Coordonnées normalisées avant conversion dans les pixels de la capture."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not (isfinite(self.x) and isfinite(self.y)):
            raise ValueError("Les coordonnées doivent être finies")


@dataclass(frozen=True)
class PoseFrame:
    sequence: int
    timestamp_ms: float
    width_px: int
    height_px: int
    shoulder: Point2D | None
    elbow: Point2D | None
    wrist: Point2D | None
    view_is_valid: bool | None = None
    camera_stable: bool | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0 or not isfinite(self.timestamp_ms) or self.timestamp_ms < 0:
            raise ValueError("Séquence ou horodatage invalide")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("Dimensions de capture invalides")


@dataclass(frozen=True)
class ElbowTrial:
    trial_id: str
    session_id: str
    side: str
    frames: tuple[PoseFrame, ...]
    stopped: bool = False

    def __post_init__(self) -> None:
        if not self.trial_id or not self.session_id:
            raise ValueError("Les identifiants d'essai et de séance sont requis")
        if self.side not in ("left", "right"):
            raise ValueError("Le côté anatomique doit être explicite")


@dataclass(frozen=True)
class Measurement:
    schema_version: str
    measurement_id: str
    session_id: str
    trial_id: str
    protocol_id: str
    protocol_version: str
    pipeline_version: str
    side: str
    value_deg: float | None
    status: MeasurementStatus
    source: MeasurementSource
    angle_convention: str
    quality_reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    valid_frame_count: int
    total_frame_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.status, MeasurementStatus):
            raise ValueError("Statut de mesure invalide")
        if not isinstance(self.source, MeasurementSource):
            raise ValueError("Source de mesure invalide")
        if self.side not in ("left", "right"):
            raise ValueError("Côté anatomique invalide")
        if not self.measurement_id or not self.session_id or not self.trial_id:
            raise ValueError("Identifiants de provenance requis")
        if self.status in (MeasurementStatus.REJECTED, MeasurementStatus.NOT_PERFORMED):
            if self.value_deg is not None:
                raise ValueError("Une mesure rejetée ou non réalisée n'a pas de valeur")
            if not self.quality_reasons:
                raise ValueError("Le motif d'absence de valeur est requis")
        elif self.value_deg is None or not isfinite(self.value_deg) or not 0 <= self.value_deg <= 180:
            raise ValueError("Une mesure acceptée exige une valeur finie")
        if self.status is MeasurementStatus.VALID and self.quality_reasons:
            raise ValueError("Une mesure valide ne porte pas de réserve")
        if self.status is MeasurementStatus.LIMITED and not self.quality_reasons:
            raise ValueError("Une mesure limitée exige une raison")
        if not 0 <= self.valid_frame_count <= self.total_frame_count:
            raise ValueError("Nombre d'images incohérent")
