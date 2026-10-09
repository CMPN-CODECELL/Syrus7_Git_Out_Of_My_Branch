"""
PgOrderStore / PgAuditSink against a real Postgres with migration kraken_002 applied.

Run inside the app container (Postgres is not exposed to the host). Dev database only: it writes
rows for user 'pg-test', including one append-only audit row that cannot be deleted.
    docker compose exec app pip install pytest pytest-asyncio
    docker compose exec app python scripts/migrate.py
    docker compose exec -e KRAKEN_PG_TESTS=1 app python -m pytest tests/integration/test_order_store_pg.py -q
Skipped unless KRAKEN_PG_TESTS=1 and DATABASE_URL points at a database with the order tables.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.getenv("KRAKEN_PG_TESTS") != "1", reason="needs Postgres (KRAKEN_PG_TESTS=1)")]


@pytest.fixture
async def pg():
    import asyncpg

    from domains.orders.infrastructure.pg_store import PgAuditSink, PgOrderStore

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=5)
    if await pool.fetchval("SELECT to_regclass('kraken_order_journal')") is None:
        await pool.close()
        pytest.skip("order tables missing; run scripts/migrate.py")
    yield PgOrderStore(pool), PgAuditSink(pool), pool
    await pool.close()


def _proposal(user: str = "pg-test"):
    from shared.contracts.orders import OrderPayload, OrderProposal, ProposalDisplay

    payload = OrderPayload(exchange="NSE", token=1594, qty=uuid.uuid4().int % 900 + 1, price=0, product="CNC")
    now = datetime.now(timezone.utc)
    display = ProposalDisplay(symbol="INFY", exchange="NSE", side="BUY", quantity=payload.qty, order_type="MARKET")
    return OrderProposal(user_id=user, kind="PLACE", payload=payload, payload_hash=payload.payload_hash(), display=display,
                         created_at=now, expires_at=now + timedelta(seconds=60), reference_ltp=153000,
                         source_check={"kind": "AVAILABLE"}, draft={"action": "BUY"})


def _journal(p):
    from shared.contracts.orders import JournalEntry

    now = datetime.now(timezone.utc)
    return JournalEntry(proposal_id=p.id, user_id=p.user_id, action="PLACE", payload=p.payload, payload_hash=p.payload_hash,
                        sent_at=now, updated_at=now, display=p.display)


async def test_round_trip_and_single_winner_claim(pg):
    store, audit, _ = pg
    p = _proposal()
    await store.save_proposal(p)
    loaded = await store.get_proposal(p.id)
    assert loaded.payload_hash == p.payload_hash and loaded.source_check == {"kind": "AVAILABLE"}
    now = datetime.now(timezone.utc)
    results = await asyncio.gather(*(store.claim(p.id, p.user_id, p.payload_hash, now, _journal(p)) for _ in range(5)))
    assert sum(r.ok for r in results) == 1
    assert (await store.get_proposal(p.id)).state == "APPROVED"


async def test_claim_failures(pg):
    store, _, _ = pg
    p = _proposal()
    await store.save_proposal(p)
    now = datetime.now(timezone.utc)
    assert (await store.claim(p.id, "someone-else", p.payload_hash, now, _journal(p))).failure == "not_owner"
    assert (await store.claim(p.id, p.user_id, "0" * 64, now, _journal(p))).failure == "hash_mismatch"
    later = now + timedelta(seconds=120)
    assert (await store.claim(p.id, p.user_id, p.payload_hash, later, _journal(p))).failure == "expired"


async def test_order_id_links_to_one_place_row_only(pg):
    store, _, _ = pg
    now = datetime.now(timezone.utc)
    a, b = _proposal(), _proposal()
    for p in (a, b):
        await store.save_proposal(p)
    ja, jb = _journal(a), _journal(b)
    assert (await store.claim(a.id, a.user_id, a.payload_hash, now, ja)).ok
    assert (await store.claim(b.id, b.user_id, b.payload_hash, now, jb)).ok
    order_id = f"pg-{uuid.uuid4().hex[:10]}"
    assert await store.link_order(ja.id, order_id)
    assert not await store.link_order(jb.id, order_id)


async def test_chat_log_round_trip(pg):
    from domains.copilot.infrastructure.chat_log import PgChatLog

    _, _, pool = pg
    if await pool.fetchval("SELECT to_regclass('kraken_chat_turns')") is None:
        pytest.skip("chat table missing; run scripts/migrate.py")
    log, user = PgChatLog(pool), f"pg-test-{uuid.uuid4().hex[:8]}"
    await log.append(user, "first", {"reply": "one", "proposals": [], "llm_available": True})
    await log.append(user, "second", {"reply": "two", "proposals": ["p-1"], "llm_available": True})
    turns = await log.recent(user, 10)
    assert [t.message for t in turns] == ["first", "second"] and turns[1].reply["proposals"] == ["p-1"]
    assert [t.message for t in await log.recent(user, 1)] == ["second"]
    await log.clear(user)
    assert await log.recent(user, 10) == []


async def test_audit_is_append_only(pg):
    import asyncpg

    _, audit, pool = pg
    marker = uuid.uuid4().hex
    await audit.record("pg_test", user_id=marker, data={"x": 1})
    with pytest.raises(asyncpg.RaiseError):
        await pool.execute("UPDATE kraken_audit_log SET kind='tampered' WHERE user_id=$1", marker)
    with pytest.raises(asyncpg.RaiseError):
        await pool.execute("DELETE FROM kraken_audit_log WHERE user_id=$1", marker)
