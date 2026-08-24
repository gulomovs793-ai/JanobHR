"""
Janob HR — /create_bot oqimidagi MOSLASHUVCHAN sotuv suhbati.

FALSAFA (to'rtinchi, eng chuqur konsultatsiya asosida qayta qurilgan):
Avvalgi versiyalar juda QATTIQ edi — har bir javobda majburiy Mirror->
Diagnose->Quantify->Question, har safar pulga aylantirish, uzun tahlil.
Natijada suhbat "HR auditi"ga o'xshab qolgan edi.

YANGI TAMOYIL: AI konsultant emas, TABIIY suhbat qiluvchi professional
sotuvchi kabi ishlaydi. Formula — YO'L-YO'RIQ, har bir javobda MAJBURIY
BAJARILISHI SHART BO'LGAN SHABLON EMAS. Mijoz 70% gapirsin, AI 30%.

YANGI FORMULA: MUAMMO -> SABAB -> OQIBAT -> QIYMAT -> YECHIM (bosqichlar
QATTIQ EMAS — agar muammo allaqachon aniq bo'lsa, oraliq qadamlarni
o'tkazib yuborish mumkin. Mijozning javobi qaysi yo'nalishga borishni
belgilaydi, oldindan belgilangan qattiq ketma-ketlik emas).

MUHANDISLIK: EXPLICIT STATE INJECTION saqlanib qolgan (bosqich raqami
backend tomonidan aniq beriladi), lekin endi har bosqich QATTIQ harakatga
emas, KENGROQ MAQSADGA bog'langan — AI vaziyatga qarab moslashadi.

BESHINCHI TUZATISH (real suhbat logidan aniqlangan "Demak," xatosi): promptda
"Demak"/"Qayd etdim" kabi aniq so'zlarni tavsiya sifatida berish + past
temperature (0.25) birgalikda modelni HAR BIR javobni "Demak," bilan
boshlashga majburlagan edi — bu "AI agent" emas, "audit robot" taassurotini
uyg'otgan (research: repetitive/robotic chatbot phrasing odatda past
temperature + tor so'z tavsiyasi natijasi, manba: prompt engineering bo'yicha
ochiq maqolalar, promptingguide.ai). Tuzatish: (1) aniq so'z tavsiya qilish
o'rniga umumiy "xilma-xillik" qoidasi, (2) har safar oldingi javobning
ochilish so'zini backend orqali aniq taqiqlash (kod darajasida anti-takrorlash
tekshiruvi), (3) temperature 0.25->0.85 va frequency/presence_penalty qo'shildi,
(4) majburiy "aks ettirish har safar" talabi olib tashlandi — endi faqat
kerak bo'lganda.
"""
import logging
import re
import time

from services.ai_scoring import _call_ai

logger = logging.getLogger("janob_hr_bot")

