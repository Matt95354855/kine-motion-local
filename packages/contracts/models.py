"""Contrats de capture POC ; compatibilité conservée avec le protocole du coude.

Ces objets ne contiennent aucune identité patient et ne constituent pas un dossier clinique.
"""

from dataclasses import dataclass, field
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
class LandmarkDiagnostic:
    """Scores techniques du détecteur, jamais une précision angulaire calibrée.

    `accepted` décrit seulement la conservation du point après les contrôles
    de finitude et les seuils existants. Un point hors image reste conservé à ce
    stade ; son rejet géométrique se fait ensuite, comme avant ce diagnostic.
    Aucun score non fini ni texte arbitraire n'entre dans la sérialisation.
    """

    visibility: float | None = None
    presence: float | None = None
    visibility_threshold: float = 0.5
    presence_threshold: float = 0.5
    accepted: bool = False
    reason: str = "missing_landmark"
    coordinate_status: str = "missing"
    non_finite_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for score in (self.visibility, self.presence):
            if score is not None and (type(score) not in (int, float) or not isfinite(score)):
                raise ValueError("Score de repère fini ou absent requis")
        for threshold in (self.visibility_threshold, self.presence_threshold):
            if type(threshold) not in (int, float) or not isfinite(threshold) or not 0 <= threshold <= 1:
                raise ValueError("Seuil de repère fini dans [0, 1] requis")
        if type(self.accepted) is not bool or not isinstance(self.reason, str) or self.reason not in {
            "accepted", "missing_landmark", "non_finite_input", "low_visibility",
            "low_presence", "low_visibility_and_presence",
        }:
            raise ValueError("Décision technique de repère invalide")
        if self.accepted != (self.reason == "accepted"):
            raise ValueError("Décision et motif de repère incohérents")
        if not isinstance(self.coordinate_status, str) or self.coordinate_status not in {"in_frame", "out_of_frame", "non_finite", "missing"}:
            raise ValueError("État des coordonnées invalide")
        if (
            not isinstance(self.non_finite_fields, tuple)
            or len(self.non_finite_fields) > 4
            or any(not isinstance(name, str) or name not in {"visibility", "presence", "x", "y"}
                   for name in self.non_finite_fields)
            or len(set(self.non_finite_fields)) != len(self.non_finite_fields)
        ):
            raise ValueError("Champs non finis de repère invalides")
        if self.accepted and (
            self.non_finite_fields or self.coordinate_status not in {"in_frame", "out_of_frame"}
            or self.visibility is None or self.presence is None
            or self.visibility < self.visibility_threshold or self.presence < self.presence_threshold
        ):
            raise ValueError("Diagnostic accepté incohérent")


def copy_landmark_diagnostics(value: dict[str, LandmarkDiagnostic]) -> dict[str, LandmarkDiagnostic]:
    """Copie bornée pour les adaptateurs existants et futurs, sans média brut."""
    if not isinstance(value, dict) or len(value) > 33:
        raise ValueError("Diagnostics de repères hors limite")
    for name, diagnostic in value.items():
        if (
            not isinstance(name, str) or not 1 <= len(name) <= 64 or not name.isidentifier()
            or not isinstance(diagnostic, LandmarkDiagnostic)
        ):
            raise ValueError("Diagnostic de repère invalide")
    return dict(value)


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
    quality_reason: str | None = None
    landmarks: dict[str, Point2D | None] = field(default_factory=dict)
    protocol_id: str = "elbow_flexion_active"
    side: str = "left"
    landmark_diagnostics: dict[str, LandmarkDiagnostic] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence < 0 or not isfinite(self.timestamp_ms) or self.timestamp_ms < 0:
            raise ValueError("Séquence ou horodatage invalide")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("Dimensions de capture invalides")
        object.__setattr__(self, "landmark_diagnostics", copy_landmark_diagnostics(self.landmark_diagnostics))


@dataclass(frozen=True)
class ElbowTrial:
    trial_id: str
    session_id: str
    side: str
    frames: tuple[PoseFrame, ...]
    stopped: bool = False
    interruption_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.trial_id or not self.session_id:
            raise ValueError("Les identifiants d'essai et de séance sont requis")
        if self.side not in ("left", "right"):
            raise ValueError("Le côté anatomique doit être explicite")
        if self.interruption_reason not in (None, "capture_interrupted"):
            raise ValueError("Motif d'interruption de capture invalide")


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
