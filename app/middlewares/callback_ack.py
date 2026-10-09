from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)


class FastCallbackAckMiddleware(BaseMiddleware):
    """Remove Telegram's callback spinner before doing handler work.

    This is UX only. It is never a financial lock and never substitutes for
    PostgreSQL idempotency/transactions in future financial modules.

    A handler that genuinely needs to answer the callback itself can set the
    flag ``manual_callback_ack=True``.
    """

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        handler_object = data.get("handler")
        flags = getattr(handler_object, "flags", {}) or {}
        manual_ack = bool(flags.get("manual_callback_ack", False))

        if not manual_ack:
            ack_started = perf_counter()
            try:
                await event.answer(cache_time=0)
                data["callback_acknowledged"] = True
            except (TelegramBadRequest, TelegramNetworkError):
                # Never block the actual handler because Telegram could not clear a spinner.
                logger.debug("Callback ACK failed", exc_info=True)
                data["callback_acknowledged"] = False
            finally:
                data["callback_ack_ms"] = (perf_counter() - ack_started) * 1000

        return await handler(event, data)