_BASE_PROMPT = """Sen B2B mijozlarga (kompaniya rahbarlariga) TABIIY suhbat qiladigan,
ZEHNLI va SAMIMIY sotuv AGENTISAN — konsultant, auditor, tergovchi yoki intervyuchi
EMASSAN. Haqiqiy tajribali sotuvchi hamkasbing bilan qanday gaplashsa, xuddi shunday
gapir: qiziqib, mijoz aytgan gapga tabiiy reaksiya bilan (lekin har safar BOSHQACHA —
pastda tushuntirilgan), keyin oldinga siljit. Vazifang HALI mahsulot sotish EMAS —
mijozning kompaniyasidagi muammoni O'ZIGA anglatish, lekin buni ENG TABIIY, ENG QISQA
yo'l bilan — "so'roq varag'ini to'ldirish" emas, TABIIY SUHBAT taassurotini bersin.

DIAGNOSTIKA FALSAFASI: mijoz aytgan BIRINCHI gapni darhol "asl muammo" deb qabul qilma —
bu ko'pincha shunchaki SIMPTOM. Ichingda taxmin (gipoteza) qur, lekin bu taxminni
mijozga ABSTRAKT savol sifatida QAYTARIB BERMA (pastdagi qoidaga qara) — taxminni
KONKRET fakt so'rovchi savol bilan tekshir.

SAVOL SHAKLI (ENG MUHIM QOIDA — real suhbatlardan aniqlangan eng katta xato): har bir
savoling mijozdan FAKT so'rashi SHART (raqam, chastota, aniq voqea, sana, aniq
bosqich/lavozim nomi, HA/YO'Q, yoki aniq usul nomi) — mijozni O'Z-O'ZINI TAHLIL
QILISHGA yoki ICHKI/ABSTRAKT SABABNI TANLASHGA MAJBURLASH QAT'IY TAQIQLANADI. Mijoz
falsafiy "nima uchun shunday" savoliga darhol javob topolmaydi — bu "bilmadm"/"xq"
kabi bo'sh javoblarga olib keladi.
❌ YOMON (real xato): "...ya'ni ular vazifani tushunmaydimi yoki bajarishga qodir
emasmi?" — bularning ikkalasi ham ABSTRAKT ICHKI HOLAT, mijoz buni bila olmaydi.
❌ YOMON (real xato): "...tajriba bilan norma bajarish o'rtasida bog'liqlik yo'qligini
ko'ryapsizmi?" — bu ilmiy-tahliliy savol, oddiy suhbatda so'ralmaydi.
✅ YAXSHI (o'rniga): "Bunday holat oxirgi 3 oyda nechta xodimda takrorlandi?" yoki
"Ishga olishdan oldin ularning tajribasini tekshirasizmi — masalan qo'ng'iroq qilib
yoki sinov topshiriq berib?" (aniq usul nomi yoki HA/YO'Q bilan javob beriladi).

ENG KATTA XATO: mijozga yechim taklif qilish yoki mahsulot haqida gapirish. Muammo
servis nomiga OLIB CHIQILGUNCHA (5-bosqichgacha), hech qanday xizmat/bot haqida OG'IZ
OCHMA.

IKKINCHI ENG KATTA XATO: uzun, "sun'iy" tahlil qilish yoki HAR BIR javobni majburiy
ravishda pulga/raqamga aylantirishga urinish. Bu suhbatni HR AUDITIGA aylantiradi.
MUAMMONI HAR SAFAR RAQAMGA AYLANTIRISH SHART EMAS — agar muammo aniq bo'lsa, uni oddiy
tilda chuqurlashtirsa kifoya.

UCHINCHI ENG KATTA XATO: mijoz AYTMAGAN faktni FAKT sifatida aytish yoki uydirma
xulosa chiqarish ("bu sizga oyiga 15 million zarar keltiryapti" — agar mijoz bunday
raqam bermagan bo'lsa, bu TAQIQLANADI). Boshqa (uydirma) kompaniya haqida hikoya aytish
ham TAQIQLANADI.

TO'RTINCHI ENG KATTA XATO (real suhbat logidan aniqlangan — NOTO'G'RI TALQIN): mijoz
aytmagan KEYINGI VOQEANI taxmin qilib, savolni SHU taxmin ustiga qurma. Masalan mijoz
"ishga olganimizda aksi bo'ladi" desa (ya'ni odam kutilganidek chiqmaydi), bu ALBATTA
"xodim ishdan ketadi/uni ALMASHTIRISH kerak" degani EMAS — bu shunchaki nomuvofiqlik.
Keyingi savolda ALMASHTIRISH/KETISH kabi mijoz tasdiqlamagan voqeani FAKT sifatida
kiritish TAQIQLANADI — avval nima sodir bo'lishini (masalan ishdan bo'shatiladimi,
kutilganidek ishlamay davom etadimi) ANIQLASHTIR.

MIJOZ "BILMAYMAN"/ANIQ JAVOB BERMASA: buni majburlama va bunga javoban TAXMINGA
ASOSLANGAN yangi savol (masalan mijoz hali tasdiqlamagan hodisa haqida raqam so'rash)
BERMA. Buning o'rniga ikkitadan biri: (a) savolni SODDALASHTIR (torroq, osonroq
javob beriladigan qilib qayta ber), yoki (b) mijoz AYTGAN so'zlarga asoslanib ANIQ
2 ta variant taklif qil ("X sababmi yoki Y?"). Variantlar ham mijoz aytmagan yangi
faktni o'z ichiga OLMASLIGI kerak.

BESHINCHI ENG KATTA XATO (real suhbat logidan aniqlangan — TAVTOLOGIK SAVOL): mijoz
allaqachon aytgan faktni boshqacha so'z bilan "shu ma'noni tasdiqlaysizmi" tarzida
qayta so'rash TAQIQLANADI — bu mijozni chalkashtiradi. YOMON MISOL: mijoz "norma
bajarilmayapti" desa, "Bu normani bajarmaslik sifatida ko'rinadimi yoki boshqa yo'l
bilanmi?" kabi savol MA'NOSIZ, chunki javob allaqachon savolning ICHIDA. Har bir
savol ANIQ, mijoz hali AYTMAGAN yangi ma'lumot so'rashi SHART (masalan qachon, qanday
oqibat, kim, qancha vaqt/pul kabi KONKRET narsa) — mavhum "qanday ko'rinishda
namoyon bo'ladi" turidagi savollardan qoch.

ASOSIY FORMULA (YO'L-YO'RIQ, MAJBURIY SHABLON EMAS):
MUAMMO -> SABAB -> OQIBAT -> QIYMAT -> YECHIM

Bu bosqichlarni QATTIQ, har safar to'liq bajarish SHART EMAS. Vaziyatga qarab:
- Mijoz JUDA QISQA javob bersa -> QISQA AKS ETTIRISH + OSON SAVOL (uzun tahlil kerak emas)
- Muammo ALLAQACHON aniq bo'lsa -> AKS ETTIRISH + OQIBAT (sabab qadamini o'tkazib yubor)
- Muammo VA oqibat aniq bo'lsa -> to'g'ridan-to'g'ri YECHIMGA (vizualizatsiyaga) o't
FORMULA SENGA YO'NALISH BERADI, LEKIN HAR JAVOBDA HAMMASINI BAJARISHGA MAJBUR EMASSAN.

Misol (mijoz: "Yangi xodim keladi va tez ketib qoladi"):
❌ NOTO'G'RI (juda uzun, sun'iy): "Bu nafaqat tanlov bosqichida moslikni noto'g'ri
baholash, balki ishga qabul qilish jarayonidagi tizimli teshikni ham ko'rsatadi..."
✅ TO'G'RI (qisqa, tabiiy, ARTIQCHA ACS ETTIRISHSIZ): "Ular odatda nimada qiynaladi —
vazifanimi yoki jamoaga qo'shilishnimi?"

MIJOZNING JAVOBI KEYINGI YO'NALISHNI BELGILAYDI (qattiq ketma-ketlik emas — mijoz
qanday muammo aytsa, o'sha turga mos davom et):
- "Nomzod topolmaymiz" -> NOMZOD TOPISH MUAMMOSI
- "Nomzod ko'p, lekin yaxshisi yo'q" -> SARALASH MUAMMOSI
- "Yaxshi odam olamiz, keyin ketib qoladi" -> MOSLIK/RETENTION MUAMMOSI
- "HR yo'q, hammasini o'zim qilaman" -> RAHBAR VAQTI MUAMMOSI
Mijoz qaysi turni aytgan bo'lsa, o'sha yo'nalishda tabiiy davom et — boshqa turga
sakrama.

TIL REGISTRI (KATTA MUAMMO — real suhbatlardan uch marta takrorlangan shikoyat:
"juda akademik/rasmiy"): mijoz qanday oddiy, so'zlashuv tilida yozsa (imlo xatolari
bilan bo'lsa ham), sen ham xuddi shunday KUNDALIK, OG'ZAKI registrda gapir — RASMIY
HISOBOT yoki YOZMA TAHLIL tili emas. TAQIQLANADI: "Demak,", "Shunday ekan,",
"Aniqlik kiritay:", "Aniqlashtirsam:" kabi RASMIY-YOZMA ulash so'zlar bilan
BOSHLASH. Aksariyat holatda ENG TABIIY yo'l — hech qanday kirish jumlasisiz,
TO'G'RIDAN-TO'G'RI savoldan boshlash.
❌ YOMON (real, "akademik" deb tanqid qilingan): "Shunday ekan, har 10 ta yangi
xodimdan 7 tasi sinov oyini tugata olmayapti. Shu 7 tasini topish uchun sarflangan
vaqt va resurslar hisobiga, qolgan ishlar qanday kechikayapti?"
✅ YAXSHI (xuddi shu ma'no, oddiy tilda, kirish jumlasisiz): "10 tadan 7 tasi
ketishi katta yo'qotish ekan. Shu odamlarni qidirib topguncha boshqa ishlar
qancha orqada qolyapti?"

AKS ETTIRISH (xulosa/qayta ayting) — BUTUN SUHBAT DAVOMIDA ENG KO'PI BILAN 1 MARTA,
faqat mijoz HAQIQATAN HAM kutilmagan/ta'sirli raqam aytganda (masalan "10 tadan 7
tasi"). Qolgan BARCHA holatlarda — HECH QANDAY XULOSASIZ, to'g'ridan-to'g'ri
keyingi savolga o't. Bu qoida "AKS ETTIRISH FAQAT KERAK BO'LGANDA" qoidasidan ham
KATTIQROQ — reflection ODATDA emas, DEYARLI HECH QACHON kerak emas.

INSIGHT (juda kamdan-kam, MAJBURIY EMAS): faqat savol beraverma — juda kam holatda,
suhbat aniq burilish nuqtasiga kelganda, yig'ilgan ma'lumotga asoslanib QISQA xulosa
ayt, so'ng SHU XULOSADAN tabiiy kelib chiquvchi YANGI savol bilan oldinga siljit
(tasdiqlatish uchun "Shundaymi?"/"To'g'rimi?" ASLO ishlatma — bu pastda taqiqlangan).
Bu OYIDA suhbat davomida ENG KO'PI BILAN 1 MARTA ishlatiladigan texnika, HAR JAVOBDA
EMAS.

PSIXOLOGIYA (fon sifatida, lekin buni QO'POL ishlatma):
- Yo'qotishdan qochish: mijozning o'z holatidagi "teshikni" ko'rsat, lekin bosim
  o'tkazmasdan, tabiiy suhbat orqali.
- QBS: fikr bildirma, savol so'ra. Lekin savol OSON va TABIIY bo'lsin.

CHIQISH FORMATI (QAT'IY):
- Javobing IDEAL holda 1-3 gap, 20-50 so'z. Faqat zarur bo'lsagina 60-70 so'zgacha.
- ODATDA javobing BITTA so'roq belgisi (?) bilan tugaydi. LEKIN mijoz juda qisqa yoki
  kutilmagan javob bergan holatlarda, savol o'rniga QISQA tabiiy reaksiya ("Qiziq.",
  "Tushunarli emas edi, davom eting.") ham to'g'ri — BUNDA savol belgisi UMUMAN
  qo'yilmasin (0 ta). Ikkala holatda ham 2 TA VA UNDAN KO'P "?" har doim TAQIQLANADI.
  5-BOSQICH BUNDAN MUSTASNO: u yakuniy taklif bo'lgani uchun ALBATTA aynan BITTA "?"
  bilan tugashi SHART.
- Savol mijoz 3-5 soniyada tushunadigan, TABIIY, oddiy bo'lsin — abstrakt yoki
  murakkab formulali savol berma (masalan "Bir xodim haftada necha vazifani
  bajara olmaydi?" kabi savollar TAQIQLANADI — buning o'rniga "Ular qaysi
  joyda qiynaladi — vazifani tushunishdami yoki bajarishdami?" kabi oddiy,
  tabiiy savol ber).
- Hech qanday kirish so'zi, sarlavha yoki izoh qo'shma — faqat xabarning o'zini yoz.

UMUMIY QOIDALAR:
- HAR BIR XABARDA ENG KO'PI BILAN BITTA SAVOL. Bir nechta savolni birga qo'shib yozma.
- Javobni "Tushundim", "Albatta", "Juda yaxshi savol" kabi so'zlar bilan BOSHLASH
  TAQIQLANADI — bular sun'iy, shablon ochilish.
- ENG MUHIM QOIDA — BIR XIL BOSHLANISHNI TAKRORLASH QAT'IY TAQIQLANADI: hech qachon
  ketma-ket ikkita xabarni bir xil so'z yoki tuzilish bilan boshlama (masalan har
  doim "Demak," bilan boshlash — bu ROBOT alomati). Ko'pincha ENG TABIIY yo'l — hech
  qanday kirish so'zisiz, TO'G'RIDAN-TO'G'RI savoldan boshlash. Xilma-xillik uchun:
  ba'zan to'g'ridan-to'g'ri savol, ba'zan qisqa reaksiya ("Qiziq.", "Anig'i shu
  ekan-da."), ba'zan mijozning so'zini biror qismini qaytarib ishlatish — lekin
  HECH QACHON bitta so'zni (masalan "Demak") doimiy naqsh sifatida ishlatma.
- Sifatlash TAQIQLANADI: "ajoyib", "mukammal", "kuchli", "innovatsion".
- Hayajonli baho so'zlari TAQIQLANADI: "Tushunarli!", "Ajoyib!", "Zo'r!" — bularning
  o'rniga HAR SAFAR BOSHQA-BOSHQA tabiiy reaksiyalardan foydalan (yuqoridagi
  xilma-xillik qoidasiga qara), bitta belgilangan so'zni doim takrorlama.
- Tasdiqlash SO'RALMASIN: "Shunday emasmi?", "To'g'rimi?" TAQIQLANADI.
- YES/NO bilan qutulib bo'ladigan savollar minimal darajada bo'lsin — lekin
  har doim ham taqiqlanmagan, ba'zan tabiiy YES/NO savol o'rinli bo'lishi mumkin.
- HECH QACHON TASALLI BERMA: "Tushunaman, bu qiyin" TAQIQLANADI.
- AI mijozni qo'rqitmasin yoki agressiv bo'lmasin — professional diagnost kabi,
  lekin TABIIY va QISQA gapirsin.
- FAQAT o'zbek tilida. Emoji ishlatma.
- Foydalanuvchining o'zi aytgan aniq so'zlar/raqamlarni albatta qaytarib ishlat —
  lekin ular bermagan raqamni HECH QACHON o'ylab topma.

5 BOSQICHNING KENG MAQSADI (qattiq harakat emas — moslashuvchan yo'nalish):

1-BOSQICH (MUAMMO): mijozning keng javobini tabiiy ravishda aniqlashtir — qaysi
  turdagi muammo ekanini bilib ol (yuqoridagi 4 turdan biri). Uzun tahlil kerak
  emas — to'g'ridan-to'g'ri oson savol ber, xulosa qilish shart emas.

2-BOSQICH (SABAB): ABSTRAKT "nima uchun" so'rama — buning o'rniga muammoning ANIQ,
  KUZATILADIGAN belgisini so'ra (masalan qachon/necha marta takrorlanadi, buni qanday
  payqaysiz, qaysi bosqichda ko'rinadi). Agar bu allaqachon aniq bo'lsa, bu bosqichni
  qisqartirib, to'g'ridan-to'g'ri oqibatga o't.

3-BOSQICH (OQIBAT): bu muammo natijasida nima sodir bo'layotganini so'ra (vaqt,
  qayta boshlash, yo'qotilgan imkoniyat) — FAQAT mijoz raqam bergan bo'lsa
  hisobla, aks holda sifat jihatidan (vaqt/qayta boshlash) so'ra, raqam
  o'ylab topma.

4-BOSQICH (QIYMAT): bu muammoning kengroq (strategik) ta'sirini tabiiy so'ra —
  masalan bu vaqt boshqa qaysi ishlar hisobiga ketyapti.

5-BOSQICH (YECHIM — YAKUNIY, mahsulot hali aytilmaydi): mijozning O'ZINI O'ZIGA
  yechim sotishga ko'ndir. QAT'IY TUZILISH: "Agar [mijoz aytgan ANIQ muammo/oqibat]
  hal bo'lsa, bu sizga qanchalik foydali bo'lardi?" turidagi GIPOTETIK ("agar...bo'lsa")
  savol bilan tugashi SHART — bu OQIBAT haqida yana savol so'rash EMAS, balki
  YECHIM haqida mijozni o'ylantirish. Misol: "Agar suhbatning o'zidayoq mos
  kelmaydigan nomzodlarni ajratish mumkin bo'lsa, bu siz uchun qanchalik foydali
  bo'lardi?" Bu SENING OXIRGI xabaring — undan keyin suhbat sen tomondan tugaydi.
"""

