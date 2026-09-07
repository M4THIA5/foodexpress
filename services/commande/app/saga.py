"""Orchestrateur de la SAGA de passage de commande (architecture.md §5.3, §6).

Commande **séquence** les étapes et déclenche les **compensations** (style
orchestration, ADR-0003). Chaque étape est tracée dans `saga_log`.

Flux nominal et compensations :

  1. crée `order` (PENDING) + snapshot des lignes depuis le menu Restaurant ;
  2. `Restaurant.acceptOrder()`  → refus ⇒ CANCELLED ;
  3. `Paiement.debit()` (Circuit Breaker) →
        - panne/circuit ouvert ⇒ *fail-fast* + `Restaurant.cancel()` ⇒ CANCELLED,
        - refus métier (402)   ⇒ `Restaurant.cancel()` ⇒ CANCELLED ;
  4. publie `OrderReadyForDelivery` ⇒ AWAITING_DELIVERY (attente événement) ;
  5. résultat livraison (événement / rappel) →
        - `DeliveryAssigned` ⇒ CONFIRMED + `OrderConfirmed`,
        - `DeliveryFailed`   ⇒ `Paiement.refund()` + `Restaurant.cancel()` ⇒ CANCELLED.

La logique métier est séparée du router pour être testable directement (clients
REST injectés). L'idempotence des étapes/compensations est portée par les services
appelés (Restaurant/Paiement) et par le contrôle d'état ici.
"""
import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import events
from app.clients import (
    PaymentUnavailable,
    RestaurantUnavailable,
    ServiceClients,
)
from app.models import Order, OrderItem, SagaLogEntry
from app.schemas import CreateOrderRequest

PENDING = "PENDING"
AWAITING_DELIVERY = "AWAITING_DELIVERY"
CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"

_TERMINAL = {CONFIRMED, CANCELLED}


def _log(order: Order, etape: str, statut: str, payload: str = "") -> None:
    order.saga_steps.append(
        SagaLogEntry(order_id=order.id, etape=etape, statut=statut, payload=payload)
    )


def get_order(session: Session, order_id: str) -> Order:
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Commande introuvable")
    return order


def create_order(
    session: Session, req: CreateOrderRequest, clients: ServiceClients
) -> Order:
    """Exécute la SAGA jusqu'à la demande de livraison (étapes synchrones)."""
    order = Order(
        id=uuid.uuid4().hex,
        client_id=req.client_id,
        restaurant_id=req.restaurant_id,
        statut=PENDING,
        montant_total=Decimal("0"),
    )
    session.add(order)
    _log(order, "ORDER_CREATED", "OK")

    # 1. Snapshot des lignes depuis le menu Restaurant (prix/nom figés).
    try:
        menu = clients.get_menu(req.restaurant_id)
    except RestaurantUnavailable as exc:
        return _cancel(session, order, "RESTAURANT_MENU", "UNAVAILABLE", str(exc))

    total = Decimal("0")
    for item in req.items:
        plat = menu.get(item.plat_id)
        if plat is None:
            # Commande ne peut pas valoriser un plat absent du menu.
            return _cancel(
                session, order, "ORDER_SNAPSHOT", "REFUSED",
                f"Plat {item.plat_id} absent du menu",
            )
        order.items.append(
            OrderItem(
                plat_id=item.plat_id,
                nom_snapshot=plat.nom,
                prix_snapshot=plat.prix,
                quantite=item.quantite,
            )
        )
        total += plat.prix * item.quantite
    order.montant_total = total.quantize(Decimal("0.01"))
    _log(order, "ORDER_SNAPSHOT", "OK", f"montant_total={order.montant_total}")

    # 2. Acceptation Restaurant (synchrone).
    items_payload = [{"plat_id": i.plat_id, "quantite": i.quantite} for i in req.items]
    try:
        accept = clients.accept_order(req.restaurant_id, order.id, items_payload)
    except RestaurantUnavailable as exc:
        return _cancel(session, order, "RESTAURANT_ACCEPT", "UNAVAILABLE", str(exc))
    if not accept.accepted:
        return _cancel(session, order, "RESTAURANT_ACCEPT", "REFUSED", accept.motif)
    _log(order, "RESTAURANT_ACCEPT", "OK")

    # 3. Paiement (synchrone, Circuit Breaker). Restaurant est déjà engagé :
    #    tout échec ici doit compenser par Restaurant.cancel().
    try:
        payment = clients.debit(order.id, order.montant_total)
    except PaymentUnavailable as exc:
        # Fail-fast (circuit ouvert / panne) → compensation immédiate.
        _log(order, "PAYMENT", "UNAVAILABLE", str(exc))
        clients.cancel_order(order.id)
        return _cancel(
            session, order, "COMPENSATION_RESTAURANT", "COMPENSATED",
            "Annulation restaurant (paiement indisponible)",
        )
    if not payment.captured:
        _log(order, "PAYMENT", "DECLINED", payment.motif)
        clients.cancel_order(order.id)
        return _cancel(
            session, order, "COMPENSATION_RESTAURANT", "COMPENSATED",
            "Annulation restaurant (paiement refusé)",
        )
    order.transaction_id = payment.transaction_id
    _log(order, "PAYMENT", "OK", f"transaction_id={payment.transaction_id}")

    # 4. Demande de livraison (asynchrone). La SAGA se met en attente de l'événement.
    order.statut = AWAITING_DELIVERY
    events.publish(
        events.ORDER_READY_FOR_DELIVERY,
        {"order_id": order.id, "restaurant_id": order.restaurant_id},
    )
    _log(order, "DELIVERY_REQUESTED", "OK")

    session.commit()
    session.refresh(order)
    return order


def apply_delivery_result(
    session: Session, order_id: str, success: bool, clients: ServiceClients
) -> Order:
    """Applique le résultat de livraison (5ᵉ étape SAGA), avec compensations.

    Idempotent : une commande déjà terminale (CONFIRMED/CANCELLED) est renvoyée
    telle quelle. N'est valable que depuis l'état AWAITING_DELIVERY.
    """
    order = get_order(session, order_id)
    if order.statut in _TERMINAL:
        return order
    if order.statut != AWAITING_DELIVERY:
        raise HTTPException(
            status_code=409, detail="Commande pas en attente de livraison"
        )

    if success:
        order.statut = CONFIRMED
        _log(order, "DELIVERY_RESULT", "OK")
        _log(order, "ORDER_CONFIRMED", "OK")
        events.publish(events.ORDER_CONFIRMED, {"order_id": order.id})
        session.commit()
        session.refresh(order)
        return order

    # Échec livraison → compensation : remboursement puis annulation restaurant.
    _log(order, "DELIVERY_RESULT", "FAILED")
    if order.transaction_id is not None:
        clients.refund(order.transaction_id)
        _log(order, "COMPENSATION_PAYMENT", "COMPENSATED",
             f"refund transaction {order.transaction_id}")
    clients.cancel_order(order.id)
    return _cancel(
        session, order, "COMPENSATION_RESTAURANT", "COMPENSATED",
        "Annulation restaurant (livraison échouée)",
    )


def _cancel(
    session: Session, order: Order, etape: str, statut: str, payload: str
) -> Order:
    """Journalise l'étape terminale, passe la commande à CANCELLED et publie."""
    _log(order, etape, statut, payload)
    order.statut = CANCELLED
    _log(order, "ORDER_CANCELLED", "OK")
    events.publish(events.ORDER_CANCELLED, {"order_id": order.id})
    session.commit()
    session.refresh(order)
    return order
