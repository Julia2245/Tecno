from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def safe_edit(
    callback: CallbackQuery,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
