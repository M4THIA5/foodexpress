"""Fixtures de test : base SQLite en mémoire, sans PostgreSQL ni RabbitMQ.

On surcharge la dépendance `get_session` pour la brancher sur un moteur SQLite
partagé (StaticPool = une seule base en mémoire pour tout le test). Le consommateur
RabbitMQ ne démarre pas en test (pas de `RABBITMQ_URL` → `start_consumer` no-op).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (enregistre les tables sur Base.metadata)
from app.main import app
from common.database import Base, get_session


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
def session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture
def client(session_factory):
    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
