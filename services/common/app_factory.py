"""Fabrique d'application FastAPI partagée : même squelette pour chaque service.

Un service ajoute ensuite ses routers métier versionnés (`settings.api_prefix`)
sur l'app retournée. OpenAPI/Swagger est exposé automatiquement sur `/docs`.

`lifespan` (optionnel) permet à un service de brancher son initialisation au
démarrage (création des tables, seed, ouverture de consommateurs...).
"""
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI

from common import metrics
from common.config import settings
from common.health import router as health_router

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app(title: str | None = None, lifespan: Lifespan | None = None) -> FastAPI:
    app = FastAPI(
        title=title or f"FoodExpress — {settings.service_name}",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(health_router)

    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {
            "service": settings.service_name,
            "status": "ok",
            "api": settings.api_prefix,
            "docs": "/docs",
        }

    @app.get("/metrics", tags=["meta"])
    def get_metrics() -> dict[str, int]:
        return metrics.snapshot()

    return app
