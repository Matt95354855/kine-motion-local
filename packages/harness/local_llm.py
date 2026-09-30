"""Client de génération vers un serveur compatible llama.cpp sur loopback."""

import json
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


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

    def check_model(self) -> bool:
        """Vérifie le modèle annoncé sans transmettre de données de séance."""
        request = Request(self.models_url, method="GET")
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=min(self.timeout_seconds, 3.0)) as response:
            body = response.read(64_001)
        if len(body) > 64_000:
            raise ValueError("Catalogue des modèles trop volumineux")
        document = json.loads(body)
        return any(
            isinstance(item, dict) and item.get("id") == self.model
            for item in document["data"]
        )

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": 2048,
                "stream": False,
            }
        ).encode("utf-8")
        request = Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=self.timeout_seconds) as response:
            body = response.read(256_001)
        if len(body) > 256_000:
            raise ValueError("Réponse LLM trop volumineuse")
        document = json.loads(body)
        return document["choices"][0]["message"]
