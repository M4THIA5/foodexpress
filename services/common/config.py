"""Configuration commune, lue depuis les variables d'environnement.

Chaque service reçoit ses valeurs via docker-compose (SERVICE_NAME, DATABASE_URL,
RABBITMQ_URL...). Les clés inconnues sont ignorées pour qu'un service puisse
recevoir des variables supplémentaires (URLs des services amont) sans erreur.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "foodexpress-service"
    api_prefix: str = "/api/v1"
    database_url: str | None = None
    rabbitmq_url: str | None = None
    # URLs des services amont appelés en synchrone (orchestrateur Commande).
    restaurant_url: str | None = None
    paiement_url: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