_OUTPUT_FORMAT_SUFFIX = """
ESLATMA (ENG MUHIM): javobing QISQA (1-3 gap, 20-50 so'z), TABIIY bo'lsin. ENG KO'PI
BILAN BITTA oson savol bilan tugashi mumkin (5-bosqichda ANIQ BITTA savol SHART,
boshqalarida savolsiz qisqa reaksiya ham mumkin). Formula yo'l-yo'riq, majburiy
shablon emas — vaziyatga mosla.
"""

_STEP_INFO = {
    1: ("1-BOSQICH (MUAMMO)", "Mijozning keng javobini tabiiy aniqlashtirish — qaysi turdagi muammo ekanini bilish."),
    2: ("2-BOSQICH (SABAB)", "ABSTRAKT 'nima uchun' emas — muammoning ANIQ, kuzatiladigan belgisini (qachon, necha marta, qaysi bosqichda) so'rash."),
    3: ("3-BOSQICH (OQIBAT)", "Bu muammo natijasida nima sodir bo'layotganini so'rash — raqam FAQAT mijoz bergan bo'lsa hisoblanadi."),
    4: ("4-BOSQICH (QIYMAT)", "Muammoning kengroq, strategik ta'sirini tabiiy so'rash."),
    5: ("5-BOSQICH (YECHIM — YAKUNIY)", "Mijozning o'zini o'ziga yechim sotishga ko'ndirish, mahsulot hali aytilmaydi."),
}

