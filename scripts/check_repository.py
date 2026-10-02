"""Garde-fou de publication : artefacts interdits et secrets usuels, sans les afficher."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {".mp4", ".mov", ".webm", ".avi", ".jpg", ".jpeg", ".png", ".wav", ".mp3", ".sqlite", ".db",
             ".gguf", ".safetensors", ".task", ".pem", ".key", ".p12", ".env"}
SECRET = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")


def main() -> None:
    paths = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT).split(b"\0")
    errors = []
    count = 0
    for raw in sorted(set(paths)):
        if not raw:
            continue
        path = ROOT / raw.decode("utf-8")
        if not path.is_file():
            continue
        count += 1
        if path.suffix.lower() in FORBIDDEN or path.name == ".env":
            errors.append(f"Artefact non publiable : {path.relative_to(ROOT)}")
        if path.stat().st_size > 2_000_000:
            errors.append(f"Fichier volumineux à examiner : {path.relative_to(ROOT)}")
            continue
        if SECRET.search(path.read_bytes()):
            errors.append(f"Secret potentiel : {path.relative_to(ROOT)}")
    if errors:
        print("\n".join(errors))
        raise SystemExit(1)
    print(f"{count} fichiers vérifiés : aucun artefact interdit ou secret usuel détecté (scan non exhaustif).")


if __name__ == "__main__":
    main()
