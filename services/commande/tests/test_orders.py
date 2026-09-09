"""SAGA de passage de commande (chemin nominal + compensations).

Chaque scénario correspond à une branche du diagramme de séquence (architecture.md
§5.3). Les verdicts Restaurant/Paiement sont pilotés par le `FakeClients`.
"""
API = "/api/v1"


def _order(items=None, client_id=1, restaurant_id=1) -> dict:
    return {
        "client_id": client_id,
        "restaurant_id": restaurant_id,
        "items": items or [{"plat_id": 11, "quantite": 2}],
    }


def _steps(body) -> dict:
    """Table {etape: statut} de la trace SAGA d'une réponse OrderOut."""
    return {s["etape"]: s["statut"] for s in body["saga_steps"]}


# ------------------------------------------------------------------- Chemin OK
def test_order_snapshot_and_total(client):
    r = client.post(f"{API}/orders", json=_order([{"plat_id": 11, "quantite": 2}]))
    assert r.status_code == 201
    body = r.json()
    assert body["statut"] == "AWAITING_DELIVERY"
    # Snapshot copié du menu + total calculé (11.50 * 2).
    assert body["items"][0]["nom_snapshot"] == "Pizza Margherita"
    assert body["montant_total"] == 23.00
    assert body["transaction_id"] is not None
    steps = _steps(body)
    assert steps["RESTAURANT_ACCEPT"] == "OK"
    assert steps["PAYMENT"] == "OK"
    assert steps["DELIVERY_REQUESTED"] == "OK"


def test_delivery_assigned_confirms_order(client):
    order_id = client.post(f"{API}/orders", json=_order()).json()["id"]
    r = client.post(f"{API}/orders/{order_id}/delivery-result", json={"success": True})
    assert r.status_code == 200
    body = r.json()
    assert body["statut"] == "CONFIRMED"
    assert _steps(body)["ORDER_CONFIRMED"] == "OK"


# ------------------------------------------------------- Compensation livraison
def test_delivery_failed_triggers_refund_and_cancel(client, clients):
    created = client.post(f"{API}/orders", json=_order()).json()
    order_id, txn = created["id"], created["transaction_id"]

    r = client.post(f"{API}/orders/{order_id}/delivery-result", json={"success": False})
    assert r.status_code == 200
    body = r.json()
    assert body["statut"] == "CANCELLED"
    # Compensations effectivement déclenchées (remboursement + annulation resto).
    assert clients.refunded == [txn]
    assert order_id in clients.cancelled
    steps = _steps(body)
    assert steps["COMPENSATION_PAYMENT"] == "COMPENSATED"
    assert steps["COMPENSATION_RESTAURANT"] == "COMPENSATED"


def test_delivery_result_is_idempotent_on_terminal_order(client):
    order_id = client.post(f"{API}/orders", json=_order()).json()["id"]
    client.post(f"{API}/orders/{order_id}/delivery-result", json={"success": True})
    # Rejouer sur une commande déjà CONFIRMED est un no-op (pas d'erreur).
    r = client.post(f"{API}/orders/{order_id}/delivery-result", json={"success": False})
    assert r.status_code == 200
    assert r.json()["statut"] == "CONFIRMED"


# -------------------------------------------------------- Refus / échec amont
def test_restaurant_refusal_cancels_without_payment(client, clients):
    clients.accept = False
    clients.accept_motif = "Restaurant fermé"
    body = client.post(f"{API}/orders", json=_order()).json()
    assert body["statut"] == "CANCELLED"
    assert body["transaction_id"] is None
    # Rien n'a été engagé côté Paiement → aucune compensation.
    assert clients.refunded == []
    assert clients.cancelled == []
    assert _steps(body)["RESTAURANT_ACCEPT"] == "REFUSED"


def test_payment_declined_compensates_restaurant(client, clients):
    clients.payment = "declined"
    order_id = None
    body = client.post(f"{API}/orders", json=_order()).json()
    order_id = body["id"]
    assert body["statut"] == "CANCELLED"
    # Restaurant était accepté → compensation par annulation.
    assert order_id in clients.cancelled
    assert _steps(body)["PAYMENT"] == "DECLINED"


def test_payment_unavailable_compensates(client, clients):
    # Paiement en panne → compensation.
    clients.payment = "unavailable"
    body = client.post(f"{API}/orders", json=_order()).json()
    order_id = body["id"]
    assert body["statut"] == "CANCELLED"
    assert order_id in clients.cancelled
    assert _steps(body)["PAYMENT"] == "UNAVAILABLE"


def test_unknown_plat_cancels_before_accept(client, clients):
    body = client.post(f"{API}/orders", json=_order([{"plat_id": 999, "quantite": 1}]))
    body = body.json()
    assert body["statut"] == "CANCELLED"
    # Plat absent du menu : refus local, Restaurant jamais appelé.
    assert clients.accept_calls == []
    assert _steps(body)["ORDER_SNAPSHOT"] == "REFUSED"


# ----------------------------------------------------------------- Consultation
def test_get_order(client):
    order_id = client.post(f"{API}/orders", json=_order()).json()["id"]
    r = client.get(f"{API}/orders/{order_id}")
    assert r.status_code == 200
    assert r.json()["id"] == order_id


def test_get_unknown_order(client):
    assert client.get(f"{API}/orders/inconnue").status_code == 404
