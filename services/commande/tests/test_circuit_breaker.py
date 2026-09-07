"""Circuit Breaker — états FERMÉ / OUVERT / DEMI-OUVERT (architecture.md §7).

Horloge injectée (`FakeClock`) pour piloter le délai de reset de façon
déterministe, sans `sleep`.
"""
import pytest

from app.circuit_breaker import CircuitBreaker, CircuitOpenError


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _boom():
    raise RuntimeError("panne Paiement")


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=10, time_fn=FakeClock())
    for _ in range(3):
        with pytest.raises(RuntimeError):
            cb.call(_boom)
    assert cb.state == "OPEN"


def test_open_circuit_fails_fast_without_calling():
    calls = {"n": 0}

    def counted():
        calls["n"] += 1
        raise RuntimeError("panne")

    cb = CircuitBreaker(failure_threshold=2, reset_timeout=10, time_fn=FakeClock())
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(counted)
    assert cb.state == "OPEN"
    # Circuit ouvert : fail-fast, la fonction n'est plus appelée.
    with pytest.raises(CircuitOpenError):
        cb.call(counted)
    assert calls["n"] == 2


def test_half_open_success_closes_circuit():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=10, time_fn=clock)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(_boom)
    assert cb.state == "OPEN"
    # Après le délai de reset → essai autorisé (demi-ouvert) ; succès → refermé.
    clock.now = 10
    assert cb.call(lambda: "ok") == "ok"
    assert cb.state == "CLOSED"


def test_half_open_failure_reopens_circuit():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=10, time_fn=clock)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(_boom)
    clock.now = 10
    # L'essai en demi-ouvert échoue → ré-ouverture immédiate.
    with pytest.raises(RuntimeError):
        cb.call(_boom)
    assert cb.state == "OPEN"


def test_business_result_does_not_open_circuit():
    # Un refus métier (402) est une valeur de retour, pas une exception :
    # il ne doit jamais compter comme un échec du circuit.
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=10, time_fn=FakeClock())
    for _ in range(5):
        assert cb.call(lambda: "DECLINED") == "DECLINED"
    assert cb.state == "CLOSED"
