"""Retry avec backoff exponentiel et jitter (appels REST de Commande).

Trois tentatives au maximum, délai doublé à chaque essai, plus un délai aléatoire qui
désynchronise les appelants : sans lui, une micro-panne produit une tempête de requêtes
au moment où le service se rétablit.

Deux règles à respecter côté appelant : ne rejouer que des opérations **idempotentes**
(Restaurant et Paiement le sont par `order_id`), et ne jamais rejouer une réponse 4xx.
"""
import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

MAX_ATTEMPTS = 3
BASE_DELAY = 0.1


def with_retry(
    fn: Callable[[], T],
    retry_on: tuple[type[Exception], ...],
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Exécute `fn`, en la rejouant sur les erreurs `retry_on`. Propage le dernier échec."""
    for attempt in range(MAX_ATTEMPTS - 1):
        try:
            return fn()
        except retry_on:
            delay = BASE_DELAY * 2**attempt
            sleep(delay + random.uniform(0, delay))
    return fn()
