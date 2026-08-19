"""
Universal yordamchi funksiyalar va konstantalar. Vakansiyalarning o'zi endi
statik lug'atda emas, ma'lumotlar bazasida (services/database.py, `vacancies`
jadvali) saqlanadi — admin bot orqali istalgan kasb uchun cheklovsiz vakansiya
yaratish, tahrirlash va o'chirish mumkin.
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
REFERENCE_CHECK_QUESTION_UZ = {
    "key": "reference_check",
    "text": (
        "So'nggi savol. Sizning tajribangiz bizga juda yoqdi. 👏\n\n"
        "Keyingi bosqichda biz oldingi rahbaringizga qo'ng'iroq qilishimiz mumkin. "
        "Agar hozir undan siz haqingizda so'rasak, u sizni 10 balldan nechchiga baholaydi "
        "va nima uchun? (Iltimos, imkon qadar aniq va rostgo'y javob bering.)"
    ),
    "ai_score": True,
}

REFERENCE_CHECK_QUESTION_RU = {
    "key": "reference_check",
    "text": (
        "Последний вопрос. Нам очень понравился ваш опыт. 👏\n\n"
        "На следующем этапе мы можем позвонить вашему бывшему руководителю. Если бы мы "
        "сейчас спросили его о вас, на сколько баллов из 10 он бы вас оценил и почему? "
        "(Пожалуйста, ответьте максимально точно и честно.)"
    ),
    "ai_score": True,
}


def build_questions(vacancy: dict, lang: str = "uz") -> list[dict]:
    """Vakansiyaning (bazadan olingan) savollariga Topgrading savolini qo'shib qaytaradi."""
    ref_question = REFERENCE_CHECK_QUESTION_RU if lang == "ru" else REFERENCE_CHECK_QUESTION_UZ
    return [*vacancy["questions"], ref_question]
