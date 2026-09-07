"""Circuit Breaker — pattern de résilience de l'appel Commande → Paiement.

Voir architecture.md §7 et ADR-0004. Paiement intègre un PSP externe : c'est le
point de défaillance le plus probable. Sans protection, une **panne** du service
(conteneur arrêté, PSP injoignable) ferait attendre chaque commande jusqu'au
timeout, puis échouer — inutilement, appel après appel.

Trois états :
- **FERMÉ (CLOSED)**  : les appels passent. Au-delà de `failure_threshold` échecs
  consécutifs, le circuit s'ouvre.
- **OUVERT (OPEN)**   : les appels échouent immédiatement (`CircuitOpenError`,
  *fail-fast*) sans toucher le réseau → la SAGA compense sans attendre. Après
  `reset_timeout`, on passe en demi-ouvert.
- **DEMI-OUVERT (HALF_OPEN)** : un appel d'essai est autorisé. Succès → refermé ;
  échec → ré-ouvert.

Distinction clé (architecture.md §3.2, psp.py) : un **refus métier** du PSP (402,
« fonds insuffisants ») est un *succès* d'appel — il ne compte pas comme échec du
circuit. Seules les **pannes** (timeout, erreur réseau, 5xx) l'ouvrent.

L'horloge est injectable (`time_fn`) pour des tests déterministes.
"""
import time
from collections.abc import Callable
from typing import TypeVar

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Levée en *fail-fast* quand le circuit est ouvert (aucun appel réseau)."""


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout: float = 15.0,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._time = time_fn
        self._state = CLOSED
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        return self._state

    def call(self, fn: Callable[[], T]) -> T:
        """Exécute `fn` sous protection du circuit.

        Lève `CircuitOpenError` sans appeler `fn` si le circuit est ouvert et que
        le délai de reset n'est pas écoulé. Toute exception de `fn` est comptée
        comme un échec puis propagée.
        """
        self._before_call()
        try:
            result = fn()
        except Exception:
            self._on_failure()
            raise
        self._on_success()
        return result

    def _before_call(self) -> None:
        if self._state == OPEN:
            if self._time() - self._opened_at >= self.reset_timeout:
                # Délai écoulé : on tente une requête d'essai.
                self._state = HALF_OPEN
            else:
                raise CircuitOpenError("Circuit ouvert (Paiement indisponible)")

    def _on_success(self) -> None:
        self._failures = 0
        self._state = CLOSED

    def _on_failure(self) -> None:
        if self._state == HALF_OPEN:
            # L'essai a échoué : on ré-ouvre immédiatement.
            self._open()
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        self._state = OPEN
        self._opened_at = self._time()
