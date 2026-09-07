# Dockerfile commun à tous les services FoodExpress.
# Le service à construire est choisi via l'ARG SERVICE (voir docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app

# Dépendances (couche cachée tant que requirements.txt ne change pas)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Package commun (config, health, database, messaging, app_factory)
COPY services/common ./common

# Code applicatif du service ciblé
ARG SERVICE
COPY services/${SERVICE}/app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
