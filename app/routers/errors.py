from __future__ import annotations

import logging

from aiogram.types import ErrorEvent, Message

logger = logging.getLogger(__name__)


async def global_error_handler(event: ErrorEvent) -> None:
    exc = event.exception
    logger.error(
        "Unhandled update error: %s",
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    update = event.update
    target: Message | None = None
    if update.message is not None:
        target = update.message
    elif update.callback_query is not None and isinstance(update.callback_query.message, Message):
        target = update.callback_query.message

    if target is not None:
        try:
            await target.answer("⚠️ حدث خطأ غير متوقع. لم يتم تنفيذ أي إجراء مالي.")
        except Exception:
            logger.debug("Could not send user-facing error message", exc_info=True)