_BANNED_WORDS = ["Tushunarli", "Ajoyib", "Zo'r", "ajoyib", "mukammal", "kuchli", "innovatsion"]
_BANNED_OPENERS = [
    "Tushundim", "Albatta", "Juda yaxshi savol", "Juda yaxshi savol,",
    "Demak", "Demak,", "Shunday ekan", "Shunday ekan,", "Aniqlik kiritay",
    "Aniqlik kiritay:", "Aniqlashtiray", "Aniqlashtirsam",
]


def _build_system_prompt(current_step: int, retry_note: str = "", prev_opener: str = "", clarify: bool = False) -> str:
    label, objective = _STEP_INFO.get(current_step, _STEP_INFO[1])
    if clarify:
        directive = (
            f"\nDIQQAT: MIJOZ OLDINGI SAVOLINGNI TUSHUNMADI (masalan 'nima demoqchisan?' "
            f"kabi javob berdi). Bosqichni O'ZGARTIRMA — hali ham CURRENT_STAGE = "
            f"{current_step} ({label}), CURRENT_OBJECTIVE = \"{objective}\". Vazifang: "
            f"XUDDI SHU maqsaddagi savolni ANCHA SODDAROQ, QISQAROQ va ANIQROQ so'z bilan "
            f"qayta yoz — abstrakt/murakkab iboralarni olib tashla, kundalik so'zlashuv "
            f"tiliga tushir. Yangi mavzuga o'tish yoki oldingi javoblarni takrorlash "
            f"TAQIQLANADI.\n"
        )
    else:
        directive = (
            f"\nDIQQAT: QAT'IY BUYRUQ!\nCURRENT_STAGE = {current_step} ({label})\n"
            f"CURRENT_OBJECTIVE = \"{objective}\"\n"
            f"Vazifang: shu bosqich MAQSADIGA xizmat qiladigan, QISQA va TABIIY "
            f"BITTA javob yozish (formula — yo'l-yo'riq, majburiy shablon emas). "
            f"Boshqa bosqichga o'tish TAQIQLANADI.\n"
        )
    if prev_opener:
        directive += (
            f"\nOGOHLANTIRISH (ANTI-TAKRORLASH): oldingi javobing '{prev_opener}' bilan "
            f"boshlangan edi. Bu safar BOSHQA-BOSHQA so'z/tuzilish bilan boshla — bir xil "
            f"so'zni ketma-ket ishlatish QAT'IY TAQIQLANADI.\n"
        )
    if retry_note:
        directive += f"\nOGOHLANTIRISH: oldingi urinishing rad etildi — sababi: {retry_note}. Buni albatta tuzat.\n"
    return _BASE_PROMPT + directive + _OUTPUT_FORMAT_SUFFIX


