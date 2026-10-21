"""Instantané technique local, sans identité, chemins privés ou secrets LLM.

Calculé au démarrage du serveur et non à chaque image. Un commit seul ne décrit
pas un arbre modifié : le hash d'implémentation identifie aussi les fichiers du
périmètre déclaré. Les valeurs indisponibles restent nulles, jamais « vérifiées ».
"""

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import re
import subprocess
from urllib.parse import urlsplit
from unicodedata import category

from packages.harness.local_llm import LocalLLMClient
from packages.pose.mediapipe_engine import POSE_OPTIONS, PRESENCE_THRESHOLD, VISIBILITY_THRESHOLD


IMPLEMENTATION_FILES = (
    "apps/web/app.js", "apps/web/capture-core.js", "apps/web/guide.js",
    "apps/web/index.html", "apps/web/style.css", "packages/contracts/models.py",
    "packages/pose/adapter.py", "packages/pose/mediapipe_engine.py",
    "packages/pose/jpeg.py", "packages/pose/synthetic_engine.py",
    "packages/biomechanics/elbow.py", "packages/biomechanics/geometry.py",
    "packages/biomechanics/protocols.py", "packages/biomechanics/motion.py",
    "packages/harness/report.py", "packages/harness/final_note.py",
    "packages/harness/runner.py", "packages/harness/tools.py", "packages/harness/live.py",
    "packages/harness/window.py", "packages/harness/local_llm.py", "packages/harness/control.py",
    "services/api/state.py", "services/api/server.py", "services/api/live.py", "services/api/inference.py",
    "services/api/capture_integrity.py",
    "services/api/provenance.py", "infra/pose-model.json", "infra/requirements-pose.lock",
)
MAX_MODEL_BYTES = 32 * 1024 * 1024


def _attribute(object_, name: str):
    """Une métadonnée absente ou illisible n'est pas un diagnostic du runtime."""
    try:
        return getattr(object_, name, None)
    except Exception:
        return None


def _bounded_text(value, limit: int) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        return None
    if any(category(character).startswith("C") for character in value):
        return None
    return value


def _model_alias(client) -> str | None:
    value = _bounded_text(_attribute(client, "model"), 256)
    if value is None:
        return None
    # Conserver l'alias exact, ou null : ne jamais créer un autre nom en le
    # nettoyant. Un identifiant org/modèle est admis, pas un chemin privé ni URL.
    if (
        value.startswith(("/", "\\", "~", "./", "../"))
        or "\\" in value or "://" in value or "?" in value or "#" in value
        or re.match(r"^[A-Za-z]:[/\\]", value)
        or ("@" in value and ":" in value.split("@", 1)[0])
        or re.match(r"(?i)^(?:Bearer|Basic)\s+", value)
        or re.search(r"(?i)\b(?:api[_-]?key|token|password|secret)\s*[=:]", value)
    ):
        return None
    return value


def _local_endpoint(client) -> str | None:
    candidate = _attribute(client, "url")
    if candidate is None:
        candidate = _attribute(client, "base_url")
    if _bounded_text(candidate, 1024) is None:
        return None
    try:
        parsed = urlsplit(candidate)
        if (
            parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1")
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment
            or parsed.path not in ("", "/", "/v1", "/v1/", "/v1/chat/completions", "/v1/models")
        ):
            return None
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            return None
        host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
        suffix = f":{port}" if port is not None else ""
        return f"http://{host}{suffix}/v1"
    except (TypeError, ValueError):
        return None


