"""Endpoints de consultation : liste des restaurants et menu (côté lecture)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import service
from app.schemas import MenuOut, RestaurantOut
from common.database import get_session

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.get("", response_model=list[RestaurantOut])
def list_restaurants(session: Session = Depends(get_session)) -> list[RestaurantOut]:
    return service.list_restaurants(session)


@router.get("/{restaurant_id}/menu", response_model=MenuOut)
def get_menu(restaurant_id: int, session: Session = Depends(get_session)) -> MenuOut:
    restaurant, plats = service.get_menu(session, restaurant_id)
    return MenuOut(restaurant=restaurant, plats=plats)
