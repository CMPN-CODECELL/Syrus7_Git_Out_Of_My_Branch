-- Kraken 002: Level 2 orders. Proposals, the order journal and an append-only audit log.

CREATE TABLE IF NOT EXISTS kraken_proposals (
    id               UUID PRIMARY KEY,
    user_id          TEXT        NOT NULL,
    kind             TEXT        NOT NULL CHECK (kind IN ('PLACE', 'MODIFY', 'CANCEL')),
    payload          JSONB       NOT NULL,
    payload_hash     TEXT        NOT NULL,
    display          JSONB       NOT NULL,
    target_order_id  TEXT,
    state            TEXT        NOT NULL DEFAULT 'PROPOSED' CHECK (state IN ('PROPOSED', 'APPROVED', 'REJECTED', 'EXPIRED')),
    state_reason     TEXT,
    created_at       TIMESTAMPTZ NOT NULL,
    expires_at       TIMESTAMPTZ NOT NULL,
    decided_at       TIMESTAMPTZ,
    reference_ltp    BIGINT,
    source_check     JSONB,
    draft            JSONB,
    request_id       TEXT
);
CREATE INDEX IF NOT EXISTS idx_kraken_proposals_user_created ON kraken_proposals (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS kraken_order_journal (
    id                 UUID PRIMARY KEY,
    -- UNIQUE: one approved proposal can produce at most one send.
    proposal_id        UUID        NOT NULL UNIQUE REFERENCES kraken_proposals (id),
    user_id            TEXT        NOT NULL,
    action             TEXT        NOT NULL CHECK (action IN ('PLACE', 'MODIFY', 'CANCEL')),
    payload            JSONB       NOT NULL,
    payload_hash       TEXT        NOT NULL,
    target_order_id    TEXT,
    state              TEXT        NOT NULL CHECK (state IN ('SENDING', 'ACKED', 'REJECTED', 'NOT_SENT', 'UNKNOWN', 'NOT_PLACED', 'AMBIGUOUS')),
    order_id           TEXT,
    order_status       TEXT,
    filled_qty         BIGINT      NOT NULL DEFAULT 0,
    avg_fill_price     BIGINT,
    reason             TEXT,
    sent_at            TIMESTAMPTZ NOT NULL,
    updated_at         TIMESTAMPTZ NOT NULL,
    reconcile_attempts INT         NOT NULL DEFAULT 0,
    next_reconcile_at  TIMESTAMPTZ,
    display            JSONB
);
CREATE INDEX IF NOT EXISTS idx_kraken_journal_user_sent ON kraken_order_journal (user_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_kraken_journal_order ON kraken_order_journal (order_id);
CREATE INDEX IF NOT EXISTS idx_kraken_journal_unresolved ON kraken_order_journal (state) WHERE state IN ('SENDING', 'UNKNOWN');
-- One 021 order can be linked to at most one PLACE row, so a reconciler can never count it twice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_kraken_journal_place_order ON kraken_order_journal (order_id)
    WHERE order_id IS NOT NULL AND action = 'PLACE';

CREATE TABLE IF NOT EXISTS kraken_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kind        TEXT        NOT NULL,
    user_id     TEXT,
    request_id  TEXT,
    proposal_id UUID,
    journal_id  UUID,
    order_id    TEXT,
    data        JSONB       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_kraken_audit_proposal ON kraken_audit_log (proposal_id);
CREATE INDEX IF NOT EXISTS idx_kraken_audit_user_at ON kraken_audit_log (user_id, at DESC);

CREATE OR REPLACE FUNCTION kraken_audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'kraken_audit_log is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_kraken_audit_append_only ON kraken_audit_log;
CREATE TRIGGER trg_kraken_audit_append_only
    BEFORE UPDATE OR DELETE ON kraken_audit_log
    FOR EACH ROW EXECUTE FUNCTION kraken_audit_append_only();
