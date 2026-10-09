-- Migration: Add IV and Underlying Price to TickData
ALTER TABLE TickData ADD COLUMN IF NOT EXISTS ImpliedVolatility DECIMAL(10,4);
ALTER TABLE TickData ADD COLUMN IF NOT EXISTS UnderlyingPrice DECIMAL(12,2);

-- Ensure retention policy is added (if not already)
SELECT add_retention_policy('tickdata', INTERVAL '7 days', if_not_exists => true);
