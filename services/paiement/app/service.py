"""Logique métier du service Paiement.

Séparée des routers pour être testable directement. Le débit et le remboursement
s'appuient sur le PSP mocké (`app.psp`). La traduction en codes HTTP (201 capturé /
402 refusé / 409 conflit) est faite par le router, conformément au diagramme de
séquence SAGA (architecture.md §5.3).
"""
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import psp
from app.models import Refund, Transaction
from app.schemas import PaymentRequest, RefundRequest

CAPTURED = "CAPTURED"
DECLINED = "DECLINED"
PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
REFUNDED = "REFUNDED"

# Statuts pour lesquels un remboursement a du sens (un débit a été capturé).
_REFUNDABLE = {CAPTURED, PARTIALLY_REFUNDED, REFUNDED}


def _to_decimal(montant: float | Decimal) -> Decimal:
    return Decimal(str(montant)).quantize(Decimal("0.01"))


def debit(session: Session, req: PaymentRequest) -> Transaction:
    """Débite le client via le PSP. Idempotent par `order_id`.

    Une re-tentative SAGA sur une commande déjà traitée renvoie la transaction
    existante (même verdict), sans rappeler le PSP.
    """
    existing = session.scalar(
        select(Transaction).where(Transaction.order_id == req.order_id)
    )
    if existing is not None:
        return existing

    montant = _to_decimal(req.montant)
    result = psp.charge(req.order_id, montant)
    transaction = Transaction(
        order_id=req.order_id,
        montant=montant,
        statut=CAPTURED if result.success else DECLINED,
        psp_reference=result.reference,
        motif=result.motif,
    )
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    return transaction


def get_transaction(session: Session, transaction_id: int) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")
    return transaction


def refund(session: Session, transaction_id: int, req: RefundRequest) -> Refund:
    """Rembourse tout ou partie d'une transaction capturée (compensation SAGA).

    - `montant` omis → remboursement du **solde restant** (usage de la compensation).
    - Un remboursement **total déjà effectué** est un no-op idempotent (rejouable) :
      la compensation SAGA doit toujours pouvoir aboutir sans double effet.
    - Refuse (409) une transaction non capturée (ex. refusée) ou un montant
      supérieur au solde restant.
    """
    transaction = get_transaction(session, transaction_id)
    if transaction.statut not in _REFUNDABLE:
        raise HTTPException(status_code=409, detail="Aucun débit à rembourser")

    restant = _to_decimal(transaction.montant) - transaction.montant_rembourse

    # Compensation rejouée sur une transaction déjà soldée : no-op idempotent.
    if req.montant is None and restant == 0:
        return transaction.refunds[-1]

    montant = _to_decimal(req.montant) if req.montant is not None else restant
    if montant <= 0 or montant > restant:
        raise HTTPException(
            status_code=409, detail="Montant de remboursement supérieur au solde"
        )

    psp.refund(transaction.psp_reference, montant)
    refund_row = Refund(
        transaction_id=transaction.id, montant=montant, motif=req.motif
    )
    session.add(refund_row)
    transaction.statut = REFUNDED if montant == restant else PARTIALLY_REFUNDED
    session.commit()
    session.refresh(refund_row)
    return refund_row
