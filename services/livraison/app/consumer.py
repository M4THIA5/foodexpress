"""Consommateur RabbitMQ du service Livraison.

Écoute `OrderReadyForDelivery` (produit par Commande) et, pour chaque message,
délègue à la logique métier (`service.handle_order_ready`) qui assigne un livreur
et publie `DeliveryAssigned` / `DeliveryFailed`. Le thread et la reconnexion sont
portés par `common.messaging.start_consumer`.
"""
import logging

from app import events, service
from common.database import SessionLocal
from common.messaging import start_consumer

logger = logging.getLogger(__name__)

# File dédiée de Livraison, liée à la routing key produite par Commande.
QUEUE = "livraison.order_ready"


def _handle(_routing_key: str, payload: dict) -> None:
    order_id = payload["order_id"]
    restaurant_id = payload["restaurant_id"]
    with SessionLocal() as session:
        service.handle_order_ready(session, order_id, restaurant_id)


def start():
    """Démarre le consommateur (no-op sans broker). Renvoie l'Event d'arrêt."""
    return start_consumer(QUEUE, [events.ORDER_READY_FOR_DELIVERY], _handle)
