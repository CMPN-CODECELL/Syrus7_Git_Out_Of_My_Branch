"""
File Overview: Idempotent database schema migration runner.
Tracks applied SQL migration scripts in 'schema_migrations' table.
"""
import os
import sys
import glob
import hashlib
import logging
import asyncio
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.settings import get_settings
import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("migration_runner")

CREATE_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    checksum VARCHAR(64) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _compute_checksum(filepath: str) -> str:
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


async def run_migrations() -> None:
    settings = get_settings()
    scripts_dir = Path(__file__).resolve().parent

    logger.info("Connecting to PostgreSQL at %s", settings.DatabaseUrl.split("@")[-1])
    conn = await asyncpg.connect(settings.DatabaseUrl)
    try:
        # 1. Ensure migrations table exists
        await conn.execute(CREATE_MIGRATION_TABLE_SQL)

        # 2. Get list of already applied migrations
        rows = await conn.fetch("SELECT version, checksum FROM schema_migrations;")
        applied = {r["version"]: r["checksum"] for r in rows}

        # 3. Discover SQL migration scripts in deterministic order
        # Ensure init_schema.sql runs first if not applied
        sql_files = sorted(glob.glob(str(scripts_dir / "*.sql")))

        # Prioritize init_schema.sql first
        init_file = str(scripts_dir / "init_schema.sql")
        if init_file in sql_files:
            sql_files.remove(init_file)
            sql_files.insert(0, init_file)

        for sql_file in sql_files:
            name = os.path.basename(sql_file)
            checksum = _compute_checksum(sql_file)

            if name in applied:
                logger.info("Migration [%s] already applied (checksum: %s). Skipping.", name, checksum[:8])
                continue

            logger.info("Applying migration [%s]...", name)
            with open(sql_file, "r", encoding="utf-8") as f:
                content = f.read()

            async with conn.transaction():
                await conn.execute(content)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2);",
                    name, checksum
                )
            logger.info("Migration [%s] applied successfully.", name)

        logger.info("All schema migrations are up to date.")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(run_migrations())
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        sys.exit(1)
