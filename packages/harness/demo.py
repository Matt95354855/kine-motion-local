"""Démonstration hors ligne avec trois images de pose entièrement synthétiques."""

import json
from dataclasses import asdict

from packages.biomechanics.elbow import assess_elbow_trial
from packages.contracts.models import ElbowTrial, Point2D, PoseFrame
from packages.harness.report import render_draft


def synthetic_trial() -> ElbowTrial:
    width, height = 640, 480

    def point(x: int, y: int) -> Point2D:
        return Point2D(x / width, y / height)

    wrists = [(320, 480), (405, 445), (440, 360)]
    frames = tuple(
        PoseFrame(
            sequence=index,
            timestamp_ms=index * 500.0,
            width_px=width,
            height_px=height,
            shoulder=point(320, 240),
            elbow=point(320, 360),
            wrist=point(*wrist),
            view_is_valid=True,
            camera_stable=True,
        )
        for index, wrist in enumerate(wrists)
    )
    return ElbowTrial("trial_demo_001", "session_demo_001", "left", frames)


def main() -> None:
    measurement = assess_elbow_trial(synthetic_trial())
    print(json.dumps(asdict(measurement), ensure_ascii=False, indent=2))
    print()
    print(render_draft(measurement))


if __name__ == "__main__":
    main()
