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
    (AI_API_KEY_3, AI_API_BASE_3, AI_MODEL_3, "asosiy (DeepSeek)"),
    (AI_API_KEY_2, AI_API_BASE_2, AI_MODEL_2, "zaxira-1 (Groq)"),
    (AI_API_KEY, AI_API_BASE, AI_MODEL, "zaxira-2 (Gemini)"),
]


async def _call_ai(
    system_prompt: str, user_prompt: str, max_tokens: int,
    extra_messages: Optional[list[dict]] = None, temperature: float = 0,
    frequency_penalty: float = 0.0, presence_penalty: float = 0.0,
) -> Optional[str]:
    """Sozlangan provayderlarni navbat bilan sinaydi, birinchi muvaffaqiyatlisidan
    xom matnni qaytaradi. Hech biri sozlanmagan yoki barchasi ishlamasa — None.

    `extra_messages` — agar berilsa (masalan ko'p-turli suhbat tarixi), ular
    system+user juftligi ORASIGA emas, balki UNING O'RNIGA emas — system
    xabaridan KEYIN, asosiy user_prompt o'rniga to'liq tarix sifatida
    ishlatiladi (bunda `user_prompt` e'tiborga olinmaydi).

    `frequency_penalty`/`presence_penalty` — 0 bo'lsa payloadga qo'shilmaydi
    (eski xatti-harakat o'zgarmaydi). Repetitiv, "bir xil so'z bilan boshlanadigan"
    javoblarni kamaytirish uchun (masalan sotuv suhbatida) musbat qiymat berish
    mumkin — OpenAI-compatible barcha provayderlar (DeepSeek/Groq/Gemini) buni
    qo'llab-quvvatlaydi.

    TIMEOUT: `max_tokens`ga QARAB HISOBLANADI, qattiq belgilangan emas — qisqa
    (50-100 tokenlik) baholash so'rovlari uchun 7s yetarli, lekin 2500 tokenlik
    savol generatsiyasi/tarjima kabi UZUN javoblar buncha vaqtda deyarli hech
    qachon ulgurmaydi va provayderlar behuda "band" deb belgilanadi. Taxminiy
    ~90 tokens/soniya generatsiya tezligi + 5s bufer bilan hisoblanadi.
    """
    active = [(k, b, m, label) for k, b, m, label in _PROVIDERS if k]
    if not active:
        return None

    timeout_seconds = max(7, round(max_tokens / 90) + 5)

    for key, base, model, label in active:
        messages = [{"role": "system", "content": system_prompt}]
        if extra_messages:
            messages += extra_messages
        else:
            messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if frequency_penalty:
            payload["frequency_penalty"] = frequency_penalty
        if presence_penalty:
            payload["presence_penalty"] = presence_penalty
        if "deepseek" in base.lower():
            # DeepSeek V4 modellari DEFAULT holda "thinking mode"da ishlaydi —
            # bu butun token byudjetini "ichki fikrlash"ga sarflab, ko'rinadigan
            # javobni BO'SH qoldirishi mumkin (rasman hujjatlashtirilgan xato
            # holati). Bizga tezkor, oddiy javob kerak — fikrlash rejimi kerak
            # emas.
            payload["thinking"] = {"type": "disabled"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{base.rstrip('/')}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            "AI provayder (%s) xatosi: HTTP %s | %s", label, resp.status, body[:300]
                        )
                        continue  # navbatdagi provayderga o'tamiz
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if not content or not content.strip():
                        # HTTP 200 keldi, lekin matn bo'sh — bu odatda "fikrlash"
                        # (reasoning) modellari max_tokens byudjetini ichki fikrlashga
                        # sarflab, ko'rinadigan javob yozishga ulgurmaganda sodir
                        # bo'ladi. Bu holatni MUVAFFAQIYAT deb hisoblamaymiz —
                        # navbatdagi provayderga o'tamiz.
                        finish_reason = data.get("choices", [{}])[0].get("finish_reason")
                        logger.warning(
                            "AI provayder (%s) bo'sh javob qaytardi (finish_reason=%s), "
                            "keyingi provayderga o'tamiz.", label, finish_reason,
                        )
                        continue
                    return content.strip()
        except Exception:
            logger.exception(
                "AI provayder (%s) so'rovi muvaffaqiyatsiz tugadi (timeout=%ss, max_tokens=%s).",
                label, timeout_seconds, max_tokens,
            )
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
- "ai_yozgan" — javob ChatGPT yoki shunga o'xshash AI chatbot orqali yozilgan/nusxa
  ko'chirilgan bo'lishi mumkinligiga shubha bор. Quyidagi belgilarga e'tibor ber: odatiy
  Telegram xabari uchun g'ayritabiiy darajada silliq, rasmiy va "muallifsiz" uslub;
  sun'iy tarzda muvozanatlashtirilgan tuzilma (masalan "Birinchidan... Ikkinchidan...
  Xulosa qilib aytganda..." kabi insho uslubi oddiy chatda kutilmaydi); shaxsiy his-tuyg'u,
  o'ziga xos tafsilot yoki tabiiy tildagi kichik nomukammalliklar (imlo xatosi, so'zlashuv
  uslubi) butunlay yo'qligi; savolga umuman aloqasi bo'lmagan haddan tashqari "to'liq"
  va "universal" javob. DIQQAT: bu faqat kuchli shubha bo'lsa qo'shilsin — puxta va
  bilimdon odam ham yaxshi yoza olishi mumkin, shuning uchun faqat bir nechta belgi
  birga uchraganda ushbu bayroqni qo'sh, yolg'iz "yaxshi yozilgan" bo'lgani uchun emas.

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
        _SYSTEM_PROMPT, f"Savol: {question}\nNomzod javobi: {answer}", max_tokens=700
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

