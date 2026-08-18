"""
Vakansiyalar konfiguratsiyasi.
Yangi vakansiya qo'shish uchun shunchaki quyidagi lug'atga yangi kalit qo'shing —
kod boshqa joyda o'zgarmaydi (to'liq dinamik tizim).

Har bir savol obyekti:
    key          -> ma'lumotlar bazasida saqlanadigan maydon nomi
    text         -> nomzodga yuboriladigan savol matni
    hard_filter  -> (ixtiyoriy) True bo'lsa va javob "salbiy" so'zlardan iborat bo'lsa,
                     nomzod avtomatik rad etiladi (masalan "yo'q", "yo'q hali" va h.k.)
    ai_score     -> (ixtiyoriy) True bo'lsa, bu javob AI orqali baholanadi (scoring)
"""

NEGATIVE_WORDS = {
    "yo'q", "yoq", "yo'q.", "yo'q,", "hali yo'q", "yoq hali",
    "hech qachon", "bilmayman", "nет", "не", "нет", "no",
}


def is_negative_answer(text: str) -> bool:
    """Hard-filter uchun: javob "yo'q" ma'nosidagi qisqa inkor bo'lsa True qaytaradi."""
    normalized = text.strip().lower().replace("’", "'").replace("ʼ", "'")
    # Juda uzun javoblarni (masalan "yo'q, lekin ko'p narsani bilaman...") inkor deb hisoblamaymiz
    if len(normalized) > 25:
        return False
    return normalized in NEGATIVE_WORDS


# --- Topgrading: "Haqiqat zardobi" savoli ---
# Barcha vakansiyalarga oxirida avtomatik qo'shiladigan umumiy savol. Bu yerda maqsad
# oddiy — noloyiq nomzodlar bu savoldan cho'chib botni tark etadi (o'z-o'zini filtrlaydi),
# haqiqiy professionallar esa xotirjam va aniq javob beradi. AI javobning ishonchliligini
# (aniq ism/raqam bor-yo'qligi, ishonch darajasi) baholaydi.
REFERENCE_CHECK_QUESTION = {
    "key": "reference_check",
    "text": (
        "So'nggi savol. Sizning tajribangiz bizga juda yoqdi. 👏\n\n"
        "Keyingi bosqichda biz oldingi rahbaringizga qo'ng'iroq qilishimiz mumkin. "
        "Agar hozir undan siz haqingizda so'rasak, u sizni 10 balldan nechchiga baholaydi "
        "va nima uchun? (Iltimos, imkon qadar aniq va rostgo'y javob bering.)"
    ),
    "ai_score": True,
}


def get_questions(vacancy_key: str) -> list[dict]:
    """Berilgan vakansiyaning savollarini, oxiriga Topgrading savoli qo'shilgan holda qaytaradi."""
    base_questions = VACANCIES[vacancy_key]["questions"]
    return [*base_questions, REFERENCE_CHECK_QUESTION]


