"""Service Paiement — débit / remboursement via un PSP externe mocké.

Service feuille de la SAGA (architecture.md §3.2) : appelé en synchrone par
l'orchestrateur Commande (débit, puis remboursement en compensation). Il intègre un
PSP mocké — point de défaillance n°1 protégé par le Circuit Breaker côté Commande
(architecture.md §7). Au démarrage il crée ses tables.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  (enregistre les tables sur Base.metadata)
from app.routers import payments
from common.app_factory import create_app
from common.config import settings
from common.database import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    if engine is not None:
        Base.metadata.create_all(engine)
    yield


app = create_app(title="FoodExpress — Paiement", lifespan=lifespan)
app.include_router(payments.router, prefix=settings.api_prefix)
