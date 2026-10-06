"""Un seul travail LLM local, partagé entre live et note, sans file d'attente."""

from dataclasses import dataclass
from threading import Lock

from packages.harness.control import InferenceControl

LIVE_BUDGET_SECONDS = 10.0
DRAFT_BUDGET_SECONDS = 30.0


@dataclass(frozen=True)
class InferenceLease:
    control: InferenceControl
    session_id: str
    token: str
    kind: str
    control_version: int | None = None


class InferenceGate:
    """L'expiration/annulation n'autorise pas à abandonner un worker actif.

    La réservation n'est libérée qu'au retour effectif de son travail. Un client
    non coopératif conserve donc son slot, au lieu de créer un thread par essai.
    Les demandes supplémentaires sont refusées immédiatement, jamais empilées.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._lease: InferenceLease | None = None

    def try_acquire(self, control: InferenceControl, session_id: str, token: str,
                    kind: str, control_version: int | None = None) -> InferenceLease | None:
        if kind not in ("live", "draft"):
            raise ValueError("Type d'analyse inconnu")
        with self._lock:
            if self._lease is not None:
                return None
            lease = InferenceLease(control, session_id, token, kind, control_version)
            self._lease = lease
            return lease

    def release(self, lease: InferenceLease | None) -> bool:
        if lease is None:
            return False
        with self._lock:
            if self._lease is not lease:
                return False
            self._lease = None
            return True

    def is_busy(self) -> bool:
        with self._lock:
            return self._lease is not None

    def cancel_session(self, session_id: str, token: str,
                       max_control_version: int | None = None) -> bool:
        with self._lock:
            lease = self._lease
            if lease is None or (lease.session_id, lease.token) != (session_id, token):
                return False
            if max_control_version is not None and (
                lease.kind != "live" or lease.control_version is None
                or lease.control_version > max_control_version
            ):
                return False
        lease.control.cancel()
        return True

    def cancel_all(self) -> bool:
        with self._lock:
            lease = self._lease
        if lease is None:
            return False
        lease.control.cancel()
        return True
