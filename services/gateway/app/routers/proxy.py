"""Reverse-proxy générique du Gateway (routage — architecture.md §8).

Route toute requête cliente `/<ressource>/…` vers le service amont correspondant
(`ROUTES`), en relayant méthode, query, corps et en-têtes, puis renvoie la réponse
telle quelle. L'authentification est terminée en amont (`require_principal`) et le
sujet propagé via `X-User-Id`. Ressource inconnue → 404 ; panne amont → 502/504
(`GatewayError`). Les endpoints d'agrégation (bff.py) sont montés **avant** ce
catch-all et ont donc priorité.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.auth import require_principal
from app.downstreams import ROUTES
from app.proxy import GatewayError, ProxyClient, get_proxy, to_response
from common.config import settings

router = APIRouter(tags=["proxy"])

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@router.api_route("/{full_path:path}", methods=_METHODS)
async def proxy(
    full_path: str,
    request: Request,
    principal: str = Depends(require_principal),
    proxy_client: ProxyClient = Depends(get_proxy),
) -> Response:
    resource = full_path.split("/", 1)[0]
    service = ROUTES.get(resource)
    if service is None:
        raise HTTPException(status_code=404, detail=f"Ressource inconnue : {resource}")

    downstream_path = f"{settings.api_prefix}/{full_path}"
    headers = dict(request.headers)
    headers["X-User-Id"] = principal  # sujet authentifié propagé à l'amont
    try:
        resp = await proxy_client.forward(
            service,
            request.method,
            downstream_path,
            params=list(request.query_params.multi_items()),
            headers=headers,
            content=await request.body(),
        )
    except GatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return to_response(resp)
