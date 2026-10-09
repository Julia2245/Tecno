from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID, uuid4

import asyncpg

from app.core.db import Database
from app.core.wallet import (
    HoldNotActive,
    HoldNotFound,
    IdempotencyConflict,
    InsufficientFunds,
    WalletBalance,
    WalletHold,
    WalletInvariantError,
    WalletMutation,
)


MAX_SAFE_BALANCE = 9_000_000_000_000_000_000


class WalletRepository:
    """Atomic wallet persistence.

    Every successful mutation writes exactly one immutable operation and one
    immutable ledger row in the same PostgreSQL transaction. Account rows are
    locked with FOR UPDATE before any balance decision is made.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_balance(
        self,
        telegram_id: int,
        *,
        asset_code: str,
        bucket: str,
    ) -> WalletBalance | None:
        pool = self.db.require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, telegram_id, asset_code, bucket, available, held, version
                FROM bot_core.wallet_accounts
                WHERE telegram_id = $1 AND asset_code = $2 AND bucket = $3
                """,
                telegram_id,
                asset_code,
                bucket,
            )
        return self._balance_from_row(row) if row else None

    async def credit(
        self,
        *,
        telegram_id: int,
        amount: int,
        asset_code: str,
        bucket: str,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        actor_telegram_id: int | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WalletMutation:
        return await self._simple_mutation(
            telegram_id=telegram_id,
            amount=amount,
            asset_code=asset_code,
            bucket=bucket,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=reason,
            actor_telegram_id=actor_telegram_id,
            metadata=metadata,
            entry_type="credit",
            available_delta=amount,
            held_delta=0,
        )

    async def debit(
        self,
        *,
        telegram_id: int,
        amount: int,
        asset_code: str,
        bucket: str,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        actor_telegram_id: int | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WalletMutation:
        return await self._simple_mutation(
            telegram_id=telegram_id,
            amount=amount,
            asset_code=asset_code,
            bucket=bucket,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=reason,
            actor_telegram_id=actor_telegram_id,
            metadata=metadata,
            entry_type="debit",
            available_delta=-amount,
            held_delta=0,
        )

    async def create_hold(
        self,
        *,
        telegram_id: int,
        amount: int,
        asset_code: str,
        bucket: str,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        actor_telegram_id: int | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[WalletMutation, WalletHold]:
        pool = self.db.require_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                operation_id, duplicate = await self._claim_operation(
                    conn,
                    idempotency_key=idempotency_key,
                    operation_type="hold_create",
                    request_hash=request_hash,
                    actor_telegram_id=actor_telegram_id,
                )
                if duplicate:
                    mutation = await self._mutation_from_existing(conn, operation_id, idempotency_key)
                    hold = await self._hold_by_created_operation(conn, operation_id)
                    return mutation, hold

                account = await self._lock_account(
                    conn,
                    telegram_id=telegram_id,
                    asset_code=asset_code,
                    bucket=bucket,
                )
                if account.available < amount:
                    raise InsufficientFunds(
                        f"available={account.available}, required={amount}, held={account.held}"
                    )

                updated = await self._apply_account_delta(
                    conn,
                    account,
                    available_delta=-amount,
                    held_delta=amount,
                )
                await self._insert_ledger(
                    conn,
                    operation_id=operation_id,
                    before=account,
                    after=updated,
                    entry_type="hold",
                    available_delta=-amount,
                    held_delta=amount,
                    reason=reason,
                    metadata=metadata,
                )

                hold_id = uuid4()
                hold_row = await conn.fetchrow(
                    """
                    INSERT INTO bot_core.wallet_holds (
                        id, account_id, amount, status, created_by_operation_id
                    )
                    VALUES ($1, $2, $3, 'active', $4)
                    RETURNING id, account_id, amount, status, created_by_operation_id,
                              closed_by_operation_id, created_at, closed_at
                    """,
                    hold_id,
                    account.account_id,
                    amount,
                    operation_id,
                )

                return (
                    WalletMutation(
                        operation_id=operation_id,
                        idempotency_key=idempotency_key,
                        duplicate=False,
                        entry_type="hold",
                        balance_after=updated,
                    ),
                    self._hold_from_row(hold_row),
                )

    async def release_hold(
        self,
        *,
        hold_id: UUID,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        actor_telegram_id: int | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[WalletMutation, WalletHold]:
        return await self._close_hold(
            hold_id=hold_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=reason,
            actor_telegram_id=actor_telegram_id,
            metadata=metadata,
            closing_status="released",
            entry_type="release",
            return_to_available=True,
        )

    async def capture_hold(
        self,
        *,
        hold_id: UUID,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        actor_telegram_id: int | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[WalletMutation, WalletHold]:
        return await self._close_hold(
            hold_id=hold_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=reason,
            actor_telegram_id=actor_telegram_id,
            metadata=metadata,
            closing_status="captured",
            entry_type="capture",
            return_to_available=False,
        )

    async def _simple_mutation(
        self,
        *,
        telegram_id: int,
        amount: int,
        asset_code: str,
        bucket: str,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        actor_telegram_id: int | None,
        metadata: Mapping[str, Any] | None,
        entry_type: str,
        available_delta: int,
        held_delta: int,
    ) -> WalletMutation:
        pool = self.db.require_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                operation_id, duplicate = await self._claim_operation(
                    conn,
                    idempotency_key=idempotency_key,
                    operation_type=entry_type,
                    request_hash=request_hash,
                    actor_telegram_id=actor_telegram_id,
                )
                if duplicate:
                    return await self._mutation_from_existing(conn, operation_id, idempotency_key)

                account = await self._lock_account(
                    conn,
                    telegram_id=telegram_id,
                    asset_code=asset_code,
                    bucket=bucket,
                )
                if account.available + available_delta < 0:
                    raise InsufficientFunds(
                        f"available={account.available}, required={amount}, held={account.held}"
                    )

                updated = await self._apply_account_delta(
                    conn,
                    account,
                    available_delta=available_delta,
                    held_delta=held_delta,
                )
                await self._insert_ledger(
                    conn,
                    operation_id=operation_id,
                    before=account,
                    after=updated,
                    entry_type=entry_type,
                    available_delta=available_delta,
                    held_delta=held_delta,
                    reason=reason,
                    metadata=metadata,
                )
                return WalletMutation(
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                    duplicate=False,
                    entry_type=entry_type,
                    balance_after=updated,
                )

    async def _close_hold(
        self,
        *,
        hold_id: UUID,
        idempotency_key: str,
        request_hash: str,
        reason: str,
        actor_telegram_id: int | None,
        metadata: Mapping[str, Any] | None,
        closing_status: str,
        entry_type: str,
        return_to_available: bool,
    ) -> tuple[WalletMutation, WalletHold]:
        pool = self.db.require_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                operation_id, duplicate = await self._claim_operation(
                    conn,
                    idempotency_key=idempotency_key,
                    operation_type=f"hold_{entry_type}",
                    request_hash=request_hash,
                    actor_telegram_id=actor_telegram_id,
                )
                if duplicate:
                    mutation = await self._mutation_from_existing(conn, operation_id, idempotency_key)
                    hold = await self._hold_by_id(conn, hold_id)
                    return mutation, hold

                hold_row = await conn.fetchrow(
                    """
                    SELECT id, account_id, amount, status, created_by_operation_id,
                           closed_by_operation_id, created_at, closed_at
                    FROM bot_core.wallet_holds
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    hold_id,
                )
                if hold_row is None:
                    raise HoldNotFound(str(hold_id))
                hold = self._hold_from_row(hold_row)
                if hold.status != "active":
                    raise HoldNotActive(f"hold={hold.id} status={hold.status}")

                account_row = await conn.fetchrow(
                    """
                    SELECT id, telegram_id, asset_code, bucket, available, held, version
                    FROM bot_core.wallet_accounts
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    hold.account_id,
                )
                if account_row is None:
                    raise WalletInvariantError(f"account missing for hold {hold.id}")
                account = self._balance_from_row(account_row)
                if account.held < hold.amount:
                    raise WalletInvariantError(
                        f"held balance invariant broken for account={account.account_id}"
                    )

                available_delta = hold.amount if return_to_available else 0
                held_delta = -hold.amount
                updated = await self._apply_account_delta(
                    conn,
                    account,
                    available_delta=available_delta,
                    held_delta=held_delta,
                )
                await self._insert_ledger(
                    conn,
                    operation_id=operation_id,
                    before=account,
                    after=updated,
                    entry_type=entry_type,
                    available_delta=available_delta,
                    held_delta=held_delta,
                    reason=reason,
                    metadata=metadata,
                )

                closed_row = await conn.fetchrow(
                    """
                    UPDATE bot_core.wallet_holds
                    SET status = $2,
                        closed_by_operation_id = $3,
                        closed_at = NOW()
                    WHERE id = $1
                    RETURNING id, account_id, amount, status, created_by_operation_id,
                              closed_by_operation_id, created_at, closed_at
                    """,
                    hold.id,
                    closing_status,
                    operation_id,
                )

                return (
                    WalletMutation(
                        operation_id=operation_id,
                        idempotency_key=idempotency_key,
                        duplicate=False,
                        entry_type=entry_type,
                        balance_after=updated,
                    ),
                    self._hold_from_row(closed_row),
                )

    async def _claim_operation(
        self,
        conn: asyncpg.Connection,
        *,
        idempotency_key: str,
        operation_type: str,
        request_hash: str,
        actor_telegram_id: int | None,
    ) -> tuple[UUID, bool]:
        operation_id = uuid4()
        row = await conn.fetchrow(
            """
            INSERT INTO bot_core.wallet_operations (
                id, idempotency_key, operation_type, request_hash, actor_telegram_id
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            operation_id,
            idempotency_key,
            operation_type,
            request_hash,
            actor_telegram_id,
        )
        if row is not None:
            return row["id"], False

        existing = await conn.fetchrow(
            """
            SELECT id, operation_type, request_hash
            FROM bot_core.wallet_operations
            WHERE idempotency_key = $1
            """,
            idempotency_key,
        )
        if existing is None:
            raise WalletInvariantError("idempotency operation disappeared unexpectedly")
        if existing["operation_type"] != operation_type or existing["request_hash"] != request_hash:
            raise IdempotencyConflict(idempotency_key)
        return existing["id"], True

    async def _lock_account(
        self,
        conn: asyncpg.Connection,
        *,
        telegram_id: int,
        asset_code: str,
        bucket: str,
    ) -> WalletBalance:
        await conn.execute(
            """
            INSERT INTO bot_core.wallet_accounts (telegram_id, asset_code, bucket)
            VALUES ($1, $2, $3)
            ON CONFLICT (telegram_id, asset_code, bucket) DO NOTHING
            """,
            telegram_id,
            asset_code,
            bucket,
        )
        row = await conn.fetchrow(
            """
            SELECT id, telegram_id, asset_code, bucket, available, held, version
            FROM bot_core.wallet_accounts
            WHERE telegram_id = $1 AND asset_code = $2 AND bucket = $3
            FOR UPDATE
            """,
            telegram_id,
            asset_code,
            bucket,
        )
        if row is None:
            raise WalletInvariantError("wallet account could not be created or locked")
        return self._balance_from_row(row)

    async def _apply_account_delta(
        self,
        conn: asyncpg.Connection,
        before: WalletBalance,
        *,
        available_delta: int,
        held_delta: int,
    ) -> WalletBalance:
        next_available = before.available + available_delta
        next_held = before.held + held_delta
        if next_available < 0 or next_held < 0:
            raise InsufficientFunds(
                f"account={before.account_id}, available={before.available}, held={before.held}"
            )
        if next_available > MAX_SAFE_BALANCE or next_held > MAX_SAFE_BALANCE:
            raise WalletInvariantError(f"wallet balance overflow for account={before.account_id}")

        row = await conn.fetchrow(
            """
            UPDATE bot_core.wallet_accounts
            SET available = available + $2,
                held = held + $3,
                version = version + 1,
                updated_at = NOW()
            WHERE id = $1
              AND available + $2 >= 0
              AND held + $3 >= 0
            RETURNING id, telegram_id, asset_code, bucket, available, held, version
            """,
            before.account_id,
            available_delta,
            held_delta,
        )
        if row is None:
            raise InsufficientFunds(
                f"account={before.account_id}, available={before.available}, held={before.held}"
            )
        return self._balance_from_row(row)

    async def _insert_ledger(
        self,
        conn: asyncpg.Connection,
        *,
        operation_id: UUID,
        before: WalletBalance,
        after: WalletBalance,
        entry_type: str,
        available_delta: int,
        held_delta: int,
        reason: str,
        metadata: Mapping[str, Any] | None,
    ) -> None:
        metadata_json = json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True)
        await conn.execute(
            """
            INSERT INTO bot_core.wallet_ledger (
                operation_id, account_id, entry_type,
                available_before, available_delta, available_after,
                held_before, held_delta, held_after,
                version_before, version_after,
                reason, metadata
            )
            VALUES (
                $1, $2, $3,
                $4, $5, $6,
                $7, $8, $9,
                $10, $11,
                $12, $13::jsonb
            )
            """,
            operation_id,
            before.account_id,
            entry_type,
            before.available,
            available_delta,
            after.available,
            before.held,
            held_delta,
            after.held,
            before.version,
            after.version,
            reason,
            metadata_json,
        )

    async def _mutation_from_existing(
        self,
        conn: asyncpg.Connection,
        operation_id: UUID,
        idempotency_key: str,
    ) -> WalletMutation:
        row = await conn.fetchrow(
            """
            SELECT
                l.entry_type,
                a.id AS account_id,
                a.telegram_id,
                a.asset_code,
                a.bucket,
                l.available_after AS available,
                l.held_after AS held,
                l.version_after AS version
            FROM bot_core.wallet_ledger l
            JOIN bot_core.wallet_accounts a ON a.id = l.account_id
            WHERE l.operation_id = $1
            ORDER BY l.id
            LIMIT 1
            """,
            operation_id,
        )
        if row is None:
            raise WalletInvariantError(f"ledger missing for operation {operation_id}")
        balance = WalletBalance(
            account_id=row["account_id"],
            telegram_id=row["telegram_id"],
            asset_code=row["asset_code"],
            bucket=row["bucket"],
            available=row["available"],
            held=row["held"],
            version=row["version"],
        )
        return WalletMutation(
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            duplicate=True,
            entry_type=row["entry_type"],
            balance_after=balance,
        )

    async def _hold_by_created_operation(
        self,
        conn: asyncpg.Connection,
        operation_id: UUID,
    ) -> WalletHold:
        row = await conn.fetchrow(
            """
            SELECT id, account_id, amount, status, created_by_operation_id,
                   closed_by_operation_id, created_at, closed_at
            FROM bot_core.wallet_holds
            WHERE created_by_operation_id = $1
            """,
            operation_id,
        )
        if row is None:
            raise WalletInvariantError(f"hold missing for operation {operation_id}")
        return self._hold_from_row(row)

    async def _hold_by_id(self, conn: asyncpg.Connection, hold_id: UUID) -> WalletHold:
        row = await conn.fetchrow(
            """
            SELECT id, account_id, amount, status, created_by_operation_id,
                   closed_by_operation_id, created_at, closed_at
            FROM bot_core.wallet_holds
            WHERE id = $1
            """,
            hold_id,
        )
        if row is None:
            raise HoldNotFound(str(hold_id))
        return self._hold_from_row(row)

    @staticmethod
    def _balance_from_row(row: asyncpg.Record) -> WalletBalance:
        return WalletBalance(
            account_id=row["id"],
            telegram_id=row["telegram_id"],
            asset_code=row["asset_code"],
            bucket=row["bucket"],
            available=row["available"],
            held=row["held"],
            version=row["version"],
        )

    @staticmethod
    def _hold_from_row(row: asyncpg.Record) -> WalletHold:
        return WalletHold(
            id=row["id"],
            account_id=row["account_id"],
            amount=row["amount"],
            status=row["status"],
            created_by_operation_id=row["created_by_operation_id"],
            closed_by_operation_id=row["closed_by_operation_id"],
            created_at=row["created_at"],
            closed_at=row["closed_at"],
        )
