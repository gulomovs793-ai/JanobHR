"""
Ko'p mijozli (multi-tenant) rejim uchun asosiy mexanizm.

Bitta bot o'rniga endi HAR BIR MIJOZNING O'Z BOTI bor (bitta token — ham
nomzod, ham admin funksiyalari shu bitta botda ishlaydi). Kelayotgan har bir
yangilanish (update) qaysi bot orqali kelgani (bot.token) asosida, qaysi
mijozga (tenant) tegishli ekani aniqlanadi va shu ma'lumot barcha
handler'larga `tenant_id` va `is_admin` sifatida uzatiladi.

MUHIM: shu middleware orqali aniqlangan `tenant_id`dan boshqa hech qanday
yo'l bilan tenant_id olinmasligi kerak — aks holda mijozlar orasidagi
izolatsiya buzilishi mumkin.
"""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from services import database

logger = logging.getLogger("janob_hr_bot")


class TenantMiddleware(BaseMiddleware):
    """Har bir yangilanish uchun `bot.token` orqali tegishli mijozni (tenant)
    bazadan topadi va `tenant_id` + `is_admin` ni handler'lar uchun tayyorlaydi.

    Agar token bazada ro'yxatdan o'tmagan bo'lsa (masalan mijoz endi
    nofaollashtirilgan), so'rov butunlay e'tiborsiz qoldiriladi — hech qanday
    handler ishga tushmaydi.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        bot = data["bot"]
        tenant = await database.get_tenant_by_token(bot.token)

        if tenant is None or tenant["status"] != "active":
            logger.warning("Faol bo'lmagan/notanish token orqali so'rov keldi, e'tiborsiz qoldirildi.")
            return None

        data["tenant_id"] = tenant["id"]
        data["tenant"] = tenant

        user = data.get("event_from_user")
        data["is_admin"] = bool(user and user.id in tenant["admin_user_ids"])

        return await handler(event, data)


class IsAdmin(BaseFilter):
    """Faqat shu mijozning admin ro'yxatidagi foydalanuvchilar uchun."""

    async def __call__(self, event: TelegramObject, is_admin: bool = False) -> bool:
        return is_admin


class IsNotAdmin(BaseFilter):
    """Faqat oddiy nomzodlar uchun (admin bo'lmaganlar)."""

    async def __call__(self, event: TelegramObject, is_admin: bool = False) -> bool:
        return not is_admin
