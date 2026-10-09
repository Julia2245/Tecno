from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from app.config import get_settings
from app.core.db import Database
from app.core.logging import configure_logging
from app.middlewares.callback_ack import FastCallbackAckMiddleware
from app.middlewares.latency import UpdateLatencyMiddleware
from app.repositories.users import UserRepository
from app.repositories.wallet import WalletRepository
from app.routers import build_root_router
from app.services.users import UserService
from app.services.wallet import WalletService

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    db = Database(
        settings.database_url,
        min_size=settings.pg_pool_min,
        max_size=settings.pg_pool_max,
        command_timeout=settings.pg_command_timeout,
    )
    await db.connect()
    await db.apply_migrations(PROJECT_ROOT / "migrations")

    session = AiohttpSession(limit=settings.telegram_connection_limit)
    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )
    dp = Dispatcher()

    # Fast callback ACK is deliberately isolated from business logic.
    dp.callback_query.middleware(FastCallbackAckMiddleware())
    dp.update.outer_middleware(UpdateLatencyMiddleware(settings.slow_update_warning_ms))
    dp.include_router(build_root_router())

    user_repository = UserRepository(db)
    user_service = UserService(user_repository)
    wallet_repository = WalletRepository(db)
    wallet_service = WalletService(wallet_repository)

    try:
        me = await bot.get_me()
        if not settings.bot_display_name:
            # Mutable runtime display label only; no project branding is hardcoded.
            settings.bot_display_name = me.first_name or "البوت"
        logger.info("Starting @%s (%s)", me.username or "", me.id)

        # False by default so a restart never silently discards legitimate updates.
        await bot.delete_webhook(drop_pending_updates=settings.drop_pending_updates)
        await dp.start_polling(
            bot,
            settings=settings,
            db=db,
            user_service=user_service,
            wallet_service=wallet_service,
            allowed_updates=dp.resolve_used_update_types(),
            tasks_concurrency_limit=settings.max_concurrent_updates,
            close_bot_session=False,
        )
    finally:
        await db.close()
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
