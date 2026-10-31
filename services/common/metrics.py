"""Compteurs d'activation des mécanismes de dégradation, exposés sur `GET /metrics`.

Un fallback ne doit jamais masquer une panne : chaque activation est comptée et
journalisée, et le franchissement de `ALERT_THRESHOLD` produit une alerte (niveau ERROR,
à brancher sur l'outil d'alerte). Les compteurs vivent en mémoire, par processus.
"""
import logging
import threading
from collections import Counter

logger = logging.getLogger(__name__)

ALERT_THRESHOLD = 10

_counters: Counter[str] = Counter()
_lock = threading.Lock()


def incr(name: str) -> None:
    with _lock:
        _counters[name] += 1
        total = _counters[name]
    logger.warning("Dégradation %s (total %d)", name, total)
    if total == ALERT_THRESHOLD:
        logger.error("ALERTE : %s activé %d fois", name, total)


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counters)


def reset() -> None:
    with _lock:
        _counters.clear()
