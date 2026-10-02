"""Microbenchmark anonyme du chemin sans personne ; pas de benchmark clinique."""

import argparse
import json
import statistics
import time

from scripts.prepare_pose import MODEL, model_matches


def main() -> None:
    parser = argparse.ArgumentParser(description="Mesurer l'initialisation et le traitement de JPEG vides")
    parser.add_argument("--frames", type=int, default=30)
    args = parser.parse_args()
    if not 3 <= args.frames <= 600:
        parser.error("Entre 3 et 600 images")
    if not model_matches(MODEL):
        parser.error("Vérifier d'abord le modèle de pose")
    from packages.pose.mediapipe_engine import MediaPipePoseEngine
    import cv2
    import numpy as np
    ok, encoded = cv2.imencode(".jpg", np.zeros((480, 640, 3), dtype=np.uint8))
    if not ok:
        parser.error("Échec encodage")
    jpeg = encoded.tobytes()
    start = time.perf_counter()
    engine = MediaPipePoseEngine(str(MODEL))
    loaded_ms = (time.perf_counter() - start) * 1000
    durations = []
    try:
        for index in range(args.frames):
            start = time.perf_counter()
            observation = engine.detect(jpeg, index * 200, "left")
            durations.append((time.perf_counter() - start) * 1000)
            if observation.quality_reason != "no_pose":
                raise RuntimeError("Une pose a été inventée sur image vide")
    finally:
        engine.close()
    print(json.dumps({"fixture": "blank_jpeg_640x480", "frames": args.frames,
        "init_ms": round(loaded_ms, 1), "p50_ms": round(statistics.median(durations), 1),
        "p95_ms": round(sorted(durations)[int((len(durations) - 1) * .95)], 1),
        "mean_processing_hz": round(1000 / statistics.mean(durations), 1),
        "limitation": "Sans personne : ne mesure ni précision, ni coût du suivi d'une pose, ni performance GPU/LLM"}, indent=2))


if __name__ == "__main__":
    main()
