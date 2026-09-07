"""Assignation livreur (consommateur SAGA) + idempotence + endpoints d'observation.

Le levier de démo : restaurant 2 est hors zone couverte → `DeliveryFailed`
(couriers.NO_COVERAGE_RESTAURANTS) ; tout autre restaurant → `DeliveryAssigned`.
"""
from app import couriers, service

API = "/api/v1"


class _CaptureEvents:
    """Double de `publish` : enregistre les événements émis (routing_key, payload)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event_type: str, payload: dict) -> bool:
        self.events.append((event_type, payload))
        return True


# ------------------------------------------------------ logique (service direct)

def test_assign_publishes_delivery_assigned(session):
    events = _CaptureEvents()
    delivery = service.handle_order_ready(session, "cmd-1", 1, publish=events)

    assert delivery.statut == service.ASSIGNED
    assert delivery.assignment.livreur_id is not None
    assert events.events == [
        ("delivery.assigned", {"order_id": "cmd-1", "livreur_id": delivery.assignment.livreur_id})
    ]


def test_no_coverage_publishes_delivery_failed(session):
    events = _CaptureEvents()
    # Restaurant 2 = hors zone (levier de démo « livraison KO »).
    delivery = service.handle_order_ready(session, "cmd-2", 2, publish=events)

    assert delivery.statut == service.FAILED
    assert delivery.assignment.livreur_id is None
    assert delivery.assignment.statut == service.NO_COURIER
    [(event_type, payload)] = events.events
    assert event_type == "delivery.failed"
    assert payload["order_id"] == "cmd-2"


def test_handle_is_idempotent(session):
    events = _CaptureEvents()
    first = service.handle_order_ready(session, "cmd-3", 1, publish=events)
    second = service.handle_order_ready(session, "cmd-3", 1, publish=events)

    assert first.id == second.id
    # Rejeu d'un événement redélivré : aucune republication (pas de double effet SAGA).
    assert len(events.events) == 1


def test_courier_selection_is_deterministic():
    # Même order_id → même livreur, de façon reproductible (levier de démo/rejeu).
    a = couriers.assign_courier("same-id", 1)
    b = couriers.assign_courier("same-id", 1)
    assert a.assigned and b.assigned
    assert a.courier == b.courier


# ------------------------------------------------------------- endpoints HTTP

def test_post_delivery_returns_assignment(client):
    r = client.post(f"{API}/deliveries", json={"order_id": "cmd-10", "restaurant_id": 1})
    assert r.status_code == 201
    body = r.json()
    assert body["statut"] == "ASSIGNED"
    assert body["assignment"]["livreur_id"] is not None


def test_post_delivery_no_coverage(client):
    r = client.post(f"{API}/deliveries", json={"order_id": "cmd-11", "restaurant_id": 2})
    assert r.status_code == 201
    assert r.json()["statut"] == "FAILED"


def test_get_delivery(client):
    client.post(f"{API}/deliveries", json={"order_id": "cmd-12", "restaurant_id": 1})
    r = client.get(f"{API}/deliveries/cmd-12")
    assert r.status_code == 200
    assert r.json()["order_id"] == "cmd-12"


def test_get_unknown_delivery_404(client):
    r = client.get(f"{API}/deliveries/inconnue")
    assert r.status_code == 404


def test_list_deliveries(client):
    client.post(f"{API}/deliveries", json={"order_id": "cmd-13", "restaurant_id": 1})
    client.post(f"{API}/deliveries", json={"order_id": "cmd-14", "restaurant_id": 2})
    r = client.get(f"{API}/deliveries")
    assert r.status_code == 200
    assert {d["order_id"] for d in r.json()} == {"cmd-13", "cmd-14"}
