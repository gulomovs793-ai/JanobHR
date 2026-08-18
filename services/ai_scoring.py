"""
Janob HR Bot — AI orqali "A-Player" tahlili.

Oddiy 0-100 baholashdan farqli o'laroq, bu modul nomzod javobini haqiqiy HR
direktor kabi 3 mezon bo'yicha (Natijadorlik, Mas'uliyat, Aniqlik) baholaydi,
"qizil bayroqlarni" (qurbon sindromi, abstrakt javob, "Men/Biz" nomutanosibligi)
aniqlaydi va 🟢/🟡/🔴 yakuniy verdikt chiqaradi.

AI_API_KEY bo'sh bo'lsa, hech narsa chaqirilmaydi (None qaytadi) — bot AI'siz
ham ishlayveradi.
"""
import json
import logging
import re
from typing import Optional, TypedDict

import aiohttp

from config import AI_API_BASE, AI_API_KEY, AI_MODEL

logger = logging.getLogger("janob_hr_bot")


class ScoreResult(TypedDict):
    score: int  # 0-100, uchala mezonning o'rtachasi
    verdict: str  # "yashil" | "sariq" | "qizil"
    natijadorlik: int
    masuliyat: int
    aniqlik: int
    red_flags: list[str]
    izoh: str  # 1 gapli qisqa xulosa


_SYSTEM_PROMPT = """Sen Google va Apple kompaniyalarida ishlagan 15 yillik tajribaga ega, \
juda qattiqqo'l va professional HR direktorsan. Sening vazifang — Telegram-bot orqali \
kelgan nomzodning bitta savolga bergan javobini sovuqqonlik bilan, hissiyotsiz tahlil qilish.

Javobni 3 ta qat'iy mezon bo'yicha 0 dan 100 gacha bahola:
1. natijadorlik — Matnda aniq raqamlar, foizlar, muddatlar bormi, yoki faqat quruq umumiy gaplarmi?
2. masuliyat — Muammo haqida gapirganda, nomzod boshqalarni/vaziyatni ayblaydimi ("Biz",
   "Bozor yomon edi", "Rahbarim ahmoq edi"), yoki o'z harakatiga mas'uliyat oladimi ("Men qildim")?
3. aniqlik — Savolga to'g'ridan-to'g'ri va tushunarli javob berdimi, yoki chalg'itib,
   umumiy gapirdimi?

Quyidagi "qizil bayroqlarni" alohida qidir va topilganlarini ro'yxatga qo'sh (topilmasa bo'sh qoldir):
- "qurbon_sindromi" — nomzod muvaffaqiyatsizlikni doim tashqi omillarga (bozor, rahbar,
  hamkasblar) yozadi, o'z aybini hech qachon tan olmaydi.
- "abstrakt_javob" — javobda faqat umumiy iboralar bor ("qattiq ishlayman", "yaxshi
  munosabatda bo'laman"), lekin hech qanday aniq qadam yoki raqam yo'q.
- "narsissizm" — nomzod jamoaviy natijani ham faqat o'ziniki qilib ko'rsatadi, boshqalarning
  hissasini butunlay inkor etadi.

Uchala mezon o'rtachasi asosida yakuniy "verdict" tanla:
- "yashil" — o'rtacha ball 75 dan yuqori va jiddiy qizil bayroq yo'q
- "sariq" — o'rtacha ball 50-74 oralig'ida, yoki bitta yengil bayroq bor
- "qizil" — o'rtacha ball 50 dan past, yoki jiddiy bayroq(lar) bor

FAQAT quyidagi JSON formatida javob ber, boshqa hech qanday matn, izoh yoki markdown yozma:
{"natijadorlik": <son>, "masuliyat": <son>, "aniqlik": <son>, "verdict": "<yashil|sariq|qizil>", \
"red_flags": [<satrlar ro'yxati>], "izoh": "<15 so'zdan oshmagan, o'zbek tilida qisqa xulosa>"}
"""


async def score_answer(question: str, answer: str) -> Optional[ScoreResult]:
    if not AI_API_KEY:
        return None

    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Savol: {question}\nNomzod javobi: {answer}"},
        ],
        "temperature": 0,
        "max_tokens": 300,
    }
    headers = {"Authorization": f"Bearer {AI_API_KEY}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{AI_API_BASE.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("AI scoring API xatosi: HTTP %s | %s", resp.status, body[:300])
                    return None
                data = await resp.json()
    except Exception:
        logger.exception("AI scoring so'rovi muvaffaqiyatsiz tugadi.")
        return None

    try:
        content = data["choices"][0]["message"]["content"].strip()
        # Ba'zi modellar JSON'ni ```json ... ``` bilan o'rab yuborishi mumkin — tozalaymiz.
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
        parsed = json.loads(content)

        natijadorlik = max(0, min(100, int(parsed.get("natijadorlik", 0))))
        masuliyat = max(0, min(100, int(parsed.get("masuliyat", 0))))
        aniqlik = max(0, min(100, int(parsed.get("aniqlik", 0))))
        avg = round((natijadorlik + masuliyat + aniqlik) / 3)

        verdict = str(parsed.get("verdict", "")).strip().lower()
        if verdict not in ("yashil", "sariq", "qizil"):
            # AI noto'g'ri qiymat qaytarsa, ballga qarab o'zimiz aniqlaymiz (himoya chizig'i).
            verdict = "yashil" if avg >= 75 else "sariq" if avg >= 50 else "qizil"

        red_flags = parsed.get("red_flags") or []
        if not isinstance(red_flags, list):
            red_flags = []

        izoh = str(parsed.get("izoh", "")).strip()[:200]

        return ScoreResult(
            score=avg,
            verdict=verdict,
            natijadorlik=natijadorlik,
            masuliyat=masuliyat,
            aniqlik=aniqlik,
            red_flags=[str(f) for f in red_flags],
            izoh=izoh,
        )
    except Exception:
        logger.exception("AI javobini o'qib bo'lmadi: %s", data)
        return None


class AggregateResult(TypedDict):
    avg_score: int
    verdict: str  # "yashil" | "sariq" | "qizil"
    red_flags: list[str]


def aggregate_scores(ai_scores: dict) -> Optional[AggregateResult]:
    """Bir nechta savol bo'yicha AI baholarini bitta yakuniy natijaga birlashtiradi.

    ai_scores — {savol_key: ScoreResult} lug'ati (questions.py'da to'planadi).
    Hech qanday AI ball bo'lmasa (masalan AI_API_KEY sozlanmagan), None qaytadi.
    """
    valid = [v for v in ai_scores.values() if isinstance(v, dict) and "score" in v]
    if not valid:
        return None

    avg_score = round(sum(v["score"] for v in valid) / len(valid))

    all_flags: list[str] = []
    for v in valid:
        for flag in v.get("red_flags", []):
            if flag not in all_flags:
                all_flags.append(flag)

    has_qizil = any(v.get("verdict") == "qizil" for v in valid)
    if has_qizil or avg_score < 50:
        verdict = "qizil"
    elif all_flags or avg_score < 75:
        verdict = "sariq"
    else:
        verdict = "yashil"

    return AggregateResult(avg_score=avg_score, verdict=verdict, red_flags=all_flags)
