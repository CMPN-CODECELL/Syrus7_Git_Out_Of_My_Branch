from shared.infrastructure.celery_app import celery_app
import logging
import json
from shared.constants import Channels
from shared.infrastructure.redis_client import get_redis_client_sync

logger = logging.getLogger(__name__)

@celery_app.task(name="analytics.dispatch_alert", queue="analytics")
def dispatch_alert(alert_payload: dict):
    """
    Dispatches an analytical alert to external sinks and UI.
    """
    symbol = alert_payload.get("symbol", "GLOBAL")
    label = alert_payload.get("composite_label", "NEUTRAL")
    
    logger.warning("ALERT: [%s] Market Signal: %s", symbol, label)
    
    # Mirror to Redis Pub/Sub for UI
    try:
        redis = get_redis_client_sync()
        channel = Channels.ALERT_DISPATCHED.format(symbol=symbol)
        redis.publish(channel, json.dumps(alert_payload))
    except Exception as exc:
        logger.error("Failed to publish alert to Pub/Sub: %s", exc)

