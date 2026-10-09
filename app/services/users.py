from __future__ import annotations

from aiogram.types import User as TelegramUser

from app.repositories.users import UserRecord, UserRepository


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository

    async def sync_profile(self, telegram_user: TelegramUser) -> UserRecord:
        return await self.repository.upsert_from_telegram(telegram_user)
