"""Installation explicite du seul modèle de pose ; ne touche pas aux LLM."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "infra" / "pose-model.json").read_text(encoding="utf-8"))
MODEL = ROOT / "models" / MANIFEST["filename"]


def model_matches(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest() == MANIFEST["sha256"]


def prepare(download: bool = False) -> Path:
    if model_matches(MODEL):
        return MODEL
    if MODEL.exists():
        raise ValueError("Modèle présent mais SHA-256 différent : examinez-le avant de le remplacer")
    if not download:
        raise FileNotFoundError("Modèle absent. Installer explicitement avec --download, hors séance")
    MODEL.parent.mkdir(exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=MODEL.parent, suffix=".part", delete=False) as handle:
            temporary = Path(handle.name)
            size = 0
            with build_opener(ProxyHandler({})).open(MANIFEST["url"], timeout=60) as response:
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > 32 * 1024 * 1024:
                        raise ValueError("Ressource de pose anormalement volumineuse")
                    handle.write(block)
        if not model_matches(temporary):
            raise ValueError("Échec de l'intégrité SHA-256 : modèle non installé")
        os.replace(temporary, MODEL)
        return MODEL
    finally:
        if temporary and temporary.exists():
            temporary.unlink()  # Uniquement notre téléchargement temporaire.


def main() -> None:
    parser = argparse.ArgumentParser(description="Vérifier ou installer le modèle de pose local")
    parser.add_argument("--download", action="store_true", help="Autoriser ce téléchargement explicite avant la séance")
    args = parser.parse_args()
    try:
        print(f"Modèle vérifié : {prepare(args.download)}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