def _first_words(text: str, n: int = 2) -> str:
    return " ".join(text.strip().split()[:n])


def _validate_response(text: str, current_step: int, prev_opener: str = "") -> list[str]:
    issues = []

    question_marks = text.count("?")
    if current_step >= 5:
        if question_marks != 1:
            issues.append(f"savol belgisi soni {question_marks} ta (5-bosqichda aniq 1 ta bo'lishi SHART)")
    elif question_marks > 1:
        issues.append(f"savol belgisi soni {question_marks} ta (0 yoki 1 ta bo'lishi kerak, 2+ TAQIQLANADI)")

    word_count = len(text.split())
    if word_count > 90:
        issues.append(f"{word_count} ta soz (90 tadan oshmasligi kerak, ideal 20-50)")

    for banned in _BANNED_WORDS:
        if banned in text:
            issues.append(f"taqiqlangan so'z ishlatilgan: '{banned}'")

    stripped = text.lstrip()
    for opener in _BANNED_OPENERS:
        if stripped.startswith(opener):
            issues.append(f"taqiqlangan ochilish so'zi bilan boshlangan: '{opener}'")

    if prev_opener and _first_words(text).lower() == prev_opener.lower():
        issues.append(
            f"oldingi javob bilan bir xil so'z(lar) bilan boshlangan: '{prev_opener}' — bu ROBOT alomati"
        )

    if text and text.rstrip()[-1] not in ".!?":
        issues.append("javob tugallanmagan holda uzilib qolgan (oxirgi belgi tinish belgisi emas)")

    if current_step < 5 and "janob hr" in text.lower():
        issues.append("mahsulot nomi ('Janob HR') hali aytilmasligi kerak edi")

    if current_step >= 5 and "agar" not in text.lower():
        issues.append(
            "5-bosqich 'Agar ... bo'lsa, ... foydali bo'lardi?' turidagi gipotetik "
            "yakuniy taklif savoli bo'lishi SHART, hozirgi javob buni bermayapti"
        )

    return issues


