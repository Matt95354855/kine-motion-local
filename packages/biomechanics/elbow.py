"""Évaluation expérimentale d'un essai synthétique de flexion du coude.

Les drapeaux de vue et de stabilité proviennent ici de données d'entrée ; leur
détection automatique et les seuils cliniques ne sont pas encore développés.
"""

from packages.biomechanics.geometry import apparent_elbow_flexion_deg
from packages.contracts.models import (
    ElbowTrial,
    Measurement,
    MeasurementSource,
    MeasurementStatus,
)

PROTOCOL_ID = "elbow_flexion_active"
PROTOCOL_VERSION = "0.1.0-dev"
PIPELINE_VERSION = "0.1.0-dev"


def assess_elbow_trial(trial: ElbowTrial) -> Measurement:
    """Renvoyer une valeur seulement si l'essai respecte les contrôles connus.

    Ce calcul sur des repères fournis n'est pas une validation de vidéo réelle.
    """

    def result(
        status: MeasurementStatus,
        value: float | None = None,
        reasons: tuple[str, ...] = (),
        evidence: tuple[str, ...] = (),
        valid_count: int = 0,
    ) -> Measurement:
        return Measurement(
            schema_version="1.0",
            measurement_id=f"{trial.trial_id}:apparent_elbow_flexion",
            session_id=trial.session_id,
            trial_id=trial.trial_id,
            protocol_id=PROTOCOL_ID,
            protocol_version=PROTOCOL_VERSION,
            pipeline_version=PIPELINE_VERSION,
            side=trial.side,
            value_deg=value,
            status=status,
            source=MeasurementSource.ALGORITHM,
            angle_convention="flexion_180_minus_internal",
            quality_reasons=reasons,
            evidence_refs=evidence,
            valid_frame_count=valid_count,
            total_frame_count=len(trial.frames),
        )

    if trial.stopped:
        return result(MeasurementStatus.REJECTED, reasons=("stopped",))
    if not trial.frames:
        return result(MeasurementStatus.NOT_PERFORMED, reasons=("not_performed",))

    if any(
        current.sequence <= previous.sequence
        or current.timestamp_ms <= previous.timestamp_ms
        for previous, current in zip(trial.frames, trial.frames[1:])
    ):
        return result(MeasurementStatus.REJECTED, reasons=("invalid_timestamps",))
    if any(frame.view_is_valid is None for frame in trial.frames):
        return result(MeasurementStatus.REJECTED, reasons=("view_unverified",))
    if any(frame.view_is_valid is False for frame in trial.frames):
        return result(MeasurementStatus.REJECTED, reasons=("out_of_plane",))
    if any(frame.camera_stable is None for frame in trial.frames):
        return result(MeasurementStatus.REJECTED, reasons=("camera_stability_unverified",))
    if any(frame.camera_stable is False for frame in trial.frames):
        return result(MeasurementStatus.REJECTED, reasons=("camera_moved",))

    accepted: list[tuple[float, int]] = []
    reasons: set[str] = set()
    for frame in trial.frames:
        if frame.shoulder is None or frame.elbow is None or frame.wrist is None:
            reasons.add("occlusion")
            continue
        try:
            angle = apparent_elbow_flexion_deg(
                frame.shoulder, frame.elbow, frame.wrist, frame.width_px, frame.height_px
            )
        except ValueError as exc:
            reasons.add("out_of_frame" if str(exc) == "Repère hors image" else "degenerate_landmarks")
            continue
        accepted.append((angle, frame.sequence))

    valid_count = len(accepted)
    if valid_count < 3:
        reasons.add("insufficient_frames")
    if valid_count / len(trial.frames) < 0.8:
        reasons.add("insufficient_coverage")
    if "insufficient_frames" in reasons or "insufficient_coverage" in reasons:
        return result(MeasurementStatus.REJECTED, reasons=tuple(sorted(reasons)), valid_count=valid_count)

    peak_angle, peak_sequence = max(accepted, key=lambda item: item[0])
    status = MeasurementStatus.LIMITED if reasons else MeasurementStatus.VALID
    return result(
        status,
        value=peak_angle,
        reasons=tuple(sorted(reasons)),
        evidence=(f"{trial.trial_id}:frame:{peak_sequence}",),
        valid_count=valid_count,
    )
