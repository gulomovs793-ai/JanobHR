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
                "key": "hard_client",
                "text": "Qiyin mijoz bilan qanday ishlaysiz? Bitta real holatni yozib bering.",
                "ai_score": True,
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
                "key": "style",
                "text": "Sizga qaysi dizayn yo'nalishi (uslub) yaqinroq va nega?",
                "ai_score": True,
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
                "key": "cases",
                "text": "Oldingi ishlaringizdan eng yaxshi natija bergan case'ni qisqacha yozib bering.",
                "ai_score": True,
            },
        ],
        "resume_required": False,
    },
}


def vacancy_keyboard_rows():
    """Vakansiyalar ro'yxatini (callback_data, matn) juftliklari sifatida qaytaradi."""
    return [(key, data["title"]) for key, data in VACANCIES.items()]