MUHIM: qisqa javoblarni noto'g'ri rad etishdan saqlan. Masalan, savol "Qaysi platformalarda \
tajribangiz bor?" bo'lsa, "Instagram" yoki "Instagram va TikTok" kabi bir necha so'zlik \
javoblar TO'LIQ TO'G'RI va "HA" deb belgilanishi kerak — ular qisqa bo'lgani uchun emas, \
balki savolga aniq javob bergani uchun. Faqat quyidagi holatlarda "YOQ" deb hisobla:
- javob butunlay bema'ni/tushunarsiz matn (masalan tasodifiy harflar)
- javob spam yoki reklama
- javob savolga umuman aloqasi bo'lmagan boshqa mavzuda (masalan ob-havo haqida so'ralganda ovqat haqida yozish)
- javob shunchaki bitta emoji yoki nuqta kabi mazmunsiz belgi

Ikkilanib qolsang — "HA" deb belgila (shubhadan foyda nomzodga berilsin).

FAQAT bitta so'z bilan javob ber: HA yoki YOQ. Boshqa hech qanday matn yozma.
"""


async def check_relevance(question: str, answer: str) -> Optional[bool]:
    """AI_score bilan belgilanmagan (oddiy faktik) savollar uchun yengil aloqadorlik tekshiruvi.

    True — javob mavzuga/kasbga aloqador, False — aloqasiz/bema'ni. Hech qanday
    provayder sozlanmagan yoki barchasi ishlamasa, None qaytaradi — bunday holda
    chaqiruvchi tekshiruvni o'tkazib yuborishi kerak (botni AI'siz ham ishlashi uchun).
    """
    content = await _call_ai(
        _RELEVANCE_SYSTEM_PROMPT, f"Savol: {question}\nNomzod javobi: {answer}", max_tokens=50
    )
    if content is None:
        return None
    return content.strip().upper().startswith("HA")


_QUESTION_GENERATION_PROMPT = """Sen professional HR maslahatchisan. "Scorecard" va "Behavioral" \
intervyu metodologiyasidan foydalanib, berilgan lavozim uchun {count} ta Telegram-bot \
intervyu savoli tuzasan (o'zbek tilida).

Talablar:
1. Kamida bitta savol "hard_filter" bo'lsin — oddiy Ha/Yo'q formatida javob talab qiladigan,
   nomzodning shu soha bo'yicha minimal tajribasi bor-yo'qligini so'raydigan savol.
2. Kamida bitta savol "scorecard" uslubida bo'lsin: lavozimning eng muhim, o'lchanadigan
   natijasi haqida ANIQ RAQAMLI maqsad qo'yib ("Kompaniya X oyda Y natijaga erishishi kerak"),
   nomzoddan shu maqsadga qanday erishishini so'ra.
3. Kamida bitta "yutuq" (achievement) savoli va bitta "eng jiddiy xato va undan olingan dars"
   savoli bo'lsin (ikkalasi ham "behavioral" savollar, A-Player'larni "Men" tilida gapirishini
   aniqlash uchun).
