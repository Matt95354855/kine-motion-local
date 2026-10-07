"""Résumé temporel descriptif ; aucun seuil clinique ni comptage thérapeutique.

Le diagnostic optionnel ``robustness`` décrit seulement les images reçues. Une
durée de perte est l'écart entre première et dernière image invalide d'un groupe,
pas une durée d'absence de personne ou de panne caméra (une image seule : 0 ms).
Le contexte du pic brut utilise seulement les voisins immédiats : angle fini,
séquence contiguë et écart temporel positif d'au plus 1000 ms. Ce critère technique
ne confirme ni l'angle, ni une précision, ni une plausibilité biomécanique. Aucun
point ou angle manquant n'est interpolé ; aucune valeur finale n'est modifiée.
La plus grande variation adjacente utilise le même critère technique, conserve
le signe fin moins début et le premier ex aequo en valeur absolue. Ce nombre ne
constitue pas une détection de faute, de mouvement impossible ou de valeur aberrante.
"""

from collections import Counter
from math import isfinite

from packages.biomechanics.protocols import angle_and_reason, get_protocol
from packages.contracts.models import PoseFrame

MAX_INVALID_INTERVALS = 32
PEAK_NEIGHBOR_GAP_MS = 1000


def frame_angle(frame: PoseFrame) -> float | None:
    return angle_and_reason(frame, frame.side)[0]


def _finite_number(value) -> bool:
    return type(value) in (int, float) and isfinite(value)


