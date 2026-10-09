from celery import Celery
from celery.schedules import crontab
from app.config.settings import get_settings

settings = get_settings()

# Celery runs analysis jobs only. Nothing scheduled here talks to 021 or sends orders.
celery_app = Celery(
    "Kraken",
    broker=settings.RedisUrl,
    backend=settings.RedisUrl,
    include=[
        "domains.ingestion.tasks.ingestion_tasks",
        "domains.ingestion.tasks.market_tasks",
        "domains.analytics.tasks.alert_tasks",
        "domains.historical.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_routes={
        "ingestion.*": {"queue": "ingestion"},
        "analytics.*": {"queue": "analytics"},
        "historical.*": {"queue": "analytics"},
        "domains.ingestion.tasks.*": {"queue": "ingestion"},
        "domains.analytics.tasks.*": {"queue": "analytics"},
    },
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
)

celery_app.conf.beat_schedule = {
    # Before market open (IST): refresh ~1 year of daily candles for holdings + positions.
    "daily-candle-backfill": {
        "task": "historical.backfill_daily",
        "schedule": crontab(hour=8, minute=45, day_of_week="mon-fri"),
    },
}
