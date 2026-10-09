from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.core.db import Database
from app.core.ui import safe_edit
from app.keyboards.common import admin_menu

router = Router(name="admin")


def _is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.super_admin_ids


@router.message(Command("admin"))
async def admin_command(message: Message, settings: Settings) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id, settings):
        return
    await message.answer("🛠 <b>لوحة الإدارة</b>\n\nالمرحلة الحالية: Core فقط.", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:home")
async def admin_home(callback: CallbackQuery, settings: Settings) -> None:
    if not _is_admin(callback.from_user.id, settings):
        return
    await safe_edit(callback, "🛠 <b>لوحة الإدارة</b>\n\nالمرحلة الحالية: Core فقط.", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:status")
async def admin_status(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _is_admin(callback.from_user.id, settings):
        return
    db_ok = await db.ping()
    await safe_edit(
        callback,
        "📊 <b>حالة النواة</b>\n\n"
        f"Telegram: ✅\nPostgreSQL: {'✅' if db_ok else '❌'}\n"
        "Financial modules: غير مفعلة بعد",
        reply_markup=admin_menu(),
    )
