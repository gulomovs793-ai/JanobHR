"""
Ko'p mijozli (multi-tenant) rejim uchun asosiy mexanizm.

Har bir mijozning IKKITA ALOHIDA BOTI bor:
- Nomzod-bot (`bot_token`) — ariza qabul qiladi.
- Admin panel-bot (`admin_bot_token`) — faqat shu mijozning administratorlari
  ishlatadi (vakansiya boshqaruvi, qarorlar, statistika).

Kelayotgan har bir yangilanish qaysi TOKEN orqali kelgani asosida, qaysi
mijozga (`tenant_id`) VA qaysi BOTGA (`bot_role`: "candidate" yoki "admin")
tegishli ekani aniqlanadi.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS
from services import database

logger = logging.getLogger("janob_hr_bot")


class TenantMiddleware(BaseMiddleware):
    """Har bir yangilanish uchun `bot.token` orqali tegishli mijoz va bot
    rolini bazadan topadi. Notanish/nofaol token — so'rov butunlay
    e'tiborsiz qoldiriladi.

    Founder Bot (FOUNDER_BOT_TOKEN) — istisno: u hech qanday mijozga
    tegishli emas, shuning uchun tenants jadvalida umuman qidirilmaydi.
    Token mos kelsa, to'g'ridan-to'g'ri bot_role="founder" bilan o'tkaziladi."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot = data["bot"]

        if FOUNDER_BOT_TOKEN and bot.token == FOUNDER_BOT_TOKEN:
            data["bot_role"] = "founder"
            data["is_admin"] = False
            return await handler(event, data)

        result = await database.get_tenant_by_role_token(bot.token)

        if result is None:
            logger.warning("Notanish token orqali so'rov keldi, e'tiborsiz qoldirildi.")
            return None

        tenant, bot_role = result
        if tenant["status"] != "active":
            logger.warning(
                "Nofaol mijoz (id=%s) tokeni orqali so'rov keldi.", tenant["id"]
            )
            return None

        data["tenant_id"] = tenant["id"]
        data["tenant"] = tenant
        data["bot_role"] = bot_role  # "candidate" | "admin"

        user = data.get("event_from_user")
        # is_admin: FAQAT Admin panel-bot orqali kelgan VA mijozning admin
        # ro'yxatida bo'lgan foydalanuvchi uchun true. Nomzod-bot orqali
        # kelgan hech kim (hatto mijozning o'zi ham) is_admin=True bo'la olmaydi.
        data["is_admin"] = bool(
            bot_role == "admin" and user and user.id in tenant["admin_user_ids"]
        )

        return await handler(event, data)


class IsCandidateBot(BaseFilter):
    """Faqat nomzod-bot orqali kelgan yangilanishlar uchun."""

    async def __call__(
        self, event: TelegramObject, bot_role: str = "candidate"
    ) -> bool:
        return bot_role == "candidate"


class IsAdminBot(BaseFilter):
    """Faqat Admin panel-bot orqali, VA shu mijozning admin ro'yxatidagi
    foydalanuvchidan kelgan yangilanishlar uchun."""

    async def __call__(
        self,
        event: TelegramObject,
        bot_role: str = "candidate",
        is_admin: bool = False,
    ) -> bool:
        return bot_role == "admin" and is_admin


class IsFounderBot(BaseFilter):
    """Faqat Founder Bot orqali, VA FOUNDER_USER_IDS ro'yxatidagi
    foydalanuvchidan kelgan yangilanishlar uchun (ikki bosqichli tekshiruv —
    token TO'G'RI kelishi HAM YETARLI EMAS, yuboruvchi shaxs ham
    ro'yxatda bo'lishi shart)."""

    async def __call__(
        self, event: TelegramObject, bot_role: str = "candidate"
    ) -> bool:
        if bot_role != "founder":
            return False
        user = getattr(event, "from_user", None)
        return bool(user and user.id in FOUNDER_USER_IDS)
