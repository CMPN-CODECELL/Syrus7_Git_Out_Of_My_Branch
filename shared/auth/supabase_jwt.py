"""
Server-side verification of Supabase access tokens.

Every token is checked for signature, expiry, audience and subject. Verification uses the
project's legacy HS256 secret when SUPABASE_JWT_SECRET is set, otherwise the project's JWKS
(asymmetric keys). With neither configured, every token is rejected (fail closed).
"""
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException, Request, status

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_ASYMMETRIC_ALGORITHMS = ["ES256", "RS256"]


class AuthError(Exception):
    """Raised when a token cannot be verified."""


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    email: Optional[str]
    claims: Dict[str, Any]


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


def verify_supabase_jwt(token: str) -> AuthUser:
    settings = get_settings()
    if not token or token.count(".") != 2:
        raise AuthError("Malformed token")

    options = {"require": ["exp", "sub"]}
    try:
        if settings.SupabaseJwtSecret:
            claims = jwt.decode(
                token,
                settings.SupabaseJwtSecret,
                algorithms=["HS256"],
                audience=settings.SupabaseJwtAudience,
                options=options,
            )
        elif settings.SupabaseUrl:
            jwks_url = settings.SupabaseUrl.rstrip("/") + "/auth/v1/.well-known/jwks.json"
            signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=_ASYMMETRIC_ALGORITHMS,
                audience=settings.SupabaseJwtAudience,
                options=options,
            )
        else:
            raise AuthError("Authentication is not configured on the server")
    except AuthError:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid token") from exc

    return AuthUser(user_id=str(claims["sub"]), email=claims.get("email"), claims=claims)


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header.startswith("Bearer ") else ""


async def require_user(request: Request) -> AuthUser:
    """FastAPI dependency: 401 unless the request carries a verified Supabase token."""
    cached = getattr(request.state, "user", None)
    if isinstance(cached, AuthUser):
        return cached
    try:
        user = verify_supabase_jwt(bearer_token(request))
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    request.state.user = user
    return user
