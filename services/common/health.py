"""Endpoint de santé commun, monté par tous les services (healthcheck Compose)."""
from fastapi import APIRouter

from common.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    # `async` : répond sans passer par le pool de threads, même quand il est saturé.
    return {"status": "healthy", "service": settings.service_name}
