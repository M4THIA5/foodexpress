"""Modèles ORM du service Paiement (base PostgreSQL dédiée).

Deux tables (voir architecture.md §3.2) :
- `transactions` : un débit par commande (`order_id`), résultat renvoyé par le PSP.
- `refunds`      : remboursements (total/partiel) rattachés à une transaction.

`order_id` est une chaîne : Paiement ne connaît pas le format d'identifiant de
Commande et reste ainsi faiblement couplé. Il est **unique** → idempotence des
re-tentatives SAGA sur le débit.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Un débit par commande : garantit l'idempotence des re-tentatives SAGA.
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    montant: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # CAPTURED | DECLINED | PARTIALLY_REFUNDED | REFUNDED
    statut: Mapped[str] = mapped_column(String(20))
    # Référence renvoyée par le PSP en cas de succès (vide si refusé).
    psp_reference: Mapped[str] = mapped_column(String(64), default="")
    # Motif de refus du PSP (vide si capturé).
    motif: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    refunds: Mapped[list["Refund"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )

    @property
    def montant_rembourse(self) -> Decimal:
        """Total déjà remboursé (somme des remboursements rattachés)."""
        return sum((r.montant for r in self.refunds), Decimal("0"))


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    montant: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    motif: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    transaction: Mapped[Transaction] = relationship(back_populates="refunds")
