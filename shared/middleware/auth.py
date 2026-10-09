import json
import base64
import logging
from typing import Optional, Dict, Any
from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config.settings import get_settings

logger = logging.getLogger("api.auth")


def _decode_jwt_payload_unverified(token: str) -> Optional[Dict[str, Any]]:
    """Helper to safely extract claims from JWT without signature verification if secret unavailable."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        # Pad if needed
        padding = 4 - (len(payload_b64) % 4)
        if padding and padding != 4:
            payload_b64 += "=" * padding
        decoded = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        return json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        logger.debug("Failed decoding JWT payload: %s", exc)
        return None


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    Defense-in-depth authentication middleware:
    - Verifies internal service keys for ingestion and administrative routes.
    - Inspects Bearer tokens for user mutation endpoints (alerts, watchlists).
    - Allows read-only access for public market ticker / status endpoints.
    """

    PROTECTED_INGESTION_PREFIXES = ("/v1/ingestion/",)
    PROTECTED_WRITE_PATHS = (
        ("/v1/notifications/alerts", "POST"),
        ("/v1/notifications/alerts", "DELETE"),
    )

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        path = request.url.path
        method = request.method.upper()

        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key", "") or request.headers.get("X-Internal-API-Key", "")

        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif api_key_header:
            token = api_key_header.strip()

        # Extract user context if JWT
        user_claims = _decode_jwt_payload_unverified(token) if token and "." in token else None
        request.state.token = token
        request.state.user = user_claims
        request.state.authenticated = bool(token)

        # 1. Internal ingestion route check
        is_ingestion_path = any(path.startswith(prefix) for prefix in self.PROTECTED_INGESTION_PREFIXES)
        if is_ingestion_path and settings.InternalApiKey:
            if token != settings.InternalApiKey:
                logger.warning("Unauthorized ingestion access attempt to %s from %s", path, request.client.host if request.client else "unknown")
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid or missing internal API key"}
                )

        # 2. Write protection for user mutation routes
        for protected_path, protected_method in self.PROTECTED_WRITE_PATHS:
            if path.startswith(protected_path) and method == protected_method:
                # If SupabaseKey or InternalApiKey is configured, ensure request has a token
                if (settings.SupabaseKey or settings.InternalApiKey) and not token:
                    logger.warning("Unauthenticated %s attempt to %s", method, path)
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "Authentication required for this operation"}
                    )

        return await call_next(request)

