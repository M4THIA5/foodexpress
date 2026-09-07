"""Schémas Pydantic (contrats d'API exposés dans l'OpenAPI /docs)."""
from pydantic import BaseModel, ConfigDict, Field


class OrderItemIn(BaseModel):
    """Ligne de panier : le client fournit le plat et la quantité.

    Le nom et le prix ne sont **pas** fournis par le client : Commande les récupère
    du menu Restaurant et en fait un snapshot (architecture.md §3.1).
    """

    plat_id: int
    quantite: int = Field(gt=0)


class CreateOrderRequest(BaseModel):
    """Corps de `POST /orders` (passage de commande, entrée de la SAGA)."""

    client_id: int
    restaurant_id: int
    items: list[OrderItemIn] = Field(min_length=1)


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plat_id: int
    nom_snapshot: str
    prix_snapshot: float
    quantite: int


class SagaStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    etape: str
    statut: str
    payload: str


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: int
    restaurant_id: int
    statut: str
    montant_total: float
    transaction_id: int | None
    items: list[OrderItemOut]
    # Trace de la SAGA (étapes + compensations), utile à la démo/soutenance.
    saga_steps: list[SagaStepOut]


class DeliveryResultIn(BaseModel):
    """Résultat de livraison appliqué à la SAGA.

    En production cet état arrive par événement RabbitMQ (`DeliveryAssigned` /
    `DeliveryFailed`, architecture.md §4.2). Tant que le consommateur Livraison
    n'existe pas, ce corps est reçu via un endpoint de rappel qui simule
    l'événement (`POST /orders/{id}/delivery-result`).
    """

    success: bool
    motif: str = Field(default="", max_length=255)
