"""Publication des événements métier de la SAGA (côté producteur asynchrone).

Commande publie sur l'exchange topic `foodexpress.events` (architecture.md §4.2) :
- `OrderReadyForDelivery` → consommé par Livraison ;
- `OrderConfirmed` / `OrderCancelled` → consommés par Notification.

Publication **best-effort** : le broker peut être indisponible (démarrage, panne).
Un échec de publication ne casse pas la SAGA — il est journalisé et l'appelant
poursuit. En l'absence de `RABBITMQ_URL` (tests, exécution isolée), c'est un no-op.
"""
import json
import logging

import pika
from sqlalchemy.orm import Session

from app.models import OutboxEvent
from common.config import settings
from common.messaging import EVENTS_EXCHANGE, get_connection

logger = logging.getLogger(__name__)

# Types d'événements (= routing keys topic).
ORDER_READY_FOR_DELIVERY = "order.ready_for_delivery"
ORDER_CONFIRMED = "order.confirmed"
ORDER_CANCELLED = "order.cancelled"
# Interne : jamais publié, le relais l'exécute par un appel à Paiement (app/outbox.py).
PAYMENT_VOID = "payment.void"


def enqueue(session: Session, event_type: str, payload: dict) -> None:
    """Écrit l'événement dans l'outbox, dans la transaction de la commande."""
    session.add(
        OutboxEvent(
            order_id=payload["order_id"],
            event_type=event_type,
            payload=json.dumps(payload),
        )
    )


def publish(event_type: str, payload: dict) -> bool:
    """Publie un événement. Renvoie True si émis, False sinon (no-op/panne)."""
    if not settings.rabbitmq_url:
        return False
    try:
        connection = get_connection()
        try:
            channel = connection.channel()
            channel.exchange_declare(
                exchange=EVENTS_EXCHANGE, exchange_type="topic", durable=True
            )
            channel.basic_publish(
                exchange=EVENTS_EXCHANGE,
                routing_key=event_type,
                body=json.dumps(payload).encode(),
                properties=pika.BasicProperties(
                    content_type="application/json", delivery_mode=2
                ),
            )
        finally:
            connection.close()
        return True
    except Exception:  # broker indisponible : best-effort, on ne casse pas la SAGA
        logger.warning("Publication de %s échouée (broker indisponible)", event_type)
        return False
