"""Schémas Pydantic (contrats d'API exposés dans l'OpenAPI /docs)."""
from pydantic import BaseModel, ConfigDict, Field


class DeliveryRequest(BaseModel):
    """Corps de la demande de livraison (rappel HTTP simulant l'événement).

    En production, cette information arrive par l'événement `OrderReadyForDelivery`
    (architecture.md §4.2). L'endpoint HTTP permet de déclencher/rejouer une
    assignation sans broker (démo et test du service en isolation).
    """

    order_id: str = Field(min_length=1, max_length=64)
    restaurant_id: int


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    livreur_id: int | None
    livreur_nom: str
    statut: str


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: str
    restaurant_id: int
    statut: str
    assignment: AssignmentOut | None