def _robustness(frames: tuple[PoseFrame, ...], samples: list[dict]) -> dict:
    valid = [_finite_number(sample["angle_deg"]) for sample in samples]
    reasons = []
    for frame, sample, usable in zip(frames, samples, valid):
        if usable:
            reasons.append(None)
        elif sample["angle_deg"] is not None:
            reasons.append("nonfinite_angle")
        else:
            # Ne pas changer quality_reason dans le contrat historique à quatre
            # champs : les raisons déduites sont propres à ces diagnostics.
            reasons.append(angle_and_reason(frame, frame.side)[1] or "angle_unavailable")

    timestamps_valid = all(_finite_number(frame.timestamp_ms) for frame in frames)
    monotonic_timestamps = timestamps_valid and all(
        current.timestamp_ms > previous.timestamp_ms
        for previous, current in zip(frames, frames[1:])
    )
    gaps = [
        current.timestamp_ms - previous.timestamp_ms
        for previous, current in zip(frames, frames[1:])
    ] if monotonic_timestamps else []
    nonquantified = [reason == "rotation_not_measurable_2d" for reason in reasons]
    quantified_protocol = bool(frames) and get_protocol(frames[0].protocol_id).mode != "guide_only"

    largest_change = None
    largest_absolute_delta = -1.0
    if monotonic_timestamps:
        for index in range(1, len(samples)):
            previous, current = samples[index - 1], samples[index]
            gap = current["timestamp_ms"] - previous["timestamp_ms"]
            if (
                not valid[index - 1] or not valid[index]
                or current["sequence"] != previous["sequence"] + 1
                or not 0 < gap <= PEAK_NEIGHBOR_GAP_MS
            ):
                continue
            delta = current["angle_deg"] - previous["angle_deg"]
            if abs(delta) > largest_absolute_delta:
                largest_absolute_delta = abs(delta)
                largest_change = {
                    "start_sequence": previous["sequence"], "end_sequence": current["sequence"],
                    "start_timestamp_ms": previous["timestamp_ms"],
                    "end_timestamp_ms": current["timestamp_ms"],
                    "gap_ms": gap, "delta_deg": round(delta, 1),
                }

    intervals = []
    interval_count = 0
    longest = 0 if monotonic_timestamps else None
    start = None
    # Un sentinelle clôt un dernier groupe invalide sans extrapoler après lui.
    for index in range(len(frames) + 1):
        unusable = index < len(frames) and not valid[index] and not nonquantified[index]
        if unusable and start is None:
            start = index
        if start is not None and not unusable:
            end = index - 1
            first, last = frames[start], frames[end]
            duration = last.timestamp_ms - first.timestamp_ms if monotonic_timestamps else None
            interval_count += 1
            if duration is not None:
                longest = max(longest, duration)
            if len(intervals) < MAX_INVALID_INTERVALS:
                intervals.append({
                    "start_sequence": first.sequence, "end_sequence": last.sequence,
                    "start_timestamp_ms": first.timestamp_ms,
                    "end_timestamp_ms": last.timestamp_ms,
                    "observed_duration_ms": duration, "frame_count": end - start + 1,
                    "reasons": sorted(set(reasons[start:end + 1])),
                })
            start = None

    widths = [frame.width_px for frame in frames if _finite_number(frame.width_px) and frame.width_px > 0]
    heights = [frame.height_px for frame in frames if _finite_number(frame.height_px) and frame.height_px > 0]
    dimensions = {
        "min_width_px": min(widths) if widths else None,
        "max_width_px": max(widths) if widths else None,
        "min_height_px": min(heights) if heights else None,
        "max_height_px": max(heights) if heights else None,
    }
    usable_indices = [index for index, usable in enumerate(valid) if usable]
    peak = None
    if usable_indices:
        # max conserve le premier ex aequo, comme la sélection de preuve du coude.
        peak_index = max(usable_indices, key=lambda index: samples[index]["angle_deg"])
        peak_sample = samples[peak_index]

        def neighbor(offset: int):
            index = peak_index + offset
            if not 0 <= index < len(samples):
                return None, "boundary"
            if not monotonic_timestamps:
                return None, "timestamp_order"
            if not valid[index]:
                return None, "invalid_sample"
            sample = samples[index]
            if sample["sequence"] != peak_sample["sequence"] + offset:
                return None, "sequence_gap"
            gap = abs(sample["timestamp_ms"] - peak_sample["timestamp_ms"])
            if not 0 < gap <= PEAK_NEIGHBOR_GAP_MS:
                return None, "time_gap"
            return {
                "sequence": sample["sequence"], "timestamp_ms": sample["timestamp_ms"],
                "gap_ms": gap,
                "delta_deg": round(abs(peak_sample["angle_deg"] - sample["angle_deg"]), 1),
            }, None

        before, before_reason = neighbor(-1)
        after, after_reason = neighbor(1)
        context = "before_and_after" if before is not None and after is not None else (
            "before_only" if before is not None else "after_only" if after is not None else "isolated"
        )
        peak = {
            "sequence": peak_sample["sequence"], "timestamp_ms": peak_sample["timestamp_ms"],
            "angle_deg": peak_sample["angle_deg"], "temporal_context": context,
            "neighbor_gap_limit_ms": PEAK_NEIGHBOR_GAP_MS,
            "before": before, "after": after,
            "before_unavailable_reason": before_reason,
            "after_unavailable_reason": after_reason,
        }
    return {
        "schema_version": "1.0",
        "quantified_protocol": quantified_protocol,
        "usable_frames": sum(valid), "unusable_frames": len(frames) - sum(valid),
        "nonquantified_frames": sum(nonquantified),
        "invalid_reason_counts": dict(sorted(Counter(
            reason for reason in reasons if reason and reason != "rotation_not_measurable_2d"
        ).items())),
        "invalid_intervals": intervals, "invalid_interval_count": interval_count,
        "invalid_intervals_truncated": interval_count > MAX_INVALID_INTERVALS,
        "longest_invalid_observed_duration_ms": longest,
        "timestamps_strictly_increasing": monotonic_timestamps,
        "max_adjacent_sample_gap_ms": max(gaps) if gaps else None,
        "largest_adjacent_angle_change": largest_change,
        "analyzed_image_dimensions": dimensions, "raw_peak": peak,
    }


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
        "robustness": _robustness(frames, samples),
    }
