"""Poste webcam : tunnel OpenSSH vers le calculateur, sans modèle ni capture disque.

Ne configure ni Windows, ni le pare-feu, ni les clés. OpenSSH demande lui-même
l'authentification et la vérification de l'empreinte du serveur dans le terminal.
"""

import argparse
from http.client import HTTPConnection, HTTPException
from ipaddress import ip_address
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import webbrowser


def ssh_command(server: str, user: str, port: int = 8765, ssh_port: int = 22,
                identity: str | None = None, executable: str = "ssh") -> list[str]:
    if not isinstance(server, str) or not server or server.startswith("-"):
        raise ValueError("Adresse du serveur requise, sans URL ni option SSH")
    try:
        ip_address(server)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", server):
            raise ValueError("Utilisez une adresse IP ou un nom DNS simple")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}", user):
        raise ValueError("Nom de compte Windows simple requis")
    if not all(isinstance(p, int) and not isinstance(p, bool) and 1 <= p <= 65535 for p in (port, ssh_port)):
        raise ValueError("Port invalide")
    command = [executable, "-F", "none", "-N", "-T", "-p", str(ssh_port), "-l", user,
               "-o", "StrictHostKeyChecking=ask", "-o", "UpdateHostKeys=no",
               "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
               "-o", "ServerAliveCountMax=2", "-o", "ForwardAgent=no",
               "-o", "ForwardX11=no", "-o", "PermitLocalCommand=no",
               "-L", f"127.0.0.1:{port}:127.0.0.1:{port}"]
    if identity:
        path = Path(identity).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("Clé SSH introuvable")
        command.extend(["-o", "IdentitiesOnly=yes", "-i", str(path)])
    command.append(server)
    return command


def check_available_port(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def ready(port: int) -> bool:
    connection = HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", "/api/status")
        response = connection.getresponse()
        body = response.read(32769)
        if response.status != 200 or len(body) > 32768:
            return False
        status = json.loads(body)
        return status.get("topology", {}).get("camera") == "browser_client" and isinstance(status.get("protocols"), list)
    except (OSError, ValueError, HTTPException, AttributeError):
        return False
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ouvrir Kiné depuis le poste doté d'une webcam")
    parser.add_argument("--server", required=True, help="IP privée du Windows GPU, ou adresse VPN")
    parser.add_argument("--user", required=True, help="Compte SSH du Windows")
    parser.add_argument("--port", type=int, default=8765, help="Même port sur le client et le serveur")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--identity", help="Chemin local d'une clé SSH ; jamais son contenu")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    executable = shutil.which("ssh")
    if not executable:
        parser.error("Client OpenSSH absent : voir docs/two-machine-setup.md")
    try:
        command = ssh_command(args.server, args.user, args.port, args.ssh_port, args.identity, executable)
        check_available_port(args.port)
    except (OSError, ValueError) as error:
        parser.error(str(error) + ". En cas de port occupé, changer --port sur les deux postes.")
    print("Vérifiez l'empreinte SSH sur le Windows avant de l'accepter. Aucun mot de passe n'est conservé par Kiné.")
    process = subprocess.Popen(command)  # Liste d'arguments, pas de shell ; SSH conserve son terminal natif.
    try:
        # L'authentification initiale peut prendre du temps : aucune caméra n'est
        # ouverte et aucune image n'est envoyée avant le choix dans le navigateur.
        while process.poll() is None:
            if ready(args.port):
                url = f"http://127.0.0.1:{args.port}"
                print(f"Kiné prêt : {url} — caméra sur CE poste, calcul sur le Windows. Ctrl+C ferme le tunnel.")
                if not args.no_browser:
                    webbrowser.open(url)
                process.wait()
                break
            time.sleep(0.5)
        if process.returncode:
            parser.exit(1, "Tunnel fermé : vérifier le compte, l'empreinte, OpenSSH et le serveur Kiné sur le Windows.\n")
    except KeyboardInterrupt:
        print("Tunnel fermé. Le navigateur doit arrêter l'essai si la connexion est perdue.")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
