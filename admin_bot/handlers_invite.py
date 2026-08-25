"""Admin bot — taklifnoma havolasi orqali YANGI (hali admin bo'lmagan)
foydalanuvchini qabul qilish.

MUHIM: bu router `admin_root`dagi (IsAdminBot) filtrdan TASHQARIDA — chunki
IsAdminBot() ishlashi uchun foydalanuvchi ALLAQACHON admin bo'lishi kerak
(tuxum-tovuq muammosi). Shu sabab bu yerda faqat `bot_role == "admin"`
tekshiriladi, `is_admin` EMAS. Agar xabar taklifnoma havolasi bo'lmasa,
`SkipHandler` orqali admin_root'dagi oddiy /start'ga uzatiladi.
"""
import logging

from aiogram import Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

from services import database

logger = logging.getLogger("janob_hr_bot")

router = Router(name="admin_invite")


@router.message(CommandStart())
async def handle_admin_invite(
    message: Message, command: CommandObject, tenant_id: int, bot_role: str = "candidate",
):
    if bot_role != "admin" or not command.args or not command.args.startswith("admin_"):
        raise SkipHandler  # oddiy /start yoki nomzod-bot — admin_root/candidate_root o'zi ishlaydi

    token = command.args[len("admin_"):]
    invite_tenant_id = await database.consume_admin_invite(token, message.from_user.id)

    if invite_tenant_id != tenant_id:
        await message.answer("⚠️ Bu taklifnoma yaroqsiz yoki allaqachon ishlatilgan.")
        return

    await database.add_admin_user(tenant_id, message.from_user.id)
    await message.answer(
        "✅ Siz shu kompaniyaning admin panelida ishlash huquqini oldingiz!\n\n"
        "Davom etish uchun /start yozing."
    )
