-- Kraken 001: keep ~13 months of daily candles so SMA(200) and 1-year history are available.
-- The inherited policy dropped OHLC rows after 90 days.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM remove_retention_policy('OhlcCandles', if_exists => TRUE);
        PERFORM add_retention_policy('OhlcCandles', INTERVAL '400 days', if_not_exists => TRUE);
    END IF;
END $$;
