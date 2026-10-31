# FoodExpress

Plateforme de livraison de repas en **architecture microservices**.

## Périmètre du prototype

4 services + Gateway, chacun avec sa propre base PostgreSQL (aucune base partagée),
et RabbitMQ pour les événements asynchrones :

| Composant  | Port hôte | Rôle |
|------------|-----------|------|
| Gateway / BFF | 8000 | point d'entrée unique, reverse-proxy |
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

### Expériences de chaos

Toutes partent d'une stack saine. Variable utilisée : `G=http://127.0.0.1:8000/api/v1`.

| Expérience | Injecter | Annuler |
|------------|----------|---------|
| Paiement muet (allumé, ne répond plus) | `docker compose pause paiement` | `docker compose unpause paiement` |
| Paiement arrêté (erreur immédiate) | `docker compose stop paiement` | `docker compose start paiement` |
| Paiement lent (3 s) | voir ci-dessous | voir ci-dessous |
| Perte du broker | `docker compose stop rabbitmq` | `docker compose start rabbitmq` |
| Restaurant en erreur une fois sur trois | `RESTAURANT_ERROR_EVERY=3 docker compose up -d restaurant` | `docker compose up -d restaurant` |

Commande joint Paiement à travers Toxiproxy, piloté par son API (port 8474) :

```bash
# 3 s de latence sur les réponses de Paiement
curl -X POST http://127.0.0.1:8474/proxies/paiement/toxics \
  -d '{"name":"lent","type":"latency","stream":"downstream","attributes":{"latency":3000}}'
# retirer la latence
curl -X DELETE http://127.0.0.1:8474/proxies/paiement/toxics/lent
```

Une panne ne se propage que si les appels s'accumulent. Pour observer la cascade, il
faut dépasser les 100 connexions du Gateway, tout en surveillant un menu dans un autre
terminal :

```bash
echo '{"client_id":42,"restaurant_id":1,"items":[{"plat_id":11,"quantite":1}]}' > /tmp/order.json
# 150 commandes simultanées, abandonnées par le client au bout de 30 s
seq 150 | xargs -P150 -I{} curl -s -m 30 -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer demo" -H "Content-Type: application/json" \
  -d @/tmp/order.json "$G/orders" | sort | uniq -c
# surveillance
while true; do
  curl -s -o /dev/null -m 10 -H "Authorization: Bearer demo" \
    -w '%{http_code} %{time_total}s\n' "$G/restaurants/1/menu"; sleep 1
done
```

La trace `saga_steps` de `GET $G/orders/<id>` est horodatée : l'écart entre deux étapes
donne la latence observée d'un appel, et donc la base de calibrage d'un timeout.

> **Podman rootless** :
> - préférer `127.0.0.1` à `localhost` (la résolution IPv6 `::1` des ports publiés
>   peut réinitialiser la connexion) ;
> - RabbitMQ n'a **pas** de healthcheck (cf. commentaire dans `docker-compose.yml` :
>   un healthcheck sur cette image casse l'écriture du `.erlang.cookie` → `eacces`) ;
>   les services attendent le broker via `service_started` + reconnexion applicative.
>   Après un ancien démarrage échoué, purger l'état résiduel : `podman compose down -v`.

> État actuel : prototype fonctionnel — SAGA orchestrée et compensations. Branche
> d'exercice : les appels sortants n'ont **aucune** protection (ni timeout, ni retry,
> ni circuit breaker, ni bulkhead, ni fallback).
