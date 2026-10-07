"""Catalogue POC : projections 2D descriptives, jamais des examens diagnostiques.

Les noms de repères sont anatomiques, indépendants du miroir de l'aperçu.
Les nouveaux protocoles restent systématiquement « limited », même sur des
repères parfaits. La direction demandée n'est pas vérifiée automatiquement.
"""

from dataclasses import asdict, dataclass
from math import atan2, degrees, hypot

from packages.biomechanics.elbow import assess_elbow_trial
from packages.biomechanics.geometry import internal_angle_deg, normalized_to_pixel
from packages.contracts.models import ElbowTrial, Measurement, MeasurementSource, MeasurementStatus, Point2D, PoseFrame


@dataclass(frozen=True)
class MovementProtocol:
    id: str
    label: str
    view: str
    framing: str
    metric_label: str
    mode: str
    points: tuple[str, ...]
    guide: str
    side_kind: str = "anatomical"
    version: str = "0.1.0-dev"
    limitation: str = "Projection 2D expérimentale ; ce n'est pas une amplitude articulaire clinique."

    def names(self, side: str) -> tuple[str, ...]:
        return tuple(name.format(side=side) for name in self.points)


PROTOCOLS = {
    item.id: item for item in (
        MovementProtocol("elbow_flexion_active", "Coude · flexion", "profil", "Épaule, coude et poignet visibles",
                         "Flexion apparente", "flexion", ("{side}_shoulder", "{side}_elbow", "{side}_wrist"), "elbow"),
        MovementProtocol("knee_flexion_active", "Genou · flexion", "profil", "Hanche, genou et cheville visibles",
                         "Flexion apparente", "flexion", ("{side}_hip", "{side}_knee", "{side}_ankle"), "knee"),
        MovementProtocol("shoulder_abduction_active", "Épaule · élévation latérale", "face", "Tronc et bras entier visibles",
                         "Élévation apparente", "internal", ("{side}_elbow", "{side}_shoulder", "{side}_hip"), "shoulder"),
        MovementProtocol("hip_flexion_active", "Hanche · flexion", "profil", "Épaule, hanche et genou visibles",
                         "Flexion apparente", "flexion", ("{side}_shoulder", "{side}_hip", "{side}_knee"), "hip"),
        MovementProtocol("trunk_lateral_inclination", "Tronc · inclinaison latérale", "face", "Deux épaules et bassin visibles",
                         "Inclinaison projetée", "vertical", ("left_shoulder", "right_shoulder", "left_hip", "right_hip"),
                         "trunk", "direction", limitation="Axe épaules-bassin relatif à la verticale de l'image ; caméra droite requise, pas une mesure rachidienne."),
        MovementProtocol("neck_lateral_inclination", "Cou · inclinaison latérale", "face", "Deux oreilles et deux épaules visibles",
                         "Inclinaison tête / épaules", "axes", ("left_ear", "right_ear", "left_shoulder", "right_shoulder"),
                         "neck_tilt", "direction", limitation="Proxy : axe des oreilles relatif à l'axe des épaules. Ce n'est pas l'amplitude cervicale ; perspective et occlusions non corrigées."),
        MovementProtocol("neck_rotation_guided", "Cou · rotation guidée", "face", "Tête et épaules visibles",
                         "Observation guidée · sans angle", "guide_only", ("left_ear", "right_ear", "left_shoulder", "right_shoulder"),
                         "neck_turn", "direction", limitation="Rotation cervicale hors du plan de l'image : aucun angle ni amplitude calculés en 2D."),
    )
}


def get_protocol(protocol_id: str) -> MovementProtocol:
    try:
        return PROTOCOLS[protocol_id]
    except (KeyError, TypeError) as exc:
        raise ValueError("Protocole inconnu") from exc


def protocol_catalog() -> list[dict]:
    return [{**asdict(item), "quantified": item.mode != "guide_only",
             "harness_supported": item.id == "elbow_flexion_active"} for item in PROTOCOLS.values()]


def selected_points(frame: PoseFrame, side: str) -> tuple[Point2D | None, ...]:
    protocol = get_protocol(frame.protocol_id)
    # Compatibilité avec les anciens adaptateurs du coude uniquement.
    if not frame.landmarks and protocol.id == "elbow_flexion_active":
        return frame.shoulder, frame.elbow, frame.wrist
    return tuple(frame.landmarks.get(name) for name in protocol.names(side))


def angle_and_reason(frame: PoseFrame, side: str = "left") -> tuple[float | None, str | None]:
    if frame.quality_reason:
        return None, frame.quality_reason
    protocol = get_protocol(frame.protocol_id)
    if protocol.mode == "guide_only":
        return None, "rotation_not_measurable_2d"
    points = selected_points(frame, side)
    if any(p is None for p in points):
        return None, "occlusion"
    try:
        pixels = [normalized_to_pixel(p, frame.width_px, frame.height_px) for p in points]
        if protocol.mode in ("flexion", "internal"):
            value = internal_angle_deg(*pixels)
            return (180.0 - value if protocol.mode == "flexion" else value), None
        a, b, c, d = pixels
        if protocol.mode == "vertical":
            dx, dy = (a[0] + b[0] - c[0] - d[0]) / 2, (a[1] + b[1] - c[1] - d[1]) / 2
            if hypot(dx, dy) < 1e-6:
                raise ValueError("Segment dégénéré")
            return degrees(atan2(abs(dx), -dy)), None
        # Deux axes orientés gauche -> droite : correction de l'aspect en pixels.
        u, v = (b[0] - a[0], b[1] - a[1]), (d[0] - c[0], d[1] - c[1])
        if hypot(*u) < 1e-6 or hypot(*v) < 1e-6:
            raise ValueError("Segment dégénéré")
        return degrees(atan2(abs(u[0] * v[1] - u[1] * v[0]), u[0] * v[0] + u[1] * v[1])), None
    except ValueError as exc:
        return None, "out_of_frame" if str(exc) == "Repère hors image" else "degenerate_landmarks"


