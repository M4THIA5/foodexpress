"""Endpoint de santé commun, monté par tous les services (healthcheck Compose)."""
from fastapi import APIRouter

from common.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "healthy", "service": settings.service_name}
