"""Harness borné : outils explicites, sortie vérifiée et repli déterministe."""

import json
from dataclasses import dataclass
from typing import Protocol

from packages.harness.report import render_draft
from packages.harness.tools import ToolContext, ToolRegistry


class ChatClient(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> dict: ...


@dataclass(frozen=True)
class HarnessResult:
    deterministic_draft: str
    proposed_note: str | None
    tool_names: tuple[str, ...]
    fallback_reason: str | None


def run_harness(
    context: ToolContext,
    client: ChatClient | None,
    registry: ToolRegistry | None = None,
    allow_visual_evidence: bool = False,
) -> HarnessResult:
    """La note du LLM reste distincte du compte rendu et attend la revue humaine."""
    draft = render_draft(context.measurement)
    if client is None:
        return HarnessResult(draft, None, (), "llm_unavailable")

    visual_enabled = allow_visual_evidence and context.keyframe_jpeg is not None
    registry = registry or ToolRegistry(include_visual_evidence=visual_enabled)
    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "Tu prépares uniquement une courte note descriptive en français pour revue par un kiné. "
                "Utilise les outils de la séance. Ne déduis aucun diagnostic, exercice, dosage ou chiffre. "
                "Réponds en JSON: {\"measurement_ref\": \"...\", \"text\": \"...\", "
                "\"requires_professional_review\": true}. Le texte ne doit contenir aucun nombre."
            ),
        },
        {"role": "user", "content": "Décris les limites observées pour la mesure de la séance courante."},
    ]
    used: list[str] = []
    try:
        if visual_enabled:
            evidence = registry.call("get_capture_keyframe", {}, context)
            messages[-1]["content"] = [
                {"type": "text", "text": "Image de preuve " + str(evidence["evidence_ref"]) + ". Décris seulement ce qui est visible."},
                {"type": "image_url", "image_url": {"url": evidence["image_url"]}},
            ]
            used.append("get_capture_keyframe")
        for _ in range(4):
            message = client.complete(messages, registry.definitions())
            calls = message.get("tool_calls") or []
            if calls:
                if len(used) + len(calls) > 4:
                    raise ValueError("tool_limit")
                messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
                for call in calls:
                    name = call["function"]["name"]
                    args = json.loads(call["function"]["arguments"])
                    output = registry.call(name, args, context)
                    used.append(name)
                    if name == "get_capture_keyframe":
                        content = [
                            {"type": "text", "text": str(output["evidence_ref"])},
                            {"type": "image_url", "image_url": {"url": output["image_url"]}},
                        ]
                    else:
                        content = json.dumps(output, ensure_ascii=False)
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
                continue

            candidate = json.loads(message["content"])
            if not isinstance(candidate, dict) or set(candidate) != {
                "measurement_ref", "text", "requires_professional_review"
            }:
                raise ValueError("invalid_schema")
            note = candidate["text"]
            if (
                candidate["measurement_ref"] != context.measurement.measurement_id
                or candidate["requires_professional_review"] is not True
                or not isinstance(note, str)
                or not 1 <= len(note) <= 500
                or any(character.isdigit() for character in note)
            ):
                raise ValueError("invalid_claim")
            return HarnessResult(draft, note, tuple(used), None)
        raise ValueError("round_limit")
    except (KeyError, TypeError, IndexError, ValueError, OSError, TimeoutError) as exc:
        return HarnessResult(draft, None, tuple(used), type(exc).__name__)
