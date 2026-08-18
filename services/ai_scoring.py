"""
Janob HR Bot — AI orqali "A-Player" tahlili.

Oddiy 0-100 baholashdan farqli o'laroq, bu modul nomzod javobini haqiqiy HR
direktor kabi 3 mezon bo'yicha (Natijadorlik, Mas'uliyat, Aniqlik) baholaydi,
"qizil bayroqlarni" (qurbon sindromi, abstrakt javob, "Men/Biz" nomutanosibligi)
aniqlaydi va 🟢/🟡/🔴 yakuniy verdikt chiqaradi.

AI PROVAYDER ZANJIRI: asosiy provayder (AI_API_KEY/AI_API_BASE/AI_MODEL) ishlamay
qolsa (kredit tugasa, limit yoki server xatosi bo'lsa), avtomatik ravishda
zaxira provayderlarga (AI_API_KEY_2, keyin AI_API_KEY_3) o'tiladi — barchasi
bir xil OpenAI-compatible formatda so'raladi va bir xil JSON strukturasida
javob kutiladi, shuning uchun nomzod yoki admin hech narsani sezmaydi.

Hech qanday provayder sozlanmagan bo'lsa yoki barchasi ishlamasa, None qaytadi
— bot AI'siz ham ishlayveradi.
"""
import json
import logging
import re
from typing import Optional, TypedDict

import aiohttp

from config import (
    AI_API_BASE,
    AI_API_BASE_2,
    AI_API_BASE_3,
    AI_API_KEY,
    AI_API_KEY_2,
    AI_API_KEY_3,
    AI_MODEL,
    AI_MODEL_2,
    AI_MODEL_3,
)

logger = logging.getLogger("janob_hr_bot")

# (kalit, manzil, model, log-yorlig'i) — kalit bo'sh bo'lgan provayderlar
# avtomatik o'tkazib yuboriladi.
_PROVIDERS = [
    (AI_API_KEY, AI_API_BASE, AI_MODEL, "asosiy"),
    (AI_API_KEY_2, AI_API_BASE_2, AI_MODEL_2, "zaxira-1"),
    (AI_API_KEY_3, AI_API_BASE_3, AI_MODEL_3, "zaxira-2"),
]


async def _call_ai(system_prompt: str, user_prompt: str, max_tokens: int) -> Optional[str]:
    """Sozlangan provayderlarni navbat bilan sinaydi, birinchi muvaffaqiyatlisidan
    xom matnni qaytaradi. Hech biri sozlanmagan yoki barchasi ishlamasa — None.
    """
    active = [(k, b, m, label) for k, b, m, label in _PROVIDERS if k]
    if not active:
        return None

    for key, base, model, label in active:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{base.rstrip('/')}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=aiohttp.ClientTimeout(total=25),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            "AI provayder (%s) xatosi: HTTP %s | %s", label, resp.status, body[:300]
                        )
                        continue  # navbatdagi provayderga o'tamiz
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception:
            logger.exception("AI provayder (%s) so'rovi muvaffaqiyatsiz tugadi.", label)
            continue  # navbatdagi provayderga o'tamiz

    logger.error("Barcha AI provayderlar ishlamadi (%d ta sinaldi).", len(active))
    return None


class ScoreResult(TypedDict):
    score: int  # 0-100, uchala mezonning o'rtachasi
    verdict: str  # "yashil" | "sariq" | "qizil"
    natijadorlik: int
    masuliyat: int
    aniqlik: int
    relevant: bool  # javob savolga/kasbga umuman aloqadormi
    red_flags: list[str]
    izoh: str  # 1 gapli qisqa xulosa


