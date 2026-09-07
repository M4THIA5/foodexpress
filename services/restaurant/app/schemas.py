"""Schémas Pydantic (contrats d'API exposés dans l'OpenAPI /docs)."""
from pydantic import BaseModel, ConfigDict, Field


class PlatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    prix: float
    disponible: bool


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    cuisine: str
    actif: bool


class MenuOut(BaseModel):
    """Menu d'un restaurant : profil + liste des plats."""

    restaurant: RestaurantOut
    plats: list[PlatOut]


class OrderItemIn(BaseModel):
    plat_id: int
    quantite: int = Field(gt=0)


class AcceptOrderRequest(BaseModel):
    """Corps de `acceptOrder()` appelé par l'orchestrateur Commande."""

    order_id: str = Field(min_length=1, max_length=64)
    items: list[OrderItemIn] = Field(min_length=1)


class OrderAcceptanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: str
    restaurant_id: int
    statut: str
    motif: str
