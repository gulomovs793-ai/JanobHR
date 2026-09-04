"""Admin bot — asosiy menyu va statistika."""

import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import MINI_APP_BASE_URL, WEBHOOK_BASE_URL
from services import database
from services.hiring_intelligence import compare_candidates, hiring_funnel
from services.plans import (
    FEATURE_ADVANCED_REPORTING,
    FEATURE_FUNNEL_ANALYTICS,
    FEATURE_PER_VACANCY_REPORTING,
    FEATURE_PRIORITY_SUPPORT,
    FEATURE_TOP_CANDIDATE_COMPARE,
    has_feature,
)

router = Router(name="admin_menu")
logger = logging.getLogger("janob_hr_bot")

ADMIN_MENU = {
    "panel": "🖥 Boshqaruv paneli",
    "new": "📥 Yangi arizalar",
    "candidates": "👥 Nomzodlar",
    "vacancies": "💼 Vakansiyalar",
    "interviews": "📅 Suhbatlar",
    "stats": "📊 Statistika",
    "billing": "💳 Tarif va to'lov",
    "help": "☎️ Yordam",
}


def _fresh_miniapp_url(tenant_id: int) -> str:
    """Har ochishda yangi URL berib, Telegram Desktop stale WebView'ini chetlab o'tadi."""
    miniapp_base = (MINI_APP_BASE_URL or f"{WEBHOOK_BASE_URL}/miniapp").rstrip("/")
    return f"{miniapp_base}/{tenant_id}?launch={time.time_ns()}"


async def _refresh_chat_menu_button(message: Message, tenant_id: int) -> None:
    """Private chat menu tugmasini ham ayni paytdagi yangi launch URLga yangilaydi."""
    if not WEBHOOK_BASE_URL:
        return
    try:
        await message.bot.set_chat_menu_button(
            chat_id=message.chat.id,
            menu_button=MenuButtonWebApp(
                text="Boshqaruv paneli",
                web_app=WebAppInfo(url=_fresh_miniapp_url(tenant_id)),
            ),
        )
    except TelegramAPIError as exc:
        logger.warning(
            "Admin Mini App chat menu tugmasi yangilanmadi: tenant_id=%s chat_id=%s error=%s",
            tenant_id,
            message.chat.id,
            exc,
        )


def _service_keyboard(tenant_id: int) -> ReplyKeyboardMarkup:
    # Reply-keyboard WebApp tugmasi ayrim Telegram klientlarida SimpleWebView
    # sifatida ochilib, server auth uchun kerakli initData'ni bermasligi mumkin.
    # Shuning uchun persistent tugma oddiy matn; bosilganda quyidagi handler
    # signed initData beradigan inline WebApp tugmasini yuboradi.
    panel = KeyboardButton(text=ADMIN_MENU["panel"])
    return ReplyKeyboardMarkup(
        keyboard=[
            [panel],
            [KeyboardButton(text=ADMIN_MENU["new"]), KeyboardButton(text=ADMIN_MENU["candidates"])],
            [KeyboardButton(text=ADMIN_MENU["vacancies"]), KeyboardButton(text=ADMIN_MENU["interviews"])],
            [KeyboardButton(text=ADMIN_MENU["stats"]), KeyboardButton(text=ADMIN_MENU["billing"])],
            [KeyboardButton(text=ADMIN_MENU["help"])],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Kerakli xizmatni tanlang",
    )


def _main_menu_keyboard(overall: dict, tenant_id: int):
    builder = InlineKeyboardBuilder()
    if WEBHOOK_BASE_URL:
        builder.button(
            text="🖥 Boshqaruv paneli",
            web_app=WebAppInfo(url=_fresh_miniapp_url(tenant_id)),
        )
    builder.button(
        text=f"📥 Yangi arizalar · {overall['pending']}",
        callback_data="apps:list:pending:0",
    )
    builder.button(text="👥 Barcha nomzodlar", callback_data="apps:list:all:0")
    builder.button(text="💼 Vakansiyalar", callback_data="menu:vacancies")
    builder.button(text="📅 Suhbatlar", callback_data="menu:interview")
    builder.button(text="📊 Hisobot", callback_data="menu:stats")
    builder.button(text="💳 Tarif va limitlar", callback_data="menu:billing")
    builder.button(text="➕ Yangi vakansiya", callback_data="menu:new")
    builder.adjust(1, 1, 1, 2, 1, 1, 1)
    return builder.as_markup()


async def show_main_menu(message: Message, tenant_id: int, *, edit: bool = False):
    overall = await database.get_overall_stats(tenant_id)
    await _refresh_chat_menu_button(message, tenant_id)
    text = (
        "👔 <b>Janob HR · Ishga qabul</b>\n\n"
        f"Yangi: <b>{overall['pending']}</b>   ·   "
        f"Suhbatga: <b>{overall['accepted']}</b>   ·   "
        f"Jami: <b>{overall['total']}</b>\n\n"
        "Bugungi ishni qayerdan boshlaysiz?"
    )
    if edit:
        await message.edit_text(text, reply_markup=_main_menu_keyboard(overall, tenant_id))
    else:
        await message.answer(text, reply_markup=_service_keyboard(tenant_id))


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, tenant_id: int):
    await state.clear()
    await show_main_menu(message, tenant_id)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, tenant_id: int):
    await state.clear()
    await show_main_menu(message, tenant_id)


