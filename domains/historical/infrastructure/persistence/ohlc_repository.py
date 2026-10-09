"""
File Overview: TimescaleDB/PostgreSQL persistence adapter implementing IOhlcRepositoryPort.
Uses asyncpg pool for high-throughput bulk inserts and range queries.
"""
import logging
from typing import List, Optional
from datetime import datetime, timezone
import asyncpg

from domains.historical.domain.entities import CandleEntity
from domains.historical.ports.interface.outbound.i_ohlc_repository_port import IOhlcRepositoryPort

logger = logging.getLogger(__name__)


class TimescaleOhlcRepository(IOhlcRepositoryPort):
    """Async PostgreSQL / TimescaleDB repository implementation for OHLC candles."""

    def __init__(self, db_pool: asyncpg.Pool):
        self._pool = db_pool

    async def save_candles(self, candles: List[CandleEntity]) -> int:
        if not candles:
            return 0

        records = [
            (
                c.symbol.upper(),
                c.timestamp.replace(tzinfo=timezone.utc) if c.timestamp.tzinfo is None else c.timestamp,
                c.timeframe,
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume,
            )
            for c in candles
        ]

        query = """
            INSERT INTO OhlcCandles (symbol, timestamp, timeframe, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (symbol, timeframe, timestamp) 
            DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume;
        """

        async with self._pool.acquire() as conn:
            await conn.executemany(query, records)

        logger.debug("Saved %d OHLC candles to TimescaleDB", len(records))
        return len(records)

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        end_time: Optional[datetime] = None,
    ) -> List[CandleEntity]:
        symbol_upper = symbol.strip().upper()
        
        if end_time:
            query = """
                SELECT symbol, timestamp, timeframe, open, high, low, close, volume
                FROM OhlcCandles
                WHERE UPPER(symbol) = $1 AND timeframe = $2 AND timestamp <= $3
                ORDER BY timestamp DESC
                LIMIT $4;
            """
            params = (symbol_upper, timeframe, end_time, limit)
        else:
            query = """
                SELECT symbol, timestamp, timeframe, open, high, low, close, volume
                FROM OhlcCandles
                WHERE UPPER(symbol) = $1 AND timeframe = $2
                ORDER BY timestamp DESC
                LIMIT $3;
            """
            params = (symbol_upper, timeframe, limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        candles = [
            CandleEntity(
                symbol=r["symbol"],
                timestamp=r["timestamp"],
                timeframe=r["timeframe"],
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=int(r["volume"]),
            )
            for r in rows
        ]

        # Return ascending by timestamp
        candles.reverse()
        return candles