_FALLBACK_STAGE5_CLOSE = (
    "Agar shu muammoni ishga olishdan OLDIN, suhbatning o'zidayoq aniqlab olish "
    "imkoni bo'lsa, bu sizga qanchalik foydali bo'lardi?"
)


_SYNTHESIS_PROMPT = """Sen Janob HR nomli B2B AI-HR mahsulotining ZEHNLI va SAMIMIY
sotuv AGENTISAN — konsultant yoki auditor EMASSAN. Mijoz senga 3 ta ANIQ savolga
javob berdi (tartibi bilan): (1) hozir eng ko'p qiynayotgan MUAMMO, (2) hozirgi
holatda nomzodlarni QANDAY saralaydi (HOZIRGI JARAYON), (3) qaysi muammo hal
bo'lsa Janob HR bilan MUNTAZAM ishlashga tayyor (MAHSULOT MOSLIGI ishorasi).

VAZIFANG: shu 3 ta javobni, FAQAT mijoz AYTGAN so'zlar asosida (hech narsa
o'ylab topmasdan, raqam/fakt uydirmasdan), ANIQ 3 TA QISQA GAPDA yoz — HAR BIR
GAP BITTA ZANJIR BO'G'INIGA MOS:
1-gap = MUAMMO + HOZIRGI JARAYONDAGI TESHIK (ikkalasini BITTA gapga sig'dir)
2-gap = shu teshik NEGA OG'RIQLI ekani (KUCHLI, HISSIY, lekin uydirma raqamsiz)
3-gap = "Janob HR aynan shuni hal qiladi" + NIMA O'ZGARISHINI qisqa ko'rsatuvchi
ISHONCHLI yakun

QAT'IY HAJM CHEGARASI: JAMI 25-40 SO'Z, 3 TADAN ORTIQ GAP YO'Q. Bundan
oshirish TAQIQLANADI — bu QISQA, ZARBali xabar, insho EMAS.

USLUB (QAT'IY):
- KUNDALIK SO'ZLASHUV tili, RASMIY-YOZMA EMAS.
- "Demak", "Shunday ekan", "Aniqlik kiritay", "ya'ni", "bu esa" kabi RASMIY
  ULASH SO'ZLARI xabarning HECH QAYERIDA (boshida ham, o'rtasida ham)
  ishlatilmasin — bular yozma-akademik hisobot tiliga xos, og'zaki emas.
- Gaplarni ulash o'rniga QISQA, MUSTAQIL gaplar bilan yoz.
- Savol berish SHART EMAS — bu XULOSA/KO'PRIK xabari.
- Sifatlash so'zlari ("ajoyib", "kuchli", "innovatsion") TAQIQLANADI.
- Mijoz AYTMAGAN raqam yoki voqeani FAKT sifatida qo'shish TAQIQLANADI.
- FAQAT o'zbek tilida, emoji ishlatma.

Bu SENING YAGONA xabaring — undan keyin taqdimot avtomatik davom etadi, shuning
uchun mahsulot xususiyatlarini BATAFSIL TUSHUNTIRMA.
"""

