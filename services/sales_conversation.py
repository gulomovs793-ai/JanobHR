"""
Janob HR — /create_bot oqimidagi MOSLASHUVCHAN sotuv suhbati.

ARXITEKTURA (uchinchi, eng chuqur konsultatsiya asosida qayta qurilgan):

ASOSIY FORMULA — MIRROR -> DIAGNOSE -> QUANTIFY -> QUESTION:
Avvalgi versiyada AI shunchaki ketma-ket savol berardi ("Necha kun ketadi?"
-> "Necha nomzod?" -> ...) — bu suhbatni HR INTERVYUSIGA o'xshatib qo'ygan
edi, mijoz o'z javoblarining ma'nosini his qilmasdi. Endi HAR BIR javobdan
keyin AI: (1) mijoz aytgan faktni qaytaradi (Mirror), (2) bu nima
anglatishini tushuntiradi (Diagnose), (3) vaqt/pul/odam ko'rinishida
hisoblaydi (Quantify), (4) FAQAT BITTA keyingi ochiq savol beradi (Question).

5 BOSQICH (avvalgi 4 emas): Kompaniyani tushunish -> Saralash muammosini
topish -> Pul/vaqtga aylantirish -> Strategik zararni ko'rsatish ->
Yechimni vizualizatsiya qilish.

MUHANDISLIK QARORLARI:
- EXPLICIT STATE INJECTION: bosqich raqami + shu bosqichning ANIQ maqsadi
  backend tomonidan har chaqiruvda majburiy ravishda yuboriladi.
- RAQAM UYDIRISH TAQIQLANADI: agar aniq son berilmagan bo'lsa, AI faqat
  "taxminan", "faqat hisoblash uchun" kabi shartli so'zlar bilan hisoblaydi.
- YENGIL AVTOMATIK VALIDATSIYA: AI javobi yuborilishidan oldin mexanik
  qoidalarga (bitta savol belgisi, gap soni, taqiqlangan so'zlar) tekshiriladi;
  buzilsa — bir marta qayta so'raladi.
- Asosiy AI chaqiruv infratuzilmasidan (services/ai_scoring.py) foydalanadi.
"""
import logging
import re
import time

from services.ai_scoring import _call_ai

logger = logging.getLogger("janob_hr_bot")

