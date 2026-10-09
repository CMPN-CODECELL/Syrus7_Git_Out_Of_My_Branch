"""Postgres OrderStore / AuditSink (tables from scripts/migration_kraken_002_orders.sql).

claim() runs the compare-and-set and the journal insert in one transaction; the UNIQUE
constraint on journal.proposal_id is a second guard against double execution.
"""
import json
import logging
import uuid
from typing import Any, Optional

import asyncpg

from domains.orders.ports import ClaimResult
from shared.contracts.orders import FINAL_ORDER_STATUSES, JournalEntry, OrderPayload, OrderProposal, ProposalDisplay

logger = logging.getLogger(__name__)


def _j(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value, default=str, separators=(",", ":"))


def _load(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _proposal(row: asyncpg.Record) -> OrderProposal:
    return OrderProposal(
        id=row["id"], user_id=row["user_id"], kind=row["kind"],
        payload=OrderPayload.model_validate(_load(row["payload"])), payload_hash=row["payload_hash"],
        display=ProposalDisplay.model_validate(_load(row["display"])), target_order_id=row["target_order_id"],
        created_at=row["created_at"], expires_at=row["expires_at"], state=row["state"], state_reason=row["state_reason"],
        decided_at=row["decided_at"], reference_ltp=row["reference_ltp"], source_check=_load(row["source_check"]),
        draft=_load(row["draft"]), request_id=row["request_id"],
    )


def _journal(row: asyncpg.Record) -> JournalEntry:
    display = _load(row["display"])
    return JournalEntry(
        id=row["id"], proposal_id=row["proposal_id"], user_id=row["user_id"], action=row["action"],
        payload=OrderPayload.model_validate(_load(row["payload"])), payload_hash=row["payload_hash"],
        target_order_id=row["target_order_id"], state=row["state"], order_id=row["order_id"],
        order_status=row["order_status"], filled_qty=row["filled_qty"], avg_fill_price=row["avg_fill_price"],
        reason=row["reason"], sent_at=row["sent_at"], updated_at=row["updated_at"],
        reconcile_attempts=row["reconcile_attempts"], next_reconcile_at=row["next_reconcile_at"],
        display=ProposalDisplay.model_validate(display) if display else None,
    )


_JOURNAL_COLUMNS = (
    "id, proposal_id, user_id, action, payload, payload_hash, target_order_id, state, order_id, order_status, "
    "filled_qty, avg_fill_price, reason, sent_at, updated_at, reconcile_attempts, next_reconcile_at, display"
)


class PgOrderStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def save_proposal(self, p: OrderProposal) -> None:
        await self._pool.execute(
            """INSERT INTO kraken_proposals (id, user_id, kind, payload, payload_hash, display, target_order_id, state,
                   state_reason, created_at, expires_at, decided_at, reference_ltp, source_check, draft, request_id)
               VALUES ($1,$2,$3,$4::jsonb,$5,$6::jsonb,$7,$8,$9,$10,$11,$12,$13,$14::jsonb,$15::jsonb,$16)""",
            p.id, p.user_id, p.kind, _j(p.payload.to_request_json()), p.payload_hash, _j(p.display.model_dump(mode="json")),
            p.target_order_id, p.state, p.state_reason, p.created_at, p.expires_at, p.decided_at, p.reference_ltp,
            _j(p.source_check), _j(p.draft), p.request_id,
        )

    async def get_proposal(self, proposal_id: uuid.UUID) -> Optional[OrderProposal]:
        row = await self._pool.fetchrow("SELECT * FROM kraken_proposals WHERE id = $1", proposal_id)
        return _proposal(row) if row else None

    async def transition_proposal(self, proposal_id, *, from_state, to_state, reason, now) -> bool:
        result = await self._pool.execute(
            "UPDATE kraken_proposals SET state=$3, state_reason=$4, decided_at=$5 WHERE id=$1 AND state=$2",
            proposal_id, from_state, to_state, reason, now,
        )
        return result.endswith(" 1")

    async def claim(self, proposal_id, user_id, payload_hash, now, journal: JournalEntry) -> ClaimResult:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE kraken_proposals SET state='APPROVED', decided_at=$4
                       WHERE id=$1 AND user_id=$2 AND state='PROPOSED' AND expires_at > $4 AND payload_hash=$3
                       RETURNING *""",
                    proposal_id, user_id, payload_hash, now,
                )
                if row is None:
                    current = await conn.fetchrow("SELECT * FROM kraken_proposals WHERE id=$1", proposal_id)
                    if current is None:
                        return ClaimResult(False, failure="not_found")
                    p = _proposal(current)
                    if p.user_id != user_id:
                        return ClaimResult(False, failure="not_owner")
                    if p.state != "PROPOSED":
                        return ClaimResult(False, proposal=p, failure="not_proposed")
                    if p.expires_at <= now:
                        return ClaimResult(False, proposal=p, failure="expired")
                    return ClaimResult(False, proposal=p, failure="hash_mismatch")
                await conn.execute(
                    f"""INSERT INTO kraken_order_journal ({_JOURNAL_COLUMNS})
                        VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::jsonb)""",
                    journal.id, journal.proposal_id, journal.user_id, journal.action, _j(journal.payload.to_request_json()),
                    journal.payload_hash, journal.target_order_id, journal.state, journal.order_id, journal.order_status,
                    journal.filled_qty, journal.avg_fill_price, journal.reason, journal.sent_at, journal.updated_at,
                    journal.reconcile_attempts, journal.next_reconcile_at,
                    _j(journal.display.model_dump(mode="json")) if journal.display else None,
                )
                return ClaimResult(True, proposal=_proposal(row), journal=journal)

    async def get_journal(self, journal_id) -> Optional[JournalEntry]:
        row = await self._pool.fetchrow(f"SELECT {_JOURNAL_COLUMNS} FROM kraken_order_journal WHERE id=$1", journal_id)
        return _journal(row) if row else None

    async def update_journal(self, e: JournalEntry) -> None:
        await self._pool.execute(
            """UPDATE kraken_order_journal SET state=$2, order_id=$3, order_status=$4, filled_qty=$5, avg_fill_price=$6,
                   reason=$7, updated_at=NOW(), reconcile_attempts=$8, next_reconcile_at=$9 WHERE id=$1""",
            e.id, e.state, e.order_id, e.order_status, e.filled_qty, e.avg_fill_price, e.reason,
            e.reconcile_attempts, e.next_reconcile_at,
        )

    async def link_order(self, journal_id, order_id: str) -> bool:
        try:
            result = await self._pool.execute(
                "UPDATE kraken_order_journal SET order_id=$2, updated_at=NOW() WHERE id=$1", journal_id, order_id)
        except asyncpg.UniqueViolationError:
            return False
        return result.endswith(" 1")

    async def _many(self, where: str, *args, suffix: str = "") -> list[JournalEntry]:
        rows = await self._pool.fetch(f"SELECT {_JOURNAL_COLUMNS} FROM kraken_order_journal WHERE {where} {suffix}", *args)
        return [_journal(r) for r in rows]

    async def list_journal(self, user_id: str, limit: int = 50) -> list[JournalEntry]:
        return await self._many("user_id=$1", user_id, limit, suffix="ORDER BY sent_at DESC LIMIT $2")

    async def unresolved_journal(self) -> list[JournalEntry]:
        return await self._many("state IN ('SENDING','UNKNOWN')")

    async def open_journal(self) -> list[JournalEntry]:
        finals = list(FINAL_ORDER_STATUSES)
        return await self._many("order_id IS NOT NULL AND state='ACKED' AND (order_status IS NULL OR NOT (order_status = ANY($1::text[])))", finals)

    async def journal_by_order_id(self, order_id: str) -> list[JournalEntry]:
        return await self._many("order_id=$1", order_id)

    async def linked_place_order_ids(self) -> set[str]:
        rows = await self._pool.fetch("SELECT order_id FROM kraken_order_journal WHERE order_id IS NOT NULL AND action='PLACE'")
        return {r["order_id"] for r in rows}

    async def latest_proposals(self, user_id: str, limit: int = 5) -> list[OrderProposal]:
        rows = await self._pool.fetch(
            "SELECT * FROM kraken_proposals WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2", user_id, limit)
        return [_proposal(r) for r in rows]


class PgAuditSink:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def record(self, kind, *, user_id=None, request_id=None, proposal_id=None, journal_id=None, order_id=None, data=None) -> None:
        try:
            await self._pool.execute(
                """INSERT INTO kraken_audit_log (kind, user_id, request_id, proposal_id, journal_id, order_id, data)
                   VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)""",
                kind, user_id, request_id, proposal_id, journal_id, order_id, _j(data or {}),
            )
        except Exception as exc:  # the audit trail must never block trading paths
            logger.error("audit write failed (%s): %s", kind, exc)
