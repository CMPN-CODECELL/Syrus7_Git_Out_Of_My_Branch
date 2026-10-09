-- Kraken 003: durable chat history. One row per exchange (the trader's message and Kraken's reply).
-- The reply column holds what the UI renders: text, tool traces, tool data and proposal ids.
-- It never holds order state: cards are always re-read from kraken_proposals.

CREATE TABLE IF NOT EXISTS kraken_chat_turns (
    id          BIGSERIAL   PRIMARY KEY,
    user_id     TEXT        NOT NULL,
    message     TEXT        NOT NULL,
    reply       JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kraken_chat_turns_user_id ON kraken_chat_turns (user_id, id DESC);
