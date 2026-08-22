"""
Janob HR — userbot sessiya kalitini yaratish.

Buni FAQAT O'Z KOMPYUTERINGIZDA, bir marta ishga tushiring:
    pip install telethon
    python userbot_login.py

Telefon raqamingiz, Telegram yuborgan kod va (agar yoqilgan bo'lsa) ikki
bosqichli parolingizni so'raydi. Natijada uzun bir qator (sessiya kaliti)
chiqadi — shuni Render'da TELEGRAM_USERBOT_SESSION o'zgaruvchisiga qo'ying.

⚠️ Bu kalit hisobingizga TO'LIQ kirish huquqini beradi. Uni faqat Render
Environment'ga qo'ying — hech qayerga yozib qo'ymang, hech kimga bermang,
skrinshot qilib yubormang.
"""
import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    print("\n=== Janob HR — userbot sessiyasini yaratish ===\n")
    print("API ID va API HASH ni https://my.telegram.org → API development tools")
    print("sahifasidan olasiz.\n")

    api_id = int(input("API ID: ").strip())
    api_hash = input("API HASH: ").strip()

    if not api_id or not api_hash:
        print("\nAPI ID yoki HASH kiritilmadi. Bekor qilindi.")
        return

    client = TelegramClient(StringSession(), api_id, api_hash)
    async with client:
        me = await client.get_me()
        username = f"@{me.username}" if getattr(me, "username", None) else ""
        print(f"\nMuvaffaqiyatli: {me.first_name or ''} {username}")

        session_string = client.session.save()

        print("\n─────────────────────────────────────────────")
        print("TELEGRAM_USERBOT_SESSION qiymati (nusxa oling):\n")
        print(session_string)
        print("\n─────────────────────────────────────────────")
        print("Buni Render → Environment ga qo'ying. Hech kimga bermang.\n")


if __name__ == "__main__":
    asyncio.run(main())
