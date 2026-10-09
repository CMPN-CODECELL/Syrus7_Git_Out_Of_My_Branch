-- Migration: Add composite indexes to TickData and update retention policy
CREATE INDEX IF NOT EXISTS idx_tickdata_symbol_time ON TickData (Symbol, Timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tickdata_option_lookup ON TickData (Symbol, ExpiryDate, StrikePrice, InstrumentType, Timestamp DESC);

-- Update retention policy to 90 days
SELECT remove_retention_policy('tickdata', if_exists => true);
SELECT add_retention_policy('tickdata', INTERVAL '90 days', if_not_exists => true);
