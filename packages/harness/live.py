"""Observation technique bornée d'un instantané de capture, sans conclusion clinique.

Le modèle choisit un code vérifiable, jamais une phrase libre. Les images restent
dans l'appel local et ne figurent pas dans le résultat retourné au navigateur.
"""

import json
from base64 import b64encode
from dataclasses import dataclass
from math import isfinite
from typing import Callable

from packages.biomechanics.protocols import get_protocol
from packages.harness.runner import ChatClient


MAX_LIVE_SAMPLES = 25
MAX_IMAGE_BYTES = 1_000_000
MAX_ROUNDS = 4
MAX_TOOL_CALLS = 4
MAX_CONTENT_CHARS = 1024
OBSERVATION_TEXT = {
    "awaiting_frames": "En attente d’images de capture. Vue et stabilité à vérifier.",
    "pose_visible": "Repères disponibles sur cette fenêtre. Vue et stabilité à vérifier.",
    "tracking_lost": "Suivi indisponible sur cette fenêtre. Aucune mesure validée.",
    "tracking_partial": "Suivi partiel sur cette fenêtre. Vue et stabilité à vérifier.",
    "guide_only": "Observation guidée uniquement, sans angle calculé. Vue et stabilité à vérifier.",
}


@dataclass(frozen=True)
class LiveSnapshot:
    session_id: str
    window_ref: str
    protocol_id: str
    side: str
    start_timestamp_ms: int
    end_timestamp_ms: int
    samples: tuple[dict, ...]
    images: tuple[bytes, ...] = ()
    image_metadata: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        for identifier in (self.session_id, self.window_ref, self.protocol_id):
            if not isinstance(identifier, str) or not 1 <= len(identifier) <= 160:
                raise ValueError("invalid_snapshot_identifier")
        get_protocol(self.protocol_id)
        if self.side not in ("left", "right"):
            raise ValueError("invalid_snapshot_side")
        if (
            type(self.start_timestamp_ms) is not int
            or type(self.end_timestamp_ms) is not int
            or self.start_timestamp_ms < 0
            or self.end_timestamp_ms < self.start_timestamp_ms
        ):
            raise ValueError("invalid_snapshot_timestamps")
        if not isinstance(self.samples, tuple) or len(self.samples) > MAX_LIVE_SAMPLES:
            raise ValueError("invalid_snapshot_samples")
        copied_samples = []
        previous_sequence, previous_timestamp = -1, -1
        for sample in self.samples:
            if not isinstance(sample, dict) or set(sample) != {
                "sequence", "timestamp_ms", "angle_deg", "quality_reason"
            }:
                raise ValueError("invalid_snapshot_sample")
            sequence, timestamp = sample["sequence"], sample["timestamp_ms"]
            angle, reason = sample["angle_deg"], sample["quality_reason"]
            if (
                type(sequence) is not int
                or sequence <= previous_sequence
                or type(timestamp) is not int
                or timestamp <= previous_timestamp
                or not self.start_timestamp_ms <= timestamp <= self.end_timestamp_ms
                or (angle is not None and (
                    type(angle) not in (int, float) or not isfinite(angle) or not 0 <= angle <= 180
                ))
                or (reason is not None and (not isinstance(reason, str) or not 1 <= len(reason) <= 100))
            ):
                raise ValueError("invalid_snapshot_sample_value")
            copied_samples.append(dict(sample))
            previous_sequence, previous_timestamp = sequence, timestamp
        if not isinstance(self.images, tuple) or len(self.images) > 2:
            raise ValueError("invalid_snapshot_images")
        if any(
            not isinstance(image, bytes)
            or not image.startswith(b"\xff\xd8")
            or len(image) > MAX_IMAGE_BYTES
            for image in self.images
        ):
            raise ValueError("invalid_snapshot_image")
        if not isinstance(self.image_metadata, tuple) or (
            self.image_metadata and len(self.image_metadata) != len(self.images)
        ):
            raise ValueError("invalid_snapshot_image_metadata")
        sample_positions = {(sample["sequence"], sample["timestamp_ms"]) for sample in copied_samples}
        copied_metadata = []
        previous_sequence, previous_timestamp = -1, -1
        for metadata in self.image_metadata:
            if not isinstance(metadata, dict) or set(metadata) != {"sequence", "timestamp_ms"}:
                raise ValueError("invalid_snapshot_image_metadata")
            sequence, timestamp = metadata["sequence"], metadata["timestamp_ms"]
            if (
                type(sequence) is not int or type(timestamp) is not int
                or sequence <= previous_sequence or timestamp <= previous_timestamp
                or (sequence, timestamp) not in sample_positions
            ):
                raise ValueError("invalid_snapshot_image_metadata")
            copied_metadata.append(dict(metadata))
            previous_sequence, previous_timestamp = sequence, timestamp
        # Les valeurs admises sont scalaires : une copie de chaque dict suffit.
        object.__setattr__(self, "samples", tuple(copied_samples))
        object.__setattr__(self, "images", tuple(bytes(image) for image in self.images))
        object.__setattr__(self, "image_metadata", tuple(copied_metadata))


