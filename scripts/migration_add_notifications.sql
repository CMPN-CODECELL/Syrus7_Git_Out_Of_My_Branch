-- Migration: Add Notification & Alert Rule Tables with TimescaleDB Data Retention

-- 0. Drop legacy AlertRules table if old schema (RuleId column) exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE LOWER(table_name) = 'alertrules' AND LOWER(column_name) = 'ruleid'
    ) THEN
        DROP TABLE AlertRules CASCADE;
    END IF;
END $$;

-- 1. Create AlertRules table
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

CREATE INDEX IF NOT EXISTS idx_alert_rules_symbol ON AlertRules (symbol, is_active);

-- 2. Create NotificationLogs table
CREATE TABLE IF NOT EXISTS NotificationLogs (
    id UUID NOT NULL,
    rule_id UUID NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    condition_type VARCHAR(32) NOT NULL,
    triggered_value DOUBLE PRECISION NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    message TEXT NOT NULL,
    channels TEXT[] NOT NULL,
    status VARCHAR(32) NOT NULL,
    error_message TEXT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for querying notification history by symbol/rule
CREATE INDEX IF NOT EXISTS idx_notification_logs_symbol_time ON NotificationLogs (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_notification_logs_rule_id ON NotificationLogs (rule_id, timestamp DESC);

-- 3. Convert NotificationLogs to TimescaleDB Hypertable (partitioned on timestamp)
SELECT create_hypertable('NotificationLogs', 'timestamp', if_not_exists => TRUE);

-- 4. Enable 14-day Automated Data Retention Policy to prevent database bloat
SELECT add_retention_policy('NotificationLogs', INTERVAL '14 days', if_not_exists => TRUE);
