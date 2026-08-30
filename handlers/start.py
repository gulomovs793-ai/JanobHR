"""
Janob HR Bot — /start, /cancel: til tanlash, nomzodni kutib olish va oqimni
boshqarish. KO'P MIJOZLI: /start bosilganda, agar yuboruvchi shu mijozning
admin ro'yxatida bo'lsa — Admin menyu, aks holda — nomzod oqimi ko'rsatiladi
(bitta bot, ikkala rol).
"""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from i18n import CHOOSE_LANGUAGE_PROMPT, DEFAULT_LANG, LANGUAGES, t
from services import database
from states import ApplyForm

router = Router(name="start")

_COPY = {
    "uz": {
        "home": (
            "👔 <b>Janob HR</b>\n\n"
            "O'zingizga mos ishni tanlang va arizani Telegram ichida yuboring. "
            "Jarayon odatda 5–7 daqiqa davom etadi.\n\n"
            "Nimadan boshlaymiz?"
        ),
        "jobs": "💼 Ochiq vakansiyalar",
        "status": "📄 Arizam holati",
        "about": "ℹ️ Jarayon qanday ishlaydi?",
        "about_text": (
            "<b>Ariza topshirish tartibi</b>\n\n"
            "1. Vakansiyani tanlaysiz\n"
            "2. Qisqa savollarga javob berasiz\n"
            "3. Aloqa ma'lumotingizni qoldirasiz\n"
            "4. Natijani shu bot orqali olasiz\n\n"
            "Ariza bepul. Ma'lumotlaringiz faqat ish beruvchi tomonidan ko'riladi."
        ),
        "none": "Sizda hali yuborilgan ariza yo'q.",
        "back": "⬅️ Bosh menyu",
    },
    "ru": {
        "home": (
            "👔 <b>Janob HR</b>\n\n"
            "Выберите подходящую вакансию и отправьте заявку прямо в Telegram. "
            "Обычно это занимает 5–7 минут.\n\n"
            "С чего начнём?"
        ),
        "jobs": "💼 Открытые вакансии",
        "status": "📄 Статус заявки",
        "about": "ℹ️ Как это работает?",
        "about_text": (
            "<b>Как подать заявку</b>\n\n"
            "1. Выберите вакансию\n"
            "2. Ответьте на короткие вопросы\n"
            "3. Оставьте контакты\n"
            "4. Получите результат в этом боте\n\n"
            "Заявка бесплатна. Данные видит только работодатель."
        ),
        "none": "У вас пока нет отправленных заявок.",
        "back": "⬅️ Главное меню",
    },
}

_APPLICATION_STATUS = {
    "pending": ("⏳", "Ko'rib chiqilmoqda", "На рассмотрении"),
    "accepted": ("✅", "Suhbatga chaqirildi", "Приглашение на собеседование"),
    "declined": ("—", "Hozircha davom etmadi", "Заявка не прошла дальше"),
    "rejected_hard_filter": (
        "—",
        "Talablarga mos kelmadi",
        "Не соответствует требованиям",
    ),
    "rejected_irrelevant": ("—", "Ariza yakunlanmadi", "Заявка не завершена"),
    "rejected_ai_generated": ("—", "Ariza yakunlanmadi", "Заявка не завершена"),
}


def _home_keyboard(lang: str):
    copy = _COPY[lang]
    builder = InlineKeyboardBuilder()
    builder.button(text=copy["jobs"], callback_data=f"candidate:jobs:{lang}")
    builder.button(text=copy["status"], callback_data=f"candidate:status:{lang}")
    builder.button(text=copy["about"], callback_data=f"candidate:about:{lang}")
    builder.button(text="🌐 Til / Язык", callback_data="candidate:language")
    builder.adjust(1)
    return builder.as_markup()


async def _show_home(message: Message, lang: str, *, edit: bool = False):
    method = message.edit_text if edit else message.answer
    await method(_COPY[lang]["home"], reply_markup=_home_keyboard(lang))