def llm_binding_provenance(bindings: dict | None, declared_quantization: str | None = None) -> list[dict]:
    """Décrit la configuration, jamais un chargement ou un appel LLM effectif.

    Aucun endpoint n'est contacté. Alias et vision correspondent au client local
    déclaré ; version du runtime, révision/poids et quantification sont inconnus.
    FP4 est uniquement un choix déclaré pour les deux modèles du projet, pas une
    inspection des poids. Un éventuel modèle personnalisé ne l'hérite pas.
    """
    if not isinstance(bindings, dict):
        return []
    declaration = _bounded_text(declared_quantization, 32)
    descriptors = []
    for model_id, binding in bindings.items():
        if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", model_id):
            continue
        client = _attribute(binding, "client")
        configured = client is not None
        endpoint = _local_endpoint(client) if configured else None
        descriptors.append({
            "id": model_id, "label": _bounded_text(_attribute(binding, "label"), 128),
            "configured": configured,
            "model_alias": _model_alias(client) if configured else None,
            "endpoint": endpoint,
            "api_style": "openai_compatible_chat_completions" if (
                isinstance(client, LocalLLMClient) and endpoint is not None
            ) else None,
            "vision_supported": _attribute(binding, "supports_images") is True,
            "vision_enabled": configured and _attribute(binding, "image_enabled") is True,
            "model_revision": None, "runtime_version": None,
            "configured_quantization": None,
            "declared_quantization_choice": declaration if model_id in ("gpt_oss", "qwen36") else None,
            "quantization_verified": None,
        })
    return descriptors


def _git(root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True,
                                text=True, timeout=2, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def _implementation_digest(root: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        for name in IMPLEMENTATION_FILES:
            path = root / name
            if path.is_symlink() or path.stat().st_size > 2_000_000:
                return None
            content = path.read_bytes()
            # Chemins relatifs et longueurs évitent les concaténations ambiguës.
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(str(len(content)).encode("ascii") + b"\0" + content)
        return digest.hexdigest()
    except OSError:
        return None


def analysis_provenance(
    root: Path, pose_mode: str, model_path: str | None = None,
    llm_bindings: dict | None = None, declared_quantization: str | None = None,
) -> dict:
    """Inventaire du code/pose réellement configurés ; aucun chargement de LLM."""
    root = Path(root)
    commit = _git(root, "rev-parse", "HEAD")
    if commit is not None and not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        commit = None
    status = _git(root, "status", "--porcelain", "--untracked-files=normal")
    mode = pose_mode if pose_mode in ("mediapipe_experimental", "synthetic_demo") else "unknown"
    package_version = None
    configured_hash = actual_hash = verified = None
    if mode == "mediapipe_experimental":
        try:
            package_version = version("mediapipe")
        except PackageNotFoundError:
            pass
        try:
            manifest = json.loads((root / "infra" / "pose-model.json").read_text(encoding="utf-8"))
            candidate = manifest.get("sha256")
            if isinstance(candidate, str) and re.fullmatch(r"[0-9a-f]{64}", candidate):
                configured_hash = candidate
        except (OSError, ValueError, AttributeError):
            pass
        if model_path is not None:
            try:
                path = Path(model_path)
                if path.is_file() and path.stat().st_size <= MAX_MODEL_BYTES:
                    with path.open("rb") as handle:
                        actual_hash = hashlib.file_digest(handle, "sha256").hexdigest()
            except OSError:
                pass
            if actual_hash is not None and configured_hash is not None:
                verified = actual_hash == configured_hash
    return {
        "schema_version": "1.0", "snapshot": "server_startup",
        "git_commit": commit, "working_tree_dirty": bool(status) if status is not None else None,
        "implementation_sha256": _implementation_digest(root),
        "implementation_hash_scope": "pose_geometry_capture_contracts_report_harness_transport_lifecycle",
        "python_version": platform.python_version(), "pose_engine": mode,
        "pose_package_version": package_version,
        "pose_model": {"sha256": actual_hash, "configured_sha256": configured_hash, "hash_verified": verified},
        "pose_settings": {
            **POSE_OPTIONS, "delegate": "CPU", "running_mode": "VIDEO",
            "landmark_visibility_threshold": VISIBILITY_THRESHOLD,
            "landmark_presence_threshold": PRESENCE_THRESHOLD,
        } if mode == "mediapipe_experimental" else None,
        "llm_runtime": {
            "schema_version": "1.0", "snapshot": "server_startup_configuration",
            "models": llm_binding_provenance(llm_bindings, declared_quantization),
        },
    }
