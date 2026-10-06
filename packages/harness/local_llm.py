"""Client de génération vers un serveur compatible llama.cpp sur loopback."""

import json
from http.client import HTTPConnection, HTTPException
import socket
from threading import Event, Thread
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from packages.harness.control import InferenceControl


_MAX_RESPONSE_BYTES = 256_000


def _message_from_body(body: bytes) -> dict:
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("Réponse LLM trop volumineuse")
    try:
        document = json.loads(body)
    except RecursionError:
        raise ValueError("Enveloppe LLM trop imbriquée") from None
    if not isinstance(document, dict):
        raise ValueError("Enveloppe LLM invalide")
    choices = document.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("Choix LLM invalide")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("Message LLM invalide")
    return message


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ValueError("Redirection du serveur LLM refusée")


class LocalLLMClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 20.0) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "::1")
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Le LLM doit être sur une adresse HTTP loopback explicite")
        if not model or timeout_seconds <= 0:
            raise ValueError("Modèle et délai requis")
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.models_url = base_url.rstrip("/") + "/v1/models"
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._host = parsed.hostname
        self._port = parsed.port if parsed.port is not None else 80

    def check_model(self) -> bool:
        """Vérifie le modèle annoncé sans transmettre de données de séance."""
        request = Request(self.models_url, method="GET")
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=min(self.timeout_seconds, 3.0)) as response:
            body = response.read(64_001)
        if len(body) > 64_000:
            raise ValueError("Catalogue des modèles trop volumineux")
        try:
            document = json.loads(body)
        except RecursionError:
            raise ValueError("Catalogue des modèles trop imbriqué") from None
        if not isinstance(document, dict) or not isinstance(document.get("data"), list):
            raise ValueError("Catalogue des modèles invalide")
        return any(
            isinstance(item, dict) and item.get("id") == self.model
            for item in document["data"]
        )

    def _payload(self, messages: list[dict], tools: list[dict]) -> bytes:
        return json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": 2048,
                "stream": False,
            }
        ).encode("utf-8")

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        request = Request(
            self.url,
            data=self._payload(messages, tools),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=self.timeout_seconds) as response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
        return _message_from_body(body)

    def complete_controlled(
        self, messages: list[dict], tools: list[dict], control: InferenceControl
    ) -> dict:
        """Interrompt l'attente locale, y compris headers et corps au compte-gouttes.

        Le socket est enregistré avant connect/send/read : le watcher unique peut
        le fermer à toute étape. Aucun proxy ni aucune redirection n'est utilisé.
        Le budget est celui du travail entier, non réinitialisé à chaque tour.
        """
        control.check()
        payload = self._payload(messages, tools)
        timeout = min(self.timeout_seconds, control.remaining_seconds())
        connection = HTTPConnection(self._host, self._port, timeout=timeout)
        family = socket.AF_INET6 if self._host == "::1" else socket.AF_INET
        transport = socket.socket(family, socket.SOCK_STREAM)
        transport.settimeout(timeout)
        connection.sock = transport
        watcher_done = Event()

        def close_transport() -> None:
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            transport.close()

        def watch_budget() -> None:
            while not watcher_done.is_set():
                try:
                    control.check()
                except TimeoutError:
                    close_transport()
                    return
                watcher_done.wait(0.02)

        watcher = Thread(target=watch_budget, name="llm-budget-watch", daemon=True)
        watcher_started = False
        response = None
        try:
            watcher.start()
            watcher_started = True
            transport.connect((self._host, self._port))
            control.check()
            connection.request(
                "POST", "/v1/chat/completions", body=payload,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            control.check()
            if 300 <= response.status < 400:
                raise ValueError("Redirection du serveur LLM refusée")
            if not 200 <= response.status < 300:
                raise OSError("Le serveur LLM a refusé la requête")
            if response.length is not None and response.length > _MAX_RESPONSE_BYTES:
                raise ValueError("Réponse LLM trop volumineuse")
            body = bytearray()
            while True:
                control.check()
                chunk = response.read1(min(8192, _MAX_RESPONSE_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise ValueError("Réponse LLM trop volumineuse")
            if response.length is not None and response.length > 0:
                raise ValueError("Réponse LLM tronquée")
            control.check()
            message = _message_from_body(bytes(body))
            control.check()
            return message
        except HTTPException:
            control.check()
            raise OSError("Réponse HTTP du serveur LLM invalide") from None
        except Exception:
            # shutdown peut produire EOF, BadStatusLine ou OSError : exposer la
            # cause d'annulation/deadline stable plutôt que l'erreur du socket.
            control.check()
            raise
        finally:
            watcher_done.set()
            close_transport()
            if response is not None:
                response.close()
            connection.close()
            if watcher_started:
                watcher.join(timeout=0.2)
