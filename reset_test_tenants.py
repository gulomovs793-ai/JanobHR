"""
Asoschidan (o'zingizning kompaniyangizdan) BOSHQA barcha mijozlarni
(test uchun /create_bot orqali yaratilganlarni) butunlay o'chiradi —
shu bilan ularning tokenlarini qayta ishlatish mumkin bo'ladi.

⚠️ Bu amalni ORTGA QAYTARIB BO'LMAYDI. Faqat TEST ma'lumotlarini
tozalash uchun ishlating.

Ishga tushirish (Render -> Shell bo'limida):
    python reset_test_tenants.py
"""
import asyncio

import aiosqlite

from config import BOT_TOKEN
from services import database as db


async def main():
    await db.init_db()

    founder = await db.get_tenant_by_token(BOT_TOKEN)
    if not founder:
        print("❌ Asoschi tenant topilmadi — hech narsa o'chirilmadi.")
        return
    founder_id = founder["id"]
    print(f"✅ Asoschi (SAQLANADI): id={founder_id}, {founder['company_name']}")

    all_tenants = await db.list_tenants()
    to_delete = [t for t in all_tenants if t["id"] != founder_id]

    if not to_delete:
        print("\nO'chiriladigan boshqa mijoz yo'q — baza allaqachon toza.")
        return

    print(f"\nO'CHIRILADI ({len(to_delete)} ta):")
    for t in to_delete:
        print(f"  - id={t['id']}, {t['company_name']} ({t['status']})")

    async with aiosqlite.connect(db.SQLITE_PATH) as conn:
        for t in to_delete:
            tid = t["id"]
            await conn.execute("DELETE FROM applications WHERE tenant_id = ?", (tid,))
            await conn.execute("DELETE FROM vacancies WHERE tenant_id = ?", (tid,))
            await conn.execute("DELETE FROM interview_slots WHERE tenant_id = ?", (tid,))
            await conn.execute("DELETE FROM interview_settings WHERE tenant_id = ?", (tid,))
            await conn.execute("DELETE FROM payment_orders WHERE tenant_id = ?", (tid,))
            await conn.execute("DELETE FROM tenants WHERE id = ?", (tid,))
        await conn.commit()

    print(f"\n✅ {len(to_delete)} ta test mijoz va ularning barcha ma'lumotlari o'chirildi.")
    print("Endi o'sha tokenlarni /create_bot orqali qaytadan ishlatishingiz mumkin.")
    print("\n⚠️ Diqqat: bot jarayoni (bot.py) hali xotirasida eski mijozlar royxatini saqlab")
    print("qolgan bo'lishi mumkin — o'zgarish to'liq amal qilishi uchun xizmatni")
    print("\"Manual Deploy\" yoki \"Restart\" qiling.")


if __name__ == "__main__":
    asyncio.run(main())
