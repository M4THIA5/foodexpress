"""Schémas Pydantic (contrats d'API exposés dans l'OpenAPI /docs)."""
from pydantic import BaseModel, ConfigDict, Field


class PaymentRequest(BaseModel):
    """Corps de `debit()` appelé par l'orchestrateur Commande."""

    order_id: str = Field(min_length=1, max_length=64)
    montant: float = Field(gt=0)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: str
    montant: float
    statut: str
    psp_reference: str
    motif: str
    montant_rembourse: float


class RefundRequest(BaseModel):
    """Corps de `refund()` : `montant` omis = remboursement du solde restant.

    La compensation SAGA appelle un remboursement total (montant omis).
    """

    montant: float | None = Field(default=None, gt=0)
    motif: str = Field(default="", max_length=255)


class RefundOut(BaseModel):
    id: int
    transaction_id: int
    montant: float
    motif: str
    # État de la transaction après remboursement (PARTIALLY_REFUNDED | REFUNDED).
    statut_transaction: str
    montant_restant: float