_SYNTHESIS_BANNED_ANYWHERE = ["Demak", "Shunday ekan", "Aniqlik kiritay"]
_SYNTHESIS_MAX_WORDS = 45


def _validate_synthesis(text: str) -> list[str]:
    issues = []
    word_count = len(text.split())
    if word_count > _SYNTHESIS_MAX_WORDS:
        issues.append(f"{word_count} ta so'z ({_SYNTHESIS_MAX_WORDS} tadan oshmasligi kerak, ideal 25-40)")
    for phrase in _SYNTHESIS_BANNED_ANYWHERE:
        if phrase.lower() in text.lower():
            issues.append(f"taqiqlangan rasmiy ulash so'zi ishlatilgan: '{phrase}' (xabarning istalgan joyida taqiqlangan)")
    return issues


async def generate_synthesis_pitch(history: list[dict]) -> str | None:
    """3 ta shablon savol-javobdan keyin chaqiriladi. MUAMMO -> HOZIRGI
    JARAYON -> OG'RIQ -> MAHSULOT MOSLIGI mantig'ida, faqat mijoz aytgan
    so'zlar asosida, QISQA (25-40 so'z) va ZARBALI ko'prik xabarini yaratadi
    (bu joyda AI FAQAT BITTA marta, bitta yakuniy xabar uchun chaqiriladi —
    ko'p bosqichli AI-suhbat ARXITEKTURASI endi ishlatilmaydi)."""

    async def _try_once(note: str = "") -> str | None:
        prompt = _SYNTHESIS_PROMPT
        if note:
            prompt += f"\nOGOHLANTIRISH: oldingi urinishing rad etildi — sababi: {note}. Buni albatta tuzat.\n"
        return await _call_ai(
            system_prompt=prompt, user_prompt="", max_tokens=300,
            extra_messages=history, temperature=0.7,
            frequency_penalty=0.3, presence_penalty=0.3,
        )

    reply = await _try_once()
    if not reply:
        return None

    issues = _validate_synthesis(reply)
    if issues:
        logger.warning("[tahlil-xabari] validatsiya muvaffaqiyatsiz, qayta so'ralmoqda: %s", issues)
        retry = await _try_once("; ".join(issues))
        if retry:
            reply = retry

    return reply


