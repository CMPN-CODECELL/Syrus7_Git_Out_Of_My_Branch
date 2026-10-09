import json
import asyncio
import logging
import os
from typing import Optional
from redis.asyncio import Redis

from domains.notifications.infrastructure.persistence.alert_repository import PostgresAlertRuleRepository
from domains.notifications.infrastructure.channels.websocket_channel import WebSocketNotificationChannelAdapter
from domains.notifications.infrastructure.channels.webhook_channel import WebhookNotificationChannelAdapter
from domains.notifications.infrastructure.channels.email_channel import EmailNotificationChannelAdapter
from domains.notifications.application.evaluate_alerts_service import EvaluateAlertsService
from shared.constants import Streams

logger = logging.getLogger("notification_subscriber")


class NotificationStreamSubscriber:
    """Background consumer daemon listening to Redis Streams and evaluating active alert rules."""

    def __init__(self, redis_client: Redis, repository: Optional[PostgresAlertRuleRepository] = None):
        self.redis = redis_client
        self.consume_stream = Streams.OPTIONS_PRICED
        self.repo = repository or PostgresAlertRuleRepository()
        self.channels = [
            WebSocketNotificationChannelAdapter(),
            WebhookNotificationChannelAdapter(),
            EmailNotificationChannelAdapter(),
        ]
        self.evaluator = EvaluateAlertsService(repository=self.repo, channels=self.channels)

    async def start_consuming(self):
        last_id = "$"
        logger.info(f"Notification Stream Subscriber listening on stream '{self.consume_stream}'...")

        while True:
            try:
                events = await self.redis.xread({self.consume_stream: last_id}, count=5, block=5000)
                if not events:
                    continue

                for stream, messages in events:
                    for message_id, payload in messages:
                        try:
                            await self.process_event(payload)
                        except Exception as exc:
                            logger.error(f"Failed to process alert stream event {message_id}: {exc}", exc_info=True)
                        last_id = message_id
            except asyncio.CancelledError:
                logger.info("Notification Stream Subscriber stopping...")
                break
            except Exception as ex:
                logger.error(f"Error in Notification Stream Subscriber consume loop: {ex}")
                await asyncio.sleep(2)

    async def process_event(self, payload: dict):
        raw_data = payload.get(b"data") or payload.get("data")
        if not raw_data:
            return

        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode("utf-8")

        parsed = json.loads(raw_data)
        symbol = parsed.get("symbol")
        if not symbol:
            return

        # Prepare normalized tick evaluation dictionary
        tick_dict = {
            "spot_price": parsed.get("spot_price") or parsed.get("last_price"),
            "implied_volatility": parsed.get("implied_volatility") or parsed.get("iv"),
            "delta": parsed.get("delta"),
        }

        # Check if priced chain is attached
        chain = parsed.get("chain", [])
        if chain and isinstance(chain, list):
            for item in chain:
                strike_tick = {
                    "last_price": item.get("live_call") or item.get("bs_fair_call"),
                    "implied_volatility": item.get("call_iv"),
                }
                await self.evaluator.evaluate_tick_event(symbol, strike_tick)

        # Evaluate top-level symbol tick
        await self.evaluator.evaluate_tick_event(symbol, tick_dict)


async def main():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_client = Redis.from_url(redis_url)
    try:
        subscriber = NotificationStreamSubscriber(redis_client)
        await subscriber.start_consuming()
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass
    asyncio.run(main())
