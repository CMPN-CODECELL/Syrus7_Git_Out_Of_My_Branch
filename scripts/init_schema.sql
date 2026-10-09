CREATE TABLE IF NOT EXISTS TickData (
    Timestamp       TIMESTAMPTZ     NOT NULL,
    Symbol          VARCHAR(20)     NOT NULL,
    Exchange        VARCHAR(5)      NOT NULL,
    InstrumentType  VARCHAR(5)      NOT NULL,  -- EQ | FUT | CE | PE
    LastPrice       DECIMAL(12,2),
    OpenInterest    BIGINT          DEFAULT 0,
    Volume          BIGINT,
    ExpiryDate      DATE,
    StrikePrice     DECIMAL(10,2),
    ImpliedVolatility DECIMAL(10,4),
    UnderlyingPrice DECIMAL(12,2)
);

-- Idempotent hypertable creation
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'tickdata') THEN
        PERFORM create_hypertable('tickdata', 'timestamp', chunk_time_interval => INTERVAL '1 day');
    END IF;
END $$;

-- Composite indexes for high-speed ticker lookups and option analytics
CREATE INDEX IF NOT EXISTS idx_tickdata_symbol_time ON TickData (Symbol, Timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tickdata_option_lookup ON TickData (Symbol, ExpiryDate, StrikePrice, InstrumentType, Timestamp DESC);

-- Retention Policy (90 days for research and multi-day export support)
SELECT add_retention_policy('tickdata', INTERVAL '90 days', if_not_exists => true);

-- Detected events
CREATE TABLE IF NOT EXISTS DetectedEvents (
    EventId         UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    Symbol          VARCHAR(20)     NOT NULL,
    EventType       VARCHAR(30)     NOT NULL,
    Headline        TEXT,
    EventDate       DATE,
    SourceType      VARCHAR(10),
    Confidence      DECIMAL(5,4)    DEFAULT 1.0,
    DetectedAt      TIMESTAMPTZ     DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_events_symbol_time ON DetectedEvents (Symbol, DetectedAt DESC);

-- Alert rules (user-defined V2)
CREATE TABLE IF NOT EXISTS AlertRules (
    id UUID PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    condition_type VARCHAR(32) NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    channels TEXT[] NOT NULL,
    cooldown_seconds INT NOT NULL DEFAULT 300,
    last_triggered_at TIMESTAMPTZ NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    webhook_url TEXT NULL,
    email_destination TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Domain events log
CREATE TABLE IF NOT EXISTS DomainEvents (
    EventId         UUID            PRIMARY KEY,
    EventType       VARCHAR(100)    NOT NULL,
    Payload         JSONB           NOT NULL,
    OccurredAt      TIMESTAMPTZ     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_domain_events_occurred_at ON DomainEvents (OccurredAt DESC);
CREATE INDEX IF NOT EXISTS idx_domain_events_payload_symbol ON DomainEvents ((Payload->>'symbol'));
