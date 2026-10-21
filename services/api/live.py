"""Coordination non bloquante d'une observation locale sur une fenêtre courte.

Le budget et la révocation interrompent le transport lorsqu'il coopère. Un appel
non coopératif conserve le slot jusqu'à sa terminaison réelle ; le serveur ne
prétend pas tuer le calcul GPU d'un service externe. Aucun travail n'est en file.
"""

from dataclasses import dataclass
from math import isfinite
from threading import RLock, Thread
from time import monotonic
from typing import Callable

from packages.harness.live import LiveSnapshot, run_live_harness
from packages.harness.control import ControlledChatClient, InferenceControl
from packages.harness.runner import ChatClient
from services.api.inference import InferenceGate, InferenceLease


MIN_LIVE_SAMPLES = 3


@dataclass(frozen=True)
class _Configuration:
    session_id: str
    token: str
    model_id: str
    include_image: bool
    control_version: int | None = None


@dataclass
class _Job:
    configuration: _Configuration
    generation: int
    started_at: float
    control: InferenceControl | None = None
    lease: InferenceLease | None = None
    active: bool = True


class LiveHarnessCoordinator:
    """Le serveur conserve un résultat au plus, sans JPEG ni historique LLM."""

    def __init__(
        self,
        manager,
        clock: Callable[[], float] = monotonic,
        inference_interval_seconds: float = 3,
        result_ttl_seconds: float = 10,
        inference_gate: InferenceGate | None = None,
        analysis_budget_seconds: float = 10,
        on_completion_start: Callable[[str, str, str, bool, list[dict]], None] | None = None,
    ) -> None:
        if (
            inference_interval_seconds < 0 or result_ttl_seconds <= 0
            or analysis_budget_seconds <= 0
            or not all(isfinite(value) for value in (
                inference_interval_seconds, result_ttl_seconds, analysis_budget_seconds
            ))
        ):
            raise ValueError("Délais d'observation invalides")
        self._manager = manager
        self._clock = clock
        self._interval = inference_interval_seconds
        self._ttl = result_ttl_seconds
        self._budget = analysis_budget_seconds
        self._on_completion_start = on_completion_start
        self._inference_gate = inference_gate if inference_gate is not None else InferenceGate()
        self._lock = RLock()
        self._configuration: _Configuration | None = None
        self._generation = 0
        self._session_generation = 0
        # Un seul watermark, jamais un registre croissant de séances/tokens.
        self._control_scope: tuple[str, str] | None = None
        self._highest_control_version = -1
        self._revoked_control_version = -1
        self._job: _Job | None = None
        self._result: dict | None = None
        self._result_started_at: float | None = None
        self._last_started_at: float | None = None
        self._last_window_ref: str | None = None
        self._failed = False
        self._closed = False

    def _invalidate_locked(self) -> None:
        if self._job is not None:
            self._job.active = False
            if self._job.control is not None:
                self._job.control.cancel()
        self._generation += 1
        self._result = None
        self._result_started_at = None
        self._failed = False

    def _version_current_locked(self, configuration: _Configuration) -> bool:
        version = configuration.control_version
        if version is None or self._control_scope != (
            configuration.session_id, configuration.token
        ):
            return True
        return (
            version >= self._highest_control_version
            and version > self._revoked_control_version
        )

    def _remember_version_locked(self, configuration: _Configuration) -> None:
        if configuration.control_version is None:
            return
        scope = (configuration.session_id, configuration.token)
        if self._control_scope != scope:
            self._control_scope = scope
            self._highest_control_version = -1
            self._revoked_control_version = -1
        self._highest_control_version = max(
            self._highest_control_version, configuration.control_version
        )

    def _continues(self, job: _Job) -> bool:
        # Ne jamais maintenir notre verrou pendant l'accès au gestionnaire.
        try:
            job.control.check()
        except TimeoutError:
            return False
        with self._lock:
            if (
                self._closed
                or not job.active
                or job.generation != self._generation
                or job.configuration != self._configuration
                or self._job is not job
                or self._clock() - job.started_at >= self._ttl
                or not self._version_current_locked(job.configuration)
            ):
                return False
        try:
            configuration = job.configuration
            if configuration.control_version is None:
                active = self._manager.get(
                    configuration.session_id, configuration.token
                ).active
            else:
                active = self._manager.live_is_current(
                    configuration.session_id, configuration.token,
                    configuration.control_version,
                )
        except (PermissionError, ValueError):
            return False
        try:
            job.control.check()
        except TimeoutError:
            return False
        with self._lock:
            return bool(active) and (
                not self._closed
                and job.active
                and job.generation == self._generation
                and job.configuration == self._configuration
                and self._job is job
                and self._clock() - job.started_at < self._ttl
                and self._version_current_locked(job.configuration)
            )

    def _response_locked(self, window: dict, warming_up: bool = False) -> dict:
        age_ms = None
        result = None
        stale = False
        if self._result_started_at is not None:
            age_seconds = max(0, self._clock() - self._result_started_at)
            age_ms = round(age_seconds * 1000)
            stale = age_seconds >= self._ttl
            if stale:
                self._result = None
            if self._result is not None and not stale and not warming_up:
                # Une copie évite qu'un appelant altère l'unique résultat gardé.
                result = dict(self._result)
                if isinstance(result.get("tool_names"), list):
                    result["tool_names"] = list(result["tool_names"])
        budget_remaining_ms = None
        if self._job is not None:
            try:
                remaining = self._job.control.remaining_seconds()
            except TimeoutError:
                remaining = 0
            budget_remaining_ms = max(0, round(remaining * 1000))
            analysis_state = (
                "running" if self._job.active and remaining > 0
                and not self._job.control.cancelled else "cancelling"
            )
        elif self._inference_gate.is_busy():
            analysis_state = "busy"
        else:
            analysis_state = "idle"
        if warming_up:
            state = "warming_up"
        elif result is not None:
            state = "ready"
        elif self._job is not None:
            state = "running"
        elif analysis_state == "busy":
            state = "busy"
        elif stale:
            state = "stale"
        elif self._failed:
            state = "unavailable"
        else:
            # Attend un nouveau créneau/une nouvelle fenêtre, sans file d'attente.
            state = "running"
        response = {
            "state": state,
            "window": dict(window),
            "result": result,
            "result_age_ms": age_ms,
            "analysis_state": analysis_state,
            "budget_remaining_ms": budget_remaining_ms,
        }
        if analysis_state == "busy":
            response["busy_reason"] = "analysis_busy"
        return response

    def _poll_response_locked(
        self, configuration: _Configuration, window: dict, warming_up: bool = False
    ) -> dict:
        # Une requête suspendue ne reçoit pas le résultat d'une configuration
        # plus récente, même si son instantané termine après le changement.
        if (
            configuration != self._configuration
            or not self._version_current_locked(configuration)
            or self._closed
        ):
            raise PermissionError("Contrôle live révoqué")
        return self._response_locked(window, warming_up)

    def _execute(self, job: _Job, snapshot: LiveSnapshot, client: ChatClient | None) -> None:
        result = None
        failed = False
        try:
            if not self._continues(job):
                return
            job.control.check()
            callback = None
            if self._on_completion_start is not None:
                configuration = job.configuration
                callback = lambda messages: self._on_completion_start(
                    configuration.session_id, configuration.token, configuration.model_id,
                    configuration.include_image, messages)
            controlled_client = ControlledChatClient(client, job.control, callback) if client is not None else None
            result = run_live_harness(
                snapshot,
                controlled_client,
                allow_visual_evidence=job.configuration.include_image,
                should_continue=lambda: self._continues(job),
            )
            job.control.check()
            if not isinstance(result, dict):
                failed = True
                result = None
        except Exception:
            # Pas de détails serveur, de prompt ou d'image dans la réponse web.
            failed = True
        finally:
            try:
                job.control.check()
                valid = self._continues(job)
            except TimeoutError:
                valid = False
            with self._lock:
                try:
                    job.control.check()
                except TimeoutError:
                    valid = False
                if (
                    valid
                    and job.active
                    and job.configuration == self._configuration
                    and self._job is job
                    and job.generation == self._generation
                    and self._version_current_locked(job.configuration)
                ):
                    if result is not None and result.get("fallback_reason") != "cancelled":
                        self._result = dict(result)
                        # L'âge vient des observations, pas de la fin du calcul.
                        self._result_started_at = job.started_at
                        self._failed = False
                    elif failed:
                        self._failed = True
                elif (
                    job.generation == self._generation
                    and job.configuration == self._configuration
                    and not self._closed
                    and self._clock() - job.started_at >= self._ttl
                ):
                    # Indiquer l'obsolescence sans publier le résultat tardif.
                    self._result = None
                    self._result_started_at = job.started_at
                    self._failed = False
                elif (
                    failed and job.generation == self._generation
                    and job.configuration == self._configuration
                    and not self._closed
                ):
                    self._failed = True
                job.active = False
                # Ne libérer ni sur stop ni à l'expiration : le travail finit ici.
                job.control.cancel()
                self._inference_gate.release(job.lease)
                if self._job is job:
                    self._job = None

    def _discard_job(self, job: _Job) -> None:
        """Libère une réservation pour laquelle aucun worker n'a démarré."""
        with self._lock:
            job.active = False
            if (
                job.generation == self._generation
                and job.configuration == self._configuration
                and not self._closed
            ):
                if self._clock() - job.started_at >= self._ttl:
                    self._result = None
                    self._result_started_at = job.started_at
                else:
                    try:
                        job.control.check()
                    except TimeoutError:
                        self._failed = True
            job.control.cancel()
            self._inference_gate.release(job.lease)
            if self._job is job:
                self._job = None

    def poll(
        self,
        session_id: str,
        token: str,
        model_id: str,
        client: ChatClient | None,
        include_image: bool = False,
        control_version: int | None = None,
    ) -> dict:
        """Consulte/démarre une observation sans attendre la génération du LLM.

        Le consentement aux images et l'alias du modèle sont validés par l'API.
        Le gestionnaire valide ici la séance active et fournit une copie bornée.
        """
        if type(include_image) is not bool:
            raise ValueError("Consentement visuel explicite requis")
        if control_version is not None and (
            type(control_version) is not int or control_version < 0
        ):
            raise ValueError("Version de contrôle live invalide")
        with self._lock:
            session_generation = self._session_generation
        session = self._manager.get(session_id, token)
        if not session.active:
            raise ValueError("Capture active requise")
        if control_version is not None and not self._manager.live_is_current(
            session_id, token, control_version
        ):
            raise ValueError("Observation désactivée ou révoquée")
        window = self._manager.live_window_info(session_id, token)
        configuration = _Configuration(
            session_id, token, model_id, include_image, control_version
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("Coordinateur fermé")
            if (
                session_generation != self._session_generation
                or not self._version_current_locked(configuration)
            ):
                raise PermissionError("Contrôle live révoqué")
            self._remember_version_locked(configuration)
            if configuration != self._configuration:
                self._invalidate_locked()
                self._configuration = configuration
            if window["sample_count"] < MIN_LIVE_SAMPLES:
                return self._poll_response_locked(configuration, window, warming_up=True)
            now = self._clock()
            if self._job is not None or window["window_ref"] == self._last_window_ref:
                return self._poll_response_locked(configuration, window)
            if (
                client is not None
                and self._last_started_at is not None
                and now - self._last_started_at < self._interval
            ):
                return self._poll_response_locked(configuration, window)
            # Le slot est réservé avant la copie, même pour le repli déterministe.
            source_age_seconds = max(0, window.get("latest_sample_age_ms") or 0) / 1000
            job = _Job(configuration, self._generation, now - source_age_seconds)
            budget_seconds = min(self._budget, max(0, self._ttl - source_age_seconds))
            if budget_seconds <= 0:
                self._result = None
                self._result_started_at = job.started_at
                return self._poll_response_locked(configuration, window)
            job.control = InferenceControl(
                timeout_seconds=budget_seconds, clock=self._clock,
            )
            job.lease = self._inference_gate.try_acquire(
                job.control, session_id, token, "live", control_version=control_version,
            )
            if job.lease is None:
                job.control.cancel()
                return self._poll_response_locked(configuration, window)
            self._job = job
        try:
            snapshot = self._manager.live_snapshot(
                session_id, token, include_images=include_image
            )
        except Exception:
            self._discard_job(job)
            raise
        if len(snapshot.samples) < MIN_LIVE_SAMPLES:
            with self._lock:
                self._discard_job(job)
                return self._poll_response_locked(configuration, window, warming_up=True)
        try:
            job.control.check()
            continues = self._continues(job)
        except TimeoutError:
            continues = False
        if not continues:
            with self._lock:
                self._discard_job(job)
                return self._poll_response_locked(configuration, window)
        with self._lock:
            if (
                job.generation != self._generation
                or self._closed
                or not self._version_current_locked(job.configuration)
            ):
                self._discard_job(job)
                return self._poll_response_locked(configuration, window)
            self._last_window_ref = snapshot.window_ref
            self._failed = False
            if client is not None:
                self._last_started_at = now
                try:
                    Thread(
                        target=self._execute,
                        args=(job, snapshot, client),
                        daemon=True,
                        name="live-harness",
                    ).start()
                except RuntimeError:
                    self._discard_job(job)
                    self._failed = True
                return self._poll_response_locked(configuration, window)
        # Sans LLM, seules vingt-cinq observations scalaires sont examinées.
        self._execute(job, snapshot, None)
        with self._lock:
            return self._poll_response_locked(configuration, window)

    def stop(self, session_id: str, token: str, control_version: int | None = None) -> None:
        """Révoque et interrompt le transport coopératif, sans attendre le worker."""
        self._manager.get(session_id, token)
        with self._lock:
            if control_version is not None:
                if type(control_version) is not int or control_version < 0:
                    raise ValueError("Version de contrôle live invalide")
                scope = (session_id, token)
                if self._control_scope not in (None, scope):
                    return
                self._control_scope = scope
                self._highest_control_version = max(self._highest_control_version, control_version)
                self._revoked_control_version = max(self._revoked_control_version, control_version)
            if (
                self._configuration is not None
                and self._configuration.session_id == session_id
                and self._configuration.token == token
                and (
                    control_version is None
                    or self._configuration.control_version is None
                    or self._configuration.control_version <= control_version
                )
            ):
                self._invalidate_locked()
                self._configuration = None

    def invalidate(self) -> None:
        """Révoque l'observation lors d'un changement global de séance."""
        with self._lock:
            self._invalidate_locked()
            self._configuration = None
            self._session_generation += 1
            self._control_scope = None
            self._highest_control_version = -1
            self._revoked_control_version = -1

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._invalidate_locked()
            self._configuration = None
            self._session_generation += 1
            self._control_scope = None
            self._highest_control_version = -1
            self._revoked_control_version = -1
