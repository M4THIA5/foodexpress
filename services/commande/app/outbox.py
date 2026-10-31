"""Outbox : aucun événement n'est perdu quand le broker est indisponible.

La SAGA écrit l'événement dans la table `outbox`, **dans la même transaction** que
l'état de la commande (`events.enqueue`). Un thread le publie ensuite et le marque comme
émis. Broker en panne : l'événement attend, dans l'ordre, et repart à la reconnexion.
"""
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events
from app.models import OutboxEvent
from common import metrics
from common.database import SessionLocal

logger = logging.getLogger(__name__)

POLL_INTERVAL = 0.5
BATCH_SIZE = 100


def relay_once(
    session: Session, publish: Callable[[str, dict], bool] = events.publish
) -> int:
    """Publie les événements en attente, dans l'ordre. S'arrête au premier échec."""
    pending = session.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.id)
        .limit(BATCH_SIZE)
    ).all()
    sent = 0
    for row in pending:
        if not publish(row.event_type, row.decoded_payload):
            metrics.incr("fallback.outbox_en_attente")
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
