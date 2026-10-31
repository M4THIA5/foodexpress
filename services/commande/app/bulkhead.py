"""Bulkhead : limite le nombre d'appels simultanés vers une dépendance.

Le timeout limite la **durée** d'un appel, le bulkhead limite leur **volume**. Sans lui,
une dépendance lente occupe tous les threads de Commande (40 par défaut), y compris ceux
qui serviraient une autre dépendance ou une simple consultation. Au-delà de la limite,
l'appel est refusé tout de suite au lieu de faire la queue.
"""
import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class BulkheadFullError(Exception):
    """Trop d'appels simultanés vers cette dépendance : refus immédiat."""


class Bulkhead:
    def __init__(self, name: str, max_concurrent: int) -> None:
        self.name = name
        self._slots = threading.BoundedSemaphore(max_concurrent)

    def call(self, fn: Callable[[], T]) -> T:
        if not self._slots.acquire(blocking=False):
            raise BulkheadFullError(f"{self.name} saturé : appel refusé")
        try:
            return fn()
        finally:
            self._slots.release()