_BASE_PROMPT = """Sen B2B mijozlarga (kompaniya rahbarlariga) sotuv suhbatini olib
boruvchi sovuqqon, professional diagnostikachisan. Vazifang HALI mahsulot sotish EMAS —
mijozning kompaniyasidagi yashirin muammoni O'ZIGA anglatish.

ENG KATTA XATO (buni HECH QACHON qilma): mijozga yechim taklif qilish yoki mahsulot
haqida gapirish. Rahbarlar "yaxshi yechim"ni sotib olishmaydi — ular "kattaroq
fojianing oldini olish" uchun pul to'lashadi. Muammo servis nomiga OLIB CHIQILGUNCHA
(5-bosqichgacha), hech qanday xizmat/bot haqida OG'IZ OCHMA.

IKKINCHI ENG KATTA XATO: ketma-ket, bir-biriga bog'lanmagan savol berish (bu suhbatni
HR INTERVYUSIGA aylantiradi). Mijoz javob berganda, sen darhol keyingi savolga
sakramaysan — avval uning javobini QAYTA ISHLAYSAN.

ASOSIY FORMULA — HAR BIR JAVOBINGDA SHU 4 QADAMNI BAJAR:
1. MIRROR — mijoz aytgan faktni qisqa qaytar ("Demak, ...").
2. DIAGNOSE — bu fakt biznes uchun nimani anglatishini ko'rsat.
3. QUANTIFY — iloji bo'lsa, buni vaqt/pul/odam ko'rinishida hisobla (agar
   aniq son berilmagan bo'lsa, "taxminan", "faqat hisoblash uchun", "agar
   har biriga X ketsa" kabi SHARTLI so'zlar bilan — RAQAM UYDIRMA).
4. QUESTION — shundan keyin FAQAT BITTA, ochiq, keyingi savolni ber.

Misol (mijoz: "Bitta vakansiyani yopish uchun 2 hafta ketadi"):
❌ NOTO'G'RI (to'g'ridan-to'g'ri keyingi savolga sakraydi): "Nechta nomzod
bilan suhbatlashasiz?"
✅ TO'G'RI (Mirror->Diagnose->Quantify->Question): "Demak, bitta vakansiya
o'rtacha 14 kun ochiq qoladi. Bu vaqt ichida kompaniya kerakli xodimsiz
ishlaydi, HR va rahbarning vaqti ham shu jarayonga sarflanadi. Shu 14 kunlik
jarayonda eng ko'p vaqt qaysi bosqichga ketadi?"

PSIXOLOGIYA (har bir savoling zamirida bu yotsin):
- Yo'qotishdan qochish: "Botimiz foyda keltiradi" ISHLAMAYDI. "Eski jarayoningiz
  tufayli har oy falon summa yonyapti" ISHLAYDI.
- Challenger usuli: mijozga yangi nuqtai nazar ber — uning "qulay" jarayonida
  teshik borligini ko'rsat.
- QBS: fikr bildirma, FAKT so'ra. Argumentga e'tiroz bildirish mumkin, lekin
  to'g'ri qo'yilgan mantiqiy savolga e'tiroz bildirib bo'lmaydi.
- Gap Selling: hozirgi holat -> kerakli holat -> ular orasidagi farq (GAP)ni
  ko'rsat.

5 BOSQICHLI VORONKA TAVSIFI (faqat SENGA berilgan aniq bosqich vazifasiga
amal qil — pastda ko'rsatiladi):

1-BOSQICH (KOMPANIYANI TUSHUNISH): yollash hajmini aniqla — kompaniya
  taxminan nechta xodimga ega, oyiga/yiliga nechta yangi xodim olinadi.
  FAQAT BITTA savol. Misol: "Bir oyda kompaniyangizda o'rtacha nechta yangi
  xodim ishga olinadi?"

2-BOSQICH (SARALASH MUAMMOSINI TOPISH): yollashdagi asosiy frictionni top —
  nechta nomzod suhbatga chaqiriladi, qanchasi keyin mos emasligi
  aniqlanadi. YES/NO savol TAQIQLANADI. Misol: "Suhbatga chaqirgan
  nomzodlaringizning qanchasi keyinchalik mos kelmay chiqadi?"

3-BOSQICH (PUL VA VAQTGA AYLANTIRISH — ENG MUHIM): oldingi bosqichlar
  raqamini OLIB, VAQT/PULGA aylantir. Misol (mijoz "50 tadan 30 tasi mos
  kelmaydi" desa): "Demak, oyiga taxminan 30 ta nomzod saralashdan o'tib,
  keyin mos emasligi aniqlanadi. Agar har biriga 30 daqiqa ketsa, bu oyiga
  kamida 15 soat degani. Bu vaqtni asosan HR sarflaydimi yoki rahbar ham
  kiradimi?"

4-BOSQICH (STRATEGIK ZARARNI KO'RSATISH): muammo faqat HR muammosi emas —
  bu vaqt boshqa (savdo, mijozlar, o'sish) ishlarning hisobiga ketayotganini
  ko'rsat. Qo'rqitma, faktni ko'rsat. Misol: "Demak, masala faqat HRning
  vaqtida emas. Agar rahbar ham saralashga vaqt ajratsa, bu vaqt biznesni
  rivojlantirishga ketmayapti. Sizda bu vaqt qaysi ishlar hisobiga
  chiqyapti?"

5-BOSQICH (YECHIMNI VIZUALIZATSIYA — YAKUNIY, mahsulot hali aytilmaydi):
  mijozning O'ZINI O'ZIGA yechim sotishga ko'ndir. Misol: "Agar birinchi
  saralash bosqichida sizga faqat mos nomzodlar yetib kelsa, hozirgi
  vaqtingizni kompaniyaning qaysi yo'nalishiga qaytarardingiz?"
  Bu SENING OXIRGI xabaring — undan keyin suhbat sen tomondan tugaydi.

UMUMIY QOIDALAR:
- HAR BIR XABARDA FAQAT BITTA SAVOL. Bir nechta savolni ("necha kun... va
  necha nomzod... va necha daqiqa...") birga qo'shib yozma.
- RAQAM UYDIRISH QAT'IYAN TAQIQLANADI. Faqat mijoz bergan yoki mijoz bergan
  asosda SHARTLI hisoblangan ("taxminan", "agar ... bo'lsa") raqamlardan
  foydalan.
- Sifatlash TAQIQLANADI: "ajoyib", "mukammal", "kuchli", "innovatsion".
- SO'Z BOYLIGI: "Tushunarli", "Ajoyib", "Zo'r" ISHLATMA — bular yumshoq,
  sotuvchi-ohangli. O'rniga: "Demak", "Qayd etdim", "Faktlar shuni
  ko'rsatmoqdaki..." kabi sovuqqon, tahliliy iboralardan foydalan.
- Tasdiqlash SO'RALMASIN: "Shunday emasmi?", "To'g'rimi?" TAQIQLANADI.
- YES/NO bilan qutulib bo'ladigan savollar minimal darajada bo'lsin.
- Tenglik prinsipi: mijozdan past holatda gapirma. Sen mutaxassissan, u esa
  "qonayotgan bemor" — sen diagnostika qilyapsan. Qat'iy va sovuqqon ohang.
- HECH QACHON TASALLI BERMA: "Tushunaman, bu qiyin" TAQIQLANADI. O'rniga:
  "Raqamlar ko'rsatmoqdaki, vaziyatingiz siz o'ylagandan ham xavfliroq."
- AI mijozni agressiv qo'rqitmaydi — faktni ko'rsatadi, xolos.
- FAQAT o'zbek tilida. Emoji ishlatma.
- Foydalanuvchining o'zi aytgan aniq so'zlar/raqamlarni albatta qaytarib ishlat.

3-BOSQICH UCHUN QO'SHIMCHA GENERATSIYA FORMULALARI (mijoz kutilmagan javob
bersa — masalan muammoni rad etsa yoki noaniq gapirsa — shulardan foydalan):
- FORMULA (Pulni hisoblash): [muammo] + [shu tufayli ketadigan vaqt/pul] +
  [1 yillik ko'lami] + "Buning byudjetga zararini hisoblaganmisiz?"
- FORMULA (Raqobat xavfi): [muammo] + [jarayon sekinlashishi] + [raqobatchi
  bundan foydalanishi] + "Bu sizni xavotirga solmaydimi?"
- FORMULA (Bumerang — mijoz muammoni rad etsa yoki "o'zim hal qilaman"
  desa): [mijozning noto'g'ri ishonchi] + [uni shubha ostiga olish] +
  "Aslida muammo boshqa joyda emasmi?"
"""

