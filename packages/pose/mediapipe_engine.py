"""Adaptateur MediaPipe expérimental pour un modèle `.task` déjà installé.

La dépendance et ses éventuels appels réseau doivent être vérifiés sur le poste
cible avant tout usage avec des données réelles. Aucun modèle n'est téléchargé.
"""

from pathlib import Path
from math import isfinite
import os

from packages.contracts.models import LandmarkDiagnostic, Point2D
from packages.pose.adapter import PoseObservation
from packages.pose.jpeg import bounded_jpeg_dimensions


VISIBILITY_THRESHOLD = 0.5
PRESENCE_THRESHOLD = 0.5
POSE_OPTIONS = {
    "num_poses": 2,
    "min_pose_detection_confidence": 0.5,
    "min_pose_presence_confidence": 0.5,
    "min_tracking_confidence": 0.5,
    "output_segmentation_masks": False,
}
LANDMARK_INDICES = {"left_ear": 7, "right_ear": 8, "left_shoulder": 11, "right_shoulder": 12,
                    "left_elbow": 13, "right_elbow": 14, "left_wrist": 15, "right_wrist": 16,
                    "left_hip": 23, "right_hip": 24, "left_knee": 25, "right_knee": 26,
                    "left_ankle": 27, "right_ankle": 28}


def observation_from_landmarks(width: int, height: int, landmarks: list, side: str) -> PoseObservation:
    """Conversion testable sans runtime natif ; qualité par protocole en aval."""
    if side not in ("left", "right"):
        raise ValueError("Côté anatomique invalide")
    if len(landmarks) != 33:
        return PoseObservation(width, height, None, None, None, "degenerate_landmarks",
                               landmark_diagnostics={name: LandmarkDiagnostic() for name in LANDMARK_INDICES})

    diagnostics = {}

    def point(name: str, index: int) -> Point2D | None:
        landmark = landmarks[index]
        raw = {field: getattr(landmark, field, None) for field in ("visibility", "presence", "x", "y")}
        # Les scores NaN/inf sont diagnostiqués mais jamais exportés tels quels.
        values = {field: float(value) if value is not None and isfinite(value) else None
                  for field, value in raw.items()}
        non_finite = tuple(field for field, value in raw.items() if value is not None and values[field] is None)
        if raw["x"] is None or raw["y"] is None:
            coordinate_status = "missing"
        elif values["x"] is None or values["y"] is None:
            coordinate_status = "non_finite"
        else:
            coordinate_status = "in_frame" if 0 <= values["x"] <= 1 and 0 <= values["y"] <= 1 else "out_of_frame"
        if any(value is None for value in raw.values()):
            reason = "missing_landmark"
        elif non_finite:
            reason = "non_finite_input"
        elif values["visibility"] < VISIBILITY_THRESHOLD and values["presence"] < PRESENCE_THRESHOLD:
            reason = "low_visibility_and_presence"
        elif values["visibility"] < VISIBILITY_THRESHOLD:
            reason = "low_visibility"
        elif values["presence"] < PRESENCE_THRESHOLD:
            reason = "low_presence"
        else:
            reason = "accepted"
        accepted = reason == "accepted"
        diagnostics[name] = LandmarkDiagnostic(
            visibility=values["visibility"], presence=values["presence"],
            visibility_threshold=VISIBILITY_THRESHOLD, presence_threshold=PRESENCE_THRESHOLD,
            accepted=accepted, reason=reason, coordinate_status=coordinate_status,
            non_finite_fields=non_finite,
        )
        return Point2D(values["x"], values["y"]) if accepted else None

    points = {name: point(name, index) for name, index in LANDMARK_INDICES.items()}
    return PoseObservation(width, height, points[f"{side}_shoulder"], points[f"{side}_elbow"],
                           points[f"{side}_wrist"], landmarks=points, landmark_diagnostics=diagnostics)


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
            **POSE_OPTIONS,
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

        # L'occlusion est évaluée pour le protocole sélectionné : un poignet
        # masqué n'invalide pas un essai du genou ou une observation du cou.
        return observation_from_landmarks(width, height, poses[0], side)

    def close(self) -> None:
        self._landmarker.close()