4. Qolgan savollar kasbga oid amaliy/texnik bilim va vaziyat-asosli savollar bo'lsin.
5. Har bir ochiq (fikr-mulohaza talab qiladigan, ko'p so'zli javob kutiladigan) savolga
   "ai_score": true qo'y. Oddiy faktik/ro'yxat savollariga (masalan "qanday vositalardan
   foydalanasiz") "ai_score" qo'shmasang ham bo'ladi.
6. Har bir savol uchun qisqa, lotin harflarida, pastki chiziqli "key" o'ylab top (masalan
   "scorecard_plan", "achievement", "mistake_lesson").
7. Kamida bitta savol nomzodning da'vo qilingan tajribasi HAQIQIYLIGINI tekshirishga
   xizmat qilsin — bunday savol umumiy tushunchani bilgan har qanday odam emas, balki
   FAQAT haqiqiy amaliy tajribaga ega odam aniq va batafsil javob bera oladigan, sohaga
   xos texnik/amaliy tafsilotni so'rasin (masalan, aniq dastur funksiyasi nomi, real
   ish jarayonining tafsiloti, yoki soha ichidagi maxsus atama/protsedura). Maqsad —
   faqat kitobdan o'qib bilgan yoki tajribasini o'ylab topgan nomzodlarni ajratib olish.