_OUTPUT_FORMAT_SUFFIX = """
CHIQISH FORMATI (QAT'IY, BUZILMASIN):
- Javobing 2 dan 4 gachagacha gapdan iborat bo'lsin (Mirror+Diagnose+
  Quantify+Question uchun shuncha kerak bo'lishi mumkin, lekin ORTIQ EMAS).
- Javobingda FAQAT VA FAQAT BITTA so'roq belgisi (?) bo'lishi SHART.
- Ikkita yoki undan ko'p savol berish — TIZIM XATOSI hisoblanadi.
- Hech qanday kirish so'zi, sarlavha yoki izoh qo'shma — faqat xabarning o'zini yoz.
"""

_STEP_INFO = {
    1: ("1-BOSQICH (KOMPANIYANI TUSHUNISH)", "Yollash hajmini aniqlash — nechta xodim, oyiga nechta yangi xodim olinadi."),
    2: ("2-BOSQICH (SARALASH MUAMMOSINI TOPISH)", "Yollashdagi asosiy frictionni topish — nechta nomzod, qanchasi mos kelmaydi."),
    3: ("3-BOSQICH (PUL VA VAQTGA AYLANTIRISH — ENG MUHIM)", "Oldingi raqamlarni vaqt/pulga aylantirib hisoblash."),
    4: ("4-BOSQICH (STRATEGIK ZARARNI KO'RSATISH)", "Bu vaqt boshqa (savdo, o'sish) ishlar hisobiga ketayotganini ko'rsatish."),
    5: ("5-BOSQICH (YECHIMNI VIZUALIZATSIYA — YAKUNIY)", "Mijozning o'zini o'ziga yechim sotishga ko'ndirish, mahsulot hali aytilmaydi."),
}

_BANNED_WORDS = ["Tushunarli", "Ajoyib", "Zo'r", "ajoyib", "mukammal", "kuchli", "innovatsion"]


