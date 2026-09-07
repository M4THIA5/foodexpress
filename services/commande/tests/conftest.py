"""Fixtures de test Commande : base SQLite en mémoire + clients REST simulés.

L'orchestrateur appelle Restaurant et Paiement en synchrone. On n'exécute pas de
vrai HTTP en test : on injecte un `FakeClients` configurable (via la surcharge de
la dépendance `get_clients`) qui joue les verdicts métier et **enregistre les
compensations** (annulations restaurant, remboursements) pour les assertions.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (enregistre les tables sur Base.metadata)
from app.clients import (
    AcceptResult,
    PaymentResult,
    PaymentUnavailable,
    PlatSnapshot,
    get_clients,
)
from app.main import app
from common.database import Base, get_session

# Menu de démonstration (miroir du seed Restaurant : Chez Luigi).
FAKE_MENU = {
    11: PlatSnapshot("Pizza Margherita", Decimal("11.50"), True),
    12: PlatSnapshot("Pâtes Carbonara", Decimal("13.00"), True),
    13: PlatSnapshot("Tiramisu", Decimal("6.00"), False),
}


class FakeClients:
    """Double de test de `ServiceClients` : verdicts pilotables + traces."""

    def __init__(self) -> None:
        self.menu = dict(FAKE_MENU)
        self.accept = True
        self.accept_motif = ""
        self.payment = "captured"  # captured | declined | unavailable
        # Traces pour les assertions de compensation.
        self.accept_calls: list[str] = []
        self.cancelled: list[str] = []
        self.refunded: list[int] = []
        self._next_txn = 1000

    def get_menu(self, restaurant_id: int) -> dict[int, PlatSnapshot]:
        return dict(self.menu)

    def accept_order(self, restaurant_id, order_id, items) -> AcceptResult:
        self.accept_calls.append(order_id)
        return AcceptResult(self.accept, "" if self.accept else self.accept_motif)

    def cancel_order(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    def debit(self, order_id, montant) -> PaymentResult:
        if self.payment == "unavailable":
            raise PaymentUnavailable("Circuit ouvert (Paiement indisponible)")
        if self.payment == "declined":
            return PaymentResult(captured=False, motif="Fonds insuffisants")
        self._next_txn += 1
        return PaymentResult(captured=True, transaction_id=self._next_txn)

    def refund(self, transaction_id: int) -> None:
        self.refunded.append(transaction_id)


@pytest.fixture
def clients() -> FakeClients:
    return FakeClients()


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield TestSession
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(session_factory, clients):
    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_clients] = lambda: clients
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
