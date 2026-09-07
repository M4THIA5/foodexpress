"""Modèles ORM du service Restaurant (base PostgreSQL dédiée).

Trois tables (voir architecture.md §3.3) :
- `restaurants`        : profil + état ouvert/fermé (`actif`).
- `plats`              : lignes de menu d'un restaurant (nom, prix, disponibilité).
- `order_acceptances`  : décision d'acceptation/refus/annulation par commande.

`order_id` est une chaîne (UUID-friendly) : le service Restaurant ne connaît pas
le format d'identifiant de Commande et reste ainsi faiblement couplé.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120))
    cuisine: Mapped[str] = mapped_column(String(60), default="")
    # `actif` = restaurant ouvert et prenant des commandes. Levier de démo : un
    # restaurant `actif=False` provoque un refus déterministe (409) dans la SAGA.
    actif: Mapped[bool] = mapped_column(Boolean, default=True)

    plats: Mapped[list["Plat"]] = relationship(
        back_populates="restaurant", cascade="all, delete-orphan"
    )


class Plat(Base):
    __tablename__ = "plats"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"))
    nom: Mapped[str] = mapped_column(String(120))
    prix: Mapped[float] = mapped_column(Numeric(10, 2))
    disponible: Mapped[bool] = mapped_column(Boolean, default=True)

    restaurant: Mapped[Restaurant] = relationship(back_populates="plats")


class OrderAcceptance(Base):
    __tablename__ = "order_acceptances"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Un seul verdict par commande : garantit l'idempotence des re-tentatives SAGA.
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"))
    # ACCEPTED | REFUSED | CANCELLED
    statut: Mapped[str] = mapped_column(String(20))
    motif: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
