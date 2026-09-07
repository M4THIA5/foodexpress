"""Agrégation BFF — vue de suivi de commande (architecture.md §8).

`GET /api/v1/orders/{id}/suivi` compose en **une seule** réponse cliente l'état de
la commande (service Commande : statut, total, trace SAGA) et l'état de sa livraison
(service Livraison : livreur, statut). Le client fait un appel, le Gateway en
orchestre plusieurs **en parallèle** (`asyncio.gather`) et masque la topologie.

Résilience : la livraison peut ne pas exister encore (commande en cours) → la
section `livraison` vaut `null` au lieu d'une erreur. Une commande introuvable
renvoie 404 ; une panne du service Commande, 502/504.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_principal
from app.proxy import GatewayError, ProxyClient, get_proxy
from common.config import settings

router = APIRouter(tags=["bff"])


@router.get("/orders/{order_id}/suivi")
async def order_tracking(
    order_id: str,
    principal: str = Depends(require_principal),
    proxy_client: ProxyClient = Depends(get_proxy),
) -> dict:
    api = settings.api_prefix
    headers = {"X-User-Id": principal}
    commande_res, livraison_res = await asyncio.gather(
        proxy_client.forward(
            "commande", "GET", f"{api}/orders/{order_id}", headers=headers
        ),
        proxy_client.forward(
            "livraison", "GET", f"{api}/deliveries/{order_id}", headers=headers
        ),
        return_exceptions=True,
    )

    # Commande : source de vérité du suivi — une panne ou un 404 est bloquant.
    if isinstance(commande_res, GatewayError):
        raise HTTPException(status_code=commande_res.status_code, detail=str(commande_res))
    if isinstance(commande_res, BaseException):
        raise commande_res
    if commande_res.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Commande {order_id} introuvable")
    if commande_res.status_code >= 400:
        raise HTTPException(status_code=502, detail="Erreur du service Commande")

    # Livraison : optionnelle — absente tant que la SAGA n'a pas atteint la livraison.
    livraison = None
    if (
        not isinstance(livraison_res, BaseException)
        and livraison_res.status_code == 200
    ):
        livraison = livraison_res.json()

    return {
        "order_id": order_id,
        "commande": commande_res.json(),
        "livraison": livraison,
    }