def _expected_code(snapshot: LiveSnapshot) -> str:
    if not snapshot.samples:
        return "awaiting_frames"
    if get_protocol(snapshot.protocol_id).mode == "guide_only":
        tracked = sum(
            sample["quality_reason"] in (None, "rotation_not_measurable_2d")
            for sample in snapshot.samples
        )
        if tracked == len(snapshot.samples):
            return "guide_only"
    else:
        tracked = sum(
            sample["angle_deg"] is not None and sample["quality_reason"] is None
            for sample in snapshot.samples
        )
        if tracked == len(snapshot.samples):
            return "pose_visible"
    return "tracking_partial" if tracked else "tracking_lost"


def _observation(snapshot: LiveSnapshot) -> dict:
    return {
        "window_ref": snapshot.window_ref,
        "protocol_id": snapshot.protocol_id,
        "side_requested": snapshot.side,
        "side_verified": False,
        "start_timestamp_ms": snapshot.start_timestamp_ms,
        "end_timestamp_ms": snapshot.end_timestamp_ms,
        "samples": [dict(sample) for sample in snapshot.samples],
        "supported_observation_code": _expected_code(snapshot),
        "view_is_valid": None,
        "camera_stable": None,
        "angle_status": "raw_unvalidated_2d_projection",
        "provisional": True,
        "requires_professional_review": True,
    }


