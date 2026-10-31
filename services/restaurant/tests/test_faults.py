"""Injection de panne intermittente : une requête d'API sur N répond 503."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.faults import add_fault_injection
from common.config import settings


def _client() -> TestClient:
    app = FastAPI()
    add_fault_injection(app)

    @app.get("/api/v1/ping")
    def ping() -> dict:
        return {}

    @app.get("/health")
    def health() -> dict:
        return {}

    return TestClient(app)


def test_one_request_out_of_three_fails(monkeypatch):
    monkeypatch.setattr(settings, "restaurant_error_every", 3)
    client = _client()
    codes = [client.get("/api/v1/ping").status_code for _ in range(6)]
    assert codes == [200, 200, 503, 200, 200, 503]


def test_disabled_by_default():
    client = _client()
    assert {client.get("/api/v1/ping").status_code for _ in range(6)} == {200}


def test_health_is_spared(monkeypatch):
    monkeypatch.setattr(settings, "restaurant_error_every", 1)
    client = _client()
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/ping").status_code == 503
