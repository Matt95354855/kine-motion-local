"""Brouillon déterministe : les nombres viennent des mesures structurées."""

from packages.contracts.models import Measurement, MeasurementStatus

REASON_LABELS = {
    "camera_moved": "caméra déplacée",
    "camera_stability_unverified": "stabilité de la caméra non vérifiée",
    "degenerate_landmarks": "repères géométriques invalides",
    "insufficient_coverage": "trop peu d'images exploitables",
    "insufficient_frames": "nombre d'images insuffisant",
    "invalid_timestamps": "horodatages incohérents",
    "not_performed": "mouvement non réalisé",
    "occlusion": "repère masqué",
    "out_of_frame": "repère hors du cadre",
    "out_of_plane": "mouvement hors du plan défini",
    "stopped": "essai interrompu",
    "view_unverified": "vue de capture non vérifiée",
}


def render_draft(measurement: Measurement) -> str:
    if measurement.protocol_id != "elbow_flexion_active":
        raise ValueError("Ce gabarit attend la flexion active du coude")
    side = "gauche" if measurement.side == "left" else "droit"
    lines = [
        "COMPTE RENDU — BROUILLON NON VALIDÉ",
        f"Séance : {measurement.session_id}",
        f"Protocole : flexion active du coude {side} ({measurement.protocol_version})",
        "Protocole expérimental ; précision clinique non établie.",
    ]

    if measurement.status is MeasurementStatus.NOT_PERFORMED:
        lines.append("Résultat : mouvement non réalisé ; aucune valeur mesurée.")
    elif measurement.status is MeasurementStatus.REJECTED:
        lines.append("Résultat : non mesurable sur cet essai ; aucune valeur publiée.")
    else:
        value = f"{measurement.value_deg:.1f}".replace(".", ",")
        lines.append(f"Angle apparent de flexion observé dans ce protocole : {value}°.")
        if measurement.status is MeasurementStatus.LIMITED:
            lines.append("Estimation limitée : elle requiert une vérification particulière.")

    if measurement.quality_reasons:
        labels = [REASON_LABELS.get(code, code) for code in measurement.quality_reasons]
        lines.append("Limites : " + ", ".join(labels) + ".")
    if measurement.evidence_refs:
        lines.append("Preuve : " + ", ".join(measurement.evidence_refs) + ".")
    lines.append("Aucune conclusion diagnostique ni proposition d'exercice automatique.")
    lines.append("Revue et validation du kinésithérapeute requises.")
    return "\n".join(lines)
