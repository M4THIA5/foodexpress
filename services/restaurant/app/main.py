"""Service Restaurant — menus, acceptation/refus de commande, compensation.

Service feuille de la SAGA (architecture.md §3.3) : appelé en synchrone par
l'orchestrateur Commande, il n'émet aucun appel sortant. Au démarrage il crée ses
tables et insère un jeu de démonstration.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  (enregistre les tables sur Base.metadata)
from app.routers import orders, restaurants
from app.seed import seed_data
from common.app_factory import create_app
from common.config import settings
from common.database import Base, SessionLocal, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    if engine is not None:
        Base.metadata.create_all(engine)
        with SessionLocal() as session:
            seed_data(session)
    yield


app = create_app(title="FoodExpress — Restaurant", lifespan=lifespan)
app.include_router(restaurants.router, prefix=settings.api_prefix)
app.include_router(orders.router, prefix=settings.api_prefix)
