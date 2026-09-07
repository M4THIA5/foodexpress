"""API Gateway / BFF — point d'entrée unique du système (architecture.md §8).

Assure : **routage** vers le bon service amont (reverse-proxy, routers/proxy.py),
**terminaison d'authentification** mockée (auth.py), **résilience sortante**
Timeout + Retry (proxy.py), et **agrégation BFF** (routers/bff.py) — le tout en
masquant la topologie interne au client.

Les routes d'agrégation sont montées **avant** le catch-all du proxy pour avoir la
priorité de match. `/health`, `/`, `/status` restent publics (healthcheck Compose,
introspection) ; la surface `/api/v1` exige un jeton.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.downstreams import DOWNSTREAMS
from app.proxy import close_proxy
from app.routers import bff
from app.routers import proxy as proxy_router
from common.app_factory import create_app
from common.config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        yield
    finally:
        await close_proxy()  # ferme le pool httpx sortant


app = create_app(title="FoodExpress — Gateway / BFF", lifespan=lifespan)
# Ordre important : l'agrégation BFF avant le catch-all du reverse-proxy.
app.include_router(bff.router, prefix=settings.api_prefix)
app.include_router(proxy_router.router, prefix=settings.api_prefix)


@app.get("/status", tags=["meta"])
def status() -> dict:
    """Introspection : services amont configurés (démo/diagnostic)."""
    return {"gateway": "ok", "downstreams": DOWNSTREAMS}
