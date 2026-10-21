"""Fabriquer un clip géométrique anonyme pour tester le transport, pas la pose."""

import math
from pathlib import Path


def main() -> None:
    import cv2
    import numpy as np
    path = Path(__file__).resolve().parents[1] / ".cache" / "test-motion.mp4"
    path.parent.mkdir(exist_ok=True)
    video = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (640, 480))
    if not video.isOpened():
        raise RuntimeError("Encodeur de fixture indisponible")
    try:
        for frame in range(100):
            image = np.full((480, 640, 3), (40, 54, 47), dtype=np.uint8)
            elbow = (290, 260)
            bend = 0.2 + (1 - math.cos(frame / 99 * math.tau)) * 1.1
            wrist = (round(elbow[0] + 90 * math.sin(bend)), round(elbow[1] + 90 * math.cos(bend)))
            cv2.line(image, (290, 145), elbow, (160, 205, 175), 12)
            cv2.line(image, elbow, wrist, (160, 205, 175), 12)
            cv2.circle(image, elbow, 9, (215, 240, 226), -1)
            cv2.putText(image, "SYNTHETIC TEST - NO PATIENT", (115, 440), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (170, 190, 178), 1)
            video.write(image)
    finally:
        video.release()
    print(path)


if __name__ == "__main__":
    main()
