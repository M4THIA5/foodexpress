"""PSP externe mocké (Payment Service Provider).

Simule l'intégration d'un prestataire de paiement, **sans appel réseau**. C'est le
point de défaillance n°1 de l'architecture (architecture.md §2.2) : une panne du
PSP se propage donc directement à l'orchestrateur Commande.

Levier de démo SAGA : un montant `>= DECLINE_THRESHOLD` est refusé de façon
déterministe (« fonds insuffisants »), ce qui déclenche la branche de compensation
« paiement échoue » du diagramme de séquence (architecture.md §5.3). Le refus d'un
PSP est un échec **métier** (réponse 402) distinct d'une **panne** du service
Paiement (conteneur arrêté), qui remonte en erreur d'appel côté Commande.
"""
import uuid
from dataclasses import dataclass
from decimal import Decimal

# Au-delà de ce montant, le PSP mocké refuse le débit (fonds insuffisants).
DECLINE_THRESHOLD = Decimal("1000")


@dataclass(frozen=True)
class ChargeResult:
    success: bool
    reference: str = ""
    motif: str = ""


def charge(order_id: str, montant: Decimal) -> ChargeResult:
    """Débite le client. Refuse de façon déterministe au-delà du plafond de démo."""
    if montant >= DECLINE_THRESHOLD:
        return ChargeResult(success=False, motif="Fonds insuffisants")
    return ChargeResult(success=True, reference=f"psp_{uuid.uuid4().hex[:16]}")


def refund(reference: str, montant: Decimal) -> str:
    """Rembourse via le PSP. Dans le mock, le remboursement aboutit toujours."""
    return f"psp_rf_{uuid.uuid4().hex[:16]}"
