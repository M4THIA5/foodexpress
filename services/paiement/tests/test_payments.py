"""Débit via le PSP mocké (étape sync SAGA Commande → Paiement).

- Succès → 201 CAPTURED.
- Refus PSP (levier de démo : montant élevé) → 402 DECLINED.
- Idempotent par `order_id` : une re-tentative SAGA rejoue le même verdict.
"""
API = "/api/v1"


def _debit(order_id: str, montant: float) -> dict:
    return {"order_id": order_id, "montant": montant}


def test_debit_success(client):
    r = client.post(f"{API}/payments", json=_debit("cmd-1", 25.00))
    assert r.status_code == 201
    body = r.json()
    assert body["statut"] == "CAPTURED"
    assert body["order_id"] == "cmd-1"
    assert body["montant"] == 25.00
    assert body["montant_rembourse"] == 0
    assert body["psp_reference"]  # référence PSP renseignée


def test_debit_declined_over_threshold(client):
    # Montant >= 1000 € → refus déterministe du PSP (levier de démo SAGA).
    r = client.post(f"{API}/payments", json=_debit("cmd-2", 1500.00))
    assert r.status_code == 402
    body = r.json()
    assert body["statut"] == "DECLINED"
    assert "insuffisant" in body["motif"].lower()


def test_debit_idempotent_by_order_id(client):
    first = client.post(f"{API}/payments", json=_debit("cmd-3", 30.00))
    second = client.post(f"{API}/payments", json=_debit("cmd-3", 30.00))
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_debit_idempotent_preserves_declined(client):
    first = client.post(f"{API}/payments", json=_debit("cmd-4", 2000.00))
    second = client.post(f"{API}/payments", json=_debit("cmd-4", 2000.00))
    assert first.status_code == second.status_code == 402
    assert second.json()["statut"] == "DECLINED"


def test_debit_rejects_non_positive_amount(client):
    r = client.post(f"{API}/payments", json=_debit("cmd-5", 0))
    assert r.status_code == 422


def test_get_payment(client):
    created = client.post(f"{API}/payments", json=_debit("cmd-6", 12.50)).json()
    r = client.get(f"{API}/payments/{created['id']}")
    assert r.status_code == 200
    assert r.json()["order_id"] == "cmd-6"


def test_get_unknown_payment(client):
    r = client.get(f"{API}/payments/999")
    assert r.status_code == 404
