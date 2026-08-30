"""
Janob HR — "Bosh boshqaruv" boti. FAQAT `FOUNDER_USER_IDS`dagi shaxslar
ishlata oladi. Vazifasi: yangi (pending) mijozlarni ko'rib chiqish va
to'lov tasdiqlangach, bir tugma bilan faollashtirish — bu paytda ikkala
bot (nomzod + admin) uchun webhook avtomatik o'rnatiladi.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS, WEBHOOK_BASE_URL
from services import database

logger = logging.getLogger("janob_hr_founder")

router = Router(name="founder_panel")


def _tenant_summary(t: dict) -> str:
    return (
        f"<b>№{t['id']} — {t['company_name']}</b>\n"
        f"Holat: {t['status']}\n"
        f"Nomzod-bot: {t.get('bot_username') or t['bot_token'][:12] + '...'}\n"
        f"Admin-bot: {t.get('admin_bot_username') or (t.get('admin_bot_token') or '—')[:12] + '...'}\n"
        f"Admin ID(lar): {', '.join(str(a) for a in t['admin_user_ids'])}\n"
        f"Ro'yxatdan o'tgan: {t['created_at'][:16].replace('T', ' ')}"
    )


@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.from_user.id not in FOUNDER_USER_IDS:
        return
    await show_main_menu(message)


async def show_main_menu(message: Message):
    pending = await database.list_tenants(status="pending")
    active = await database.list_tenants(status="active")

    builder = InlineKeyboardBuilder()
    builder.button(text=f"⏳ Kutilmoqda ({len(pending)})", callback_data="fp:pending")
    builder.button(text=f"✅ Faol mijozlar ({len(active)})", callback_data="fp:active")
    builder.adjust(1)

    await message.answer(
        "👑 <b>Janob HR — Bosh boshqaruv</b>\n\nQuyidagilardan birini tanlang:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "fp:main")
async def back_to_main(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    await callback.message.delete()
    await show_main_menu(callback.message)
    await callback.answer()


@router.callback_query(F.data == "fp:pending")
async def list_pending(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenants = await database.list_tenants(status="pending")
    builder = InlineKeyboardBuilder()
    if not tenants:
        text = "⏳ Hozircha kutilayotgan mijoz yo'q."
    else:
        text = "⏳ <b>Faollashtirishni kutayotgan mijozlar:</b>"
        for t in tenants:
            builder.button(
                text=f"№{t['id']} — {t['company_name']}",
                callback_data=f"fp:view:{t['id']}",
            )
    builder.button(text="⬅️ Orqaga", callback_data="fp:main")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "fp:active")
async def list_active(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenants = await database.list_tenants(status="active")
    builder = InlineKeyboardBuilder()
    if not tenants:
        text = "✅ Hozircha faol mijoz yo'q."
    else:
        text = "✅ <b>Faol mijozlar:</b>"
        for t in tenants:
            builder.button(
                text=f"№{t['id']} — {t['company_name']}",
                callback_data=f"fp:view:{t['id']}",
            )
    builder.button(text="⬅️ Orqaga", callback_data="fp:main")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("fp:view:"))
async def view_tenant(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenant_id = int(callback.data.split(":")[2])
    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        await callback.answer("Bu mijoz topilmadi.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    if tenant["status"] == "pending":
        builder.button(
            text="✅ Faollashtirish", callback_data=f"fp:activate:{tenant_id}"
        )
    elif tenant["status"] == "active":
        builder.button(text="🔴 To'xtatish", callback_data=f"fp:deactivate:{tenant_id}")
    builder.button(text="⬅️ Orqaga", callback_data="fp:main")
    builder.adjust(1)

    await callback.message.edit_text(
        _tenant_summary(tenant), reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fp:activate:"))
async def activate_tenant(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenant_id = int(callback.data.split(":")[2])
    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        await callback.answer("Bu mijoz topilmadi.", show_alert=True)
        return

    from services.tenant_activation import activate_tenant as do_activate

    await callback.answer("Faollashtirilmoqda...")
    result = await do_activate(tenant_id)

    if not result["ok"]:
        await callback.message.answer(f"⚠️ {result['error']}")
        return

    await callback.message.edit_text(
        f"✅ <b>№{tenant_id} — {tenant['company_name']}</b> faollashtirildi!\n\n"
        f"Nomzod-bot: @{result['candidate_username']}\nAdmin-bot: @{result['admin_username']}\n\n"
        "Ikkala bot ham endi jonli ishlamoqda."
    )


@router.callback_query(F.data.startswith("fp:deactivate:"))
async def deactivate_tenant(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenant_id = int(callback.data.split(":")[2])
    await database.update_tenant_status(tenant_id, "inactive")
    await callback.answer("Mijoz to'xtatildi.", show_alert=True)
    await list_active(callback)


async def main():
    if not FOUNDER_BOT_TOKEN:
        raise RuntimeError("FOUNDER_BOT_TOKEN topilmadi.")
    if WEBHOOK_BASE_URL:
        raise RuntimeError(
            "Founder Bot webhook_app.py ichida ishlaydi. WEBHOOK_BASE_URL sozlangan "
            "muhitda founder_panel.py ni alohida ishga tushirmang."
        )

    await database.init_db()
    bot = Bot(
        token=FOUNDER_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Janob HR Bosh boshqaruv boti ishga tushdi ✅")
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
