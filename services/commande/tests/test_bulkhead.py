"""Bulkhead : refus immédiat au-delà de la limite, place libérée après l'appel."""
import pytest

from app.bulkhead import Bulkhead, BulkheadFullError


def test_rejects_beyond_limit_then_frees_the_slot():
    bh = Bulkhead("Paiement", max_concurrent=1)

    def inner():
        with pytest.raises(BulkheadFullError):
            bh.call(lambda: "refusé")
        return "ok"

    assert bh.call(inner) == "ok"
    assert bh.call(lambda: "de nouveau libre") == "de nouveau libre"


def test_slot_is_freed_when_the_call_fails():
    bh = Bulkhead("Paiement", max_concurrent=1)

    def boom():
        raise ValueError

    with pytest.raises(ValueError):
        bh.call(boom)
    assert bh.call(lambda: "ok") == "ok"


def test_saturated_payment_is_reported_as_unavailable_without_opening_the_circuit():
    from app.clients import PaymentUnavailable, ServiceClients

    c = ServiceClients("http://resto", "http://paiement")
    c._payment_bulkhead = Bulkhead("Paiement", max_concurrent=1)
    c._payment_bulkhead._slots.acquire()
    with pytest.raises(PaymentUnavailable, match="saturé"):
        c.debit("o", 10)
    assert c._breaker.state == "CLOSED"