VACANCIES = {
    "sales": {
        "title": "🧑‍💼 Sotuv menejeri",
        "reject_message": (
            "Anketangiz uchun rahmat! Hozircha ushbu tajriba talablarimizga to'liq mos "
            "kelmayapti, shu sababli ushbu bosqichda davom eta olmaymiz. "
            "Boshqa vakansiyalarimizni kuzatib boring — omad tilaymiz! 🙏"
        ),
        "questions": [
            {
                "key": "experience",
                "text": "Oldin sotuv sohasida ishlaganmisiz? (Ha/Yo'q)",
                "hard_filter": True,
            },
            {
                "key": "experience_details",
                "text": "Qayerda va qancha muddat sotuv qilgansiz? Qisqacha yozing.",
            },
            {
                "key": "crm",
                "text": "Qanday CRM tizimlarida ishlagansiz? (Bitrix24, amoCRM va h.k.)",
            },
            {
                # Scorecard: kelajakdagi vazifa aniq raqamda beriladi — "tajribam bor"
                # kabi umumiy javob emas, konkret reja so'raladi.
                "key": "scorecard_plan",
                "text": (
                    "Bizning kompaniya keyingi chorakda sotuvni kamida $20,000 ga "
                    "oshirishi kerak. Ishga kelganingizdan keyin birinchi 30 kun ichida "
                    "bunga qanday hissa qo'shasiz? Aniq rejangizni 3 ta qadamda yozing."
                ),
                "ai_score": True,
            },
            {
                # Behavioral: A-Player "Men" tilida va aniq raqam bilan gapiradi.
                "key": "achievement",
                "text": (
                    "Oldingi ish joyingizda erishgan eng katta va aniq yutug'ingizni "
                    "yozing (iloji bo'lsa, raqamlar bilan)."
                ),
                "ai_score": True,
            },
            {
                # Behavioral: "intellektual kamtarlik" — xatoni tan olish va undan
                # o'rganish qobiliyatini o'lchaydi.
                "key": "mistake_lesson",
                "text": (
                    "Ishingizda yo'l qo'ygan eng jiddiy xatoyingiz nima bo'lgan va "
                    "undan qanday dars oldingiz?"
                ),
                "ai_score": True,
            },
            {
                "key": "hard_client",
                "text": "Qiyin mijoz bilan qanday ishlaysiz? Bitta real holatni yozib bering.",
                "ai_score": True,
            },
            {
                # "Men/Biz" balansini alohida tekshiruvchi savol.
                "key": "teamwork",
                "text": "Jamoada ishlash tajribangizni bitta real misol bilan tushuntiring.",
                "ai_score": True,
            },
            {
                "key": "motivation",
                "text": "Nega aynan bizning kompaniyada ishlashni xohlaysiz?",
                "ai_score": True,
            },
            {
                "key": "salary_expectation",
                "text": "Kutayotgan oylik maoshingiz qancha? (taxminiy raqamda yozing)",
            },
        ],
        "resume_required": False,
    },
    "designer": {
        "title": "🎨 Dizayner",
        "reject_message": (
            "Anketangiz uchun rahmat! Hozircha tajribangiz talablarimizga mos kelmayapti. "
            "Portfolioingizni boyitib, keyinroq qayta murojaat qilishingiz mumkin. Omad! 🙏"
        ),
        "questions": [
            {
                "key": "tool",
                "text": "Figma yoki Adobe (Photoshop/Illustrator) dasturlaridan qaysi birida ishlaysiz?",
            },
            {
                "key": "portfolio",
                "text": "Portfolio (ishlaringiz namunasi) linkini yuboring.",
                "hard_filter": True,
            },
            {
                # Scorecard: o'lchanadigan chiqish hajmi + sifat nazorati bo'yicha reja.
                "key": "scorecard_output",
                "text": (
                    "Bizning brend uchun ijtimoiy tarmoqlarda oyiga kamida 20 ta post "
                    "dizayni tayyorlashingiz kerak bo'ladi. Birinchi haftada ishni "
                    "qanday tashkil qilasiz va sifatni qanday ta'minlaysiz?"
                ),
                "ai_score": True,
            },
            {
                "key": "achievement",
                "text": (
                    "Eng faxrlanadigan loyihangizni tasvirlab bering — u qanday aniq "
                    "natija (masalan, mijoz sotuvi, engagement o'sishi) keltirdi?"
                ),
                "ai_score": True,
            },
            {
                "key": "mistake_lesson",
                "text": "Dizaynda yo'l qo'ygan eng jiddiy xatoyingiz nima bo'lgan va undan qanday dars oldingiz?",
                "ai_score": True,
            },
            {
                "key": "style",
                "text": "Sizga qaysi dizayn yo'nalishi (uslub) yaqinroq va nega?",
                "ai_score": True,
            },
            {
                "key": "deadline_handling",
                "text": (
                    "Bir vaqtning o'zida bir nechta muhim topshiriq kelib qolsa, "
                    "ularni qanday tartibga solasiz?"
                ),
                "ai_score": True,
            },
            {
                "key": "feedback_handling",
                "text": "Mijoz yoki rahbar ishingizni qattiq tanqid qilsa, munosabatingiz qanday bo'ladi?",
                "ai_score": True,
            },
            {
                "key": "salary_expectation",
                "text": "Kutayotgan oylik maoshingiz qancha? (taxminiy raqamda yozing)",
            },
        ],
        "resume_required": True,
    },
    "smm": {
        "title": "📱 SMM mutaxassis",
        "reject_message": (
            "Anketangiz uchun rahmat! Hozircha tajribangiz talablarimizga mos kelmayapti. "
            "Boshqa vakansiyalarimizni kuzatib boring — omad tilaymiz! 🙏"
        ),
        "questions": [
            {
                "key": "platforms",
                "text": "Qaysi platformalarda (Instagram, Telegram, TikTok) tajribangiz bor?",
            },
            {
                "key": "content_plan",
                "text": "Kontent-reja tuzish tajribangiz bormi? (Ha/Yo'q)",
                "hard_filter": True,
            },
            {
                # Scorecard: aniq o'sish maqsadi + amalga oshirish rejasi.
                "key": "scorecard_growth",
                "text": (
                    "Bizning Instagram sahifamizni 3 oy ichida kamida 5,000 ta yangi "
                    "obunachiga olib chiqishingiz kerak. Buni qanday aniq qadamlar "
                    "bilan amalga oshirasiz?"
                ),
                "ai_score": True,
            },
            {
                "key": "cases",
                "text": (
                    "Oldingi ishlaringizdan eng yaxshi natija bergan case'ni raqamlar "
                    "bilan yozib bering (masalan: \"Reels 100,000 ko'rishga yetdi\")."
                ),
                "ai_score": True,
            },
            {
                "key": "mistake_lesson",
                "text": "SMMda qilgan eng katta xatoyingiz nima edi va undan qanday xulosa chiqardingiz?",
                "ai_score": True,
            },
            {
                "key": "trend_reaction",
                "text": (
                    "Ijtimoiy tarmoqlarda tez o'zgaruvchi trendlarga qanday moslashasiz? "
                    "Oxirgi kuzatgan va ishlatgan trendingizni ayting."
                ),
                "ai_score": True,
            },
            {
                "key": "crisis_management",
                "text": (
                    "Agar brend haqida salbiy komment yoki kichik inqiroziy vaziyat "
                    "yuzaga kelsa, birinchi qadamingiz nima bo'ladi?"
                ),
                "ai_score": True,
            },
            {
                "key": "tools",
                "text": "Qanday dizayn/analitika vositalaridan (Canva, Meta Business Suite va h.k.) foydalanasiz?",
            },
            {
                "key": "salary_expectation",
                "text": "Kutayotgan oylik maoshingiz qancha? (taxminiy raqamda yozing)",
            },
        ],
        "resume_required": False,
    },
}


def vacancy_keyboard_rows():
    """Vakansiyalar ro'yxatini (callback_data, matn) juftliklari sifatida qaytaradi."""
    return [(key, data["title"]) for key, data in VACANCIES.items()]
