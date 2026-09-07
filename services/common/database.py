"""Fabrique de session SQLAlchemy (une base par service).

Squelette prêt pour les tâches suivantes (modèles + persistance). Le moteur ne se
connecte pas à l'import : la connexion est ouverte à la première requête.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from common.config import settings


class Base(DeclarativeBase):
    """Base déclarative commune des modèles ORM d'un service."""


engine = (
    create_engine(settings.database_url, pool_pre_ping=True)
    if settings.database_url
    else None
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session():
    """Dépendance FastAPI : fournit une session et la ferme après usage."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