def assess_trial(trial: ElbowTrial, protocol_id: str) -> Measurement:
    protocol = get_protocol(protocol_id)
    if protocol_id == "elbow_flexion_active":
        return assess_elbow_trial(trial)

    def result(status, value=None, reasons=(), evidence=(), count=0):
        return Measurement("1.0", f"{trial.trial_id}:{protocol_id}", trial.session_id, trial.trial_id,
                           protocol_id, protocol.version, "0.3.0-dev", trial.side, value, status,
                           MeasurementSource.ALGORITHM, protocol.mode + "_2d_projection",
                           reasons, evidence, count, len(trial.frames))

    if trial.interruption_reason is not None:
        return result(MeasurementStatus.REJECTED, reasons=(trial.interruption_reason,))
    if trial.stopped:
        return result(MeasurementStatus.REJECTED, reasons=("stopped",))
    if not trial.frames:
        return result(MeasurementStatus.NOT_PERFORMED, reasons=("not_performed",))
    if protocol.mode == "guide_only":
        reasons = {"rotation_not_measurable_2d"} | {f.quality_reason for f in trial.frames if f.quality_reason}
        return result(MeasurementStatus.REJECTED, reasons=tuple(sorted(reasons)))
    for previous, current in zip(trial.frames, trial.frames[1:]):
        if current.sequence <= previous.sequence or current.timestamp_ms <= previous.timestamp_ms:
            return result(MeasurementStatus.REJECTED, reasons=("invalid_timestamps",))
    checks = (("view_is_valid", "view_unverified", "out_of_plane"),
              ("camera_stable", "camera_stability_unverified", "camera_moved"))
    for attribute, unverified, invalid in checks:
        if any(getattr(frame, attribute) is None for frame in trial.frames):
            return result(MeasurementStatus.REJECTED, reasons=(unverified,))
        if any(getattr(frame, attribute) is False for frame in trial.frames):
            return result(MeasurementStatus.REJECTED, reasons=(invalid,))
    if any(frame.quality_reason == "multiple_people" for frame in trial.frames):
        return result(MeasurementStatus.REJECTED, reasons=("multiple_people",))
    accepted, reasons = [], set()
    for frame in trial.frames:
        if frame.protocol_id != protocol_id:
            raise ValueError("Protocole de l'image incohérent")
        angle, reason = angle_and_reason(frame, trial.side)
        if reason:
            reasons.add(reason)
        elif angle is not None:
            accepted.append((angle, frame.sequence))
    if len(accepted) < 3:
        reasons.add("insufficient_frames")
    if len(accepted) / len(trial.frames) < 0.8:
        reasons.add("insufficient_coverage")
    if "insufficient_frames" in reasons or "insufficient_coverage" in reasons:
        return result(MeasurementStatus.REJECTED, reasons=tuple(sorted(reasons)), count=len(accepted))
    reasons.add("experimental_protocol")
    if protocol.mode == "axes":
        reasons.add("head_axis_proxy")
    if protocol.mode == "vertical":
        reasons.add("camera_vertical_reference")
    peak, sequence = max(accepted, key=lambda item: item[0])
    return result(MeasurementStatus.LIMITED, peak, tuple(sorted(reasons)),
                  (f"{trial.trial_id}:frame:{sequence}",), len(accepted))


def render_protocol_draft(measurement: Measurement) -> str:
    # Le harness du coude reste strictement inchangé.
    from packages.harness.report import REASON_LABELS, render_draft
    if measurement.protocol_id == "elbow_flexion_active":
        return render_draft(measurement)
    protocol = get_protocol(measurement.protocol_id)
    labels = {**REASON_LABELS, "experimental_protocol": "protocole non validé",
              "head_axis_proxy": "proxy d'orientation de la tête, pas une amplitude cervicale",
              "camera_vertical_reference": "référence verticale de la caméra non calibrée",
              "rotation_not_measurable_2d": "rotation non quantifiée en 2D"}
    side = "gauche" if measurement.side == "left" else "droite"
    result = "Aucune valeur publiée." if measurement.value_deg is None else f"{protocol.metric_label} : {measurement.value_deg:.1f}° (pic brut observé)."
    return "\n".join(("COMPTE RENDU — BROUILLON NON VALIDÉ", f"Protocole : {protocol.label} ({protocol.version})",
                      f"Séance : {measurement.session_id}",
                      f"Côté/direction demandé(e) : {side} ; non vérifié(e) automatiquement.", result,
                      protocol.limitation, "Limites : " + ", ".join(labels.get(r, r) for r in measurement.quality_reasons),
                      "Preuve : " + (", ".join(measurement.evidence_refs) or "aucune"),
                      "La qualité du suivi ne juge pas la bonne exécution du geste.",
                      "Aucun diagnostic ni prescription ; revue professionnelle requise."))