@router.message(F.text == ADMIN_MENU["panel"])
async def service_panel(message: Message, tenant_id: int):
    if not WEBHOOK_BASE_URL:
        await message.answer("Boshqaruv paneli vaqtincha mavjud emas. Keyinroq urinib ko'ring.")
        return
    fresh_url = _fresh_miniapp_url(tenant_id)
    try:
        await message.bot.set_chat_menu_button(
            chat_id=message.chat.id,
            menu_button=MenuButtonWebApp(
                text="Boshqaruv paneli",
                web_app=WebAppInfo(url=fresh_url),
            ),
        )
    except TelegramAPIError as exc:
        logger.warning(
            "Admin Mini App menu tugmasi yangilanmadi: tenant_id=%s chat_id=%s error=%s",
            tenant_id,
            message.chat.id,
            exc,
        )
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🖥 Boshqaruv panelini ochish",
        web_app=WebAppInfo(url=fresh_url),
    )
    await message.answer(
        "Boshqaruv panelini Telegram orqali xavfsiz oching:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "menu:main")
async def back_to_main(callback: CallbackQuery, state: FSMContext, tenant_id: int):
    await state.clear()
    await show_main_menu(callback.message, tenant_id, edit=True)
    await callback.answer()


@router.callback_query(F.data == "menu:stats")
async def show_stats(callback: CallbackQuery, tenant_id: int):
    text, markup = await _stats_content(tenant_id)
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


async def _stats_content(tenant_id: int):
    usage = await database.get_subscription_usage(tenant_id)
    plan_code = usage["plan"].code
    premium_active = not usage["expired"]
    overall = await database.get_overall_stats(tenant_id)

    lines = [
        f"📊 <b>Hisobot · {usage['plan'].name}</b>",
        "",
        f"📥 Jami ariza: <b>{overall['total']}</b>",
        f"⏳ Kutilmoqda: {overall['pending']}",
        f"✅ Suhbatga: {overall['accepted']}",
        f"❌ Rad etilgan: {overall['rejected_total']}",
    ]
    builder = InlineKeyboardBuilder()

    if premium_active and has_feature(plan_code, FEATURE_PER_VACANCY_REPORTING):
        per_vacancy = await database.get_vacancy_stats(tenant_id)
        if per_vacancy:
            lines.extend(["", "<b>Vakansiyalar bo'yicha:</b>"])
            for item in per_vacancy:
                lines.append(
                    f"• <b>{item['vacancy_title']}</b>: {item['total']} ariza · "
                    f"{item['accepted']} suhbat · {item['rejected']} rad"
                )

    funnel = None
    if premium_active and has_feature(plan_code, FEATURE_FUNNEL_ANALYTICS):
        apps = await database.list_funnel_applications(tenant_id, days=30)
        funnel = hiring_funnel(apps)
        lines.extend(
            [
                "",
                "<b>30 kunlik hiring funnel:</b>",
                (
                    f"Ariza: {funnel['applications']} → Filtrdan o'tdi: {funnel['passed_filter']} "
                    f"→ Kuchli: {funnel['strong']} → Suhbat: {funnel['interview']} "
                    f"→ Ishga olindi: {funnel['hired']}"
                ),
            ]
        )

    if funnel and premium_active and has_feature(plan_code, FEATURE_ADVANCED_REPORTING):
        rates = funnel["rates"]
        lines.extend(
            [
                "",
                "<b>BUSINESS conversion:</b>",
                f"Filtrdan o'tish: <b>{rates['filter_pass']}%</b>",
                f"Kuchli nomzod: <b>{rates['strong']}%</b>",
                f"Suhbatga o'tish: <b>{rates['interview']}%</b>",
                f"Suhbatdan hire: <b>{rates['hire']}%</b>",
                f"No-show: <b>{funnel['no_show']}</b>",
            ]
        )

    if premium_active and has_feature(plan_code, FEATURE_TOP_CANDIDATE_COMPARE):
        vacancies = await database.list_vacancies(tenant_id, active_only=False)
        active = [item for item in vacancies if item.get("active")]
        if active:
            lines.extend(["", "🏆 <b>Top-3 taqqoslash uchun vakansiyani tanlang:</b>"])
            for vacancy in active[:10]:
                builder.button(
                    text=f"🏆 {vacancy['title']}",
                    callback_data=f"intel:top:{vacancy['key']}",
                )

    if not premium_active or not has_feature(plan_code, FEATURE_FUNNEL_ANALYTICS):
        lines.extend(
            [
                "",
                "🔒 Funnel, Top-3 va risk analytics GROWTH tarifidan boshlab mavjud.",
            ]
        )

    builder.button(text="⬅️ Orqaga", callback_data="menu:main")
    builder.adjust(1)
    return "\n".join(lines), builder.as_markup()


@router.callback_query(F.data.startswith("intel:top:"))
async def top_candidates(callback: CallbackQuery, tenant_id: int):
    usage = await database.get_subscription_usage(tenant_id)
    if usage["expired"] or not has_feature(
        usage["plan"].code, FEATURE_TOP_CANDIDATE_COMPARE
    ):
        await callback.answer(
            "Top nomzodlarni taqqoslash GROWTH tarifidan boshlab mavjud.",
            show_alert=True,
        )
        return
    vacancy_key = callback.data.split(":", 2)[2]
    vacancy = await database.get_vacancy(tenant_id, vacancy_key)
    if not vacancy:
        await callback.answer("Vakansiya topilmadi.", show_alert=True)
        return
    apps = await database.list_funnel_applications(
        tenant_id, days=90, vacancy_key=vacancy_key
    )
    comparison = compare_candidates(apps, vacancy, limit=3)
    lines = [f"🏆 <b>{vacancy['title']} · Top nomzodlar</b>", ""]
    if not comparison["items"]:
        lines.append("Taqqoslash uchun yetarli faol nomzod yo'q.")
    else:
        for item in comparison["items"]:
            score = item["score"] if item["score"] is not None else "—"
            lines.append(f"<b>{item['rank']}. {item['full_name']}</b> · {score}/100")
            lines.append(f"   Kuchli tomon: {item['strength']['summary']}")
            if item["risks"]:
                risk_text = "; ".join(risk["label"] for risk in item["risks"][:2])
                lines.append(f"   ⚠️ {risk_text}")
        if comparison.get("recommendation"):
            lines.extend(["", f"🎯 {comparison['recommendation']['text']}"])

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Hisobot", callback_data="menu:stats")
    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()


async def _send_stats(message: Message, tenant_id: int):
    text, markup = await _stats_content(tenant_id)
    await message.answer(text, reply_markup=markup)


@router.message(F.text == ADMIN_MENU["new"])
async def service_new_applications(message: Message, tenant_id: int):
    from admin_bot.handlers_candidates import show_list_message

    await show_list_message(message, tenant_id, "pending", 0)


@router.message(F.text == ADMIN_MENU["candidates"])
async def service_candidates(message: Message, tenant_id: int):
    from admin_bot.handlers_candidates import show_list_message

    await show_list_message(message, tenant_id, "all", 0)


@router.message(F.text == ADMIN_MENU["vacancies"])
async def service_vacancies(message: Message, tenant_id: int):
    from admin_bot.handlers_vacancy_list import list_vacancies_message

    await list_vacancies_message(message, tenant_id)


@router.message(F.text == ADMIN_MENU["interviews"])
async def service_interviews(message: Message, state: FSMContext, tenant_id: int):
    from admin_bot.handlers_interview import _show_menu

    await _show_menu(message, state, tenant_id)


@router.message(F.text == ADMIN_MENU["billing"])
async def service_billing(message: Message, tenant_id: int):
    from admin_bot.handlers_billing import show_billing_message

    await show_billing_message(message, tenant_id)


@router.message(F.text == ADMIN_MENU["stats"])
async def service_stats(message: Message, tenant_id: int):
    await _send_stats(message, tenant_id)


@router.message(F.text == ADMIN_MENU["help"])
async def service_help(message: Message, tenant_id: int):
    usage = await database.get_subscription_usage(tenant_id)
    if not usage["expired"] and has_feature(
        usage["plan"].code, FEATURE_PRIORITY_SUPPORT
    ):
        text = (
            "⚡ <b>BUSINESS Priority Support</b>\n\n"
            "Savol yoki muammo bo'lsa, <b>@F45746</b> ga yozing. "
            "BUSINESS murojaatlari ustuvor ko'rib chiqiladi."
        )
    else:
        text = "☎️ <b>Yordam</b>\n\nSavol yoki muammo bo'lsa, <b>@F45746</b> ga yozing."
    await message.answer(text)
