"""
Janob HR Bot — AI orqali ochiq savol javoblarini 0-100 ball bilan baholash.
AI_API_KEY bo'sh bo'lsa, hech narsa chaqirilmaydi (None qaytadi) — bot AI'siz ham ishlayveradi.
"""
import logging
import re
from typing import Optional

import aiohttp

from config import AI_API_BASE, AI_API_KEY, AI_MODEL

logger = logging.getLogger("janob_hr_bot")

_SYSTEM_PROMPT = (
    "Siz HR mutaxassisisiz. Nomzodning savolga bergan javobini 0 dan 100 gacha "
    "baholang (0 — juda zaif yoki mazmunsiz javob, 100 — a'lo darajadagi javob). "
    "Faqat butun son bilan javob bering, boshqa hech qanday matn yozmang."
)


async def score_answer(question: str, answer: str) -> Optional[int]:
    if not AI_API_KEY:
        return None

    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Savol: {question}\nJavob: {answer}"},
        ],
        "temperature": 0,
        "max_tokens": 10,
    }
    headers = {"Authorization": f"Bearer {AI_API_KEY}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{AI_API_BASE.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    logger.warning("AI scoring API xatosi: HTTP %s", resp.status)
                    return None
                data = await resp.json()
    except Exception:
        logger.exception("AI scoring so'rovi muvaffaqiyatsiz tugadi.")
        return None

    try:
        content = data["choices"][0]["message"]["content"]
        match = re.search(r"\d+", content)
        if not match:
            return None
        return max(0, min(100, int(match.group())))
    except Exception:
        logger.exception("AI javobini o'qib bo'lmadi: %s", data)
        return None
