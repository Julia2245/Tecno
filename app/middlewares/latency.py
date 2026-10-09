from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

logger = logging.getLogger("performance")


class UpdateLatencyMiddleware(BaseMiddleware):
    def __init__(self, slow_warning_ms: float) -> None:
        self.slow_warning_ms = slow_warning_ms

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        started = perf_counter()
        data["update_received_perf"] = started
        try:
            return await handler(event, data)
        finally:
            elapsed_ms = (perf_counter() - started) * 1000
            update_id = event.update_id if isinstance(event, Update) else None
            log = logger.warning if elapsed_ms >= self.slow_warning_ms else logger.debug
            log("update_id=%s processing_ms=%.2f", update_id, elapsed_ms)