def _tool_definitions(include_images: bool) -> list[dict]:
    descriptions = {
        "get_live_observation": "Lire uniquement les observations provisoires de la fenêtre courante.",
        "get_protocol_definition": "Lire la convention et les limites du protocole courant non validé.",
    }
    if include_images:
        descriptions["get_recent_capture_images"] = "Lire au plus deux JPEG de la fenêtre courante, avec consentement visuel."
    return [
        {"type": "function", "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        }}
        for name, description in descriptions.items()
    ]


def _tool_output(name: str, snapshot: LiveSnapshot) -> dict:
    if name == "get_live_observation":
        return _observation(snapshot)
    if name == "get_protocol_definition":
        protocol = get_protocol(snapshot.protocol_id)
        return {
            "window_ref": snapshot.window_ref,
            "protocol_id": protocol.id,
            "version": protocol.version,
            "required_view": protocol.view,
            "framing": protocol.framing,
            "mode": protocol.mode,
            "limitation": protocol.limitation,
            "clinical_validation": "not_established",
            "view_is_valid": None,
            "camera_stable": None,
            "side_verified": False,
        }
    raise ValueError("forbidden_tool")


def run_live_harness(
    snapshot: LiveSnapshot,
    client: ChatClient | None,
    allow_visual_evidence: bool = False,
    should_continue: Callable[[], bool] | None = None,
) -> dict:
    """Le repli reste une observation déterministe, séparée de toute mesure finale.

    Le client existant et sa configuration de modèles ne sont pas modifiés.
    Les bornes concernent les échanges, pas l'annulation du calcul serveur LLM.
    """
    # Revalider et recopier protège aussi d'une mutation des dicts de l'instantané.
    snapshot = LiveSnapshot(
        snapshot.session_id, snapshot.window_ref, snapshot.protocol_id, snapshot.side,
        snapshot.start_timestamp_ms, snapshot.end_timestamp_ms, snapshot.samples, snapshot.images,
        snapshot.image_metadata,
    )
    expected = _expected_code(snapshot)
    result = {
        "window_ref": snapshot.window_ref,
        "start_timestamp_ms": snapshot.start_timestamp_ms,
        "end_timestamp_ms": snapshot.end_timestamp_ms,
        "observation_code": expected,
        "text": OBSERVATION_TEXT[expected],
        "tool_names": [],
        "fallback_reason": "llm_unavailable" if client is None else None,
        "image_count": 0,
        "requires_professional_review": True,
        "provisional": True,
        "observation_source": "deterministic",
    }
    def continues() -> bool:
        if should_continue is None:
            return True
        try:
            return should_continue() is True
        except (PermissionError, ValueError):
            return False

    def cancelled() -> dict:
        result["fallback_reason"] = "cancelled"
        result["observation_source"] = "deterministic"
        return result

    if not continues():
        return cancelled()
    if client is None:
        return result
    visual_enabled = allow_visual_evidence is True and bool(snapshot.images)
    definitions = _tool_definitions(visual_enabled)
    allowed_names = {definition["function"]["name"] for definition in definitions}
    messages = [
        {"role": "system", "content": (
            "Tu observes une fenêtre de capture expérimentale, sans mesure validée, diagnostic, "
            "prescription ni exercice. La vue, la stabilité et le côté ne sont pas validés. "
            "Utilise uniquement les outils de lecture proposés, avec arguments {}. "
            "Réponds uniquement en JSON avec exactement window_ref, observation_code et "
            "requires_professional_review:true. Choisis exclusivement le supported_observation_code "
            "fourni par les observations. Ne produis aucun texte libre ni chiffre nouveau."
        )},
        {"role": "user", "content": json.dumps(_observation(snapshot), ensure_ascii=False)},
    ]
    call_ids = set()
    images_shared = False
    try:
        for _ in range(MAX_ROUNDS):
            if not continues():
                return cancelled()
            if images_shared:
                # Compter les images présentes dans une requête réellement tentée,
                # pas celles demandées au dernier tour sans échange suivant.
                result["image_count"] = len(snapshot.images)
            message = client.complete(messages, definitions)
            if not continues():
                return cancelled()
            if not isinstance(message, dict):
                raise ValueError("invalid_message")
            calls = message.get("tool_calls")
            if calls is None:
                calls = []
            if not isinstance(calls, list):
                raise ValueError("invalid_tool_calls")
            content = message.get("content")
            if content is not None and (not isinstance(content, str) or len(content) > MAX_CONTENT_CHARS):
                raise ValueError("invalid_content")
            if calls:
                if len(result["tool_names"]) + len(calls) > MAX_TOOL_CALLS:
                    raise ValueError("tool_limit")
                validated_calls = []
                for call in calls:
                    if (
                        not isinstance(call, dict)
                        or set(call) not in ({"id", "function"}, {"id", "type", "function"})
                        or call.get("type", "function") != "function"
                    ):
                        raise ValueError("invalid_tool_call")
                    call_id, function = call.get("id"), call.get("function")
                    if (
                        not isinstance(call_id, str) or not 1 <= len(call_id) <= 128
                        or call_id in call_ids or not isinstance(function, dict)
                        or set(function) != {"name", "arguments"}
                    ):
                        raise ValueError("invalid_tool_call")
                    name, arguments = function.get("name"), function.get("arguments")
                    if not isinstance(name, str) or name not in allowed_names:
                        raise ValueError("forbidden_tool")
                    if not isinstance(arguments, str) or len(arguments) > 512:
                        raise ValueError("invalid_tool_arguments")
                    parsed_arguments = json.loads(arguments)
                    if not isinstance(parsed_arguments, dict) or parsed_arguments != {}:
                        raise ValueError("forbidden_tool_arguments")
                    call_ids.add(call_id)
                    validated_calls.append((call_id, name))
                messages.append({"role": "assistant", "content": None, "tool_calls": calls})
                send_images = False
                for call_id, name in validated_calls:
                    result["tool_names"].append(name)
                    if name == "get_recent_capture_images":
                        image_refs = [f"{snapshot.window_ref}:image:{index}" for index in range(len(snapshot.images))]
                        messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps({
                            "window_ref": snapshot.window_ref,
                            "image_refs": image_refs,
                            "images": [
                                {"image_ref": image_ref, **(
                                    snapshot.image_metadata[index] if snapshot.image_metadata else {}
                                )}
                                for index, image_ref in enumerate(image_refs)
                            ],
                            "chronology_available": bool(snapshot.image_metadata),
                            "provisional": True,
                        })})
                        send_images = True
                    else:
                        messages.append({"role": "tool", "tool_call_id": call_id,
                                         "content": json.dumps(_tool_output(name, snapshot), ensure_ascii=False)})
                if send_images and not images_shared:
                    # Les parties image viennent après toutes les réponses d'outils,
                    # dans un message multimodal standard, jamais dans le résultat web.
                    parts = [{"type": "text", "text": "Images provisoires de " + snapshot.window_ref + ". Aucun constat clinique autorisé."}]
                    for index, image in enumerate(snapshot.images):
                        if snapshot.image_metadata:
                            parts.append({"type": "text", "text": json.dumps({
                                "image_ref": f"{snapshot.window_ref}:image:{index}",
                                **snapshot.image_metadata[index],
                            })})
                        parts.append({"type": "image_url", "image_url": {
                            "url": "data:image/jpeg;base64," + b64encode(image).decode("ascii")
                        }})
                    messages.append({"role": "user", "content": parts})
                    images_shared = True
                continue
            if not isinstance(content, str):
                raise ValueError("invalid_content")
            candidate = json.loads(content)
            if not isinstance(candidate, dict) or set(candidate) != {
                "window_ref", "observation_code", "requires_professional_review"
            }:
                raise ValueError("invalid_schema")
            if candidate["window_ref"] != snapshot.window_ref:
                raise ValueError("wrong_window_ref")
            if candidate["requires_professional_review"] is not True:
                raise ValueError("review_required")
            if not isinstance(candidate["observation_code"], str) or candidate["observation_code"] not in OBSERVATION_TEXT:
                raise ValueError("unknown_observation_code")
            if candidate["observation_code"] != expected:
                raise ValueError("incompatible_observation")
            if not continues():
                return cancelled()
            result["observation_source"] = "llm"
            return result
        raise ValueError("round_limit")
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, OSError, TimeoutError) as exc:
        if not continues():
            return cancelled()
        # Ne pas renvoyer un message d'exception externe : il pourrait contenir des
        # données de capture, une adresse locale ou du texte généré non contrôlé.
        result["fallback_reason"] = str(exc) if isinstance(exc, ValueError) and str(exc) in {
            "invalid_message", "invalid_tool_calls", "invalid_content", "tool_limit",
            "invalid_tool_call", "forbidden_tool", "invalid_tool_arguments", "forbidden_tool_arguments",
            "invalid_schema", "wrong_window_ref", "review_required", "unknown_observation_code",
            "incompatible_observation", "round_limit",
        } else "llm_error"
        return result
