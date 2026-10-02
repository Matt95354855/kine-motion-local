"""Adaptateur MediaPipe expérimental pour un modèle `.task` déjà installé.

La dépendance et ses éventuels appels réseau doivent être vérifiés sur le poste
cible avant tout usage avec des données réelles. Aucun modèle n'est téléchargé.
"""

from pathlib import Path
from math import isfinite
import os

from packages.contracts.models import Point2D
from packages.pose.adapter import PoseObservation
from packages.pose.jpeg import bounded_jpeg_dimensions


class MediaPipePoseEngine:
    def __init__(self, model_path: str) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError("Modèle de pose local introuvable")
        cache = Path(__file__).resolve().parents[2] / ".cache" / "matplotlib"
        cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(cache))
        try:
            import cv2
            import mediapipe as mp
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("MediaPipe, NumPy et OpenCV doivent être installés localement") from exc

        self._cv2 = cv2
        self._mp = mp
        self._np = np
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(path), delegate=mp.tasks.BaseOptions.Delegate.CPU),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=2,
            output_segmentation_masks=False,
        )
        self._landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)

    def detect(self, jpeg_bytes: bytes, timestamp_ms: int, side: str) -> PoseObservation:
        if side not in ("left", "right"):
            raise ValueError("Côté anatomique invalide")
        expected_width, expected_height = bounded_jpeg_dimensions(jpeg_bytes)
        encoded = self._np.frombuffer(jpeg_bytes, dtype=self._np.uint8)
        bgr = self._cv2.imdecode(encoded, self._cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("Image JPEG illisible")
        height, width = bgr.shape[:2]
        if (width, height) != (expected_width, expected_height):
            raise ValueError("Dimensions JPEG incohérentes")
        rgb = self._cv2.cvtColor(bgr, self._cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        poses = result.pose_landmarks
        if len(poses) != 1:
            reason = "no_pose" if not poses else "multiple_people"
            return PoseObservation(width, height, None, None, None, reason)

        indices = (11, 13, 15) if side == "left" else (12, 14, 16)

        def point(index: int) -> Point2D | None:
            landmark = poses[0][index]
            if landmark.visibility < 0.5 or landmark.presence < 0.5:
                return None
            return Point2D(float(landmark.x), float(landmark.y))

        shoulder, elbow, wrist = (point(index) for index in indices)
        if any(p is None for p in (shoulder, elbow, wrist)):
            return PoseObservation(width, height, None, None, None, "occlusion")
        if any(not isfinite(p.x) or not isfinite(p.y) or not 0 <= p.x <= 1 or not 0 <= p.y <= 1
               for p in (shoulder, elbow, wrist)):
            return PoseObservation(width, height, None, None, None, "out_of_frame")
        return PoseObservation(width, height, shoulder, elbow, wrist)

    def close(self) -> None:
        self._landmarker.close()
