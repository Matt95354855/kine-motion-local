"""Outils de lecture autorisés pour la séance courante uniquement."""

from base64 import b64encode
from dataclasses import asdict, dataclass
from typing import Callable

from packages.contracts.models import Measurement
from packages.harness.final_note import supported_fact_codes
from packages.harness.report import render_draft


@dataclass(frozen=True)
class ToolContext:
    session_id: str
    measurement: Measurement
    keyframe_jpeg: bytes | None = None

    def __post_init__(self) -> None:
        if self.measurement.session_id != self.session_id:
            raise ValueError("La mesure ne correspond pas à la séance autorisée")
        if self.keyframe_jpeg is not None and (
            not self.measurement.evidence_refs or len(self.keyframe_jpeg) > 1_000_000
        ):
            raise ValueError("Image de preuve absente ou trop volumineuse")


ToolHandler = Callable[[ToolContext], dict[str, object]]


class ToolRegistry:
    """N'expose que les fonctions explicitement enregistrées par l'application.

    Le modèle ne choisit ni l'identifiant de séance ni un chemin de fichier.
    Les outils futurs seront branchés par code via `register_read_only`.
    """

    def __init__(self, include_visual_evidence: bool = False) -> None:
        self._handlers: dict[str, tuple[str, ToolHandler]] = {}
        self.register_read_only(
            "get_session_measurements",
            "Lire la mesure structurée et son statut pour la séance courante.",
            lambda context: {"measurements": [asdict(context.measurement)]},
        )
        self.register_read_only(
            "get_capture_observation",
            "Lire la qualité et les références des images de la séance courante, sans vidéo brute.",
            lambda context: {
                "measurement_ref": context.measurement.measurement_id,
                "supported_fact_codes": list(supported_fact_codes(context.measurement)),
                "trial_id": context.measurement.trial_id,
                "quality_reasons": list(context.measurement.quality_reasons),
                "valid_frame_count": context.measurement.valid_frame_count,
                "total_frame_count": context.measurement.total_frame_count,
                "evidence_refs": list(context.measurement.evidence_refs),
            },
        )
        self.register_read_only(
            "get_protocol_definition",
            "Lire la convention expérimentale du protocole actif.",
            lambda context: {
                "protocol_id": context.measurement.protocol_id,
                "version": context.measurement.protocol_version,
                "angle_convention": context.measurement.angle_convention,
                "clinical_validation": "not_established",
            },
        )
        self.register_read_only(
            "assemble_report_draft",
            "Lire le brouillon déterministe sans le valider ni le publier.",
            lambda context: {"draft": render_draft(context.measurement)},
        )
        if include_visual_evidence:
            self.register_read_only(
                "get_capture_keyframe",
                "Lire une seule image JPEG de preuve de la séance courante pour un modèle visuel local.",
                self._keyframe,
            )

    @staticmethod
    def _keyframe(context: ToolContext) -> dict[str, object]:
        if context.keyframe_jpeg is None:
            raise ValueError("Aucune image de preuve disponible")
        return {
            "evidence_ref": context.measurement.evidence_refs[0],
            "image_url": "data:image/jpeg;base64," + b64encode(context.keyframe_jpeg).decode("ascii"),
        }

    def register_read_only(self, name: str, description: str, handler: ToolHandler) -> None:
        if not name.isidentifier() or name.startswith("_") or name in self._handlers:
            raise ValueError("Nom d'outil invalide ou déjà enregistré")
        if not description or not callable(handler):
            raise ValueError("Description et fonction de lecture requises")
        self._handlers[name] = (description, handler)

    def definitions(self) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": definition[0],
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            }
            for name, definition in self._handlers.items()
        ]

    def call(self, name: str, arguments: object, context: ToolContext) -> dict[str, object]:
        if name not in self._handlers:
            raise ValueError("Outil non autorisé")
        if arguments != {}:
            raise ValueError("Cet outil n'accepte aucun argument du modèle")
        return self._handlers[name][1](context)
