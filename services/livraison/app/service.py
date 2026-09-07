"""Logique métier du service Livraison.

Séparée du transport (consommateur RabbitMQ, router HTTP) pour être testable
directement. `handle_order_ready` est le cœur : elle assigne un livreur mocké à une
commande prête, persiste la livraison, puis publie le résultat
(`DeliveryAssigned` / `DeliveryFailed`) qui referme la branche livraison de la SAGA
côté Commande (architecture.md §5.3).
"""
import logging
from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import couriers, events
from app.models import Assignment, Delivery

logger = logging.getLogger(__name__)

ASSIGNED = "ASSIGNED"
FAILED = "FAILED"
NO_COURIER = "NO_COURIER"

# Type de la fonction de publication (injectable pour les tests).
Publish = Callable[[str, dict], bool]


def handle_order_ready(
    session: Session,
    order_id: str,
    restaurant_id: int,
    publish: Publish = events.publish,
) -> Delivery:
    """Traite un `OrderReadyForDelivery` : assignation + persistance + événement.

    Idempotent par `order_id` : un événement redélivré renvoie la livraison déjà
    enregistrée **sans** réassigner ni republier (pas de double effet sur la SAGA).
    """
    existing = session.scalar(select(Delivery).where(Delivery.order_id == order_id))
    if existing is not None:
        return existing

    result = couriers.assign_courier(order_id, restaurant_id)
    delivery = Delivery(
        order_id=order_id,
        restaurant_id=restaurant_id,
        statut=ASSIGNED if result.assigned else FAILED,
    )
    delivery.assignment = Assignment(
        livreur_id=result.courier.id if result.courier else None,
        livreur_nom=result.courier.nom if result.courier else "",
        statut=ASSIGNED if result.assigned else NO_COURIER,
    )
    session.add(delivery)
    session.commit()
    session.refresh(delivery)

    if result.assigned:
        logger.info("Livraison %s assignée au livreur %s", order_id, result.courier.id)
        publish(
            events.DELIVERY_ASSIGNED,
            {"order_id": order_id, "livreur_id": result.courier.id},
        )
    else:
        logger.info("Livraison %s en échec : %s", order_id, result.motif)
        publish(events.DELIVERY_FAILED, {"order_id": order_id, "motif": result.motif})

    return delivery


def get_delivery(session: Session, order_id: str) -> Delivery:
    delivery = session.scalar(select(Delivery).where(Delivery.order_id == order_id))
    if delivery is None:
        raise HTTPException(status_code=404, detail="Livraison introuvable")
    return delivery


def list_deliveries(session: Session) -> list[Delivery]:
    return list(session.scalars(select(Delivery).order_by(Delivery.id)))
