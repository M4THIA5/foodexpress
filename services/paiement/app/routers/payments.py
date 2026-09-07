"""Endpoints Paiement appelés par l'orchestrateur SAGA (Commande).

- `POST /payments` (débit) : **201 capturé** ou **402 refusé** — le code HTTP porte
  le verdict du PSP (cf. séquence SAGA, architecture.md §5.3). Idempotent par
  `order_id`.
- `POST /payments/{id}/refund` : **compensation** SAGA, idempotente. 404 si la
  transaction est inconnue, 409 si rien à rembourser ou montant > solde restant.
- `GET /payments/{id}` : consultation d'une transaction.
"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app import service
from app.schemas import PaymentRequest, RefundOut, RefundRequest, TransactionOut
from common.database import get_session

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "",
    response_model=TransactionOut,
    status_code=201,
    responses={402: {"model": TransactionOut, "description": "Paiement refusé"}},
)
def debit(
    req: PaymentRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> TransactionOut:
    transaction = service.debit(session, req)
    if transaction.statut == service.DECLINED:
        response.status_code = 402
    return transaction


@router.get("/{transaction_id}", response_model=TransactionOut)
def get_payment(
    transaction_id: int, session: Session = Depends(get_session)
) -> TransactionOut:
    return service.get_transaction(session, transaction_id)


@router.post("/{transaction_id}/refund", response_model=RefundOut)
def refund(
    transaction_id: int,
    req: RefundRequest,
    session: Session = Depends(get_session),
) -> RefundOut:
    refund_row = service.refund(session, transaction_id, req)
    transaction = refund_row.transaction
    return RefundOut(
        id=refund_row.id,
        transaction_id=refund_row.transaction_id,
        montant=float(refund_row.montant),
        motif=refund_row.motif,
        statut_transaction=transaction.statut,
        montant_restant=float(transaction.montant - transaction.montant_rembourse),
    )
