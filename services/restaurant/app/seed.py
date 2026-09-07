"""Jeu de données de démonstration, inséré au démarrage si la base est vide.

Contenu pensé pour la démo SAGA :
- restaurants 1 et 2 ouverts, avec plats disponibles → chemin nominal (accepté) ;
- restaurant 3 fermé (`actif=False`) → refus déterministe (409) ;
- un plat indisponible chez le restaurant 1 → refus si commandé.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Plat, Restaurant

_SEED = [
    {
        "id": 1,
        "nom": "Chez Luigi",
        "cuisine": "Italien",
        "actif": True,
        "plats": [
            {"id": 11, "nom": "Pizza Margherita", "prix": 11.50, "disponible": True},
            {"id": 12, "nom": "Pâtes Carbonara", "prix": 13.00, "disponible": True},
            {"id": 13, "nom": "Tiramisu", "prix": 6.00, "disponible": False},
        ],
    },
    {
        "id": 2,
        "nom": "Sushi Zen",
        "cuisine": "Japonais",
        "actif": True,
        "plats": [
            {"id": 21, "nom": "Menu Maki 12 pièces", "prix": 14.90, "disponible": True},
            {"id": 22, "nom": "Ramen Tonkotsu", "prix": 12.50, "disponible": True},
        ],
    },
    {
        "id": 3,
        "nom": "Le Bistrot Fermé",
        "cuisine": "Français",
        "actif": False,
        "plats": [
            {"id": 31, "nom": "Steak frites", "prix": 16.00, "disponible": True},
        ],
    },
]


def seed_data(session: Session) -> None:
    if session.scalar(select(Restaurant).limit(1)) is not None:
        return  # base déjà peuplée : idempotent

    for r in _SEED:
        session.add(
            Restaurant(
                id=r["id"], nom=r["nom"], cuisine=r["cuisine"], actif=r["actif"]
            )
        )
        for p in r["plats"]:
            session.add(
                Plat(
                    id=p["id"],
                    restaurant_id=r["id"],
                    nom=p["nom"],
                    prix=p["prix"],
                    disponible=p["disponible"],
                )
            )
    session.commit()
