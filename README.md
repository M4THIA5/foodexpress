# FoodExpress

Plateforme de livraison de repas en **architecture microservices**.

## Périmètre du prototype

4 services + Gateway, chacun avec sa propre base PostgreSQL (aucune base partagée),
et RabbitMQ pour les événements asynchrones :

| Composant  | Port hôte | Rôle |
|------------|-----------|------|
| Gateway / BFF | 8000 | point d'entrée unique, résilience sortante |
| Commande   | 8001 | orchestrateur de la SAGA |
| Paiement   | 8002 | débit / remboursement (PSP mocké) |
| Restaurant | 8003 | menus, acceptation/refus, annulation |
| Livraison  | 8004 | assignation livreur (mocké) |
| RabbitMQ (console) | 15672 | broker d'événements |

## Structure

```
Dockerfile              # image commune, service choisi via ARG SERVICE
docker-compose.yml      # gateway + 4 services + RabbitMQ + 4 Postgres
requirements.txt        # dépendances communes
services/
  common/               # squelette partagé : config, health, database, messaging
  commande/  paiement/  restaurant/  livraison/  gateway/   # app/ par service
```

## Lancer la démo

Prérequis : Docker + Docker Compose (ou Podman + podman-compose).

```bash
docker compose up --build          # construit et démarre toute la stack
docker compose ps                  # état + healthchecks
docker compose down -v             # arrêt + suppression des volumes
```

Vérifier qu'un service répond :

```bash
curl http://127.0.0.1:8000/health  # gateway
curl http://127.0.0.1:8001/health  # commande
curl http://127.0.0.1:8000/status  # gateway → services amont configurés
```

OpenAPI / Swagger de chaque service : `http://127.0.0.1:<port>/docs`.

### Scénario de démonstration

Une fois la stack démarrée, rejouer les parcours de la SAGA (commande OK, paiement
KO, livraison KO, refus restaurant) en une commande :

```bash
./scripts/demo.sh                  # 4 parcours automatisés + vérification (✓/✗)
```

> **Podman rootless** :
> - préférer `127.0.0.1` à `localhost` (la résolution IPv6 `::1` des ports publiés
>   peut réinitialiser la connexion) ;
> - RabbitMQ n'a **pas** de healthcheck (cf. commentaire dans `docker-compose.yml` :
>   un healthcheck sur cette image casse l'écriture du `.erlang.cookie` → `eacces`) ;
>   les services attendent le broker via `service_started` + reconnexion applicative.
>   Après un ancien démarrage échoué, purger l'état résiduel : `podman compose down -v`.

> État actuel : prototype fonctionnel — SAGA orchestrée, compensations et Circuit
