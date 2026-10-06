"""Harness borné : outils explicites, sortie vérifiée et repli déterministe."""

import json
from dataclasses import dataclass
from typing import Protocol

from packages.harness.final_note import render_verified_note, supported_fact_codes
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
                "Tu restitues uniquement les faits techniques de la mesure courante pour revue par un kiné. "
                "Utilise les outils de lecture de la séance avec arguments {}. "
                "Ne déduis aucun diagnostic, exercice, dosage, chiffre ni fait depuis une image. "
                "Réponds uniquement en JSON avec exactement measurement_ref, fact_codes et "
                "requires_professional_review:true. Recopie intégralement supported_fact_codes, "
                "sans ajout, omission ni doublon. Ne produis aucun texte libre. "
                "L'application fixe seule la formulation de la note et ne valide aucune conclusion clinique."
            ),
        },
        {"role": "user", "content": json.dumps({
            "measurement_ref": context.measurement.measurement_id,
            "supported_fact_codes": supported_fact_codes(context.measurement),
        }, ensure_ascii=False)},
    ]
    used: list[str] = []
    try:
        if visual_enabled:
            evidence = registry.call("get_capture_keyframe", {}, context)
            messages[-1]["content"] = [
                {"type": "text", "text": messages[-1]["content"] + "\nImage de preuve disponible pour revue ; "
                 "ne déduis aucun fait nouveau et restitue uniquement les codes de la mesure."},
                {"type": "image_url", "image_url": {"url": evidence["image_url"]}},
            ]
            used.append("get_capture_keyframe")
        for _ in range(4):
            message = client.complete(messages, registry.definitions())
            if not isinstance(message, dict):
                raise ValueError("invalid_message")
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

            note = render_verified_note(message["content"], context.measurement)
            return HarnessResult(draft, note, tuple(used), None)
        raise ValueError("round_limit")
    except (KeyError, TypeError, IndexError, AttributeError, RecursionError, ValueError, OSError, TimeoutError) as exc:
        return HarnessResult(draft, None, tuple(used), getattr(exc, "code", type(exc).__name__))
