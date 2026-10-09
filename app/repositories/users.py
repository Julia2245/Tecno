from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aiogram.types import User as TelegramUser

from app.core.db import Database


@dataclass(slots=True, frozen=True)
class UserRecord:
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str | None
    language_code: str | None
    is_blocked: bool
    created_at: datetime
    updated_at: datetime


class UserRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def upsert_from_telegram(self, user: TelegramUser) -> UserRecord:
        pool = self.db.require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO bot_core.users (
                    telegram_id, username, first_name, last_name, language_code, is_bot
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    language_code = EXCLUDED.language_code,
                    is_bot = EXCLUDED.is_bot,
                    updated_at = NOW()
                RETURNING
                    telegram_id, username, first_name, last_name, language_code,
                    is_blocked, created_at, updated_at
                """,
                user.id,
                user.username,
                user.first_name or "",
                user.last_name,
                user.language_code,
                user.is_bot,
            )
        return UserRecord(**dict(row))

    async def get(self, telegram_id: int) -> UserRecord | None:
        pool = self.db.require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT telegram_id, username, first_name, last_name, language_code,
                       is_blocked, created_at, updated_at
                FROM bot_core.users
                WHERE telegram_id = $1
                """,
                telegram_id,
            )
        return UserRecord(**dict(row)) if row else None
