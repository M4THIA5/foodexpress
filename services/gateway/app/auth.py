"""Terminaison d'authentification **mockée** au Gateway (architecture.md §8).

Le Gateway valide un jeton porteur avant de router, puis propage le sujet
authentifié aux services amont via l'en-tête `X-User-Id` (les services font
confiance au Gateway et ne revérifient pas le jeton).

Prototype : la validation est *mockée* — tout `Authorization: Bearer <token>` non
vide est accepté et le sujet vaut le token. Un vrai Gateway vérifierait ici la
signature et l'expiration (JWT). Absence / format invalide → **401**. L'intérêt est
de démontrer que l'authentification est **terminée au Gateway**, pas répartie.
"""
from fastapi import Header, HTTPException


def require_principal(authorization: str | None = Header(default=None)) -> str:
    """Dépendance FastAPI : valide le jeton (mock) et renvoie le sujet authentifié."""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Jeton d'authentification requis",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="En-tête Authorization invalide (attendu : « Bearer <token> »)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Mock : aucune vérification cryptographique. Le sujet = le token.
    return token.strip()
