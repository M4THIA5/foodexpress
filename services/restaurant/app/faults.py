"""Injection de panne intermittente (expérience de chaos, cas pratique partie 2).

`RESTAURANT_ERROR_EVERY=3` fait répondre 503 à une requête d'API sur trois. Le compteur
rend l'expérience **reproductible**, ce qu'un tirage aléatoire ne garantirait pas. La
valeur par défaut (0) désactive l'injection. `/health` reste épargné : le conteneur doit
rester « healthy », seule l'API est dégradée.
"""
from itertools import count

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common.config import settings


def add_fault_injection(app: FastAPI) -> None:
    compteur = count(1)

    @app.middleware("http")
    async def inject_errors(request: Request, call_next):
        every = settings.restaurant_error_every
        if (
            every > 0
            and request.url.path.startswith(settings.api_prefix)
            and next(compteur) % every == 0
        ):
            return JSONResponse(
                status_code=503, content={"detail": "Panne injectée (RESTAURANT_ERROR_EVERY)"}
            )
        return await call_next(request)
