"""Admin bot — faqat ADMIN_USER_IDS ro'yxatidagi foydalanuvchilarga ruxsat berish."""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import ADMIN_USER_IDS


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")

        if user is None or user.id not in ADMIN_USER_IDS:
            if isinstance(event, Message):
                await event.answer("⛔️ Bu bot faqat administratorlar uchun mo'ljallangan.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Ruxsat yo'q.", show_alert=True)
            return None

        return await handler(event, data)
