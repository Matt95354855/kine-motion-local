"""Fraîcheur technique des images, jamais une validation du geste.

L'horloge serveur et les trous reçus ne peuvent pas être désactivés par le
client. Une interruption reste vraie jusqu'au nouvel essai, même après reprise.
Le seuil de trois secondes est technique et reste à qualifier sur le matériel.
"""

from dataclasses import dataclass
from math import isfinite

CAPTURE_WATCHDOG_TIMEOUT_MS = 3000
MAX_CAPTURE_MONITOR_DURATION_MS = 135000


def validate_capture_monitor(value: dict | None) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "watchdog_timeout_ms", "expected_duration_ms",
        "last_frame_elapsed_ms", "interrupted",
    }:
        raise ValueError("Contrat de surveillance capture invalide")
    if value["schema_version"] != "1.0" or type(value["watchdog_timeout_ms"]) is not int \
            or value["watchdog_timeout_ms"] != CAPTURE_WATCHDOG_TIMEOUT_MS \
            or type(value["interrupted"]) is not bool:
        raise ValueError("Paramètres de surveillance capture invalides")
    duration, last = value["expected_duration_ms"], value["last_frame_elapsed_ms"]
    if type(duration) not in (int, float) or not 0 <= duration <= MAX_CAPTURE_MONITOR_DURATION_MS \
            or not isfinite(duration):
        raise ValueError("Durée observée capture invalide")
    if last is not None and (type(last) not in (int, float) or not 0 <= last <= duration or not isfinite(last)):
        raise ValueError("Dernière image capture invalide")
    return dict(value)


@dataclass
class CaptureIntegrity:
    started_at: float
    first_received_at: float | None = None
    last_received_at: float | None = None
    first_source_timestamp_ms: int | None = None
    last_source_timestamp_ms: int | None = None
    max_receive_gap_ms: float = 0
    max_source_gap_ms: float = 0
    received_frame_count: int = 0
    interrupted: bool = False
    client_monitor: dict | None = None

    def observe(self, now: float) -> None:
        reference = self.last_received_at if self.last_received_at is not None else self.started_at
        if (now - reference) * 1000 >= CAPTURE_WATCHDOG_TIMEOUT_MS:
            self.interrupted = True

    def receive(self, now: float, source_timestamp_ms: int) -> None:
        reference = self.last_received_at if self.last_received_at is not None else self.started_at
        gap = max(0.0, (now - reference) * 1000)
        self.max_receive_gap_ms = max(self.max_receive_gap_ms, gap)
        if gap >= CAPTURE_WATCHDOG_TIMEOUT_MS:
            self.interrupted = True
        if self.last_source_timestamp_ms is not None:
            self.max_source_gap_ms = max(self.max_source_gap_ms,
                                         source_timestamp_ms - self.last_source_timestamp_ms)
            if self.max_source_gap_ms >= CAPTURE_WATCHDOG_TIMEOUT_MS:
                self.interrupted = True
        if self.first_received_at is None:
            self.first_received_at = now
            self.first_source_timestamp_ms = source_timestamp_ms
        self.last_received_at = now
        self.last_source_timestamp_ms = source_timestamp_ms
        self.received_frame_count += 1

    def finish(self, now: float, monitor: dict | None = None, interruption_reason: str | None = None) -> dict:
        if interruption_reason not in (None, "capture_interrupted"):
            raise ValueError("Motif d'interruption inconnu")
        self.client_monitor = validate_capture_monitor(monitor)
        self.observe(now)
        if interruption_reason is not None:
            self.interrupted = True
        if self.client_monitor is not None:
            last = self.client_monitor["last_frame_elapsed_ms"]
            tail_ms = self.client_monitor["expected_duration_ms"] - (last if last is not None else 0)
            if self.client_monitor["interrupted"] or tail_ms >= CAPTURE_WATCHDOG_TIMEOUT_MS:
                self.interrupted = True
        return self.snapshot(now)

    def snapshot(self, now: float) -> dict:
        reference = self.last_received_at if self.last_received_at is not None else self.started_at
        return {
            "schema_version": "1.0", "watchdog_timeout_ms": CAPTURE_WATCHDOG_TIMEOUT_MS,
            "interrupted": self.interrupted,
            "reason": "capture_interrupted" if self.interrupted else None,
            "server_observed_duration_ms": round(max(0.0, now - self.started_at) * 1000, 1),
            "received_frame_count": self.received_frame_count,
            "max_receive_gap_ms": round(self.max_receive_gap_ms, 1),
            "max_source_gap_ms": self.max_source_gap_ms,
            "last_received_age_ms": round(max(0.0, now - reference) * 1000, 1),
            "source_span_ms": self.last_source_timestamp_ms - self.first_source_timestamp_ms
                if self.first_source_timestamp_ms is not None else 0,
            "client_monitor": self.client_monitor,
            "limitation": "fresh_received_frames_do_not_prove_complete_motion_or_pixel_changes",
        }
