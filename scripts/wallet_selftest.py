from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

from app.config import get_settings
from app.core.db import Database
from app.core.wallet import InsufficientFunds
from app.repositories.wallet import WalletRepository
from app.services.wallet import WalletService

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_AMOUNT = 10_000
HOLD_AMOUNT = 6_000
TEST_BUCKET = "selftest"


async def run(telegram_id: int) -> int:
    settings = get_settings()
    db = Database(
        settings.database_url,
        min_size=2,
        max_size=4,
        command_timeout=settings.pg_command_timeout,
    )
    await db.connect()
    try:
        await db.apply_migrations(PROJECT_ROOT / "migrations")
        pool = db.require_pool()
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM bot_core.users WHERE telegram_id = $1)",
                telegram_id,
            )
        if not exists:
            print("SELFTEST FAILED: Telegram user is not registered. Send /start to the bot first.")
            return 2

        wallet = WalletService(WalletRepository(db))
        initial = await wallet.get_balance(telegram_id, bucket=TEST_BUCKET)
        initial_available = initial.available if initial else 0
        initial_held = initial.held if initial else 0
        if initial_available != 0 or initial_held != 0:
            print(
                "SELFTEST REFUSED: dedicated selftest bucket is not zero "
                f"(available={initial_available}, held={initial_held})."
            )
            return 3

        run_id = uuid4().hex
        prefix = f"selftest:{run_id}"

        first_credit = await wallet.credit(
            telegram_id,
            TEST_AMOUNT,
            idempotency_key=f"{prefix}:credit1",
            reason="wallet core selftest concurrency seed",
            bucket=TEST_BUCKET,
            actor_telegram_id=telegram_id,
        )
        duplicate_credit = await wallet.credit(
            telegram_id,
            TEST_AMOUNT,
            idempotency_key=f"{prefix}:credit1",
            reason="wallet core selftest concurrency seed",
            bucket=TEST_BUCKET,
            actor_telegram_id=telegram_id,
        )
        if duplicate_credit.operation_id != first_credit.operation_id or not duplicate_credit.duplicate:
            raise RuntimeError("idempotency duplicate credit check failed")

        async def competing_debit(suffix: str):
            return await wallet.debit(
                telegram_id,
                TEST_AMOUNT,
                idempotency_key=f"{prefix}:race:{suffix}",
                reason="wallet core selftest competing debit",
                bucket=TEST_BUCKET,
                actor_telegram_id=telegram_id,
            )

        race = await asyncio.gather(
            competing_debit("a"),
            competing_debit("b"),
            return_exceptions=True,
        )
        successes = [item for item in race if not isinstance(item, Exception)]
        insufficient = [item for item in race if isinstance(item, InsufficientFunds)]
        if len(successes) != 1 or len(insufficient) != 1:
            raise RuntimeError(f"concurrency guard failed: {race!r}")

        zero_after_race = await wallet.get_balance(telegram_id, bucket=TEST_BUCKET)
        if zero_after_race is None or zero_after_race.available != 0 or zero_after_race.held != 0:
            raise RuntimeError(f"unexpected balance after race: {zero_after_race!r}")

        await wallet.credit(
            telegram_id,
            TEST_AMOUNT,
            idempotency_key=f"{prefix}:credit2",
            reason="wallet core selftest hold seed",
            bucket=TEST_BUCKET,
            actor_telegram_id=telegram_id,
        )
        hold_mutation, hold = await wallet.create_hold(
            telegram_id,
            HOLD_AMOUNT,
            idempotency_key=f"{prefix}:hold",
            reason="wallet core selftest hold",
            bucket=TEST_BUCKET,
            actor_telegram_id=telegram_id,
        )
        duplicate_hold_mutation, duplicate_hold = await wallet.create_hold(
            telegram_id,
            HOLD_AMOUNT,
            idempotency_key=f"{prefix}:hold",
            reason="wallet core selftest hold",
            bucket=TEST_BUCKET,
            actor_telegram_id=telegram_id,
        )
        if (
            duplicate_hold.id != hold.id
            or duplicate_hold_mutation.operation_id != hold_mutation.operation_id
            or not duplicate_hold_mutation.duplicate
        ):
            raise RuntimeError("idempotency duplicate hold check failed")

        held_balance = await wallet.get_balance(telegram_id, bucket=TEST_BUCKET)
        if held_balance is None or held_balance.available != 4_000 or held_balance.held != 6_000:
            raise RuntimeError(f"hold accounting failed: {held_balance!r}")

        await wallet.release_hold(
            hold.id,
            idempotency_key=f"{prefix}:release",
            reason="wallet core selftest release",
            actor_telegram_id=telegram_id,
        )
        await wallet.debit(
            telegram_id,
            TEST_AMOUNT,
            idempotency_key=f"{prefix}:cleanup",
            reason="wallet core selftest cleanup",
            bucket=TEST_BUCKET,
            actor_telegram_id=telegram_id,
        )

        final = await wallet.get_balance(telegram_id, bucket=TEST_BUCKET)
        if final is None or final.available != 0 or final.held != 0:
            raise RuntimeError(f"selftest did not return to zero: {final!r}")

        print("WALLET SELFTEST: PASS")
        print("- duplicate idempotency: PASS")
        print("- concurrent double-debit protection: PASS")
        print("- hold accounting: PASS")
        print("- release accounting: PASS")
        print("- final selftest balance: 0")
        return 0
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram-id", type=int, required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.telegram_id)))


if __name__ == "__main__":
    main()
