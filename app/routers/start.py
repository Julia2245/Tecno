from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.core.ui import safe_edit
from app.keyboards.common import main_menu
from app.services.users import UserService

router = Router(name="start")


def _home_text(display_name: str) -> str:
    name = display_name or "البوت"
    return (
        f"<b>{name}</b>\n\n"
        "✅ النواة الجديدة تعمل.\n"
        "⚡ الواجهة مبنية على معالجة Async سريعة."
    )


@router.message(CommandStart())
async def start_handler(message: Message, settings: Settings, user_service: UserService) -> None:
    if message.from_user is None:
        return
    await user_service.sync_profile(message.from_user)
    await message.answer(
        _home_text(settings.bot_display_name),
        reply_markup=main_menu(is_admin=message.from_user.id in settings.super_admin_ids),
    )


@router.message(Command("menu"))
async def menu_handler(message: Message, settings: Settings) -> None:
    if message.from_user is None:
        return
    await message.answer(
        _home_text(settings.bot_display_name),
        reply_markup=main_menu(is_admin=message.from_user.id in settings.super_admin_ids),
    )


@router.callback_query(F.data == "core:home")
async def home_callback(callback: CallbackQuery, settings: Settings) -> None:
    user_id = callback.from_user.id
    await safe_edit(
        callback,
        _home_text(settings.bot_display_name),
        reply_markup=main_menu(is_admin=user_id in settings.super_admin_ids),
    )
