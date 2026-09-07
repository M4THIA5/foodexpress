"""Remboursement total / partiel (compensation SAGA Paiement.refund()).

La compensation doit toujours pouvoir aboutir et être rejouable sans double
effet (idempotence du remboursement total).
"""
API = "/api/v1"


def _debit(order_id: str, montant: float) -> dict:
    return {"order_id": order_id, "montant": montant}


def _capture(client, order_id: str, montant: float) -> dict:
    r = client.post(f"{API}/payments", json=_debit(order_id, montant))
    assert r.status_code == 201
    return r.json()


def test_refund_full(client):
    tx = _capture(client, "cmd-1", 30.00)
    r = client.post(f"{API}/payments/{tx['id']}/refund", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["montant"] == 30.00
    assert body["statut_transaction"] == "REFUNDED"
    assert body["montant_restant"] == 0


def test_refund_partial(client):
    tx = _capture(client, "cmd-2", 40.00)
    r = client.post(f"{API}/payments/{tx['id']}/refund", json={"montant": 15.00})
    assert r.status_code == 200
    body = r.json()
    assert body["montant"] == 15.00
    assert body["statut_transaction"] == "PARTIALLY_REFUNDED"
    assert body["montant_restant"] == 25.00


def test_refund_partial_then_remaining(client):
    tx = _capture(client, "cmd-3", 40.00)
    client.post(f"{API}/payments/{tx['id']}/refund", json={"montant": 15.00})
    r = client.post(f"{API}/payments/{tx['id']}/refund", json={})  # solde restant
    assert r.status_code == 200
    body = r.json()
    assert body["montant"] == 25.00
    assert body["statut_transaction"] == "REFUNDED"
    assert body["montant_restant"] == 0


def test_refund_exceeds_remaining(client):
    tx = _capture(client, "cmd-4", 20.00)
    r = client.post(f"{API}/payments/{tx['id']}/refund", json={"montant": 50.00})
    assert r.status_code == 409


def test_refund_unknown_transaction(client):
    r = client.post(f"{API}/payments/999/refund", json={})
    assert r.status_code == 404


def test_refund_declined_transaction(client):
    declined = client.post(f"{API}/payments", json=_debit("cmd-5", 1500.00)).json()
    r = client.post(f"{API}/payments/{declined['id']}/refund", json={})
    assert r.status_code == 409


def test_refund_full_is_idempotent(client):
    # Compensation SAGA rejouée : un second remboursement total est un no-op 200.
    tx = _capture(client, "cmd-6", 30.00)
    first = client.post(f"{API}/payments/{tx['id']}/refund", json={})
    second = client.post(f"{API}/payments/{tx['id']}/refund", json={})
    assert first.status_code == second.status_code == 200
    assert second.json()["statut_transaction"] == "REFUNDED"
    assert second.json()["montant_restant"] == 0