async def _show_vacancy_menu(
    message: Message, state: FSMContext, lang: str, tenant_id: int
):
    vacancies = await database.list_vacancies_localized(
        tenant_id, lang, active_only=True
    )
    greeting = t("greeting", lang)

    if not vacancies:
        await message.answer(t("no_vacancies", lang, greeting=greeting))
        return

    builder = InlineKeyboardBuilder()
    for v in vacancies:
        builder.button(text=v["title"], callback_data=f"vacancy:{v['key']}")
    builder.adjust(1)

    await message.answer(
        t("vacancy_list_prompt", lang, greeting=greeting),
        reply_markup=builder.as_markup(),
    )
    await state.set_state(ApplyForm.choosing_vacancy)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, tenant_id: int):
    await state.clear()

    builder = InlineKeyboardBuilder()
    for code, label in LANGUAGES.items():
        builder.button(text=label, callback_data=f"lang:{code}")
    builder.adjust(1)

    await message.answer(
        "👔 <b>Janob HR</b>\n\n" + CHOOSE_LANGUAGE_PROMPT,
        reply_markup=builder.as_markup(),
    )
    await state.set_state(ApplyForm.choosing_language)


@router.callback_query(ApplyForm.choosing_language, F.data.startswith("lang:"))
async def choose_language(callback: CallbackQuery, state: FSMContext, tenant_id: int):
    lang = callback.data.split(":", 1)[1]
    if lang not in LANGUAGES:
        lang = DEFAULT_LANG

    await state.set_state(None)
    await state.update_data(lang=lang)
    await _show_home(callback.message, lang, edit=True)
    await callback.answer()


@router.callback_query(F.data == "candidate:language")
async def change_language(callback: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    for code, label in LANGUAGES.items():
        builder.button(text=label, callback_data=f"lang:{code}")
    builder.adjust(1)
    await state.set_state(ApplyForm.choosing_language)
    await callback.message.edit_text(
        CHOOSE_LANGUAGE_PROMPT, reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("candidate:jobs:"))
async def open_jobs(callback: CallbackQuery, state: FSMContext, tenant_id: int):
    lang = callback.data.rsplit(":", 1)[1]
    pending = await database.get_pending_application_for_user(
        tenant_id, callback.from_user.id
    )
    if pending:
        await callback.answer(
            (
                "Bu vakansiya bo'yicha arizangiz ko'rib chiqilmoqda."
                if lang == "uz"
                else "Ваша заявка уже находится на рассмотрении."
            ),
            show_alert=True,
        )
        return
    await callback.message.delete()
    await state.update_data(lang=lang)
    await _show_vacancy_menu(callback.message, state, lang, tenant_id)
    await callback.answer()


@router.callback_query(F.data.startswith("candidate:status:"))
async def application_status(callback: CallbackQuery, tenant_id: int):
    lang = callback.data.rsplit(":", 1)[1]
    app = await database.get_latest_application_for_user(
        tenant_id, callback.from_user.id
    )
    copy = _COPY[lang]
    if app:
        icon, uz_status, ru_status = _APPLICATION_STATUS.get(
            app["status"], ("•", app["status"], app["status"])
        )
        status_text = uz_status if lang == "uz" else ru_status
        text = (
            f"📄 <b>{app['vacancy_title']}</b>\n\n"
            f"{icon} {status_text}\n"
            f"🗓 {(app.get('created_at') or '')[:10]}"
        )
    else:
        text = copy["none"]
    builder = InlineKeyboardBuilder()
    builder.button(text=copy["back"], callback_data=f"candidate:home:{lang}")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("candidate:about:"))
async def about_process(callback: CallbackQuery):
    lang = callback.data.rsplit(":", 1)[1]
    builder = InlineKeyboardBuilder()
    builder.button(text=_COPY[lang]["back"], callback_data=f"candidate:home:{lang}")
    await callback.message.edit_text(
        _COPY[lang]["about_text"], reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("candidate:home:"))
async def back_home(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.rsplit(":", 1)[1]
    await state.set_state(None)
    await state.update_data(lang=lang)
    await _show_home(callback.message, lang, edit=True)
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    current_state = await state.get_state()
    if current_state is None:
        await message.answer(t("cancel_no_active", lang))
        return

    await state.clear()
    await message.answer(t("cancel_done", lang))


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    await message.answer(t("help_text", lang))
