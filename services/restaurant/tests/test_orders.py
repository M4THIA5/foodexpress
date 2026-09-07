"""Acceptation / refus (étape sync SAGA) et compensation (cancel)."""
API = "/api/v1"


def _order(order_id: str, plat_id: int, quantite: int = 1) -> dict:
    return {"order_id": order_id, "items": [{"plat_id": plat_id, "quantite": quantite}]}


def test_accept_order(client):
    r = client.post(f"{API}/restaurants/1/orders", json=_order("cmd-1", 11))
    assert r.status_code == 200
    assert r.json()["statut"] == "ACCEPTED"


def test_refuse_closed_restaurant(client):
    # Restaurant 3 = fermé → refus déterministe (levier de démo).
    r = client.post(f"{API}/restaurants/3/orders", json=_order("cmd-2", 31))
    assert r.status_code == 409
    body = r.json()
    assert body["statut"] == "REFUSED"
    assert "fermé" in body["motif"].lower()


def test_refuse_unavailable_plat(client):
    # Tiramisu (11) indisponible chez le restaurant 1.
    r = client.post(f"{API}/restaurants/1/orders", json=_order("cmd-3", 13))
    assert r.status_code == 409
    assert r.json()["statut"] == "REFUSED"


def test_refuse_unknown_plat(client):
    r = client.post(f"{API}/restaurants/1/orders", json=_order("cmd-4", 999))
    assert r.status_code == 409
    assert "inconnu" in r.json()["motif"].lower()


def test_accept_is_idempotent(client):
    first = client.post(f"{API}/restaurants/1/orders", json=_order("cmd-5", 11))
    second = client.post(f"{API}/restaurants/1/orders", json=_order("cmd-5", 11))
    assert first.status_code == second.status_code == 200
    assert second.json()["statut"] == "ACCEPTED"


def test_refuse_replay_returns_409(client):
    # Une re-tentative SAGA d'une commande refusée rejoue le même verdict.
    first = client.post(f"{API}/restaurants/3/orders", json=_order("cmd-6", 31))
    second = client.post(f"{API}/restaurants/3/orders", json=_order("cmd-6", 31))
    assert first.status_code == second.status_code == 409


def test_cancel_accepted_order(client):
    client.post(f"{API}/restaurants/1/orders", json=_order("cmd-7", 11))
    r = client.post(f"{API}/restaurants/orders/cmd-7/cancel")
    assert r.status_code == 200
    assert r.json()["statut"] == "CANCELLED"


def test_cancel_is_idempotent_and_noop_on_unknown(client):
    # La compensation doit toujours aboutir, même sur une commande inconnue.
    r1 = client.post(f"{API}/restaurants/orders/inconnue/cancel")
    r2 = client.post(f"{API}/restaurants/orders/inconnue/cancel")
    assert r1.status_code == r2.status_code == 200
    assert r2.json()["statut"] == "CANCELLED"