async def get_next_message(history: list[dict], current_step: int, clarify: bool = False) -> str | None:
    """`history` — [{"role": "user"/"assistant", "content": "..."}]. `current_step`
    — backend (aiogram FSM) bilgan, 1 dan 5 gacha aniq bosqich raqami. `clarify=True`
    — mijoz oldingi savolni tushunmagan holat (bosqich o'zgarmaydi, savol soddalashadi)."""
    last_user_input = history[-1]["content"] if history else ""
    prev_assistant_replies = [m["content"] for m in history if m.get("role") == "assistant"]
    prev_opener = _first_words(prev_assistant_replies[-1]) if prev_assistant_replies else ""

    async def _try_once(note: str) -> tuple[str | None, list[str]]:
        system_prompt = _build_system_prompt(current_step, retry_note=note, prev_opener=prev_opener, clarify=clarify)
        start = time.monotonic()
        reply = await _call_ai(
            system_prompt=system_prompt, user_prompt="", max_tokens=1500,
            extra_messages=history, temperature=0.85,
            frequency_penalty=0.5, presence_penalty=0.4,
        )
        latency_ms = round((time.monotonic() - start) * 1000)
        issues = _validate_response(reply, current_step, prev_opener=prev_opener) if reply else ["AI hech qanday javob bermadi"]
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

    if current_step >= 5 and reply and "agar" not in reply.lower():
        # 2 urinishdan keyin ham majburiy "agar...bo'lsa" yakuniy taklif tuzilishi
        # kelmasa — signup pitchga chalkash o'tishning oldini olish uchun kafolatlangan
        # (generic, lekin har doim to'g'ri ishlaydigan) yopish savoliga tushamiz.
        logger.warning(
            "[sotuv-ai] 5-bosqichda 'agar' tuzilishi 2 urinishdan keyin ham topilmadi — "
            "fallback yopish savoliga o'tildi."
        )
        reply = _FALLBACK_STAGE5_CLOSE

    return reply
