import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from shared.logging.logger import set_correlation_id

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        set_correlation_id(request_id)
        
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
