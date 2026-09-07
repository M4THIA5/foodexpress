"""Endpoints du service Commande (point d'entrée de la SAGA).

- `POST /orders` : passe une commande et exécute la SAGA jusqu'à la demande de
  livraison. Renvoie **201** avec l'état final/intermédiaire (`statut` porte le
  résultat : AWAITING_DELIVERY si tout est OK, CANCELLED si refus/échec).
- `GET /orders/{id}` : consultation (commande + lignes + trace SAGA).
- `POST /orders/{id}/delivery-result` : applique le résultat de livraison
  (`DeliveryAssigned` / `DeliveryFailed`). Endpoint de rappel simulant l'événement
  RabbitMQ tant que le consommateur Livraison n'existe pas (architecture.md §4.2).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import saga
from app.clients import ServiceClients, get_clients
from app.schemas import CreateOrderRequest, DeliveryResultIn, OrderOut
from common.database import get_session

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderOut, status_code=201)
def create_order(
    req: CreateOrderRequest,
    session: Session = Depends(get_session),
    clients: ServiceClients = Depends(get_clients),
) -> OrderOut:
    return saga.create_order(session, req, clients)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: str, session: Session = Depends(get_session)) -> OrderOut:
    return saga.get_order(session, order_id)


@router.post("/{order_id}/delivery-result", response_model=OrderOut)
def delivery_result(
    order_id: str,
    req: DeliveryResultIn,
    session: Session = Depends(get_session),
    clients: ServiceClients = Depends(get_clients),
) -> OrderOut:
    return saga.apply_delivery_result(session, order_id, req.success, clients)
