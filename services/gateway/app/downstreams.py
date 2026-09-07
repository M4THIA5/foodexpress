"""Topologie interne connue du seul Gateway (encapsulation — architecture.md §8).

`DOWNSTREAMS` : URL de base de chaque service amont (injectée par docker-compose).
`ROUTES`      : mappe la **ressource publique** (1er segment après `/api/v1/…`) vers
le service qui la sert. Le client ignore ce découpage : il ne connaît que le
Gateway et des chemins de ressources.
"""
import os

DOWNSTREAMS = {
    "commande": os.getenv("COMMANDE_URL", "http://commande:8000"),
    "paiement": os.getenv("PAIEMENT_URL", "http://paiement:8000"),
    "restaurant": os.getenv("RESTAURANT_URL", "http://restaurant:8000"),
    "livraison": os.getenv("LIVRAISON_URL", "http://livraison:8000"),
}

# Ressource publique → service amont. Masque le nombre et l'emplacement des services.
ROUTES = {
    "orders": "commande",
    "payments": "paiement",
    "restaurants": "restaurant",
    "deliveries": "livraison",
}