_SYSTEM_PROMPT = """Sen Google va Apple kompaniyalarida ishlagan 15 yillik tajribaga ega, \
juda qattiqqo'l va professional HR direktorsan. Sening vazifang — Telegram-bot orqali \
kelgan nomzodning bitta savolga bergan javobini sovuqqonlik bilan, hissiyotsiz tahlil qilish.

Avval eng muhim narsani tekshir — "relevant": javob umuman shu savolga va kasbga aloqadormi?
Agar javob bema'ni matn, spam, mavzudan butunlay chetga chiqqan, yoki savolga hech qanday
aloqasi yo'q bo'lsa — "relevant": false qo'y (bunday holda boshqa ballarni 0 qo'yishing mumkin).
Qisqa lekin mazmunan to'g'ri javoblarni "relevant": false qilib belgilama — faqat haqiqatan
ham aloqasiz/bema'ni bo'lsa shunday qil.

Javob relevant bo'lsa, uni 3 ta qat'iy mezon bo'yicha 0 dan 100 gacha bahola:
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
- "qizil" — o'rtacha ball 50 dan past, relevant=false, yoki jiddiy bayroq(lar) bor

FAQAT quyidagi JSON formatida javob ber, boshqa hech qanday matn, izoh yoki markdown yozma:
{"relevant": <true yoki false>, "natijadorlik": <son>, "masuliyat": <son>, "aniqlik": <son>, \
"verdict": "<yashil|sariq|qizil>", "red_flags": [<satrlar ro'yxati>], \
"izoh": "<15 so'zdan oshmagan, o'zbek tilida qisqa xulosa>"}
"""


async def score_answer(question: str, answer: str) -> Optional[ScoreResult]:
    content = await _call_ai(
        _SYSTEM_PROMPT, f"Savol: {question}\nNomzod javobi: {answer}", max_tokens=300
    )
    if content is None:
        return None

    try:
        # Ba'zi modellar JSON'ni ```json ... ``` bilan o'rab yuborishi mumkin — tozalaymiz.
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
        parsed = json.loads(content)

        relevant = bool(parsed.get("relevant", True))

        natijadorlik = max(0, min(100, int(parsed.get("natijadorlik", 0))))
        masuliyat = max(0, min(100, int(parsed.get("masuliyat", 0))))
        aniqlik = max(0, min(100, int(parsed.get("aniqlik", 0))))
        avg = round((natijadorlik + masuliyat + aniqlik) / 3)

        verdict = str(parsed.get("verdict", "")).strip().lower()
        if verdict not in ("yashil", "sariq", "qizil"):
            # AI noto'g'ri qiymat qaytarsa, ballga qarab o'zimiz aniqlaymiz (himoya chizig'i).
            verdict = "yashil" if avg >= 75 else "sariq" if avg >= 50 else "qizil"
        if not relevant:
            verdict = "qizil"

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
            relevant=relevant,
            red_flags=[str(f) for f in red_flags],
            izoh=izoh,
        )
    except Exception:
        logger.exception("AI javobini o'qib bo'lmadi: %s", content)
        return None


_RELEVANCE_SYSTEM_PROMPT = """Sen HR-botning kirish filtridasan. Vazifang — nomzodning \
javobi berilgan savolga va lavozimga mazmunan aloqadormi yoki yo'qmi, shuni tekshirish.

"YOQ" deb hisobla, agar javob: bema'ni/tushunarsiz matn bo'lsa, spam bo'lsa, savolga umuman \
aloqasi bo'lmagan boshqa mavzuda bo'lsa, yoki shunchaki emoji/bitta harf kabi mazmunsiz bo'lsa.
"HA" deb hisobla, agar javob qisqa bo'lsa ham, savolga mazmunan tegishli va jiddiy javob bo'lsa.

FAQAT bitta so'z bilan javob ber: HA yoki YOQ. Boshqa hech qanday matn yozma.
"""


async def check_relevance(question: str, answer: str) -> Optional[bool]:
    """AI_score bilan belgilanmagan (oddiy faktik) savollar uchun yengil aloqadorlik tekshiruvi.

    True — javob mavzuga/kasbga aloqador, False — aloqasiz/bema'ni. Hech qanday
    provayder sozlanmagan yoki barchasi ishlamasa, None qaytaradi — bunday holda
    chaqiruvchi tekshiruvni o'tkazib yuborishi kerak (botni AI'siz ham ishlashi uchun).
    """
    content = await _call_ai(
        _RELEVANCE_SYSTEM_PROMPT, f"Savol: {question}\nNomzod javobi: {answer}", max_tokens=5
    )
    if content is None:
        return None
    return content.strip().upper().startswith("HA")


class AggregateResult(TypedDict):
    avg_score: int
    verdict: str  # "yashil" | "sariq" | "qizil"
    red_flags: list[str]


def aggregate_scores(ai_scores: dict) -> Optional[AggregateResult]:
    """Bir nechta savol bo'yicha AI baholarini bitta yakuniy natijaga birlashtiradi.

    ai_scores — {savol_key: ScoreResult} lug'ati (questions.py'da to'planadi).
    Hech qanday AI ball bo'lmasa (masalan hech bir provayder sozlanmagan), None qaytadi.
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
