"""Diagnostic local sans chargement, configuration ni téléchargement de LLM."""

import argparse
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.prepare_pose import MODEL, ROOT, model_matches


def memory_inventory() -> dict:
    try:
        if platform.system() == "Linux":
            fields = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
            return {"total_gib": round(int(fields["MemTotal"].split()[0]) / 1024 ** 2, 1),
                    "available_gib": round(int(fields["MemAvailable"].split()[0]) / 1024 ** 2, 1)}
        if platform.system() == "Darwin":
            total = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=5)
            return {"total_gib": round(int(total) / 1024 ** 3, 1), "available_gib": None}
        if platform.system() == "Windows":
            output = subprocess.check_output(["powershell", "-NoProfile", "-Command",
                "$kineOs = Get-CimInstance Win32_OperatingSystem; Write-Output $kineOs.TotalVisibleMemorySize; Write-Output $kineOs.FreePhysicalMemory"], text=True, timeout=10)
            total, available = (int(value) for value in output.split())
            return {"total_gib": round(total / 1024 ** 2, 1), "available_gib": round(available / 1024 ** 2, 1)}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return {"total_gib": None, "available_gib": None}


def inventory() -> dict:
    versions = {}
    for name in ("mediapipe", "numpy", "opencv-contrib-python"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    gpu = {"state": "nvidia_smi_absent"}
    if shutil.which("nvidia-smi"):
        try:
            check = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,memory.free",
                                    "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
            gpu = {"state": "available" if check.returncode == 0 else "driver_error", "inventory": check.stdout.strip()}
        except (OSError, subprocess.TimeoutExpired):
            gpu = {"state": "query_failed"}
    return {
        "platform": platform.platform(), "architecture": platform.machine(),
        "ram": memory_inventory(),
        "python": platform.python_version(), "python_compatible": sys.version_info[:2] == (3, 11),
        "dependencies": versions, "disk_free_gib": round(shutil.disk_usage(ROOT).free / 1024 ** 3, 1),
        "pose_asset": "verified" if model_matches(MODEL) else "missing_or_hash_mismatch",
        "gpu": gpu, "pose_compute": "CPU", "llm": "unchanged_not_loaded_or_tested",
    }


def pose_smoke() -> dict:
    from packages.pose.mediapipe_engine import MediaPipePoseEngine
    import cv2
    import numpy as np
    if not model_matches(MODEL):
        raise ValueError("Modèle de pose absent ou non vérifié")
    start = time.perf_counter()
    engine = MediaPipePoseEngine(str(MODEL))
    try:
        ok, encoded = cv2.imencode(".jpg", np.zeros((480, 640, 3), dtype=np.uint8))
        if not ok:
            raise RuntimeError("Encodage de test indisponible")
        observation = engine.detect(encoded.tobytes(), 0, "left")
        if observation.quality_reason != "no_pose":
            raise RuntimeError("Une image vide ne doit produire aucune pose")
        return {"state": "passed_blank_frame", "elapsed_ms": round((time.perf_counter() - start) * 1000),
                "limitation": "Initialisation et abstention uniquement ; aucune précision sur personne vérifiée"}
    finally:
        engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Vérifier l'installation sans modifier les modèles LLM")
    parser.add_argument("--pose-smoke", action="store_true", help="Initialiser le moteur expérimental sur une image noire")
    args = parser.parse_args()
    report = inventory()
    if args.pose_smoke:
        try:
            report["pose_smoke"] = pose_smoke()
        except (OSError, ValueError, RuntimeError, ImportError) as error:
            report["pose_smoke"] = {"state": "failed", "error": str(error)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.pose_smoke and report["pose_smoke"]["state"] != "passed_blank_frame":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
