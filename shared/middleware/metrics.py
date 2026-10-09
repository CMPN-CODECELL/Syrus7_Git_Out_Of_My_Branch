import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("api.metrics")

class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        logger.debug(
            f"metric:request_count method={request.method} path={request.url.path} status={response.status_code}"
        )
        return response
