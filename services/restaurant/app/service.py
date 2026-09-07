"""Logique métier du service Restaurant.

Séparée des routers pour être testable directement. Les fonctions renvoient des
entités ORM ; la traduction en code HTTP (200 accepté / 409 refusé) est faite par
les routers, conformément au diagramme de séquence SAGA (architecture.md §5.3).
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OrderAcceptance, Plat, Restaurant
from app.schemas import AcceptOrderRequest

ACCEPTED = "ACCEPTED"
REFUSED = "REFUSED"
CANCELLED = "CANCELLED"


def get_restaurant(session: Session, restaurant_id: int) -> Restaurant:
    restaurant = session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant introuvable")
    return restaurant


def list_restaurants(session: Session) -> list[Restaurant]:
    return list(session.scalars(select(Restaurant).order_by(Restaurant.id)))


def get_menu(session: Session, restaurant_id: int) -> tuple[Restaurant, list[Plat]]:
    restaurant = get_restaurant(session, restaurant_id)
    plats = list(
        session.scalars(
            select(Plat).where(Plat.restaurant_id == restaurant_id).order_by(Plat.id)
        )
    )
    return restaurant, plats


def accept_order(
    session: Session, restaurant_id: int, req: AcceptOrderRequest
) -> OrderAcceptance:
    """Décide d'accepter ou refuser une commande, et persiste le verdict.

    Idempotent par `order_id` : une re-tentative SAGA renvoie le verdict déjà
    enregistré (aucun double effet). Un restaurant fermé ou un plat indisponible
    entraîne un refus déterministe (levier de démo).
    """
    existing = session.scalar(
        select(OrderAcceptance).where(OrderAcceptance.order_id == req.order_id)
    )
    if existing is not None:
        return existing

    restaurant = get_restaurant(session, restaurant_id)
    statut, motif = _decide(session, restaurant, req)

    acceptance = OrderAcceptance(
        order_id=req.order_id,
        restaurant_id=restaurant_id,
        statut=statut,
        motif=motif,
    )
    session.add(acceptance)
    session.commit()
    session.refresh(acceptance)
    return acceptance


def _decide(
    session: Session, restaurant: Restaurant, req: AcceptOrderRequest
) -> tuple[str, str]:
    if not restaurant.actif:
        return REFUSED, "Restaurant fermé"

    plats = {
        p.id: p
        for p in session.scalars(
            select(Plat).where(Plat.restaurant_id == restaurant.id)
        )
    }
    for item in req.items:
        plat = plats.get(item.plat_id)
        if plat is None:
            return REFUSED, f"Plat {item.plat_id} inconnu pour ce restaurant"
        if not plat.disponible:
            return REFUSED, f"Plat « {plat.nom} » indisponible"

    return ACCEPTED, ""


def cancel_order(session: Session, order_id: str) -> OrderAcceptance:
    """Compensation SAGA : annule l'acceptation d'une commande.

    Idempotent : un `order_id` déjà annulé — ou inconnu — ne provoque pas d'erreur
    (la compensation doit toujours pouvoir aboutir).
    """
    acceptance = session.scalar(
        select(OrderAcceptance).where(OrderAcceptance.order_id == order_id)
    )
    if acceptance is None:
        # Rien à compenser : on matérialise l'annulation pour garder une trace.
        acceptance = OrderAcceptance(
            order_id=order_id,
            restaurant_id=0,
            statut=CANCELLED,
            motif="Annulation d'une commande inconnue (no-op)",
        )
        session.add(acceptance)
    else:
        acceptance.statut = CANCELLED
    session.commit()
    session.refresh(acceptance)
    return acceptance
