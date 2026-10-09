"""
File Overview: Shared enums, channel names, and configuration constants for Redis Pub/Sub and Market Data.

All Functions/Classes:
- Channels (class): Redis Pub/Sub channel templates.
- Streams (class): Redis Stream names for durable events.
- StreamGroups (class): Consumer-group names for stream processing.
- MarketStatus, OptionType (Enums): Domain status and category codes.
- RedisKeys (class): Redis key templates for cached data.
- TTL (class): Expiration times for cached items.

Endpoints/APIs:
- None.

Database Tables:
- None.
"""


from enum import Enum


# ── Redis Pub/Sub Channel Names ────────────────────────────────

class Channels:
    """Redis Pub/Sub channel name templates. Use .format(symbol=...) to build."""

    # Ingestion domain publishes:
    PRICE_UPDATED         = "market.price_updated.{symbol}"
    OPTIONS_UPDATED       = "market.options_updated.{symbol}"
    PRICE_TRIGGER         = "market.price_trigger.{symbol}"

    # Analytics domain/Alert publishes:
    ALERT_DISPATCHED      = "alerts.dispatched.{symbol}"



# ── Redis Streams (Durable Topics) ────────────────────────────

class Streams:
    """Redis Stream names for durable/replayable cross-domain events."""

    PRICE_TRIGGER         = "stream:market.price_trigger"
    OPTIONS_RAW_FETCHED   = "stream:options.raw_fetched"
    OPTIONS_PRICED        = "stream:options.priced"
    ANALYSIS_REFRESH_REQUESTED = "stream:analysis.refresh_requested"

    # Dead-letter topics
    REFRESH_REQUEST_DLQ   = "stream:dlq:refresh_request"


class StreamGroups:
    """Consumer-group names for durable stream processing."""

    REFRESH_TO_INGESTION = "cg:refresh_to_ingestion"


# ── Enums ──────────────────────────────────────────────────────

class MarketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_MARKET = "PRE_MARKET"
    POST_MARKET = "POST_MARKET"


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


# ── Redis Key Prefixes ────────────────────────────────────────

class RedisKeys:
    """Redis key templates for cached data. Use .format() to build."""

    # Ingestion domain owns:
    MARKET_PRICE       = "market:price:{symbol}"            # Today's OHLCV snapshot
    MARKET_OPTIONS     = "market:options:{symbol}"           # Latest option chain
    MARKET_OPTIONS_PRICED = "market:options:priced:{symbol}" # Fair priced option chain


# ── TTLs (seconds) ────────────────────────────────────────────

class TTL:
    MARKET_PRICE          = 60       # 60s — refreshed continuously every poll cycle
    MARKET_OPTIONS        = 120      # 2 min option chain freshness
    MARKET_OPTIONS_PRICED = 120      # 2 min priced chain freshness
    HISTORICAL_OHLC       = 3600     # 1 hour for historical OHLC bars


# ── Index Symbols (use option-chain-indices endpoint) ─────────

INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY"}
