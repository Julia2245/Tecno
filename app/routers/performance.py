from __future__ import annotations

from time import perf_counter

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import Settings
from app.core.ui import safe_edit
from app.keyboards.common import main_menu

router = Router(name="performance")


@router.callback_query(F.data == "core:latency")
async def latency_callback(
    callback: CallbackQuery,
    settings: Settings,
    update_received_perf: float,
    callback_ack_ms: float = 0.0,
) -> None:
    # The ACK happened before this handler. This measures server-side dispatch + ACK roundtrip.
    before_screen_ms = (perf_counter() - update_received_perf) * 1000
    await safe_edit(
        callback,
        "⚡ <b>اختبار الاستجابة</b>\n\n"
        f"تأكيد الزر: <code>{callback_ack_ms:.1f} ms</code>\n"
        f"الوصول لمنطق الشاشة: <code>{before_screen_ms:.1f} ms</code>\n\n"
        "هذه أرقام من جهة السيرفر؛ زمن جهاز المستخدم وشبكته قبل وصول التحديث لا يظهر هنا.",
        reply_markup=main_menu(is_admin=callback.from_user.id in settings.super_admin_ids),
    )
