"""Modèles ORM du service Commande (base PostgreSQL dédiée).

Quatre tables (voir architecture.md §3.1) :
- `orders`       : la commande et son cycle de vie
  (`PENDING → AWAITING_DELIVERY → CONFIRMED / CANCELLED`).
- `order_items`  : lignes de la commande avec **snapshot** du nom et du prix du
  plat au moment de la commande (copiés depuis Restaurant). La commande reste
  valide même si le menu change ensuite : aucune lecture croisée de base.
- `saga_log`     : trace ordonnée des étapes de la SAGA (orchestration). Sert la
  traçabilité en soutenance et l'idempotence/reprise (architecture.md §6).
- `outbox`       : événements en attente de publication (voir app/outbox.py).

L'identifiant de commande est une **chaîne UUID** générée par Commande : c'est ce
`order_id` qui est transmis à Restaurant et Paiement (couplage faible par valeur).
"""
import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Message affiché au client, selon l'étape qui a fait échouer la SAGA.
_MESSAGES = {
    ("RESTAURANT_MENU", "UNAVAILABLE"): "Le restaurant est momentanément injoignable. "
    "Votre commande n'a pas été prise, réessayez dans quelques minutes.",
    ("RESTAURANT_ACCEPT", "UNAVAILABLE"): "Le restaurant est momentanément injoignable. "
    "Votre commande n'a pas été prise, réessayez dans quelques minutes.",
    ("RESTAURANT_ACCEPT", "REFUSED"): "Le restaurant ne peut pas prendre votre commande.",
    ("PAYMENT", "UNAVAILABLE"): "Le paiement est momentanément indisponible. "
    "Réessayez dans quelques minutes.",
    ("PAYMENT", "DECLINED"): "Votre paiement a été refusé.",
    ("DELIVERY_DEADLINE", "EXPIRED"): "Aucun livreur n'a répondu à temps. "
    "Votre commande est annulée et remboursée.",
    ("DELIVERY_RESULT", "FAILED"): "Aucun livreur n'est disponible. "
    "Votre commande est annulée et remboursée.",
}


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[int] = mapped_column(Integer, index=True)
    restaurant_id: Mapped[int] = mapped_column(Integer, index=True)
    # PENDING | AWAITING_DELIVERY | CONFIRMED | CANCELLED
    statut: Mapped[str] = mapped_column(String(20))
    montant_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    # Référence de la transaction Paiement (nécessaire au remboursement de
    # compensation en cas d'échec livraison). Vide tant que le débit n'a pas eu lieu.
    transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    saga_steps: Mapped[list["SagaLogEntry"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="SagaLogEntry.id",
    )

    @property
    def message(self) -> str | None:
        """Explication destinée au client, pour une commande annulée."""
        if self.statut != "CANCELLED":
            return None
        for step in self.saga_steps:
            message = _MESSAGES.get((step.etape, step.statut))
            if message:
                return message
        return "Votre commande a été annulée."


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    plat_id: Mapped[int] = mapped_column(Integer)
    # Snapshot au moment de la commande (copié depuis le menu Restaurant).
    nom_snapshot: Mapped[str] = mapped_column(String(120))
    prix_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    quantite: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")

    @property
    def sous_total(self) -> Decimal:
        return (self.prix_snapshot * self.quantite).quantize(Decimal("0.01"))


class SagaLogEntry(Base):
    __tablename__ = "saga_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    # Étape de la SAGA : ORDER_CREATED, RESTAURANT_ACCEPT, PAYMENT,
    # DELIVERY_REQUESTED, DELIVERY_RESULT, COMPENSATION_*, ORDER_CONFIRMED...
    etape: Mapped[str] = mapped_column(String(40))
    # Statut de l'étape : OK, REFUSED, DECLINED, UNAVAILABLE, COMPENSATED...
    statut: Mapped[str] = mapped_column(String(20))
    payload: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    order: Mapped[Order] = relationship(back_populates="saga_steps")


class OutboxEvent(Base):
    """Événement à publier, écrit dans la même transaction que la commande."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Vide tant que l'événement n'a pas été remis au broker.
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    @property
    def decoded_payload(self) -> dict:
        return json.loads(self.payload)
