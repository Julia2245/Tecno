from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import get_settings
from app.core.db import Database

PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def run() -> int:
    settings = get_settings()
    db = Database(
        settings.database_url,
        min_size=1,
        max_size=2,
        command_timeout=settings.pg_command_timeout,
    )
    await db.connect()
    try:
        await db.apply_migrations(PROJECT_ROOT / "migrations")
        pool = db.require_pool()
        async with pool.acquire() as conn:
            balance_mismatches = await conn.fetch(
                """
                SELECT
                    a.id, a.telegram_id, a.asset_code, a.bucket,
                    a.available, a.held, a.version,
                    COALESCE(SUM(l.available_delta), 0)::BIGINT AS ledger_available,
                    COALESCE(SUM(l.held_delta), 0)::BIGINT AS ledger_held,
                    COUNT(l.id)::BIGINT AS ledger_count,
                    COALESCE(MAX(l.version_after), 0)::BIGINT AS ledger_max_version
                FROM bot_core.wallet_accounts a
                LEFT JOIN bot_core.wallet_ledger l ON l.account_id = a.id
                GROUP BY a.id
                HAVING a.available <> COALESCE(SUM(l.available_delta), 0)::BIGINT
                    OR a.held <> COALESCE(SUM(l.held_delta), 0)::BIGINT
                    OR a.version <> COUNT(l.id)::BIGINT
                    OR a.version <> COALESCE(MAX(l.version_after), 0)::BIGINT
                ORDER BY a.id
                """
            )
            hold_mismatches = await conn.fetch(
                """
                SELECT
                    a.id, a.telegram_id, a.asset_code, a.bucket, a.held,
                    COALESCE(SUM(h.amount) FILTER (WHERE h.status = 'active'), 0)::BIGINT AS active_holds
                FROM bot_core.wallet_accounts a
                LEFT JOIN bot_core.wallet_holds h ON h.account_id = a.id
                GROUP BY a.id
                HAVING a.held <>
                    COALESCE(SUM(h.amount) FILTER (WHERE h.status = 'active'), 0)::BIGINT
                ORDER BY a.id
                """
            )
            broken_chain = await conn.fetch(
                """
                WITH ordered AS (
                    SELECT
                        l.*,
                        LAG(l.available_after) OVER (
                            PARTITION BY l.account_id ORDER BY l.version_after
                        ) AS prev_available,
                        LAG(l.held_after) OVER (
                            PARTITION BY l.account_id ORDER BY l.version_after
                        ) AS prev_held,
                        LAG(l.version_after) OVER (
                            PARTITION BY l.account_id ORDER BY l.version_after
                        ) AS prev_version
                    FROM bot_core.wallet_ledger l
                )
                SELECT id, account_id, version_before, version_after
                FROM ordered
                WHERE
                    (version_before = 0 AND (available_before <> 0 OR held_before <> 0))
                    OR
                    (version_before > 0 AND (
                        prev_version IS NULL
                        OR version_before <> prev_version
                        OR available_before <> prev_available
                        OR held_before <> prev_held
                    ))
                ORDER BY account_id, version_after
                """
            )
            operation_mismatches = await conn.fetch(
                """
                SELECT o.id, o.idempotency_key, o.operation_type, COUNT(l.id)::BIGINT AS ledger_count
                FROM bot_core.wallet_operations o
                LEFT JOIN bot_core.wallet_ledger l ON l.operation_id = o.id
                GROUP BY o.id
                HAVING COUNT(l.id) <> 1
                ORDER BY o.created_at
                """
            )
            hold_ledger_mismatches = await conn.fetch(
                """
                SELECT h.id, h.account_id, h.amount, h.status
                FROM bot_core.wallet_holds h
                LEFT JOIN bot_core.wallet_ledger c
                  ON c.operation_id = h.created_by_operation_id
                 AND c.account_id = h.account_id
                LEFT JOIN bot_core.wallet_ledger x
                  ON x.operation_id = h.closed_by_operation_id
                 AND x.account_id = h.account_id
                WHERE c.id IS NULL
                   OR c.entry_type <> 'hold'
                   OR c.available_delta <> -h.amount
                   OR c.held_delta <> h.amount
                   OR (
                        h.status = 'released'
                        AND (
                            x.id IS NULL OR x.entry_type <> 'release'
                            OR x.available_delta <> h.amount OR x.held_delta <> -h.amount
                        )
                   )
                   OR (
                        h.status = 'captured'
                        AND (
                            x.id IS NULL OR x.entry_type <> 'capture'
                            OR x.available_delta <> 0 OR x.held_delta <> -h.amount
                        )
                   )
                ORDER BY h.created_at
                """
            )

        failures = {
            "balance/version": balance_mismatches,
            "active holds": hold_mismatches,
            "ledger chain": broken_chain,
            "operation ledger": operation_mismatches,
            "hold ledger": hold_ledger_mismatches,
        }
        failed = False
        for label, rows in failures.items():
            for row in rows:
                failed = True
                print(f"{label} mismatch:", dict(row))

        if failed:
            print("WALLET AUDIT: FAILED")
            return 2

        print("WALLET AUDIT: OK")
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