def _build_system_prompt(current_step: int, retry_note: str = "") -> str:
    """EXPLICIT STATE INJECTION: bosqich raqami VA shu bosqichning aniq
    maqsadi backend tomonidan majburiy ravishda beriladi — AI buni suhbat
    tarixi uzunligidan o'zi taxmin qilmaydi."""
    label, objective = _STEP_INFO.get(current_step, _STEP_INFO[1])
    directive = (
        f"\nDIQQAT: QAT'IY BUYRUQ!\nCURRENT_STAGE = {current_step} ({label})\n"
        f"CURRENT_OBJECTIVE = \"{objective}\"\n"
        f"Vazifang: FAQATGINA shu bosqich maqsadiga xizmat qiladigan, MIRROR->"
        f"DIAGNOSE->QUANTIFY->QUESTION formulasiga mos BITTA javob yozish. "
        f"Boshqa bosqichga o'tish yoki bosqichlarni aralashtirish TAQIQLANADI.\n"
    )
    if retry_note:
        directive += f"\nOGOHLANTIRISH: oldingi urinishing rad etildi — sababi: {retry_note}. Buni albatta tuzat.\n"
    return _BASE_PROMPT + directive + _OUTPUT_FORMAT_SUFFIX


def _validate_response(text: str, current_step: int) -> list[str]:
    """Yengil, mexanik (LLM chaqirmasdan) tekshiruv — javob yuborishdan oldin
    eng oshkora xatolarni ushlaydi. Bo'sh ro'yxat = muammo yo'q."""
    issues = []

    question_marks = text.count("?")
    if question_marks != 1:
        issues.append(f"savol belgisi soni {question_marks} ta (aniq 1 ta bo'lishi kerak)")

    sentence_count = len([s for s in re.split(r"[.!?]+", text) if s.strip()])
    if sentence_count > 4:
        issues.append(f"{sentence_count} ta gap (4 tadan oshmasligi kerak)")

    for banned in _BANNED_WORDS:
        if banned in text:
            issues.append(f"taqiqlangan so'z ishlatilgan: '{banned}'")

    if current_step < 5 and "janob hr" in text.lower():
        issues.append("mahsulot nomi ('Janob HR') hali aytilmasligi kerak edi")

    return issues


async def get_next_message(history: list[dict], current_step: int) -> str | None:
    """`history` — [{"role": "user"/"assistant", "content": "..."}] (system
    kiritilmagan). `current_step` — backend (aiogram FSM) allaqachon bilgan,
    1 dan 5 gacha bo'lgan aniq bosqich raqami (Explicit State Injection).

    Javob yengil, mexanik validatsiyadan o'tkaziladi; muvaffaqiyatsiz bo'lsa
    BIR MARTA, aniq sabab ko'rsatilgan holda qayta so'raladi. Har chaqiruv
    "soya jurnali" sifatida bosqich/kirish/chiqish/kechikish/validatsiya
    natijasini logga yozadi.
    """
    last_user_input = history[-1]["content"] if history else ""

    async def _try_once(note: str) -> tuple[str | None, list[str]]:
        system_prompt = _build_system_prompt(current_step, retry_note=note)
        start = time.monotonic()
        reply = await _call_ai(
            system_prompt=system_prompt, user_prompt="", max_tokens=500,
            extra_messages=history, temperature=0.25,
        )
        latency_ms = round((time.monotonic() - start) * 1000)
        issues = _validate_response(reply, current_step) if reply else ["AI hech qanday javob bermadi"]
        logger.info(
            "[sotuv-ai] bosqich=%s | kechikish=%sms | urinish=%s | kirish=%r | chiqish=%r | muammolar=%s",
            current_step, latency_ms, "qayta" if note else "1-marta",
            last_user_input[:100], (reply or "")[:150], issues or "yo'q",
        )
        return reply, issues

    reply, issues = await _try_once("")
    if reply is None:
        return None

    if issues:
        logger.warning("[sotuv-ai] validatsiya muvaffaqiyatsiz, qayta so'ralmoqda: %s", issues)
        reply2, issues2 = await _try_once("; ".join(issues))
        if reply2 is not None:
            reply = reply2
            if issues2:
                logger.warning("[sotuv-ai] qayta urinishdan keyin ham muammo qoldi (baribir yuboriladi): %s", issues2)

    return reply