8. Savollar orasidan ENG MUHIM bittasini (ko'pi bilan ikkitasini) — odatda "scorecard"
   yoki "yutuq" turidagi savolni — "voice": true deb ham belgila. Bu savolga nomzod
   OVOZLI xabar orqali javob berishi MAJBURIY bo'ladi (yozib emas, gapirib). Bu javob
   AI orqali baholanmaydi — audio fayl to'g'ridan-to'g'ri ish beruvchiga (adminga)
   yuboriladi, u shaxsan tinglab baholaydi. Maqsad — tayyorlab, ChatGPT yordamida
   yozib olingan javoblarni emas, jonli va tabiiy javobni olish.

TARTIB (JUDA MUHIM — javoblar RO'YXATDAGI TARTIBDA nomzodga bittalab beriladi):
9. "hard_filter" savoli RO'YXATNING ENG BOSHIDA (1-savol) bo'lishi SHART. Sabab: agar
   nomzod salbiy javob bersa, suhbat SHU YERDA to'xtaydi va rad etiladi — filtrni
   oxiriga qoldirish nomzodning ham, ishga oluvchining ham vaqtini behuda sarflaydi.
10. Undan keyin ODDIY, TEZ javob beriladigan faktik/vosita savollari (masalan qaysi
    dastur/platformadan foydalanadi) kelsin — bular nomzodni "isitib", suhbatga
    kirishishini osonlashtiradi.
11. Keyin chuqurroq scorecard/behavioral savollar (yutuq, xato-dars, vaziyatli
    savollar) — OSONDAN QIYINGA qarab, bittalab chuqurlashib borsin.
12. Oylik maosh haqidagi savol (agar bo'lsa) RO'YXATNING ENG OXIRIDA bo'lsin — bu
    standart intervyu odati.
13. HAR BIR savol FAQAT BITTA narsa so'rasin. Ikkita savolni "va"/"?...?" bilan
    bittaga qo'shib yuborish QAT'IY TAQIQLANADI (masalan "X qanday qilasiz? Va
    oxirgi marta Y qachon bo'lgan?" — bu IKKITA savol, IKKITA alohida qatorga
    bo'linishi kerak, count sonini shunga mos hisobla).

FAQAT quyidagi JSON massiv formatida javob ber, boshqa hech qanday matn yozma:
[{{"key": "...", "text": "...", "hard_filter": true}}, {{"key": "...", "text": "...", "ai_score": true}}, \
{{"key": "...", "text": "...", "voice": true}}, ...]
"""


async def generate_questions(job_title: str, description: str, count: int = 9) -> Optional[list[dict]]:
    """Berilgan lavozim uchun Scorecard/Behavioral uslubidagi savollar ro'yxatini
    AI orqali generatsiya qiladi. Muvaffaqiyatsiz bo'lsa (yoki hech qanday provayder
    sozlanmagan bo'lsa) None qaytaradi — admin bunday holda savollarni qo'lda kiritishi
    kerak bo'ladi.
    """
    system_prompt = _QUESTION_GENERATION_PROMPT.format(count=count)
    user_prompt = f"Lavozim: {job_title}\nQisqacha tavsif: {description or '(tavsif berilmagan)'}"

    content = await _call_ai(system_prompt, user_prompt, max_tokens=2500)
    if content is None:
        return None

    try:
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
        parsed = json.loads(content)
        if not isinstance(parsed, list):
            raise ValueError("AI ro'yxat (list) qaytarishi kerak edi")

        questions = []
        seen_keys = set()
        for i, item in enumerate(parsed):
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            key = str(item.get("key", f"savol_{i+1}")).strip().lower().replace(" ", "_") or f"savol_{i+1}"
            # Kalitlar takrorlanmasligi kerak (bazada ustun nomi sifatida ishlatilmaydi,
            # lekin javoblar lug'atida kalit bo'lgani uchun noyob bo'lishi shart).
            original_key = key
            n = 2
            while key in seen_keys:
                key = f"{original_key}_{n}"
                n += 1
            seen_keys.add(key)

            q = {"key": key, "text": text}
            if item.get("hard_filter"):
                q["hard_filter"] = True
            if item.get("voice"):
                # Ovozli savol AI orqali baholanmaydi (audio to'g'ridan-to'g'ri
                # adminga yuboriladi) — shuning uchun "ai_score" bayrog'i bilan
                # birga qo'yilmasligi kerak, hatto AI shunday taklif qilgan bo'lsa ham.
                q["voice"] = True
            elif item.get("ai_score"):
                q["ai_score"] = True
            questions.append(q)

        return _reorder_questions(questions) or None
    except Exception:
        logger.exception("AI savol generatsiyasi javobini o'qib bo'lmadi: %s", content)
        return None


_SALARY_KEYWORDS = ("maosh", "oylik", "ish haqi")


def _reorder_questions(questions: list[dict]) -> list[dict]:
    """AI tartib qoidasiga (filtr birinchi, maosh oxirida) to'liq rioya qilmasa
    ham, kod darajasida kafolatlaydi — prompt yo'riqnomasiga ishonib qolmaslik
    kerakligi bu loyihada bir necha marta tasdiqlangan."""
    filters = [q for q in questions if q.get("hard_filter")]
    salary = [
        q for q in questions
        if not q.get("hard_filter") and any(kw in q["text"].lower() for kw in _SALARY_KEYWORDS)
    ]
    middle = [q for q in questions if q not in filters and q not in salary]
    return filters + middle + salary


_RESUME_EXTRACTION_PROMPT = """Sen rezyume (CV) tahlilchisan. Senga nomzodning rezyume matni va \
Telegram-bot savollari ro'yxati beriladi.

Vazifang ikkita qism:
1. "summary" — rezyume asosida nomzodning tajribasi, ta'limi va asosiy ko'nikmalari haqida \
QISQA (2-3 gap, o'zbek tilida) xulosa yoz.
2. "answers" — quyida berilgan savollar ro'yxatini ko'rib chiq. FAQAT agar rezyumeda o'sha \
savolga ANIQ va ishonchli javob mavjud bo'lsa (masalan qaysi dastur/CRM ishlatgani, qancha \
yillik tajribasi borligi, qaysi tillarni bilishi kabi ODDIY FAKTIK ma'lumotlar), savol \
kalitini va rezyumedan olingan qisqa javobni qo'sh. Agar rezyumeda aniq javob bo'lmasa yoki \
taxmin qilishga to'g'ri kelsa, o'sha savolni UMUMAN QO'SHMA — bo'sh taxmin qilishdan ko'ra, \
savolni o'tkazib yuborish yaxshiroq.

MUHIM: bu FAQAT oddiy faktik savollar uchun. Agar savol nomzoddan reja, misol, tahlil yoki \
fikr-mulohaza talab qilsa (masalan "qanday reja tuzasiz", "eng katta yutug'ingiz nima"), buni \
HECH QACHON rezyumedan taxmin qilib to'ldirma — bunday savollar nomzodning o'zidan so'ralishi SHART.

Savollar ro'yxati:
{questions_list}

FAQAT quyidagi JSON formatida javob ber, boshqa hech narsa yozma:
{{"summary": "...", "answers": {{"<savol_key>": "<rezyumedan olingan qisqa javob>", ...}}}}
"""


async def extract_resume_data(resume_text: str, questions: list[dict]) -> Optional[dict]:
    """Rezyume matnidan qisqa xulosa va (faqat oddiy faktik) savollarga tayyor javoblarni
    chiqarib beradi. `questions` — faqat "ai_score" va "hard_filter" BELGILANMAGAN
    savollar ro'yxati bo'lishi kerak (chaqiruvchi shuni ta'minlashi kerak) — Scorecard/
    Behavioral savollar rezyumedan hech qachon to'ldirilmaydi.

    Muvaffaqiyatsiz bo'lsa yoki rezyume matni juda qisqa/bo'sh bo'lsa, None qaytaradi.
    """
    resume_text = (resume_text or "").strip()
    if len(resume_text) < 50 or not questions:
        return None

    questions_list = "\n".join(f'- key="{q["key"]}": {q["text"]}' for q in questions)
    system_prompt = _RESUME_EXTRACTION_PROMPT.format(questions_list=questions_list)
    # Rezyume matnini oqilona uzunlikda cheklaymiz (token byudjetini tejash uchun).
    user_prompt = resume_text[:6000]

    content = await _call_ai(system_prompt, user_prompt, max_tokens=1200)
    if content is None:
        return None

    try:
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
        parsed = json.loads(content)
        summary = str(parsed.get("summary", "")).strip()
        raw_answers = parsed.get("answers") or {}

        valid_keys = {q["key"] for q in questions}
        answers = {
            k: str(v).strip()
            for k, v in raw_answers.items()
            if k in valid_keys and str(v).strip()
        }

        if not summary and not answers:
            return None
        return {"summary": summary, "answers": answers}
    except Exception:
        logger.exception("Rezyume tahlili javobini o'qib bo'lmadi: %s", content)
        return None


_VACANCY_TRANSLATION_PROMPT = """Sen professional tarjimonsan. Senga JSON ko'rinishida ish \
vakansiyasi savollari va rad etish xabari beriladi (o'zbek tilida). Ularni tabiiy, professional \
rus tiliga tarjima qil.

QAT'IY QOIDALAR:
- Har bir savolning "key" maydonini O'ZGARTIRMA — aynan shu ko'rinishda qayta qaytar.
- Faqat "text" maydonlarini (savol matnlarini) va "reject_message"ni tarjima qil.
- "hard_filter" va "ai_score" bayroqlarini o'zgartirmasdan saqlab qol (agar mavjud bo'lsa).
- Tarjima ma'noni to'liq saqlashi, lekin rus tilida tabiiy eshitilishi kerak (so'zma-so'z emas).

FAQAT quyidagi JSON formatida javob ber, boshqa hech narsa yozma:
{{"questions": [{{"key": "...", "text": "...", ...boshqa maydonlar o'zgarishsiz...}}, ...], \
"reject_message": "..."}}

Tarjima qilinadigan ma'lumot:
{payload}
"""


_SIMPLE_TRANSLATION_PROMPT = """Sen tarjimonsan. Senga qisqa matn (odatda lavozim nomi) \
beriladi — uni o'zbek tilidan rus tiliga tabiiy, professional tarzda tarjima qil.

FAQAT tarjima qilingan matnni yoz — hech qanday izoh, tirnoq belgisi yoki qo'shimcha \
so'z qo'shma. Agar matnda emoji bo'lsa, uni saqlab qol."""


async def translate_simple_text(text: str) -> Optional[str]:
    """Qisqa matn (masalan lavozim nomi) uchun yengil tarjima. Muvaffaqiyatsiz bo'lsa
    None qaytadi."""
    content = await _call_ai(_SIMPLE_TRANSLATION_PROMPT, text, max_tokens=100)
    if content is None:
        return None
    cleaned = content.strip().strip('"').strip("'").strip()
    return cleaned or None


async def translate_vacancy_content(questions: list[dict], reject_message: str) -> Optional[dict]:
    """Vakansiya savollari va rad etish xabarini rus tiliga tarjima qiladi (key va
    hard_filter/ai_score bayroqlarini o'zgartirmasdan). Muvaffaqiyatsiz bo'lsa None
    qaytaradi — chaqiruvchi bunday holda o'zbekcha versiyani ishlatishi kerak.
    """
    payload = json.dumps(
        {"questions": questions, "reject_message": reject_message}, ensure_ascii=False,
    )
    system_prompt = _VACANCY_TRANSLATION_PROMPT.format(payload=payload)

    content = await _call_ai(system_prompt, "Tarjima qil.", max_tokens=2500)
    if content is None:
        return None

    try:
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
        parsed = json.loads(content)

        translated_questions = parsed.get("questions")
        reject_message_ru = str(parsed.get("reject_message", "")).strip()
        if not isinstance(translated_questions, list) or not reject_message_ru:
            raise ValueError("Tarjima natijasi to'liq emas")

        # Xavfsizlik: kalitlar soni va tartibi asl savollar bilan mos kelishini
        # tekshiramiz — mos kelmasa, tarjimani ishonchsiz deb hisoblaymiz.
        original_keys = [q["key"] for q in questions]
        translated_keys = [q.get("key") for q in translated_questions]
        if translated_keys != original_keys:
            logger.warning("Tarjima kalitlari asl savollar bilan mos kelmadi, bekor qilinadi.")
            return None

        return {"questions": translated_questions, "reject_message": reject_message_ru}
    except Exception:
        logger.exception("Vakansiya tarjimasi javobini o'qib bo'lmadi: %s", content)
        return None


class AggregateResult(TypedDict):
    avg_score: int
    verdict: str  # "yashil" | "sariq" | "qizil"
    red_flags: list[str]
    avg_natijadorlik: int
    avg_masuliyat: int
    avg_aniqlik: int


def aggregate_scores(ai_scores: dict) -> Optional[AggregateResult]:
    """Bir nechta savol bo'yicha AI baholarini bitta yakuniy natijaga birlashtiradi.

    ai_scores — {savol_key: ScoreResult} lug'ati (questions.py'da to'planadi).
    Hech qanday AI ball bo'lmasa (masalan hech bir provayder sozlanmagan), None qaytadi.
    """
    valid = [v for v in ai_scores.values() if isinstance(v, dict) and "score" in v]
    if not valid:
        return None

    avg_score = round(sum(v["score"] for v in valid) / len(valid))
    avg_natijadorlik = round(sum(v.get("natijadorlik", 0) for v in valid) / len(valid))
    avg_masuliyat = round(sum(v.get("masuliyat", 0) for v in valid) / len(valid))
    avg_aniqlik = round(sum(v.get("aniqlik", 0) for v in valid) / len(valid))

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

    return AggregateResult(
        avg_score=avg_score, verdict=verdict, red_flags=all_flags,
        avg_natijadorlik=avg_natijadorlik, avg_masuliyat=avg_masuliyat, avg_aniqlik=avg_aniqlik,
    )
