"""Endpoints du service Livraison.

La voie normale d'entrée est l'événement `OrderReadyForDelivery` (consommateur
RabbitMQ, architecture.md §4.2). Ces endpoints HTTP servent à **observer** les
livraisons et à en **déclencher** une hors broker (démo/test en isolation) :

- `GET  /deliveries`            : liste des livraisons.
- `GET  /deliveries/{order_id}` : livraison d'une commande (+ affectation livreur).
- `POST /deliveries`            : déclenche l'assignation (rappel simulant l'événement).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import service
from app.schemas import DeliveryOut, DeliveryRequest
from common.database import get_session

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.get("", response_model=list[DeliveryOut])
def list_deliveries(session: Session = Depends(get_session)) -> list[DeliveryOut]:
    return service.list_deliveries(session)


@router.get("/{order_id}", response_model=DeliveryOut)
def get_delivery(
    order_id: str, session: Session = Depends(get_session)
) -> DeliveryOut:
    return service.get_delivery(session, order_id)


@router.post("", response_model=DeliveryOut, status_code=201)
def request_delivery(
    req: DeliveryRequest, session: Session = Depends(get_session)
) -> DeliveryOut:
    return service.handle_order_ready(session, req.order_id, req.restaurant_id)
