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

import asyncio
import random

import httpx
from fastapi import Response

from app.downstreams import DOWNSTREAMS

# Les timeouts décroissent en descendant la chaîne, sinon le Gateway abandonne avant
# que Commande n'ait fini de compenser. Pire cas d'une SAGA : menu 1 s + acceptation 1 s
# + débit ~3,6 s (3 essais et backoff) + annulation 1 s, soit environ 6,6 s.
COMMANDE_TIMEOUT = 8.0
# Les autres services sont des feuilles : leur réponse nominale prend quelques ms.
GATEWAY_TIMEOUT = 2.0
SERVICE_TIMEOUTS = {"commande": COMMANDE_TIMEOUT}
# Retry : seules les lectures sont rejouées. Rejouer un `POST /orders` créerait une
# seconde commande, car l'identifiant est généré par Commande.
GATEWAY_ATTEMPTS = 3
GATEWAY_BASE_DELAY = 0.05
IDEMPOTENT_METHODS = {"GET", "HEAD"}
# Bulkhead : un pool de connexions par service. Une panne de Commande ne peut plus priver
# les menus de connexions. 50 dépasse les 40 threads de Commande sans empiler d'attente.
SERVICE_MAX_CONNECTIONS = {"commande": 50}
DEFAULT_MAX_CONNECTIONS = 30
# Pool plein : on refuse tout de suite plutôt que de faire attendre le client.
POOL_TIMEOUT = 0.1

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
        # `client` (tests) remplace tous les pools par un seul transport simulé.
        self._clients = {
            name: client
            or httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=SERVICE_MAX_CONNECTIONS.get(
                        name, DEFAULT_MAX_CONNECTIONS
                    )
                )
            )
            for name in self._base
        }
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

        Lève `GatewayError` (503 si le pool du service est plein, 504 sur timeout, 502
        sur autre panne réseau) une fois
        les tentatives épuisées ; un statut d'erreur *applicatif* (4xx/5xx renvoyé
        par l'amont) est en revanche relayé tel quel, sans retry.
        """
        url = f"{self._base[service]}{path}"
        fwd_headers = {
            k: v
            for k, v in (headers or {}).items()
            if k.lower() not in _STRIP_REQUEST_HEADERS
        }
        attempts = self._attempts if method.upper() in IDEMPOTENT_METHODS else 1
        last: GatewayError | None = None
        for attempt in range(attempts):
            if attempt:
                delay = GATEWAY_BASE_DELAY * 2 ** (attempt - 1)
                await asyncio.sleep(delay + random.uniform(0, delay))
            try:
                return await self._clients[service].request(
                    method,
                    url,
                    params=params,
                    headers=fwd_headers,
                    content=content,
                    timeout=httpx.Timeout(
                        SERVICE_TIMEOUTS.get(service, GATEWAY_TIMEOUT),
                        pool=POOL_TIMEOUT,
                    ),
                )
            except httpx.PoolTimeout as exc:
                raise GatewayError(f"{service} saturé : {exc}", status_code=503) from exc
            except httpx.TimeoutException as exc:
                # Pas de nouvel essai : l'amont a déjà épuisé son budget, et Commande
                # a déjà rejoué ses propres appels. Rejouer ici multiplierait la charge.
                raise GatewayError(f"{service} timeout : {exc}", status_code=504) from exc
            except httpx.TransportError as exc:
                last = GatewayError(f"{service} injoignable : {exc}", status_code=502)
        assert last is not None
        raise last

    async def aclose(self) -> None:
        for client in set(self._clients.values()):
            await client.aclose()


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
