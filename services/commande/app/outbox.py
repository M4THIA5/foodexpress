"""Outbox : aucun événement n'est perdu quand le broker est indisponible.

La SAGA écrit l'événement dans la table `outbox`, **dans la même transaction** que
l'état de la commande (`events.enqueue`). Un thread le publie ensuite et le marque comme
émis. Broker en panne : l'événement attend, dans l'ordre, et repart à la reconnexion.

Le relais rejoue aussi les annulations de débit (`PAYMENT_VOID`). Elles forment une file
à part : une panne de Paiement ne doit pas bloquer les événements, ni l'inverse.
"""
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events
from app.clients import get_clients
from app.models import OutboxEvent
from common import metrics
from common.database import SessionLocal

logger = logging.getLogger(__name__)

POLL_INTERVAL = 0.5
BATCH_SIZE = 100


def relay_once(
    session: Session,
    publish: Callable[[str, dict], bool] = events.publish,
    void: Callable[[str], bool] | None = None,
) -> int:
    """Traite chaque file dans l'ordre et s'arrête à son premier échec."""
    void = void or get_clients().void_payment
    is_void = OutboxEvent.event_type == events.PAYMENT_VOID
    return _drain(
        session,
        ~is_void,
        lambda row: publish(row.event_type, row.decoded_payload),
        "fallback.outbox_en_attente",
    ) + _drain(session, is_void, lambda row: void(row.order_id), "fallback.void_en_attente")


def _drain(session: Session, condition, send, metric: str) -> int:
    pending = session.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None), condition)
        .order_by(OutboxEvent.id)
        .limit(BATCH_SIZE)
    ).all()
    sent = 0
    for row in pending:
        if not send(row):
            metrics.incr(metric)
            break
        row.published_at = datetime.now(timezone.utc)
        session.commit()
        sent += 1
    return sent


def start() -> threading.Event:
    stop_event = threading.Event()

    def _run() -> None:
        while not stop_event.wait(POLL_INTERVAL):
            try:
                with SessionLocal() as session:
                    relay_once(session)
            except Exception:
                logger.exception("Relais outbox en échec, nouvel essai au prochain tour")

    threading.Thread(target=_run, name="outbox-relay", daemon=True).start()
    return stop_event
