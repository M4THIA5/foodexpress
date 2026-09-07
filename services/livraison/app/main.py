"""Service Livraison — assignation d'un livreur (mocké) à une commande prête.

Consommateur asynchrone de la SAGA (architecture.md §3.4, §4.2, §5.3) : il écoute
`OrderReadyForDelivery`, assigne un livreur mocké et publie `DeliveryAssigned` /
`DeliveryFailed`. Au démarrage il crée ses tables (`deliveries`, `assignments`) et
lance le consommateur RabbitMQ ; l'arrêt stoppe proprement le consommateur.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import consumer, models  # noqa: F401  (models enregistre les tables)
from app.routers import deliveries
from common.app_factory import create_app
from common.config import settings
from common.database import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    if engine is not None:
        Base.metadata.create_all(engine)
    stop_event = consumer.start()  # None sans broker (tests, exécution isolée)
    try:
        yield
    finally:
        if stop_event is not None:
            stop_event.set()


app = create_app(title="FoodExpress — Livraison", lifespan=lifespan)
app.include_router(deliveries.router, prefix=settings.api_prefix)
