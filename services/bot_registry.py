"""
Ikkala bot (nomzod-bot va admin-bot) bir xil Python jarayonida ishlaydi, lekin
ularning `Bot` obyektlari alohida. Ba'zan bir bot ikkinchisi nomidan xabar
yuborishi kerak bo'ladi — masalan, admin qaror qabul qilganda (Admin botda)
natijani nomzodga aynan NOMZOD-BOT orqali yetkazish kerak (chunki nomzod faqat
o'sha bot bilan "tanish"). Bu modul ikkala `Bot` obyektiga oddiy global
havolalarni saqlaydi — bot.py ishga tushganda to'ldiriladi.
"""
from typing import Optional

from aiogram import Bot

candidate_bot: Optional[Bot] = None
admin_bot: Optional[Bot] = None
