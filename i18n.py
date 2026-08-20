"""
Janob HR Bot — nomzod-bot uchun ikki tillilik (o'zbek/rus).

Botning o'z matnlari (tugmalar, xabarlar, xatolar) shu yerda tarjima qilingan.
Vakansiyaga oid dinamik matn (savollar, rad etish xabari) esa
`services/database.get_vacancy_localized()` orqali AI yordamida tarjima
qilinadi va keyingi safarlar uchun bazada saqlanadi (qayta tarjima qilinmaydi).

Admin bot til tanlashsiz, faqat o'zbek tilida ishlaydi — bu adminlar uchun,
ular allaqachon o'zbek tilida ishlashadi.
"""

DEFAULT_LANG = "uz"

LANGUAGES = {
    "uz": "🇺🇿 O'zbek tili",
    "ru": "🇷🇺 Русский язык",
}

CHOOSE_LANGUAGE_PROMPT = "Assalomu alaykum! / Здравствуйте!\n\nIltimos, tilni tanlang / Пожалуйста, выберите язык:"

TRANSLATIONS = {
    "uz": {
        "greeting": (
            "👔 Assalomu alaykum! Men Janob HR.\n\n"
            "Sizni kompaniyamizdagi mos lavozim bilan tanishtirish va ariza "
            "topshirishingizga yordam berish uchun shu yerdaman.\n\n"
            "Avval sizga mos vakansiyani tanlaymiz. Keyin bir nechta qisqa savollar "
            "beraman.\n\nQaysi lavozimga qiziqyapsiz? 👇"
        ),
        "no_vacancies": "{greeting}\n\nHozircha ochiq vakansiyalar yo'q. Iltimos, keyinroq qayta urinib ko'ring.",
        "vacancy_list_prompt": "{greeting}",
        "pending_application_notice": (
            "👋 Assalomu alaykum! Sizning <b>{vacancy_title}</b> vakansiyasiga yuborgan "
            "arizangiz hozircha ko'rib chiqilmoqda.\n\nNatija haqida tez orada shu yerda "
            "xabar beramiz — hozircha yangi ariza topshirishning hojati yo'q. Agar shoshilinch "
            "savolingiz bo'lsa, operator bilan bog'laning."
        ),
        "cancel_no_active": "Hozir bekor qilinadigan faol ariza yo'q. /start bilan boshlashingiz mumkin.",
        "cancel_done": "❌ Ariza bekor qilindi. Qaytadan boshlash uchun /start yuboring.",
        "help_text": (
            "👔 <b>Janob HR</b>\n\n🤖 AI asosidagi ishga qabul qiluvchi yordamchi.\n\n"
            "/start — vakansiyaga ariza topshirishni boshlash\n"
            "/cancel — joriy arizani bekor qilish\n"
            "/help — shu xabarni ko'rsatish"
        ),
        "vacancy_gone": "Bu vakansiya endi mavjud emas.",
        "vacancy_selected": "Siz tanladingiz: <b>{title}</b>",
        "resume_upfront_prompt": (
            "Agar tayyor rezyumeingiz (PDF) bo'lsa, avval shuni yuboring — men undan ba'zi "
            "ma'lumotlarni o'qib, sizga bir nechta savolni qayta berishning hojatini yo'q "
            "qilaman. 📄\n\nBo'lmasa, bemalol o'tkazib yuborishingiz mumkin."
        ),
        "skip_button": "⏭ O'tkazib yuborish",
        "resume_saved_plain": "Fayl saqlandi. Endi savollarga o'tamiz.",
        "resume_reading": "📄 Rezyumeni o'qimoqdaman...",
        "resume_no_text": (
            "Faylni saqladim, lekin undan matn o'qib bo'lmadi (skanerlangan rasm bo'lishi "
            "mumkin). Hammasi joyida — savollarni odatdagidek davom ettiramiz."
        ),
        "resume_no_match": (
            "Faylni saqladim, lekin undan avtomatik to'ldirish uchun yetarli ma'lumot topa "
            "olmadim. Savollarni odatdagidek davom ettiramiz."
        ),
        "resume_extracted_with_list": (
            "✅ Rezyumeni o'qib chiqdim!\n\nQuyidagi savollarni rezyumedan javob sifatida "
            "oldim, ularni qayta so'ramayman:\n{skipped_list}\n\nQolgan savollarni davom ettiramiz."
        ),
        "resume_extracted_no_list": "✅ Rezyumeni o'qib chiqdim. Savollarni davom ettiramiz.",
        "video_saved_upfront": "Video saqlandi. Endi savollarga o'tamiz.",
        "text_saved_upfront": "Qabul qilindi. Endi savollarga o'tamiz.",
        "question_progress": "<b>Savol {idx}/{total}</b>\n\n{text}",
        "answer_empty": "Iltimos, savolga matn ko'rinishida javob yozing.",
        "answer_too_long": (
            "Javobingiz juda uzun ({length} belgi). Iltimos, fikringizni qisqaroq — "
            "taxminan {max} belgigacha — qilib qayta yozing. ✍️"
        ),
        "irrelevant_retry": (
            "Kechirasiz, javobingiz savolga unchalik mos kelmadi. 🤔\n\nIltimos, quyidagi "
            "savolga qayta, aniqroq javob bering:\n\n{question_text}"
        ),
        "irrelevant_reject": (
            "Kechirasiz, bir necha marta savolga mos javob bera olmadingiz. ⚠️\n\nIltimos, "
            "keyinroq /start orqali qaytadan urinib ko'ring va savollarga jiddiy, mavzuga "
            "oid javob bering."
        ),
        "followup_prompt": (
            "Javobingiz biroz umumiy chiqdi. 🤔 Iltimos, aniqroq misol, raqam yoki qadam "
            "bilan kengaytirib qayta yozing.\n\nAgar shu javobingiz bilan davom etmoqchi "
            "bo'lsangiz, pastdagi tugmani bosing."
        ),
        "followup_skip_button": "✅ Shu javobim bilan davom etaman",
        "wrong_answer_type": "Iltimos, javobingizni oddiy matn ko'rinishida yozing. ✍️",
        "finish_resume_prompt": (
            "Deyarli tugadi! Agar mavjud bo'lsa, rezyume (PDF fayl), video-vizitka yoki "
            "portfolio havolangizni (link) yuboring — bu ixtiyoriy, xohlasangiz o'tkazib "
            "yuborishingiz mumkin."
        ),
        "wrong_file_type": (
            "Iltimos, PDF fayl, video yoki portfolio havolasini yuboring — yoki yuqoridagi "
            "\"O'tkazib yuborish\" tugmasini bosing."
        ),
        "portfolio_link_empty": "Iltimos, fayl, portfolio havolasi yuboring, yoki tugmani bosib o'tkazib yuboring.",
        "ask_full_name": "Deyarli tayyor! 🙌 Iltimos, to'liq ism-familiyangizni yozing (masalan: Aliyev Vali).",
        "name_too_short": "Iltimos, to'liq ism va familiyangizni yozing (masalan: Aliyev Vali).",
        "wrong_name_type": "Iltimos, ism-familiyangizni oddiy matn ko'rinishida yozing.",
        "ask_phone": (
            "Rahmat! Endi telefon raqamingizni ulashing — pastdagi tugmani bosing, yoki "
            "qo'lda yozib yuboring (masalan: +998901234567)."
        ),
        "share_phone_button": "📱 Raqamni ulashish",
        "phone_invalid": (
            "Bu telefon raqamiga o'xshamayapti. Iltimos, pastdagi tugmani bosing yoki "
            "raqamni to'liq formatda yozing (masalan: +998901234567)."
        ),
        "wrong_phone_type": "Iltimos, telefon raqamingizni pastdagi tugma orqali yuboring yoki matn ko'rinishida yozing.",
        "contact_thanks": "Rahmat! ✅",
        "application_submitted": "✅ Anketangiz qabul qilindi! Tez orada siz bilan bog'lanamiz. Rahmat!",
        "no_slots_left": (
            "Barcha suhbat vaqtlari hozircha band bo'lib qoldi 🙏 Tashvishlanmang — "
            "operatorimiz tez orada siz bilan bog'lanib, individual vaqt belgilaydi."
        ),
        "slot_offer_pick": "{intro_text}\n\n📅 Qulay bo'lgan vaqtni tanlang:",
        "slot_taken_retry": "Afsuski, bu vaqtni sizdan oldin boshqa nomzod band qildi 🙏 Boshqa vaqtni tanlang.",
        "slot_choice_accepted": "Tanlovingiz qabul qilindi ✅",
        "slot_confirmed": "✅ Siz tanladingiz: <b>{label}</b>",
        "interview_location_prefix": "📍 Manzil: {location}",
        "interview_contact_header": "👤 Suhbatni o'tkazadigan mas'ul:",
        "interview_phone_prefix": "📞 {phone}",
        "decision_accept_intro": (
            "🎉 Tabriklaymiz! Sizning nomzodingiz ma'qullandi.\n\n"
            "Endi suhbat uchun qulay vaqtni tanlang:"
        ),
        "decision_decline_text": (
            "Vaqt ajratganingiz uchun rahmat. Hozircha ushbu lavozim bo'yicha boshqa "
            "nomzodni tanladik. Kelajakda boshqa vakansiyalarimizni kuzatib boring!"
        ),
        "ai_suspect_retry": (
            "Javobingiz sun'iy intellekt (masalan ChatGPT) yordamida yozilgan bo'lishi "
            "mumkin degan taxminimiz bor. 🤖\n\nIltimos, shu savolga o'z so'zlaringiz bilan, "
            "shaxsiy tajribangizga asoslanib qayta javob bering:\n\n{question_text}"
        ),
        "ai_suspect_reject": (
            "Kechirasiz, javoblaringiz sun'iy intellekt yordamida yozilgan bo'lishi ehtimoli "
            "yuqori deb baholandi. ⚠️\n\nUshbu jarayon nomzodning shaxsiy bilim va tajribasini "
            "baholashga qaratilgan, shuning uchun davom eta olmaymiz. Agar bu xato bo'lgan "
            "deb hisoblasangiz, keyinroq /start orqali qaytadan, o'z so'zlaringiz bilan "
            "urinib ko'rishingiz mumkin."
        ),
    },
    "ru": {
        "greeting": (
            "👔 Здравствуйте! Я Janob HR.\n\n"
            "Я здесь, чтобы познакомить вас с подходящей вакансией в нашей компании и "
            "помочь подать заявку.\n\n"
            "Сначала выберем подходящую вакансию. Затем задам несколько коротких "
            "вопросов.\n\nКакая должность вас интересует? 👇"
        ),
        "no_vacancies": "{greeting}\n\nК сожалению, сейчас нет открытых вакансий. Пожалуйста, попробуйте позже.",
        "vacancy_list_prompt": "{greeting}",
        "pending_application_notice": (
            "👋 Здравствуйте! Ваша заявка на вакансию <b>{vacancy_title}</b> сейчас "
            "рассматривается.\n\nМы сообщим о результате здесь в ближайшее время — "
            "подавать новую заявку пока не нужно. Если у вас срочный вопрос, свяжитесь "
            "с оператором."
        ),
        "cancel_no_active": "Сейчас нет активной заявки для отмены. Вы можете начать с команды /start.",
        "cancel_done": "❌ Заявка отменена. Чтобы начать заново, отправьте /start.",
        "help_text": (
            "👔 <b>Janob HR</b>\n\n🤖 Помощник по подбору персонала на основе ИИ.\n\n"
            "/start — начать подачу заявки на вакансию\n"
            "/cancel — отменить текущую заявку\n"
            "/help — показать это сообщение"
        ),
        "vacancy_gone": "Эта вакансия больше недоступна.",
        "vacancy_selected": "Вы выбрали: <b>{title}</b>",
        "resume_upfront_prompt": (
            "Если у вас есть готовое резюме (PDF), отправьте его сначала — я прочитаю часть "
            "информации оттуда, и вам не придётся отвечать на некоторые вопросы повторно. "
            "📄\n\nЕсли резюме нет, можете смело пропустить этот шаг."
        ),
        "skip_button": "⏭ Пропустить",
        "resume_saved_plain": "Файл сохранён. Переходим к вопросам.",
        "resume_reading": "📄 Читаю резюме...",
        "resume_no_text": (
            "Файл сохранён, но извлечь текст не удалось (возможно, это скан-изображение). "
            "Всё в порядке — продолжаем с обычными вопросами."
        ),
        "resume_no_match": (
            "Файл сохранён, но достаточно данных для автозаполнения не нашлось. "
            "Продолжаем с обычными вопросами."
        ),
        "resume_extracted_with_list": (
            "✅ Я прочитал ваше резюме!\n\nСледующие вопросы я взял из резюме и не буду "
            "спрашивать повторно:\n{skipped_list}\n\nПродолжаем с оставшимися вопросами."
        ),
        "resume_extracted_no_list": "✅ Я прочитал ваше резюме. Продолжаем с вопросами.",
        "video_saved_upfront": "Видео сохранено. Переходим к вопросам.",
        "text_saved_upfront": "Принято. Переходим к вопросам.",
        "question_progress": "<b>Вопрос {idx}/{total}</b>\n\n{text}",
        "answer_empty": "Пожалуйста, ответьте на вопрос текстом.",
        "answer_too_long": (
            "Ваш ответ слишком длинный ({length} символов). Пожалуйста, сократите его "
            "примерно до {max} символов. ✍️"
        ),
        "irrelevant_retry": (
            "Извините, ваш ответ не совсем соответствует вопросу. 🤔\n\nПожалуйста, ответьте "
            "на вопрос ещё раз, более конкретно:\n\n{question_text}"
        ),
        "irrelevant_reject": (
            "Извините, вам несколько раз не удалось дать ответ по теме вопроса. ⚠️\n\n"
            "Пожалуйста, попробуйте снова позже через /start и отвечайте на вопросы "
            "серьёзно и по существу."
        ),
        "followup_prompt": (
            "Ваш ответ получился немного общим. 🤔 Пожалуйста, дополните его конкретным "
            "примером, цифрой или шагом.\n\nЕсли хотите оставить этот ответ как есть, "
            "нажмите кнопку ниже."
        ),
        "followup_skip_button": "✅ Оставить этот ответ",
        "wrong_answer_type": "Пожалуйста, отправьте ответ в виде обычного текста. ✍️",
        "finish_resume_prompt": (
            "Почти готово! Если у вас есть резюме (PDF), видео-визитка или ссылка на "
            "портфолио, отправьте их — это необязательно, можете пропустить этот шаг."
        ),
        "wrong_file_type": (
            "Пожалуйста, отправьте PDF-файл, видео или ссылку на портфолио — либо нажмите "
            "кнопку \"Пропустить\" выше."
        ),
        "portfolio_link_empty": "Пожалуйста, отправьте файл, ссылку на портфолио, либо нажмите кнопку, чтобы пропустить.",
        "ask_full_name": "Почти готово! 🙌 Пожалуйста, напишите своё полное имя и фамилию (например: Алиев Вали).",
        "name_too_short": "Пожалуйста, напишите полное имя и фамилию (например: Алиев Вали).",
        "wrong_name_type": "Пожалуйста, напишите имя и фамилию обычным текстом.",
        "ask_phone": (
            "Спасибо! Теперь поделитесь номером телефона — нажмите кнопку ниже или введите "
            "вручную (например: +998901234567)."
        ),
        "share_phone_button": "📱 Поделиться номером",
        "phone_invalid": (
            "Это не похоже на номер телефона. Пожалуйста, нажмите кнопку ниже или введите "
            "номер полностью (например: +998901234567)."
        ),
        "wrong_phone_type": "Пожалуйста, отправьте номер телефона через кнопку ниже или обычным текстом.",
        "contact_thanks": "Спасибо! ✅",
        "application_submitted": "✅ Ваша заявка принята! Мы скоро свяжемся с вами. Спасибо!",
        "no_slots_left": (
            "Все время для собеседования пока занято 🙏 Не переживайте — наш оператор "
            "скоро свяжется с вами и назначит индивидуальное время."
        ),
        "slot_offer_pick": "{intro_text}\n\n📅 Выберите удобное время:",
        "slot_taken_retry": "К сожалению, это время уже занял другой кандидат 🙏 Выберите другое время.",
        "slot_choice_accepted": "Ваш выбор принят ✅",
        "slot_confirmed": "✅ Вы выбрали: <b>{label}</b>",
        "interview_location_prefix": "📍 Адрес: {location}",
        "interview_contact_header": "👤 Ответственный за собеседование:",
        "interview_phone_prefix": "📞 {phone}",
        "decision_accept_intro": (
            "🎉 Поздравляем! Ваша кандидатура одобрена.\n\n"
            "Теперь выберите удобное время для собеседования:"
        ),
        "decision_decline_text": (
            "Спасибо за уделённое время. На данный момент мы выбрали другого кандидата "
            "на эту позицию. Следите за нашими другими вакансиями в будущем!"
        ),
        "ai_suspect_retry": (
            "Мы предполагаем, что ваш ответ мог быть написан с помощью искусственного "
            "интеллекта (например, ChatGPT). 🤖\n\nПожалуйста, ответьте на этот вопрос ещё "
            "раз своими словами, основываясь на личном опыте:\n\n{question_text}"
        ),
        "ai_suspect_reject": (
            "Извините, мы с высокой вероятностью определили, что ваши ответы написаны с "
            "помощью искусственного интеллекта. ⚠️\n\nЭтот процесс предназначен для оценки "
            "личных знаний и опыта кандидата, поэтому мы не можем продолжить. Если считаете "
            "это ошибкой, вы можете попробовать снова позже через /start, отвечая своими "
            "словами."
        ),
    },
}


def t(key: str, lang: str, **kwargs) -> str:
    """Berilgan kalit uchun tarjimani qaytaradi. Til yoki kalit topilmasa,
    standart (o'zbek) matnga qaytadi."""
    table = TRANSLATIONS.get(lang) or TRANSLATIONS[DEFAULT_LANG]
    template = table.get(key) or TRANSLATIONS[DEFAULT_LANG].get(key, key)
    return template.format(**kwargs) if kwargs else template
