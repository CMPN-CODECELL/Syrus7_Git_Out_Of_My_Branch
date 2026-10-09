import time
import uuid
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from shared.logging.logger import set_correlation_id

logger = logging.getLogger("api.request")

class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()
        
        # Extract correlation ID from headers or generate new one
        correlation_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or str(uuid.uuid4())
        set_correlation_id(correlation_id)
        
        response = None
        try:
            response = await call_next(request)
            # Add correlation ID to response headers
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        except Exception as exc:
            # If an error happens, log it with context
            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                exc_info=True,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "client_ip": request.client.host if request.client else None,
                }
            )
            raise exc
        finally:
            process_time = time.perf_counter() - start_time
            if response:
                status_code = response.status_code
                logger.info(
                    f"HTTP {request.method} {request.url.path} returned {status_code} in {process_time:.4f}s",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "process_time_seconds": process_time,
                        "client_ip": request.client.host if request.client else None,
                    }
                )
