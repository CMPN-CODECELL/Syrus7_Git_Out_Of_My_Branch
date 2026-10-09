-- Migration: Add Historical OHLC Hypertables and Retention Policies
-- TimescaleDB partitioning for high performance 1m, 5m, 1d candles

CREATE TABLE IF NOT EXISTS OhlcCandles (
    symbol VARCHAR(32) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    timeframe VARCHAR(8) NOT NULL DEFAULT '1m',
    open NUMERIC(14, 4) NOT NULL,
    high NUMERIC(14, 4) NOT NULL,
    low NUMERIC(14, 4) NOT NULL,
    close NUMERIC(14, 4) NOT NULL,
    volume BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, timeframe, timestamp)
);

-- Convert into TimescaleDB Hypertable partitioned by timestamp (if TimescaleDB extension enabled)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable('OhlcCandles', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);
        -- Auto retention policy: drop candles older than 90 days
        PERFORM add_retention_policy('OhlcCandles', INTERVAL '90 days', if_not_exists => TRUE);
    END IF;
END $$;

-- Indexes for fast timeframe and symbol querying
CREATE INDEX IF NOT EXISTS idx_ohlc_symbol_tf_ts ON OhlcCandles (UPPER(symbol), timeframe, timestamp DESC);
