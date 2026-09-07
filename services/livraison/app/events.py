"""Événements métier de Livraison (côté producteur asynchrone).

Livraison consomme `OrderReadyForDelivery` (produit par Commande) et publie en
retour, sur l'exchange topic `foodexpress.events` (architecture.md §4.2) :
- `DeliveryAssigned` → un livreur a été assigné, la commande peut être confirmée ;
- `DeliveryFailed`   → aucun livreur, la SAGA doit compenser.

La publication réutilise l'implémentation best-effort commune (`common.messaging`).
"""
from common.messaging import publish

__all__ = [
    "publish",
    "ORDER_READY_FOR_DELIVERY",
    "DELIVERY_ASSIGNED",
    "DELIVERY_FAILED",
]

# Événement consommé (routing key produite par Commande).
ORDER_READY_FOR_DELIVERY = "order.ready_for_delivery"

# Événements publiés (= routing keys topic).
DELIVERY_ASSIGNED = "delivery.assigned"
DELIVERY_FAILED = "delivery.failed"
