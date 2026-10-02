"""Lanceur multiplateforme ; délègue les options LLM existantes sans les changer."""

import argparse
import subprocess
import sys

from scripts.prepare_pose import ROOT, prepare


def main() -> None:
    parser = argparse.ArgumentParser(description="Lancer Kiné local — aucun modèle LLM installé ou modifié")
    parser.add_argument("--demo", action="store_true", help="Pose fictive, sans dépendance externe")
    parser.add_argument("--experimental-pose", action="store_true", help="Autoriser le moteur réel non qualifié hors ligne")
    parser.add_argument("--port", type=int, default=8765)
    args, existing_options = parser.parse_known_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port invalide")
    command = [sys.executable, "-m", "services.api.server", "--port", str(args.port)]
    if args.demo:
        command.append("--demo-pose")
    else:
        if not args.experimental_pose:
            parser.error("Le moteur réel exige --experimental-pose ; choisir --demo pour l'interface seule")
        if sys.version_info[:2] != (3, 11):
            parser.error("Le profil reproductible de pose utilise Python 3.11 dans .venv")
        try:
            path = prepare()
            from scripts.check_install import pose_smoke
            pose_smoke()
        except (OSError, ValueError, RuntimeError, ImportError) as error:
            parser.exit(1, f"Pose non prête : {error}\n")
        command.extend(["--pose-model", str(path), "--experimental-pose"])
    command.extend(existing_options)
    try:
        raise SystemExit(subprocess.call(command, cwd=ROOT))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
