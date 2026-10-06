"""Budget partagé et révocation d'un travail d'inférence local.

Le contrôle est créé une seule fois par travail, puis partagé entre ses tours.
Une annulation locale ne garantit pas l'arrêt de la génération sur le serveur.
"""

import math
from threading import Event
from time import monotonic
from typing import Callable


class InferenceCancelled(TimeoutError):
    code = "inference_cancelled"


class InferenceDeadlineExceeded(TimeoutError):
    code = "inference_deadline_exceeded"


class InferenceControl:
    """Le callback de révocation doit rester court et ne pas attendre un calcul."""

    def __init__(
        self,
        timeout_seconds: float = 10.0,
        clock: Callable[[], float] = monotonic,
        should_continue: Callable[[], bool] | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Un budget d'inférence positif et fini est requis")
        self._clock = clock
        self._deadline = clock() + timeout_seconds
        self._should_continue = should_continue
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        """Annulation explicite, sans callback ni acquisition de verrou métier."""
        return self._cancelled.is_set()

    def check(self) -> None:
        if self._cancelled.is_set():
            raise InferenceCancelled("Travail d'inférence annulé")
        if self._clock() >= self._deadline:
            raise InferenceDeadlineExceeded("Budget d'inférence dépassé")
        if self._should_continue is not None:
            try:
                current = self._should_continue()
            except Exception:
                # Une autorisation impossible à vérifier ne permet pas de continuer.
                self.cancel()
                raise InferenceCancelled("Autorisation d'inférence révoquée") from None
            if not current:
                self.cancel()
                raise InferenceCancelled("Autorisation d'inférence révoquée")
        # Le callback peut être lent ou annuler lui-même le travail.
        if self._cancelled.is_set():
            raise InferenceCancelled("Travail d'inférence annulé")
        if self._clock() >= self._deadline:
            raise InferenceDeadlineExceeded("Budget d'inférence dépassé")

    def remaining_seconds(self) -> float:
        self.check()
        return max(0.0, self._deadline - self._clock())


class ControlledChatClient:
    """Adaptateur compatible avec les doubles de test et les clients existants.

    Seuls les clients offrant complete_controlled peuvent interrompre leur attente
    réseau. Pour les autres, le résultat tardif est refusé après l'appel.
    """

    def __init__(self, client, control: InferenceControl) -> None:
        self.client = client
        self.control = control

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        self.control.check()
        method = getattr(self.client, "complete_controlled", None)
        if callable(method):
            message = method(messages, tools, self.control)
        else:
            message = self.client.complete(messages, tools)
        self.control.check()
        if not isinstance(message, dict):
            raise ValueError("Message LLM invalide")
        return message
