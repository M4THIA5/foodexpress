"""Tests du Gateway : auth mockée, routage/reverse-proxy, pannes amont, agrégation BFF."""


# --------------------------------------------------------------- Authentification
def test_missing_auth_returns_401(client):
    resp = client.get("/api/v1/orders/1")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_invalid_scheme_returns_401(client):
    resp = client.get("/api/v1/orders/1", headers={"Authorization": "Token abc"})
    assert resp.status_code == 401


def test_empty_bearer_returns_401(client):
    resp = client.get("/api/v1/orders/1", headers={"Authorization": "Bearer   "})
    assert resp.status_code == 401


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


# --------------------------------------------------------------------- Routage
def test_routes_resource_to_correct_service(client, backend):
    from tests.conftest import AUTH

    resp = client.get("/api/v1/orders/1", headers=AUTH)
    assert resp.status_code == 200
    sent = backend.requests[-1]
    assert sent.url.host == "commande"  # topologie masquée au client, résolue ici
    assert sent.url.path == "/api/v1/orders/1"


def test_routes_payments_to_paiement(client, backend):
    from tests.conftest import AUTH

    client.get("/api/v1/payments/9", headers=AUTH)
    assert backend.requests[-1].url.host == "paiement"


def test_unknown_resource_returns_404(client):
    from tests.conftest import AUTH

    resp = client.get("/api/v1/widgets/1", headers=AUTH)
    assert resp.status_code == 404


def test_forwards_method_body_and_relays_status(client, backend):
    from tests.conftest import AUTH

    backend.responses[("POST", "/api/v1/payments")] = (201, {"id": 42})
    resp = client.post("/api/v1/payments", json={"order_id": "abc"}, headers=AUTH)
    assert resp.status_code == 201
    assert resp.json() == {"id": 42}
    sent = backend.requests[-1]
    assert sent.method == "POST"
    assert sent.url.host == "paiement"
    assert b"order_id" in sent.content


def test_relays_business_error_status(client, backend):
    from tests.conftest import AUTH

    backend.responses[("POST", "/api/v1/payments")] = (402, {"motif": "refusé"})
    resp = client.post("/api/v1/payments", json={"montant": 1200}, headers=AUTH)
    assert resp.status_code == 402  # verdict métier relayé tel quel


def test_query_params_forwarded(client, backend):
    from tests.conftest import AUTH

    client.get("/api/v1/restaurants/1/menu?lang=fr", headers=AUTH)
    assert backend.requests[-1].url.params.get("lang") == "fr"


def test_propagates_user_id_and_strips_token(client, backend):
    from tests.conftest import AUTH

    client.get("/api/v1/orders/1", headers=AUTH)
    sent = backend.requests[-1]
    assert sent.headers["X-User-Id"] == "demo-token"
    assert "authorization" not in sent.headers  # auth terminée au Gateway


# ---------------------------------------------------------- Pannes amont
def test_downstream_timeout_returns_504(client, backend):
    from tests.conftest import AUTH

    backend.fail = "timeout"
    resp = client.get("/api/v1/orders/1", headers=AUTH)
    assert resp.status_code == 504


def test_downstream_unreachable_returns_502(client, backend):
    from tests.conftest import AUTH

    backend.fail = "connect"
    resp = client.get("/api/v1/orders/1", headers=AUTH)
    assert resp.status_code == 502



# ----------------------------------------------------------- Agrégation BFF
def test_bff_aggregates_commande_and_livraison(client, backend):
    from tests.conftest import AUTH

    backend.responses[("GET", "/api/v1/orders/1")] = (200, {"statut": "CONFIRMED"})
    backend.responses[("GET", "/api/v1/deliveries/1")] = (200, {"livreur": "Léo"})
    resp = client.get("/api/v1/orders/1/suivi", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["order_id"] == "1"
    assert body["commande"] == {"statut": "CONFIRMED"}
    assert body["livraison"] == {"livreur": "Léo"}


def test_bff_livraison_absent_is_null(client, backend):
    from tests.conftest import AUTH

    backend.responses[("GET", "/api/v1/orders/1")] = (200, {"statut": "PENDING"})
    backend.responses[("GET", "/api/v1/deliveries/1")] = (404, {"detail": "absente"})
    body = client.get("/api/v1/orders/1/suivi", headers=AUTH).json()
    assert body["commande"] == {"statut": "PENDING"}
    assert body["livraison"] is None


def test_bff_order_not_found_returns_404(client, backend):
    from tests.conftest import AUTH

    backend.responses[("GET", "/api/v1/orders/1")] = (404, {"detail": "absente"})
    resp = client.get("/api/v1/orders/1/suivi", headers=AUTH)
    assert resp.status_code == 404
