"""Dégradation : délai maximal de livraison, outbox, message explicite, métriques."""
from datetime import datetime, timedelta, timezone

import pytest

from app import deadlines, outbox
from app.models import OutboxEvent
from common import metrics
from common.config import settings

API = "/api/v1"
ORDER = {"client_id": 1, "restaurant_id": 1, "items": [{"plat_id": 11, "quantite": 1}]}


@pytest.fixture(autouse=True)
def _clean_metrics():
    metrics.reset()


def _later() -> datetime:
    return datetime.now(timezone.utc) + timedelta(
        seconds=settings.delivery_deadline_seconds + 1
    )


# ------------------------------------------------------------ Délai de livraison
def test_overdue_order_is_refunded_and_cancelled(client, clients, session_factory):
    created = client.post(f"{API}/orders", json=ORDER).json()
    with session_factory() as session:
        assert deadlines.expire_overdue(session, clients, now=_later()) == 1
    body = client.get(f"{API}/orders/{created['id']}").json()
    assert body["statut"] == "CANCELLED"
    assert clients.refunded == [created["transaction_id"]]
    assert created["id"] in clients.cancelled
    assert "livreur" in body["message"]
    assert metrics.snapshot()["fallback.livraison_delai_depasse"] == 1


def test_recent_order_is_left_alone(client, clients, session_factory):
    client.post(f"{API}/orders", json=ORDER)
    with session_factory() as session:
        assert deadlines.expire_overdue(session, clients) == 0
    assert clients.refunded == []


def test_expiry_drops_the_unsent_delivery_request(client, clients, session_factory):
    client.post(f"{API}/orders", json=ORDER)
    with session_factory() as session:
        deadlines.expire_overdue(session, clients, now=_later())
        types = [e.event_type for e in session.query(OutboxEvent).all()]
    assert "order.ready_for_delivery" not in types
    assert "order.cancelled" in types


# ------------------------------------------------------------------------ Outbox
def test_events_survive_a_broker_outage_and_keep_their_order(client, session_factory):
    client.post(f"{API}/orders", json=ORDER)
    client.post(f"{API}/orders", json=ORDER)
    with session_factory() as session:
        assert outbox.relay_once(session, publish=lambda *_: False) == 0
        assert metrics.snapshot()["fallback.outbox_en_attente"] == 1

        sent = []
        relayed = outbox.relay_once(session, publish=lambda t, p: sent.append(p) or True)
        assert relayed == 2
        assert outbox.relay_once(session, publish=lambda *_: True) == 0  # rien à rejouer
    assert len(sent) == 2 and sent[0] != sent[1]


def test_relay_stops_at_first_failure(client, session_factory):
    client.post(f"{API}/orders", json=ORDER)
    client.post(f"{API}/orders", json=ORDER)
    results = iter([True, False])
    with session_factory() as session:
        assert outbox.relay_once(session, publish=lambda *_: next(results)) == 1


# ------------------------------------------------------- Message et observabilité
def test_payment_outage_gives_an_explicit_message(client, clients):
    clients.payment = "unavailable"
    body = client.post(f"{API}/orders", json=ORDER).json()
    assert body["statut"] == "CANCELLED"
    assert "paiement" in body["message"].lower()
    assert metrics.snapshot()["fallback.paiement_indisponible"] == 1


def test_healthy_order_has_no_message(client):
    assert client.post(f"{API}/orders", json=ORDER).json()["message"] is None


def test_metrics_endpoint_and_alert(client, caplog):
    for _ in range(metrics.ALERT_THRESHOLD):
        metrics.incr("fallback.test")
    assert client.get("/metrics").json()["fallback.test"] == metrics.ALERT_THRESHOLD
    assert "ALERTE" in caplog.text
