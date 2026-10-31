"""Délai maximal de la SAGA : une commande ne reste pas en AWAITING_DELIVERY sans fin.

Sans verdict de Livraison passé `delivery_deadline_seconds`, la commande est compensée
(remboursement + annulation restaurant). Un verdict tardif est ignoré : la commande est
alors terminale, et `apply_delivery_result` est idempotent.
"""
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import saga
from app.clients import ServiceClients, get_clients
from app.models import Order
from common.config import settings
from common.database import SessionLocal

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5.0


def expire_overdue(
    session: Session, clients: ServiceClients, now: datetime | None = None
) -> int:
    limit = (now or datetime.now(timezone.utc)) - timedelta(
        seconds=settings.delivery_deadline_seconds
    )
    overdue = session.scalars(
        select(Order.id).where(
            Order.statut == saga.AWAITING_DELIVERY, Order.created_at < limit
        )
    ).all()
    for order_id in overdue:
        saga.expire_delivery(session, order_id, clients)
    return len(overdue)


def start() -> threading.Event:
    stop_event = threading.Event()

    def _run() -> None:
        while not stop_event.wait(POLL_INTERVAL):
            try:
                with SessionLocal() as session:
                    expire_overdue(session, get_clients())
            except Exception:
                logger.exception("Contrôle des délais en échec, nouvel essai au prochain tour")

    threading.Thread(target=_run, name="delivery-deadline", daemon=True).start()
    return stop_event
