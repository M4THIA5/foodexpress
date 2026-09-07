"""Modèles ORM du service Livraison (base PostgreSQL dédiée).

Deux tables (voir architecture.md §3.4) :
- `deliveries`   : l'**instance de processus** de livraison d'une commande prête
  (`ASSIGNED` | `FAILED`).
- `assignments`  : l'affectation d'un livreur (contexte Livreur **mocké** ici,
  architecture.md §2.2) à une livraison ; `livreur_id` nul si aucun livreur.

`order_id` est une chaîne (UUID-friendly) : Livraison ne connaît pas le format
d'identifiant de Commande et reste ainsi faiblement couplé. Son unicité garantit
l'**idempotence** face à un événement `OrderReadyForDelivery` redélivré.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Un seul enregistrement par commande : idempotence des événements redélivrés.
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    restaurant_id: Mapped[int] = mapped_column(Integer)
    # ASSIGNED | FAILED
    statut: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    assignment: Mapped["Assignment"] = relationship(
        back_populates="delivery", cascade="all, delete-orphan", uselist=False
    )


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"))
    # Livreur mocké : nul si aucun livreur disponible (livraison en échec).
    livreur_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    livreur_nom: Mapped[str] = mapped_column(String(120), default="")
    # ASSIGNED | NO_COURIER
    statut: Mapped[str] = mapped_column(String(20))

    delivery: Mapped[Delivery] = relationship(back_populates="assignment")
