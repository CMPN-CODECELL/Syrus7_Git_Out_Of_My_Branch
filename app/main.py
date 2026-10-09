"""
File Overview: Entry point for FastAPI application. Sets up middleware, lifespan hooks,
and includes domain routers following hexagonal architecture.

All Functions/Classes:
- lifespan: Manages app lifecycle. Data: startup -> warm Redis/DB connections, shutdown -> close pools.
- root: Health check endpoint. Data: None -> status dict.

Endpoints/APIs:
- /: root (health check)
- /ws/{symbol}: events_router (WebSocket)
- /v1/derivatives: derivatives_router
- /v1/symbols: symbols_router
- /v1/ingestion/nse: nse_options_router

Database Tables:
- None directly. Initializes connections for Redis and TimescaleDB.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from shared.logging import setup_logging
setup_logging()

# Domain routers
from domains.analytics.api.events_router_api import router as events_router
from domains.analytics.api.derivatives_router_api import router as derivatives_router
from domains.analytics.api.symbols_router_api import router as symbols_router
from domains.analytics.api.pricer_router_api import router as pricer_router
from domains.analytics.api.export_research_api import router as export_research_router
from domains.ingestion.api.nse_options_router_api import nse_options_router_api
from domains.notifications.api.router import router as notifications_router
from app.config.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Application lifecycle: warm connections on startup, close on shutdown."""
    from shared.infrastructure.redis_client import get_redis_client, close_redis_client
    from shared.infrastructure.database import close_database_pool

    # Startup: warm Redis connection pool
    try:
        await get_redis_client()
        logger.info("Redis connection warmed during startup")
    except Exception as exc:
        logger.warning("Redis warmup failed (will retry on first use): %s", exc)

    # Startup: initialize NSE httpx client for option chain fetching
    try:
        from domains.ingestion.api.nse_options_router_api import startup_nse_client
        await startup_nse_client()
        logger.info("NSE httpx client initialized during startup")
    except Exception as exc:
        logger.warning("NSE client startup failed (will lazy-init on first use): %s", exc)

    yield

    # Shutdown: close NSE httpx client
    try:
        from domains.ingestion.api.nse_options_router_api import shutdown_nse_client
        await shutdown_nse_client()
    except Exception as exc:
        logger.warning("NSE client shutdown error: %s", exc)

    # Shutdown: close connection pools
    await close_redis_client()
    await close_database_pool()
    logger.info("All connection pools closed")


app = FastAPI(title="AlphaStreams DDD Engine", lifespan=lifespan)

from shared.middleware import (
    RequestIDMiddleware,
    TimingMiddleware,
    MetricsMiddleware,
    APIKeyAuthMiddleware,
)
from shared.logging import StructuredLoggingMiddleware

app.add_middleware(APIKeyAuthMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(events_router)
app.include_router(events_router, prefix="/v1")
app.include_router(derivatives_router, prefix="/v1")
app.include_router(symbols_router, prefix="/v1")
app.include_router(pricer_router, prefix="/v1")
app.include_router(export_research_router, prefix="/v1")
app.include_router(nse_options_router_api, prefix="/v1/ingestion")
app.include_router(notifications_router)


@app.get("/health")
async def health(response: Response):
    from shared.infrastructure.redis_client import get_redis_client
    from shared.infrastructure.database import get_database_pool

    current_settings = get_settings()
    redis_status = "disabled"
    db_status = "disabled"
    healthy = True

    try:
        r = await get_redis_client()
        if r and await r.ping():
            redis_status = "connected"
        else:
            redis_status = "disconnected"
            if current_settings.AppEnv == "production":
                healthy = False
    except Exception as exc:
        redis_status = "error"
        logger.debug("Health check Redis ping failed: %s", exc)
        if current_settings.AppEnv == "production":
            healthy = False

    try:
        pool = await get_database_pool()
        if pool:
            async with pool.acquire() as conn:
                val = await conn.fetchval("SELECT 1")
                if val == 1:
                    db_status = "connected"
                else:
                    db_status = "disconnected"
                    if current_settings.AppEnv == "production":
                        healthy = False
        else:
            db_status = "disconnected"
            if current_settings.AppEnv == "production":
                healthy = False
    except Exception as exc:
        db_status = "error"
        logger.debug("Health check DB query failed: %s", exc)
        if current_settings.AppEnv == "production":
            healthy = False

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if healthy else "degraded",
        "environment": current_settings.AppEnv,
        "redis": redis_status,
        "database": db_status
    }


@app.get("/config")
def get_config(request: Request):
    from urllib.parse import urlparse
    settings = get_settings()
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if origin and settings.AppEnv == "production":
        parsed = urlparse(origin)
        origin_clean = f"{parsed.scheme}://{parsed.netloc}"
        allowed = settings.get_allowed_origins_list()
        if origin_clean not in allowed and "localhost" not in origin_clean and "127.0.0.1" not in origin_clean:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin access forbidden")

    return {
        "supabaseUrl": settings.SupabaseUrl,
        "supabaseKey": settings.SupabaseKey
    }


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")