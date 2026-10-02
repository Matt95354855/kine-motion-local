"""Résumé temporel descriptif ; aucun seuil clinique ni comptage thérapeutique."""

from packages.biomechanics.protocols import angle_and_reason
from packages.contracts.models import PoseFrame


def frame_angle(frame: PoseFrame) -> float | None:
    return angle_and_reason(frame, frame.side)[0]


def summarize_motion(frames: tuple[PoseFrame, ...]) -> dict:
    samples = [
        {"sequence": frame.sequence, "timestamp_ms": frame.timestamp_ms,
         "angle_deg": frame_angle(frame), "quality_reason": frame.quality_reason}
        for frame in frames
    ]
    values = [sample["angle_deg"] for sample in samples if sample["angle_deg"] is not None]
    duration_ms = frames[-1].timestamp_ms - frames[0].timestamp_ms if len(frames) > 1 else 0
    return {
        "schema_version": "1.0", "duration_ms": duration_ms,
        "processed_frames": len(frames), "usable_frames": len(values),
        "processing_rate_hz": round((len(frames) - 1) * 1000 / duration_ms, 2) if duration_ms else 0,
        "observed_excursion_deg": round(max(values) - min(values), 1) if values else None,
        "samples": samples,
    }
