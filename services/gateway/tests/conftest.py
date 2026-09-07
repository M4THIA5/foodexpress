"""Fixtures de test Gateway : services amont simulés via `httpx.MockTransport`.

On n'exécute aucun vrai HTTP : le `ProxyClient` est reconstruit autour d'un
transport simulé (`FakeBackend`) qui enregistre les requêtes relayées, renvoie des
réponses configurables et peut simuler pannes/timeouts (pour Timeout + Retry). La
dépendance `get_proxy` est surchargée pour l'injecter.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.downstreams import DOWNSTREAMS
from app.main import app
from app.proxy import ProxyClient, get_proxy

# Jeton mock accepté par l'auth du Gateway (tout Bearer non vide passe).
AUTH = {"Authorization": "Bearer demo-token"}


class FakeBackend:
    """Double des services amont : enregistre les appels, réponses pilotables."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        # Réponses par (méthode, chemin) → (status, corps JSON). Défaut : 200.
        self.responses: dict[tuple[str, str], tuple[int, dict]] = {}
        # Simulation de panne : "timeout" | "connect" | None.
        self.fail: str | None = None
        # Nombre d'échecs transitoires avant succès (pour tester le Retry).
        self.fail_times = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise httpx.ConnectError("panne transitoire", request=request)
        if self.fail == "timeout":
            raise httpx.ReadTimeout("amont lent", request=request)
        if self.fail == "connect":
            raise httpx.ConnectError("amont injoignable", request=request)
        status, payload = self.responses.get(
            (request.method, request.url.path),
            (200, {"path": request.url.path, "host": request.url.host}),
        )
        return httpx.Response(status, json=payload)


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def client(backend):
    transport = httpx.MockTransport(backend.handler)
    proxy = ProxyClient(DOWNSTREAMS, client=httpx.AsyncClient(transport=transport))
    app.dependency_overrides[get_proxy] = lambda: proxy
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
