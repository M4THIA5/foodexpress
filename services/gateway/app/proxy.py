"""Client HTTP sortant résilient du Gateway (Timeout + Retry — architecture.md §7, §8).

Le Gateway est un reverse-proxy : il relaie la requête cliente vers le service amont
puis renvoie sa réponse. Chaque appel sortant porte un **Timeout court** et un
**Retry limité** sur erreurs transitoires. Une panne amont (réseau/timeout après
retries) est convertie en `GatewayError` — traduite en **502/504** côté client — la
topologie interne restant masquée.

Le client est asynchrone (`httpx.AsyncClient`) : un proxy est I/O-bound et peut
relayer plusieurs appels en parallèle (voir l'agrégation BFF). `ProxyClient` est
injecté via `get_proxy`, surchargeable en test (transport simulé).
"""
from __future__ import annotations

import httpx
from fastapi import Response

from app.downstreams import DOWNSTREAMS

# Timeout court : on ne bloque pas le client si un service amont est en panne.
GATEWAY_TIMEOUT = 5.0
# Retry limité sur erreurs transitoires (idempotent au niveau transport).
GATEWAY_ATTEMPTS = 2

# En-têtes à ne pas relayer tels quels vers l'amont (hop-by-hop / recalculés /
# terminaison d'auth au Gateway — voir auth.py qui réémet `X-User-Id`).
_STRIP_REQUEST_HEADERS = {"host", "content-length", "connection", "authorization"}
# En-têtes de réponse recalculés par le serveur ASGI ou gérés via `media_type`.
_STRIP_RESPONSE_HEADERS = {
    "content-length",
    "content-type",
    "connection",
    "transfer-encoding",
}


class GatewayError(Exception):
    """Service amont injoignable après Timeout + Retry → réponse 502/504."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProxyClient:
    """Relaie une requête vers un service amont avec Timeout + Retry."""

    def __init__(
        self,
        base_urls: dict[str, str],
        client: httpx.AsyncClient | None = None,
        attempts: int = GATEWAY_ATTEMPTS,
    ) -> None:
        self._base = {name: url.rstrip("/") for name, url in base_urls.items()}
        self._client = client or httpx.AsyncClient(timeout=GATEWAY_TIMEOUT)
        self._attempts = attempts

    async def forward(
        self,
        service: str,
        method: str,
        path: str,
        *,
        params=None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        """Relaie l'appel vers `service` et renvoie sa réponse HTTP brute.

        Lève `GatewayError` (504 sur timeout, 502 sur autre panne réseau) une fois
        les tentatives épuisées ; un statut d'erreur *applicatif* (4xx/5xx renvoyé
        par l'amont) est en revanche relayé tel quel, sans retry.
        """
        url = f"{self._base[service]}{path}"
        fwd_headers = {
            k: v
            for k, v in (headers or {}).items()
            if k.lower() not in _STRIP_REQUEST_HEADERS
        }
        last: GatewayError | None = None
        for _ in range(self._attempts):
            try:
                return await self._client.request(
                    method, url, params=params, headers=fwd_headers, content=content
                )
            except httpx.TimeoutException as exc:
                last = GatewayError(f"{service} timeout : {exc}", status_code=504)
            except httpx.TransportError as exc:
                last = GatewayError(f"{service} injoignable : {exc}", status_code=502)
        assert last is not None
        raise last

    async def aclose(self) -> None:
        await self._client.aclose()


def to_response(resp: httpx.Response) -> Response:
    """Convertit une réponse amont `httpx` en réponse FastAPI relayée telle quelle."""
    headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in _STRIP_RESPONSE_HEADERS
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=headers,
        media_type=resp.headers.get("content-type"),
    )


# Instance partagée (réutilise le pool de connexions httpx entre requêtes).
_proxy: ProxyClient | None = None


def get_proxy() -> ProxyClient:
    """Dépendance FastAPI : client proxy partagé (surchargeable en test)."""
    global _proxy
    if _proxy is None:
        _proxy = ProxyClient(DOWNSTREAMS)
    return _proxy


async def close_proxy() -> None:
    """Ferme proprement le client partagé au shutdown (lifespan)."""
    global _proxy
    if _proxy is not None:
        await _proxy.aclose()
        _proxy = None
