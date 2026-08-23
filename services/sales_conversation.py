"""
Janob HR — /create_bot oqimidagi MOSLASHUVCHAN sotuv suhbati.

Oddiy, qattiq belgilangan 3 ta savol o'rniga, AI orqali HAQIQIY suhbat
olib boradi: mijozning har bir javobiga qarab keyingi savolni o'zi
moslashtiradi. Maqsad — mijozning "og'rig'i"ni chiqarib olish, uni tan
oldirish, va aynan o'sha muammoga Janob HR yechim ekanini ko'rsatish
(klassik konsultativ sotuv strategiyasi).

Bir xil provayder ro'yxati va zaxira zanjiridan (services/ai_scoring.py
bilan bir xil tamoyilda) foydalanadi, lekin BUTUN SUHBAT TARIXINI
uzatadi — bitta savol-javob emas.
"""
import logging
from typing import Optional

import aiohttp

from config import (
    AI_API_BASE, AI_API_BASE_2, AI_API_BASE_3,
    AI_API_KEY, AI_API_KEY_2, AI_API_KEY_3,
    AI_MODEL, AI_MODEL_2, AI_MODEL_3,
)

logger = logging.getLogger("janob_hr_bot")

_PROVIDERS = [
    (AI_API_KEY, AI_API_BASE, AI_MODEL, "asosiy"),
    (AI_API_KEY_2, AI_API_BASE_2, AI_MODEL_2, "zaxira-1"),
    (AI_API_KEY_3, AI_API_BASE_3, AI_MODEL_3, "zaxira-2"),
]

_SYSTEM_PROMPT = """Sen — Janob HR (AI-HR bot) uchun konsultativ sotuv suhbatini olib
boruvchi yordamchisan. Suhbatdoshing — kichik/o'rta biznes egasi, u hozirgina
Janob HR botini nomzod sifatida sinab ko'rdi va potensial mijoz.

MAQSADING: uning yollash/kadrlar bilan bog'liq HAQIQIY OG'RIG'INI chiqarib
olish, uni tan oldirish, va shu muammoga Janob HR yechim ekanini tabiiy
ravishda ko'rsatish. Bu — reklama emas, HAQIQIY qiziqish bilan suhbat.

QOIDALAR:
- Har safar FAQAT BITTA savol yoki qisqa fikr bilan javob ber (2-3 gap).
- Suhbatdoshning OLDINGI javobiga chinakam munosabat bildir (uni takrorlama,
  balki chuqurlashtir yoki aniqlashtir).
- Hissiy, do'stona ohangda yoz, lekin professional. O'zbek tilida.
- Agar suhbatdosh "yollash muammosi yo'q" desa — hurmat bilan qabul qil,
  lekin baribir Janob HR foydali bo'lishi mumkinligini (masalan kelajakda)
  qisqa eslat.
- HECH QACHON o'zingdan raqam/statistika to'qima — faqat suhbatdosh aytgan
  narsaga tayan.
- Agar bu SENING 3-JAVOBING bo'lsa (ya'ni foydalanuvchidan 3-marta javob
  kelgan bo'lsa) — endi savol berma, buning o'rniga uning aytgan muammosini
  bir jumlada umumlashtirib, Janob HR aynan shu muammoni qanday hal
  qilishini 1-2 gapda tushuntirib, suhbatni yakunla."""


async def _call_ai_conversation(messages: list[dict]) -> Optional[str]:
    """`messages` — [{"role": "system"/"user"/"assistant", "content": "..."}]
    ko'rinishidagi to'liq suhbat tarixi. Sozlangan provayderlarni navbat
    bilan sinaydi, birinchi muvaffaqiyatlisidan matnni qaytaradi."""
    active = [(k, b, m, label) for k, b, m, label in _PROVIDERS if k]
    if not active:
        return None

    for key, base, model, label in active:
        payload = {"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 200}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{base.rstrip('/')}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=aiohttp.ClientTimeout(total=12),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning("AI provayder (%s) xatosi: HTTP %s | %s", label, resp.status, body[:300])
                        continue
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if content and content.strip():
                        return content.strip()
        except Exception:
            logger.exception("AI provayder (%s) so'rovida xato.", label)
            continue

    return None


async def get_next_message(history: list[dict]) -> Optional[str]:
    """`history` — [{"role": "user"/"assistant", "content": "..."}] (system
    kiritilmagan). Tizim prompti avtomatik qo'shiladi."""
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + history
    return await _call_ai_conversation(messages)
