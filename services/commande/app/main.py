"""Service Commande — orchestrateur de la SAGA de passage de commande.

Centre du flux critique (architecture.md §3.1, §5.3) : il crée la commande, en
séquence les étapes synchrones (Restaurant, Paiement — ce dernier protégé par un
Circuit Breaker) puis asynchrone (Livraison via RabbitMQ), et pilote les
compensations. Au démarrage il crée ses tables (`orders`, `order_items`, `saga_log`)
et lance le consommateur qui referme la branche livraison (`DeliveryAssigned` /
`DeliveryFailed`) ; l'arrêt stoppe proprement le consommateur.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import consumer, models  # noqa: F401  (models enregistre les tables)
from app.routers import orders
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


app = create_app(title="FoodExpress — Commande", lifespan=lifespan)
app.include_router(orders.router, prefix=settings.api_prefix)
