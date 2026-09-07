"""Endpoints appelés par l'orchestrateur SAGA (Commande).

- `acceptOrder()` renvoie **200 accepté** ou **409 refusé** (voir séquence SAGA,
  architecture.md §5.3) : le code HTTP porte le verdict pour l'orchestrateur.
- `cancel()` est la **compensation** ; elle est idempotente et répond toujours 200.
"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app import service
from app.schemas import AcceptOrderRequest, OrderAcceptanceOut
from common.database import get_session

router = APIRouter(prefix="/restaurants", tags=["orders"])


@router.post(
    "/{restaurant_id}/orders",
    response_model=OrderAcceptanceOut,
    responses={409: {"model": OrderAcceptanceOut, "description": "Commande refusée"}},
)
def accept_order(
    restaurant_id: int,
    req: AcceptOrderRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> OrderAcceptanceOut:
    acceptance = service.accept_order(session, restaurant_id, req)
    if acceptance.statut != service.ACCEPTED:
        response.status_code = 409
    return acceptance


@router.post("/orders/{order_id}/cancel", response_model=OrderAcceptanceOut)
def cancel_order(
    order_id: str, session: Session = Depends(get_session)
) -> OrderAcceptanceOut:
    return service.cancel_order(session, order_id)
