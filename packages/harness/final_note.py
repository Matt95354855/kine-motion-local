"""Note finale à vocabulaire fermé : le modèle ne fournit jamais le texte affiché.

Les faits admis proviennent exclusivement de la mesure de la séance autorisée.
Ils doivent être restitués intégralement ; leur ordre et leur formulation sont
fixés par l'application, indépendamment du modèle et des images éventuelles.
"""

import json

from packages.contracts.models import Measurement, MeasurementStatus


MAX_CONTENT_CHARS = 4096
STATUS_CODES = {
    MeasurementStatus.VALID: "measurement_recorded",
    MeasurementStatus.LIMITED: "measurement_limited",
    MeasurementStatus.REJECTED: "measurement_rejected",
    MeasurementStatus.NOT_PERFORMED: "movement_not_performed",
}
FACT_TEXT = {
    "measurement_recorded": "Mesure enregistrée par le pipeline, sans validation clinique.",
    "measurement_limited": "Estimation limitée, à vérifier par le professionnel.",
    "measurement_rejected": "Aucune valeur retenue pour cet essai.",
    "movement_not_performed": "Mouvement non réalisé, sans valeur mesurée.",
    "protocol_experimental": "Protocole expérimental, précision clinique non établie.",
    "camera_moved": "Caméra déplacée pendant la capture.",
    "camera_stability_unverified": "Stabilité de la caméra non vérifiée.",
    "capture_interrupted": "Capture interrompue ou couverture temporelle incomplète ; aucune valeur retenue.",
    "degenerate_landmarks": "Repères géométriques invalides.",
    "insufficient_coverage": "Trop peu d’images exploitables.",
    "insufficient_frames": "Nombre d’images insuffisant.",
    "invalid_timestamps": "Horodatages incohérents.",
    "not_performed": "Capture non réalisée.",
    "no_pose": "Le détecteur n’a pas retourné de pose sur certaines images de la capture.",
    "multiple_people": "Le détecteur a retourné plusieurs poses sur des images de la capture.",
    "occlusion": "Un repère requis est indisponible ou sous le seuil de confiance du détecteur sur certaines images.",
    "out_of_frame": "Repère hors du cadre sur des images de la capture.",
    "out_of_plane": "Mouvement hors du plan défini.",
    "stopped": "Essai interrompu.",
    "view_unverified": "Vue de capture non vérifiée.",
    "head_axis_proxy": "Orientation de la tête utilisée comme proxy, sans amplitude cervicale validée.",
    "camera_vertical_reference": "Référence verticale de la caméra non calibrée.",
    "rotation_not_measurable_2d": "Rotation observée sans angle calculé.",
    "quality_limitation_unclassified": "Une limite de qualité nécessite une vérification professionnelle.",
}
QUALITY_CODES = frozenset(FACT_TEXT) - frozenset(STATUS_CODES.values()) - {
    "protocol_experimental", "quality_limitation_unclassified"
}
REVIEW_TEXT = "Revue professionnelle requise ; note non validée."


class FinalNoteValidationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def supported_fact_codes(measurement: Measurement) -> tuple[str, ...]:
    """Ne jamais propager un motif libre ou un identifiant dans la note affichée."""
    reasons = set()
    for reason in measurement.quality_reasons:
        if reason == "experimental_protocol":
            continue  # Déjà présent dans toutes les notes de ce POC.
        reasons.add(reason if reason in QUALITY_CODES else "quality_limitation_unclassified")
    return (STATUS_CODES[measurement.status], "protocol_experimental", *sorted(reasons))


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    candidate = {}
    for key, value in pairs:
        if key in candidate:
            raise FinalNoteValidationError("duplicate_note_field")
        candidate[key] = value
    return candidate


def render_verified_note(content: object, measurement: Measurement) -> str:
    """Refuser toute réponse libre, incomplète ou contredisant la mesure courante."""
    if not isinstance(content, str) or not 1 <= len(content) <= MAX_CONTENT_CHARS:
        raise FinalNoteValidationError("invalid_note_content")
    candidate = json.loads(content, object_pairs_hook=_unique_object)
    if not isinstance(candidate, dict) or set(candidate) != {
        "measurement_ref", "fact_codes", "requires_professional_review"
    }:
        raise FinalNoteValidationError("invalid_note_schema")
    if not isinstance(candidate["measurement_ref"], str) or candidate["measurement_ref"] != measurement.measurement_id:
        raise FinalNoteValidationError("measurement_ref_mismatch")
    if candidate["requires_professional_review"] is not True:
        raise FinalNoteValidationError("review_required")
    codes = candidate["fact_codes"]
    if not isinstance(codes, list) or not 1 <= len(codes) <= len(FACT_TEXT):
        raise FinalNoteValidationError("invalid_fact_codes")
    if any(not isinstance(code, str) or code not in FACT_TEXT for code in codes):
        raise FinalNoteValidationError("unknown_fact_code")
    if len(codes) != len(set(codes)):
        raise FinalNoteValidationError("duplicate_fact_code")
    expected = supported_fact_codes(measurement)
    if set(codes) != set(expected):
        raise FinalNoteValidationError("unsupported_fact_set")
    # Aucun texte ni ordre fourni par le modèle n'est utilisé dans ce résultat.
    return " ".join([*(FACT_TEXT[code] for code in expected), REVIEW_TEXT])
