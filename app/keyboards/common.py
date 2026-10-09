from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="⚡ اختبار سرعة الأزرار", callback_data="core:latency")],
        [InlineKeyboardButton(text="🔄 تحديث القائمة", callback_data="core:home")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 لوحة الإدارة", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 حالة النواة", callback_data="admin:status")],
            [InlineKeyboardButton(text="⬅️ الرئيسية", callback_data="core:home")],
        ]
    )
