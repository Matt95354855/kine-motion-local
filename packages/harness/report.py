"""Brouillon déterministe : les nombres viennent des mesures structurées."""

from packages.contracts.models import Measurement, MeasurementStatus

REASON_LABELS = {
    "camera_moved": "caméra déplacée",
    "camera_stability_unverified": "stabilité de la caméra non vérifiée",
    "capture_interrupted": "capture interrompue ou couverture temporelle incomplète",
    "degenerate_landmarks": "repères géométriques invalides",
    "insufficient_coverage": "trop peu d'images exploitables",
    "insufficient_frames": "nombre d'images insuffisant",
    "invalid_timestamps": "horodatages incohérents",
    "not_performed": "mouvement non réalisé",
    "no_pose": "pose non retournée par le détecteur sur certaines images",
    "multiple_people": "plusieurs poses retournées par le détecteur",
    "occlusion": "repère requis indisponible ou sous le seuil de confiance du détecteur",
    "out_of_frame": "coordonnées d'un repère requis hors de l'image",
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
        lines.append(f"Angle apparent de flexion observé dans ce protocole : {value}° (pic brut 2D).")
        if measurement.status is MeasurementStatus.LIMITED:
            lines.append("Estimation limitée : elle requiert une vérification particulière.")

    if measurement.quality_reasons:
        labels = [REASON_LABELS.get(code, code) for code in measurement.quality_reasons]
        lines.append("Limites : " + ", ".join(labels) + ".")
    if measurement.evidence_refs:
        lines.append("Preuve : " + ", ".join(measurement.evidence_refs) + ".")
    lines.append("Aucune conclusion diagnostique ni proposition d'exercice automatique.")
    lines.append("La qualité du suivi ne juge pas la bonne exécution du geste.")
    lines.append("Revue et validation du kinésithérapeute requises.")
    return "\n".join(lines)


def render_capture_diagnostics(measurement: Measurement, motion: dict) -> str:
    """Décrire les images reçues, sans transformer un défaut de suivi en faute du geste."""
    robustness = motion.get("robustness") or {}
    lines = ["DIAGNOSTICS TECHNIQUES DU SUIVI", "Ces constats ne jugent pas l'exécution du geste."]
    if not robustness:
        lines.append("Contexte temporel détaillé indisponible pour cette version.")
        return "\n".join(lines)
    if measurement.protocol_id == "neck_rotation_guided":
        lines.append("Parcours guidé : absence d'angle attendue ; elle ne constitue pas à elle seule une perte de suivi.")
    else:
        usable = robustness["usable_frames"]
        unusable = robustness["unusable_frames"]
        lines.append(f"Angle calculable sur {usable}/{usable + unusable} images reçues ; {unusable} non exploitables.")
    for reason, count in sorted(robustness["invalid_reason_counts"].items()):
        if count:
            label = REASON_LABELS.get(reason, "limite technique non classée")
            lines.append(f"- {count} image(s) : {label}.")
    intervals = robustness["invalid_intervals"]
    for item in intervals:
        start = item["start_timestamp_ms"] / 1000
        end = item["end_timestamp_ms"] / 1000
        lines.append(f"- Suivi non exploitable : {start:.2f}–{end:.2f} s, {item['frame_count']} image(s).")
    if robustness.get("invalid_intervals_truncated"):
        lines.append("Liste des intervalles tronquée ; les comptes incluent toutes les images reçues.")
    peak = robustness.get("raw_peak")
    # Une mesure rejetée ne récupère jamais un nombre par le biais du résumé brut.
    if measurement.value_deg is not None and peak is not None:
        context = peak["temporal_context"]
        labels = {
            "isolated": "aucun voisin immédiatement adjacent exploitable dans la fenêtre technique",
            "before_only": "voisin immédiatement précédent exploitable uniquement",
            "after_only": "voisin immédiatement suivant exploitable uniquement",
            "before_and_after": "voisins immédiatement précédent et suivant exploitables",
        }
        lines.append("Contexte du pic brut : " + labels[context] + ".")
        lines.append(f"Fenêtre technique : écart maximal de {peak['neighbor_gap_limit_ms']} ms, sans franchir de trou de suivi.")
        for direction in ("before", "after"):
            neighbor = peak.get(direction)
            if neighbor:
                lines.append(f"Écart brut au voisin {'précédent' if direction == 'before' else 'suivant'} : {neighbor['delta_deg']:.1f}° en {neighbor['gap_ms']:.0f} ms.")
        lines.append("Des voisins exploitables ne valident ni le pic ni sa précision angulaire.")
    change = robustness.get("largest_adjacent_angle_change")
    if measurement.value_deg is not None and change is not None:
        lines.append(f"Plus grande variation brute entre voisins éligibles : {change['delta_deg']:+.1f}° en {change['gap_ms']:.0f} ms, de {change['start_timestamp_ms'] / 1000:.2f} à {change['end_timestamp_ms'] / 1000:.2f} s.")
        lines.append("Cette variation n'est pas classée comme erreur ou geste incorrect ; aucune limite biomécanique n'est appliquée.")
    lines.append("Précision angulaire non établie ; aucun lissage ni interpolation des pertes.")
    lines.append("Les images reçues ne prouvent pas que tout le mouvement a été capturé.")
    return "\n".join(lines)
