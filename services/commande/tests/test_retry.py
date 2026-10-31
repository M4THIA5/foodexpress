"""Retry : nombre de tentatives, backoff doublé, jitter, erreurs non rejouées."""
import pytest

from app.retry import BASE_DELAY, MAX_ATTEMPTS, with_retry


class Flaky:
    def __init__(self, failures: int, error: type[Exception] = ConnectionError) -> None:
        self.failures = failures
        self.error = error
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error("panne")
        return "ok"


def test_recovers_after_transient_errors():
    fn = Flaky(failures=2)
    assert with_retry(fn, (ConnectionError,), sleep=lambda _: None) == "ok"
    assert fn.calls == 3


def test_gives_up_after_max_attempts():
    fn = Flaky(failures=10)
    with pytest.raises(ConnectionError):
        with_retry(fn, (ConnectionError,), sleep=lambda _: None)
    assert fn.calls == MAX_ATTEMPTS


def test_other_errors_are_not_retried():
    fn = Flaky(failures=1, error=ValueError)
    with pytest.raises(ValueError):
        with_retry(fn, (ConnectionError,), sleep=lambda _: None)
    assert fn.calls == 1


def test_delay_doubles_with_jitter():
    delays: list[float] = []
    with pytest.raises(ConnectionError):
        with_retry(Flaky(failures=10), (ConnectionError,), sleep=delays.append)
    assert BASE_DELAY <= delays[0] <= 2 * BASE_DELAY
    assert 2 * BASE_DELAY <= delays[1] <= 4 * BASE_DELAY


def _client():
    from app.clients import ServiceClients

    return ServiceClients("http://resto", "http://paiement")


def _fake(monkeypatch, responses):
    import httpx

    from app import clients as module, retry

    calls = []
    def fake(url, **_):
        calls.append(url)
        status = responses.pop(0)
        return httpx.Response(
            status, json={"id": 7, "motif": "x"}, request=httpx.Request("POST", url)
        )
    monkeypatch.setattr(module.httpx, "post", fake)
    monkeypatch.setattr(retry.time, "sleep", lambda _: None)
    monkeypatch.setattr(retry, "BASE_DELAY", 0)
    return calls


def test_debit_retries_5xx_then_succeeds(monkeypatch):
    calls = _fake(monkeypatch, [503, 201])
    assert _client().debit("o", 10).captured
    assert len(calls) == 2


def test_debit_refusal_is_not_retried(monkeypatch):
    calls = _fake(monkeypatch, [402])
    assert not _client().debit("o", 10).captured
    assert len(calls) == 1


def test_accept_refusal_is_not_retried(monkeypatch):
    calls = _fake(monkeypatch, [409])
    assert not _client().accept_order(1, "o", []).accepted
    assert len(calls) == 1
