"""Clients REST synchrones de l'orchestrateur (Commande → Restaurant / Paiement).

Ces appels sont les étapes **synchrones** de la SAGA (architecture.md §4.1) :
l'orchestrateur a besoin du résultat pour avancer ou compenser.

- Restaurant : lecture du menu (snapshot), `acceptOrder()`, `cancel()` (compensation).
- Paiement   : `debit()`, `refund()` (compensation).

Les appels sont **directs** : aucun mécanisme de résilience (pas de Circuit Breaker,
pas de Retry, pas de Timeout explicite). Un appel part sur le réseau à chaque fois
et attend la réponse de l'amont.

Le résultat *métier* est renvoyé sous forme de dataclasses ; les **pannes** (réseau,
5xx) lèvent `RestaurantUnavailable` / `PaymentUnavailable` — distinctes d'un refus
métier (Restaurant 409, Paiement 402), qui reste un appel réussi.

`ServiceClients` est injecté via la dépendance `get_clients`, surchargeable en test.
"""
from dataclasses import dataclass
from decimal import Decimal

import httpx

from common.config import settings


class RestaurantUnavailable(Exception):
    """Restaurant injoignable (réseau/5xx) — la commande ne peut avancer."""


class PaymentUnavailable(Exception):
    """Paiement injoignable (réseau/5xx) → compensation SAGA."""


class _PaymentServiceError(Exception):
    """Réponse HTTP inattendue du service Paiement (5xx) : panne."""


@dataclass(frozen=True)
class PlatSnapshot:
    nom: str
    prix: Decimal
    disponible: bool


@dataclass(frozen=True)
class AcceptResult:
    accepted: bool
    motif: str = ""


@dataclass(frozen=True)
class PaymentResult:
    captured: bool
    transaction_id: int | None = None
    motif: str = ""


class ServiceClients:
    def __init__(
        self,
        restaurant_url: str | None = None,
        paiement_url: str | None = None,
    ) -> None:
        self._restaurant_url = (restaurant_url or "").rstrip("/")
        self._paiement_url = (paiement_url or "").rstrip("/")
        self._api = settings.api_prefix

    # ---------------------------------------------------------------- Restaurant
    def get_menu(self, restaurant_id: int) -> dict[int, PlatSnapshot]:
        """Récupère le menu pour constituer le snapshot des lignes de commande."""
        url = f"{self._restaurant_url}{self._api}/restaurants/{restaurant_id}/menu"
        try:
            resp = httpx.get(url)
        except httpx.HTTPError as exc:
            raise RestaurantUnavailable(str(exc)) from exc
        if resp.status_code != 200:
            raise RestaurantUnavailable(f"menu HTTP {resp.status_code}")
        return {
            p["id"]: PlatSnapshot(
                nom=p["nom"], prix=Decimal(str(p["prix"])), disponible=p["disponible"]
            )
            for p in resp.json()["plats"]
        }

    def accept_order(
        self, restaurant_id: int, order_id: str, items: list[dict]
    ) -> AcceptResult:
        """Appelle `acceptOrder()` : 200 accepté, 409 refusé (verdict métier)."""
        url = f"{self._restaurant_url}{self._api}/restaurants/{restaurant_id}/orders"
        body = {"order_id": order_id, "items": items}
        try:
            resp = httpx.post(url, json=body)
        except httpx.HTTPError as exc:
            raise RestaurantUnavailable(str(exc)) from exc
        if resp.status_code == 200:
            return AcceptResult(accepted=True)
        if resp.status_code == 409:
            return AcceptResult(accepted=False, motif=resp.json().get("motif", ""))
        raise RestaurantUnavailable(f"acceptOrder HTTP {resp.status_code}")

    def cancel_order(self, order_id: str) -> None:
        """Compensation : `Restaurant.cancel()`. Best-effort (idempotent côté resto)."""
        url = f"{self._restaurant_url}{self._api}/restaurants/orders/{order_id}/cancel"
        try:
            httpx.post(url)
        except httpx.HTTPError:
            # La compensation est rejouable : une panne ici ne doit pas la bloquer.
            pass

    # ------------------------------------------------------------------ Paiement
    def debit(self, order_id: str, montant: Decimal) -> PaymentResult:
        """Débit (appel direct, sans protection).

        Renvoie un `PaymentResult` (201 capturé / 402 refusé métier). Lève
        `PaymentUnavailable` si le service est en panne.
        """
        url = f"{self._paiement_url}{self._api}/payments"
        body = {"order_id": order_id, "montant": float(montant)}
        try:
            resp = httpx.post(url, json=body)
            if resp.status_code == 201:
                return PaymentResult(captured=True, transaction_id=resp.json()["id"])
            if resp.status_code == 402:
                return PaymentResult(
                    captured=False, motif=resp.json().get("motif", "Paiement refusé")
                )
            raise _PaymentServiceError(f"debit HTTP {resp.status_code}")
        except (httpx.HTTPError, _PaymentServiceError) as exc:
            raise PaymentUnavailable(str(exc)) from exc

    def refund(self, transaction_id: int) -> None:
        """Compensation : `Paiement.refund()` (total). Best-effort et idempotent."""
        url = f"{self._paiement_url}{self._api}/payments/{transaction_id}/refund"
        try:
            httpx.post(url, json={"motif": "Compensation SAGA"})
        except httpx.HTTPError:
            pass


# Instance partagée (réutilisée entre requêtes).
_clients: ServiceClients | None = None


def get_clients() -> ServiceClients:
    """Dépendance FastAPI : clients REST partagés (surchargeable en test)."""
    global _clients
    if _clients is None:
        _clients = ServiceClients(settings.restaurant_url, settings.paiement_url)
    return _clients
