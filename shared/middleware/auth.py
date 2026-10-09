import hmac
import logging

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config.settings import get_settings
from shared.auth.supabase_jwt import AuthError, bearer_token, verify_supabase_jwt

logger = logging.getLogger("api.auth")


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    Defense-in-depth authentication middleware:
    - Internal service key (constant-time compare) for ingestion routes.
    - Verified Supabase JWT (signature, expiry, audience) for every user-scoped route.
      Unverified tokens are never trusted; request.state.user is set only after verification.
    - Public read-only market routes stay open.
    Route-level `Depends(require_user)` is the primary guard for new routers; this middleware
    covers older routers that predate it.
    """

    PROTECTED_INGESTION_PREFIXES = ("/v1/ingestion/",)
    USER_PREFIXES = ("/v1/notifications/",)

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        path = request.url.path

        token = bearer_token(request)
        api_key = request.headers.get("X-API-Key", "") or request.headers.get("X-Internal-API-Key", "")
        request.state.user = None

        # 1. Internal ingestion routes
        if any(path.startswith(prefix) for prefix in self.PROTECTED_INGESTION_PREFIXES) and settings.InternalApiKey:
            supplied = api_key or token
            if not supplied or not hmac.compare_digest(supplied, settings.InternalApiKey):
                logger.warning("Unauthorized ingestion access attempt to %s", path)
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid or missing internal API key"},
                )
            return await call_next(request)

        # 2. User-scoped legacy routes require a verified user
        if any(path.startswith(prefix) for prefix in self.USER_PREFIXES):
            try:
                request.state.user = verify_supabase_jwt(token)
            except AuthError as exc:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": str(exc)},
                    headers={"WWW-Authenticate": "Bearer"},
                )

        return await call_next(request)
