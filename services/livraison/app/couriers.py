"""Flotte de livreurs mockée (contexte Livreur, mocké dans Livraison).

Simule la **ressource** livreur (identité, disponibilité) *sans* service Livreur
réel : architecture.md §2.2 distingue Livreur (la ressource) de Livraison
(l'instance de processus) et rabat la disponibilité livreur ici pour le prototype.

Levier de démo SAGA : les restaurants de `NO_COVERAGE_RESTAURANTS` sont **hors zone
couverte** → aucun livreur → `DeliveryFailed` de façon déterministe. C'est la
branche « échec livraison » du diagramme de séquence (architecture.md §5.3), qui
déclenche les compensations `Paiement.refund()` + `Restaurant.cancel()`.
"""
import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Courier:
    id: int
    nom: str


# Flotte de démonstration (le contexte Livreur est mocké, architecture.md §2.2).
_FLEET = [Courier(1, "Alex"), Courier(2, "Sam"), Courier(3, "Nour")]

# Restaurants sans couverture livreur : assignation impossible (levier de démo).
# Sushi Zen (id 2) sert de scénario « livraison KO » pour la démo (Enonce §démo).
NO_COVERAGE_RESTAURANTS = {2}


@dataclass(frozen=True)
class AssignmentResult:
    assigned: bool
    courier: Courier | None = None
    motif: str = ""


def assign_courier(order_id: str, restaurant_id: int) -> AssignmentResult:
    """Assigne un livreur disponible à une commande prête (mock déterministe)."""
    if restaurant_id in NO_COVERAGE_RESTAURANTS:
        return AssignmentResult(assigned=False, motif="Aucun livreur dans la zone")
    # Sélection stable d'un livreur à partir de l'`order_id` (reproductible en test
    # et entre exécutions, contrairement à hash() qui est salé par processus).
    digest = int(hashlib.sha1(order_id.encode()).hexdigest(), 16)
    courier = _FLEET[digest % len(_FLEET)]
    return AssignmentResult(assigned=True, courier=courier)
