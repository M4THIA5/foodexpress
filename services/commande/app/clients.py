"""Clients REST synchrones de l'orchestrateur (Commande → Restaurant / Paiement).

Ces appels sont les étapes **synchrones** de la SAGA (architecture.md §4.1) :
l'orchestrateur a besoin du résultat pour avancer ou compenser.

- Restaurant : lecture du menu (snapshot), `acceptOrder()`, `cancel()` (compensation).
- Paiement   : `debit()` protégé par **Timeout + Retry + Circuit Breaker**
  (architecture.md §7), `refund()` (compensation).

Le résultat *métier* est renvoyé sous forme de dataclasses ; les **pannes** (réseau,
timeout, 5xx) lèvent `RestaurantUnavailable` / `PaymentUnavailable` — distinctes
d'un refus métier (Restaurant 409, Paiement 402), qui reste un appel réussi.

`ServiceClients` est injecté via la dépendance `get_clients`, surchargeable en test.
"""
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.circuit_breaker import CircuitBreaker, CircuitOpenError
from common.config import settings

# Timeout court sur Paiement : on ne veut pas bloquer la SAGA en cas de panne PSP.
PAYMENT_TIMEOUT = 2.0
RESTAURANT_TIMEOUT = 3.0
# Retry limité sur erreurs transitoires avant de compter un échec du circuit.
PAYMENT_ATTEMPTS = 2


class RestaurantUnavailable(Exception):
    """Restaurant injoignable (réseau/timeout/5xx) — la commande ne peut avancer."""


class PaymentUnavailable(Exception):
    """Paiement injoignable ou circuit ouvert (*fail-fast*) → compensation SAGA."""


class _PaymentServiceError(Exception):
    """Réponse HTTP inattendue du service Paiement (5xx) : panne → échec circuit."""


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
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._restaurant_url = (restaurant_url or "").rstrip("/")
        self._paiement_url = (paiement_url or "").rstrip("/")
        self._api = settings.api_prefix
        self._breaker = breaker or CircuitBreaker()

    # ---------------------------------------------------------------- Restaurant
    def get_menu(self, restaurant_id: int) -> dict[int, PlatSnapshot]:
        """Récupère le menu pour constituer le snapshot des lignes de commande."""
        url = f"{self._restaurant_url}{self._api}/restaurants/{restaurant_id}/menu"
        try:
            resp = httpx.get(url, timeout=RESTAURANT_TIMEOUT)
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
            resp = httpx.post(url, json=body, timeout=RESTAURANT_TIMEOUT)
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
            httpx.post(url, timeout=RESTAURANT_TIMEOUT)
        except httpx.HTTPError:
            # La compensation est rejouable : une panne ici ne doit pas la bloquer.
            pass

    # ------------------------------------------------------------------ Paiement
    def debit(self, order_id: str, montant: Decimal) -> PaymentResult:
        """Débit protégé par Circuit Breaker (+ Timeout + Retry).

        Renvoie un `PaymentResult` (201 capturé / 402 refusé métier). Lève
        `PaymentUnavailable` si le service est en panne ou le circuit ouvert.
        """
        url = f"{self._paiement_url}{self._api}/payments"
        body = {"order_id": order_id, "montant": float(montant)}

        def _do_debit() -> PaymentResult:
            resp = httpx.post(url, json=body, timeout=PAYMENT_TIMEOUT)
            if resp.status_code == 201:
                return PaymentResult(captured=True, transaction_id=resp.json()["id"])
            if resp.status_code == 402:
                return PaymentResult(
                    captured=False, motif=resp.json().get("motif", "Paiement refusé")
                )
            raise _PaymentServiceError(f"debit HTTP {resp.status_code}")

        try:
            return self._breaker.call(lambda: self._retry(_do_debit))
        except CircuitOpenError as exc:
            raise PaymentUnavailable(str(exc)) from exc
        except (httpx.HTTPError, _PaymentServiceError) as exc:
            raise PaymentUnavailable(str(exc)) from exc

    def refund(self, transaction_id: int) -> None:
        """Compensation : `Paiement.refund()` (total). Best-effort et idempotent."""
        url = f"{self._paiement_url}{self._api}/payments/{transaction_id}/refund"
        try:
            httpx.post(url, json={"motif": "Compensation SAGA"}, timeout=PAYMENT_TIMEOUT)
        except httpx.HTTPError:
            pass

    @staticmethod
    def _retry(fn):
        """Retry limité sur erreurs transitoires (le circuit compte l'échec final)."""
        last: Exception | None = None
        for _ in range(PAYMENT_ATTEMPTS):
            try:
                return fn()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
        raise last  # type: ignore[misc]


# Instance partagée (le Circuit Breaker doit conserver son état entre requêtes).
_clients: ServiceClients | None = None


def get_clients() -> ServiceClients:
    """Dépendance FastAPI : clients REST partagés (surchargeable en test)."""
    global _clients
    if _clients is None:
        _clients = ServiceClients(settings.restaurant_url, settings.paiement_url)
    return _clients
