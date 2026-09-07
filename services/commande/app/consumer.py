"""Consommateur RabbitMQ de Commande — clôture de la branche livraison de la SAGA.

Écoute les événements publiés par Livraison (architecture.md §4.2) :
- `DeliveryAssigned` → la commande passe CONFIRMED (`OrderConfirmed`) ;
- `DeliveryFailed`   → compensation : `Paiement.refund()` + `Restaurant.cancel()`.

Il **réutilise** l'étape SAGA `saga.apply_delivery_result` (déjà testée et exposée
aussi via l'endpoint de rappel `POST /orders/{id}/delivery-result`) : l'événement
et le rappel HTTP convergent vers la même logique idempotente.
"""
import logging

from app import saga
from app.clients import get_clients
from common.database import SessionLocal
from common.messaging import start_consumer

logger = logging.getLogger(__name__)

# File dédiée de Commande, liée aux deux verdicts de livraison.
QUEUE = "commande.delivery_result"
DELIVERY_ASSIGNED = "delivery.assigned"
DELIVERY_FAILED = "delivery.failed"


def _handle(routing_key: str, payload: dict) -> None:
    order_id = payload["order_id"]
    success = routing_key == DELIVERY_ASSIGNED
    with SessionLocal() as session:
        saga.apply_delivery_result(session, order_id, success, get_clients())


def start():
    """Démarre le consommateur (no-op sans broker). Renvoie l'Event d'arrêt."""
    return start_consumer(QUEUE, [DELIVERY_ASSIGNED, DELIVERY_FAILED], _handle)
