from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise RuntimeError(f"Expected block not found in {path}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def splice(path: str, start_marker: str, end_marker: str, replacement: str) -> None:
    text = read(path)
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    write(path, text[:start] + replacement + text[end:])


# ---------------------------------------------------------------------------
# 1. Admin Mini App must launch with signed Telegram initData.
# ---------------------------------------------------------------------------
replace_once(
    "admin_bot/handlers_menu.py",
    '''def _service_keyboard(tenant_id: int) -> ReplyKeyboardMarkup:\n    miniapp_base = (MINI_APP_BASE_URL or f"{WEBHOOK_BASE_URL}/miniapp").rstrip("/")\n    panel = KeyboardButton(text=ADMIN_MENU["panel"])\n    if WEBHOOK_BASE_URL:\n        panel = KeyboardButton(\n            text=ADMIN_MENU["panel"],\n            web_app=WebAppInfo(url=f"{miniapp_base}/{tenant_id}"),\n        )\n    return ReplyKeyboardMarkup(\n''',
    '''def _service_keyboard(tenant_id: int) -> ReplyKeyboardMarkup:\n    # Reply-keyboard WebApp tugmasi ayrim Telegram klientlarida SimpleWebView\n    # sifatida ochilib, server auth uchun kerakli initData'ni bermasligi mumkin.\n    # Shuning uchun persistent tugma oddiy matn; bosilganda quyidagi handler\n    # signed initData beradigan inline WebApp tugmasini yuboradi.\n    panel = KeyboardButton(text=ADMIN_MENU["panel"])\n    return ReplyKeyboardMarkup(\n''',
)

insert_after = '''@router.message(Command("cancel"))\nasync def cmd_cancel(message: Message, state: FSMContext, tenant_id: int):\n    await state.clear()\n    await show_main_menu(message, tenant_id)\n\n\n'''
admin_panel_handler = '''@router.message(F.text == ADMIN_MENU["panel"])\nasync def service_panel(message: Message, tenant_id: int):\n    if not WEBHOOK_BASE_URL:\n        await message.answer("Boshqaruv paneli vaqtincha mavjud emas. Keyinroq urinib ko'ring.")\n        return\n    miniapp_base = (MINI_APP_BASE_URL or f"{WEBHOOK_BASE_URL}/miniapp").rstrip("/")\n    builder = InlineKeyboardBuilder()\n    builder.button(\n        text="🖥 Boshqaruv panelini ochish",\n        web_app=WebAppInfo(url=f"{miniapp_base}/{tenant_id}"),\n    )\n    await message.answer(\n        "Boshqaruv panelini Telegram orqali xavfsiz oching:",\n        reply_markup=builder.as_markup(),\n    )\n\n\n'''
replace_once("admin_bot/handlers_menu.py", insert_after, insert_after + admin_panel_handler)


# ---------------------------------------------------------------------------
# 2. Deploys must not discard candidate/admin Telegram updates.
# ---------------------------------------------------------------------------
replace_once(
    "webhook_app.py",
    '        await bot.set_webhook(url=webhook_url, drop_pending_updates=True)\n',
    '''        # Deploy/restart oralig'ida kelgan nomzod xabarlari yo'qolmasin.\n        # Deduplikatsiya handler/FSM qatlamida qilinadi, pending update'ni\n        # Telegram serveridan o'chirish production uchun xavfli.\n        await bot.set_webhook(url=webhook_url, drop_pending_updates=False)\n''',
)


# ---------------------------------------------------------------------------
# 3. One logical application = one durable submission key.
#    Also enforce application quota inside the same SQLite write transaction.
# ---------------------------------------------------------------------------
replace_once(
    "handlers/vacancy.py",
    '"""Janob HR Bot — vakansiya tanlash bosqichi."""\n\n',
    '"""Janob HR Bot — vakansiya tanlash bosqichi."""\n\nimport uuid\n\n',
)
replace_once(
    "handlers/vacancy.py",
    '''        vacancy_questions=build_questions(vacancy, lang),\n        question_index=0,\n''',
    '''        vacancy_questions=build_questions(vacancy, lang),\n        # Bir arizaning butun FSM umri davomida o'zgarmaydigan idempotency kalit.\n        # Telegram retry/restart bo'lsa ham shu ariza DBda ikki marta paydo bo'lmaydi.\n        submission_key=uuid.uuid4().hex,\n        question_index=0,\n''',
)

replace_once(
    "services/database.py",
    'logger = logging.getLogger("janob_hr_bot")\n\n',
    '''logger = logging.getLogger("janob_hr_bot")\n\n\nclass ApplicationLimitReached(RuntimeError):\n    """Tarif ariza limiti atomik saqlash paytida tugagan."""\n\n\n''',
)
replace_once(
    "services/database.py",
    '''    tenant_id INTEGER NOT NULL,\n    user_id INTEGER NOT NULL,\n    username TEXT,\n''',
    '''    tenant_id INTEGER NOT NULL,\n    user_id INTEGER NOT NULL,\n    submission_key TEXT,\n    username TEXT,\n''',
)
replace_once(
    "services/database.py",
    '''        await db.execute(_CREATE_SYSTEM_NOTIFICATIONS_TABLE_SQL)\n        # Mavjud Render diskidagi eski bazalarni ma'lumot yo'qotmasdan\n''',
    '''        await db.execute(_CREATE_SYSTEM_NOTIFICATIONS_TABLE_SQL)\n\n        # Ko'p async handler bir vaqtda o'qib/yozishi mumkin. WAL readerlarni\n        # writer sabab bloklanishini kamaytiradi; busy_timeout qisqa locklarda\n        # tasodifiy "database is locked" xatosini oldini oladi.\n        await db.execute("PRAGMA journal_mode=WAL")\n        await db.execute("PRAGMA synchronous=NORMAL")\n        await db.execute("PRAGMA busy_timeout=5000")\n\n        cursor = await db.execute("PRAGMA table_info(applications)")\n        application_columns = {row[1] for row in await cursor.fetchall()}\n        if "submission_key" not in application_columns:\n            await db.execute("ALTER TABLE applications ADD COLUMN submission_key TEXT")\n        await db.execute(\n            "CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_submission_key "\n            "ON applications(tenant_id, submission_key) "\n            "WHERE submission_key IS NOT NULL"\n        )\n\n        # Mavjud Render diskidagi eski bazalarni ma'lumot yo'qotmasdan\n''',
)

health_block = '''\n\nasync def healthcheck() -> bool:\n    """Render health endpoint uchun eng arzon real DB tekshiruvi."""\n    try:\n        async with aiosqlite.connect(SQLITE_PATH, timeout=3) as db:\n            await db.execute("PRAGMA busy_timeout=3000")\n            cursor = await db.execute("SELECT 1")\n            row = await cursor.fetchone()\n        return bool(row and row[0] == 1)\n    except Exception:\n        logger.exception("SQLite healthcheck muvaffaqiyatsiz.")\n        return False\n\n\n'''
replace_once(
    "services/database.py",
    "\n\n# ============================= MIJOZLAR (tenants) =============================\n",
    health_block + "# ============================= MIJOZLAR (tenants) =============================\n",
)

save_application = '''async def save_application(\n    *,\n    tenant_id: int,\n    user_id: int,\n    username: str,\n    full_name: str,\n    vacancy_key: str,\n    vacancy_title: str,\n    answers: dict,\n    ai_scores: dict,\n    resume_file_id: str | None,\n    video_file_id: str | None,\n    status: str,\n    phone_number: str = "",\n    lang: str = "uz",\n    ai_suspect_flags: list | None = None,\n    voice_answers: dict | None = None,\n    submission_key: str | None = None,\n) -> int:\n    """Arizani idempotent va tarif limitiga nisbatan atomik saqlaydi.\n\n    Avvalgi get_subscription_usage() -> INSERT ketma-ketligi race condition\n    qoldirardi: limitda 1 joy qolsa, ikki nomzod bir paytda o'tib ketishi\n    mumkin edi. BEGIN IMMEDIATE bilan quota tekshiruvi va INSERT bitta write\n    transaction ichida bajariladi.\n    """\n    from services.plans import get_plan\n\n    created_at = datetime.now(timezone.utc).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:\n        await db.execute("PRAGMA busy_timeout=5000")\n        await db.execute("BEGIN IMMEDIATE")\n        try:\n            if submission_key:\n                cursor = await db.execute(\n                    "SELECT id FROM applications WHERE tenant_id=? AND submission_key=? LIMIT 1",\n                    (tenant_id, submission_key),\n                )\n                existing = await cursor.fetchone()\n                if existing:\n                    await db.commit()\n                    return existing[0]\n\n            cursor = await db.execute(\n                "SELECT plan_code, subscription_started_at, subscription_expires_at, created_at "\n                "FROM tenants WHERE id=?",\n                (tenant_id,),\n            )\n            tenant = await cursor.fetchone()\n            if not tenant:\n                raise ValueError("Mijoz topilmadi")\n\n            plan = get_plan(tenant[0])\n            expires_at = tenant[2]\n            expired = bool(\n                plan.code not in {"trial", "legacy"}\n                and (not expires_at or expires_at <= created_at)\n            )\n            if expired:\n                raise ApplicationLimitReached("Tarif muddati tugagan")\n\n            if plan.application_limit is not None:\n                period_start = tenant[1] or tenant[3]\n                cursor = await db.execute(\n                    "SELECT COUNT(*) FROM applications WHERE tenant_id=? AND created_at>=?",\n                    (tenant_id, period_start),\n                )\n                used = (await cursor.fetchone())[0]\n                if used >= plan.application_limit:\n                    raise ApplicationLimitReached("Tarifdagi ariza limiti tugagan")\n\n            cursor = await db.execute(\n                """\n                INSERT INTO applications (\n                    tenant_id, user_id, submission_key, username, full_name, vacancy_key,\n                    vacancy_title, answers, ai_scores, resume_file_id, video_file_id, status,\n                    phone_number, lang, ai_suspect_flags, voice_answers, created_at\n                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n                """,\n                (\n                    tenant_id,\n                    user_id,\n                    submission_key,\n                    username,\n                    full_name,\n                    vacancy_key,\n                    vacancy_title,\n                    json.dumps(answers, ensure_ascii=False),\n                    json.dumps(ai_scores, ensure_ascii=False),\n                    resume_file_id,\n                    video_file_id,\n                    status,\n                    phone_number,\n                    lang,\n                    json.dumps(ai_suspect_flags or [], ensure_ascii=False),\n                    json.dumps(voice_answers or {}, ensure_ascii=False),\n                    created_at,\n                ),\n            )\n            await db.commit()\n            return cursor.lastrowid\n        except Exception:\n            await db.rollback()\n            raise\n\n\n'''
splice(
    "services/database.py",
    "async def save_application(\n",
    "async def get_application(",
    save_application,
)

# Atomic application state transitions are the single source of truth for both
# Telegram Admin and Mini App actions.
transition_function = '''async def transition_application_status(\n    tenant_id: int,\n    app_id: int,\n    new_status: str,\n    allowed_from: set[str] | tuple[str, ...],\n) -> bool:\n    allowed_statuses = {\n        "pending",\n        "saved",\n        "accepted",\n        "declined",\n        "rejected_hard_filter",\n        "rejected_irrelevant",\n        "rejected_ai_generated",\n        "hired",\n        "not_hired",\n        "no_show",\n    }\n    if new_status not in allowed_statuses or not allowed_from:\n        raise ValueError("Noto'g'ri nomzod holati.")\n    invalid_from = set(allowed_from) - allowed_statuses\n    if invalid_from:\n        raise ValueError("Noto'g'ri boshlang'ich holat.")\n\n    placeholders = ",".join("?" for _ in allowed_from)\n    params = [new_status, app_id, tenant_id, *allowed_from]\n    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:\n        await db.execute("PRAGMA busy_timeout=5000")\n        cursor = await db.execute(\n            f"UPDATE applications SET status=? WHERE id=? AND tenant_id=? "\n            f"AND status IN ({placeholders})",\n            params,\n        )\n        await db.commit()\n        return cursor.rowcount > 0\n\n\n'''
replace_once(
    "services/database.py",
    "async def try_book_slot(tenant_id: int, app_id: int, slot: str, capacity: int) -> bool:\n",
    transition_function
    + "async def try_book_slot(tenant_id: int, app_id: int, slot: str, capacity: int) -> bool:\n",
)

new_try_book_slot = '''async def try_book_slot(tenant_id: int, app_id: int, slot: str, capacity: int) -> bool:\n    """Suhbat slotini atomik band qiladi va pipeline holatini sinxronlaydi.\n\n    Yuqori ball sabab admin qaroridan oldin slot taklif qilingan nomzod slotni\n    tanlasa, u endi mantiqan `accepted` bo'ladi. Bir xil tugmani qayta bosish\n    esa idempotent: o'z sloti to'lib qolgan bo'lsa ham muvaffaqiyat qaytadi.\n    """\n    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:\n        await db.execute("PRAGMA busy_timeout=5000")\n        cursor = await db.execute(\n            """\n            UPDATE applications\n            SET selected_slot = ?, status = 'accepted'\n            WHERE id = ? AND tenant_id = ?\n              AND status IN ('pending', 'saved', 'accepted')\n              AND (\n                    selected_slot = ?\n                    OR (SELECT COUNT(*) FROM applications\n                        WHERE selected_slot = ? AND tenant_id = ?) < ?\n                  )\n            """,\n            (slot, app_id, tenant_id, slot, slot, tenant_id, capacity),\n        )\n        await db.commit()\n        return cursor.rowcount > 0\n\n\n'''
splice(
    "services/database.py",
    "async def try_book_slot(tenant_id: int, app_id: int, slot: str, capacity: int) -> bool:\n",
    "async def count_slot_bookings(",
    new_try_book_slot,
)


# ---------------------------------------------------------------------------
# 4. Candidate flow: voice retries + final phone submission are idempotent.
# ---------------------------------------------------------------------------
new_voice_handler = '''@router.message(ApplyForm.answering_questions, F.voice)\nasync def handle_voice_answer(message: Message, state: FSMContext):\n    """Ovozli javobni tahlilsiz saqlaydi, Telegram retry'ni dubl qilmaydi."""\n    async with _answer_lock(message):\n        data = await state.get_data()\n        if data.get("last_answer_message_id") == message.message_id:\n            logger.info(\n                "Dubl voice update e'tiborsiz qoldirildi: chat=%s message=%s",\n                message.chat.id,\n                message.message_id,\n            )\n            return\n\n        lang = data.get("lang", DEFAULT_LANG)\n        idx = data["question_index"]\n        questions = data["vacancy_questions"]\n        q = questions[idx]\n        if not q.get("voice"):\n            await message.answer(t("wrong_answer_type", lang))\n            return\n\n        voice_answers = data.get("voice_answers", {})\n        voice_answers[q["key"]] = message.voice.file_id\n        answers = data.get("answers", {})\n        answers[q["key"]] = t("voice_answer_placeholder", lang)\n\n        await state.update_data(\n            last_answer_message_id=message.message_id,\n            voice_answers=voice_answers,\n            answers=answers,\n            question_index=idx + 1,\n            irrelevant_retry_count=0,\n            ai_suspect_retry_count=0,\n        )\n        await message.answer(t("voice_received", lang))\n        await ask_current_question(message, state)\n\n\n'''
splice(
    "handlers/questions.py",
    "@router.message(ApplyForm.answering_questions, F.voice)\n",
    "async def _process_answer(",
    new_voice_handler,
)

new_reject = '''async def _reject_and_save(\n    message: Message,\n    state: FSMContext,\n    data: dict,\n    answers: dict,\n    ai_scores: dict,\n    reject_text: str,\n    status: str,\n):\n    """Rad javobini yuboradi va statistikani idempotent tarzda saqlaydi."""\n    await message.answer(reject_text)\n    try:\n        await database.save_application(\n            tenant_id=data["tenant_id"],\n            user_id=message.from_user.id,\n            submission_key=data.get("submission_key"),\n            username=message.from_user.username or "",\n            full_name=message.from_user.full_name,\n            vacancy_key=data["vacancy_key"],\n            vacancy_title=data["vacancy_title"],\n            answers=answers,\n            ai_scores=ai_scores,\n            resume_file_id=None,\n            video_file_id=None,\n            status=status,\n            lang=data.get("lang", DEFAULT_LANG),\n            ai_suspect_flags=data.get("ai_suspect_flagged_keys", []),\n            voice_answers=data.get("voice_answers", {}),\n        )\n    except database.ApplicationLimitReached:\n        # Limit aynan shu vaqtda tugashi mumkin. Nomzodga rad javobi allaqachon\n        # berildi; tarifni oshirib yuborishdan ko'ra statistik yozuvni o'tkazamiz.\n        logger.info("Rad etilgan ariza tarif limiti sabab DBga yozilmadi.")\n    finally:\n        await state.clear()\n\n\n'''
splice(
    "handlers/questions.py",
    "async def _reject_and_save(\n",
    "# Oddiy faktik savollarda",
    new_reject,
)

replace_once(
    "handlers/questions.py",
    '''    app_id = await database.save_application(\n        tenant_id=tenant_id,\n        user_id=message.from_user.id,\n        username=message.from_user.username or "",\n''',
    '''    try:\n        app_id = await database.save_application(\n            tenant_id=tenant_id,\n            user_id=message.from_user.id,\n            submission_key=data.get("submission_key"),\n            username=message.from_user.username or "",\n''',
)
replace_once(
    "handlers/questions.py",
    '''        voice_answers=data.get("voice_answers", {}),\n    )\n\n    await message.answer(t("application_submitted", lang))\n''',
    '''            voice_answers=data.get("voice_answers", {}),\n        )\n    except database.ApplicationLimitReached:\n        await message.answer(\n            "Компания временно приостановила приём новых заявок. Попробуйте позже."\n            if lang == "ru"\n            else "Kompaniya yangi arizalarni qabul qilishni vaqtincha to'xtatgan. Keyinroq urinib ko'ring."\n        )\n        await state.clear()\n        return\n\n    await message.answer(t("application_submitted", lang))\n''',
)

replace_once(
    "handlers/contact.py",
    'import logging\nimport re\n',
    'import asyncio\nimport logging\nimport re\n',
)
replace_once(
    "handlers/contact.py",
    'router = Router(name="contact")\n\n',
    '''router = Router(name="contact")\n\n# Ikki parallel contact/text update bitta arizani ikki marta yakunlamasin.\n_FINISH_LOCKS: dict[tuple[int, int], asyncio.Lock] = {}\n\n\ndef _finish_lock(message: Message) -> asyncio.Lock:\n    key = (message.chat.id, message.from_user.id)\n    lock = _FINISH_LOCKS.get(key)\n    if lock is None:\n        lock = asyncio.Lock()\n        _FINISH_LOCKS[key] = lock\n    return lock\n\n\n''',
)
new_finish_contact = '''async def _finish_contact_collection(message: Message, state: FSMContext, phone: str):\n    from handlers.questions import complete_application\n\n    async with _finish_lock(message):\n        if await state.get_state() != ApplyForm.waiting_phone.state:\n            logger.info(\n                "Dubl yakuniy contact update e'tiborsiz qoldirildi: chat=%s message=%s",\n                message.chat.id,\n                message.message_id,\n            )\n            return\n        data = await state.get_data()\n        lang = data.get("lang", DEFAULT_LANG)\n        await state.update_data(candidate_phone=phone)\n        # Ikkinchi parallel update waiting_phone handleriga kirib ulgurgan bo'lsa\n        # ham lockdan keyin shu holatni ko'rib qaytadi. Ma'lumot clear qilinmaydi.\n        await state.set_state(ApplyForm.finished)\n        await message.answer(t("contact_thanks", lang), reply_markup=ReplyKeyboardRemove())\n        await complete_application(message, state)\n\n\n'''
splice(
    "handlers/contact.py",
    "async def _finish_contact_collection(",
    "@router.message(ApplyForm.waiting_phone, F.contact)\n",
    new_finish_contact,
)


# ---------------------------------------------------------------------------
# 5. Admin bot and Mini App share one atomic candidate-state machine.
# ---------------------------------------------------------------------------
replace_once(
    "admin_bot/handlers_decisions.py",
    '''    _, action, app_id_str = callback.data.split(":")\n    app_id = int(app_id_str)\n\n''',
    '''    try:\n        _, action, app_id_str = callback.data.split(":")\n        app_id = int(app_id_str)\n    except (ValueError, TypeError):\n        await callback.answer("Noto'g'ri amal.", show_alert=True)\n        return\n    if action not in {"save", "accept", "reject"}:\n        await callback.answer("Noto'g'ri amal.", show_alert=True)\n        return\n\n''',
)
replace_once(
    "admin_bot/handlers_decisions.py",
    '''    if action == "save":\n        await database.update_status(tenant_id, app_id, "saved")\n        await callback.answer("🟡 Keyin ko'rish uchun saqlandi")\n        return\n''',
    '''    if action == "save":\n        changed = await database.transition_application_status(\n            tenant_id, app_id, "saved", {"pending", "saved"}\n        )\n        if not changed:\n            await callback.answer("Bu anketa bo'yicha qaror allaqachon qabul qilingan.", show_alert=True)\n            return\n        await callback.answer("🟡 Keyin ko'rish uchun saqlandi")\n        return\n''',
)
replace_once(
    "admin_bot/handlers_decisions.py",
    '''    await database.update_status(tenant_id, app_id, new_status)\n\n    candidate_bot = Bot(token=tenant["bot_token"])\n''',
    '''    changed = await database.transition_application_status(\n        tenant_id, app_id, new_status, {"pending", "saved"}\n    )\n    if not changed:\n        await callback.answer(\n            "Bu anketa bo'yicha boshqa joydan qaror qabul qilindi.", show_alert=True\n        )\n        return\n\n    candidate_bot = Bot(token=tenant["bot_token"])\n''',
)

replace_once(
    "miniapp_api.py",
    'from config import PAYMENT_CARD_HOLDER, PAYMENT_CARD_NUMBER\n',
    'from config import PAYMENT_CARD_HOLDER, PAYMENT_CARD_NUMBER, WEBHOOK_BASE_URL\n',
)
replace_once(
    "miniapp_api.py",
    '''async def health(request: web.Request):\n    return web.json_response({"ok": True, "service": "janob-hr"})\n''',
    '''async def health(request: web.Request):\n    db_ok = await database.healthcheck()\n    configured = bool(WEBHOOK_BASE_URL)\n    payload = {\n        "ok": db_ok and configured,\n        "service": "janob-hr",\n        "database": "ok" if db_ok else "error",\n        "webhook_configured": configured,\n    }\n    return web.json_response(payload, status=200 if payload["ok"] else 503)\n''',
)
replace_once(
    "miniapp_api.py",
    '''    new_status = {"accept": "accepted", "save": "saved", "reject": "declined"}[action]\n    await database.update_status(tenant["id"], app_id, new_status)\n    if action != "save":\n''',
    '''    new_status = {"accept": "accepted", "save": "saved", "reject": "declined"}[action]\n    changed = await database.transition_application_status(\n        tenant["id"], app_id, new_status, {"pending", "saved"}\n    )\n    if not changed:\n        raise web.HTTPConflict(text="Bu nomzod bo'yicha boshqa joydan qaror qabul qilindi.")\n    if action != "save":\n''',
)
replace_once(
    "miniapp_api.py",
    '''    if app["status"] != "accepted":\n        raise web.HTTPConflict(text="Faqat suhbatdagi nomzodni yakunlash mumkin.")\n    await database.update_status(tenant["id"], app_id, outcome)\n    return web.json_response({"ok": True, "status": outcome})\n''',
    '''    if app["status"] != "accepted":\n        raise web.HTTPConflict(text="Faqat suhbatdagi nomzodni yakunlash mumkin.")\n    changed = await database.transition_application_status(\n        tenant["id"], app_id, outcome, {"accepted"}\n    )\n    if not changed:\n        raise web.HTTPConflict(text="Nomzod holati boshqa joydan o'zgartirilgan.")\n    return web.json_response({"ok": True, "status": outcome})\n''',
)
replace_once(
    "miniapp_api.py",
    '    return web.json_response({"ok": True})\nasync def candidate_detail(request: web.Request):\n',
    '    return web.json_response({"ok": True})\n\n\nasync def candidate_detail(request: web.Request):\n',
)


# ---------------------------------------------------------------------------
# 6. Release regression tests: cross-channel logic and data integrity.
# ---------------------------------------------------------------------------
market_tests = r'''import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiogram.types import Message

import webhook_app
from admin_bot.handlers_menu import ADMIN_MENU, _service_keyboard, service_panel
from services import database


class MarketReadyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "market.db")
        self.path_patch = patch.object(database, "SQLITE_PATH", self.db_path)
        self.path_patch.start()
        await database.init_db()
        self.tenant_id = await database.create_tenant(
            "Market Test", "candidate-token", "admin-token", [777]
        )

    async def asyncTearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    async def _save(self, key: str, *, user_id: int = 1) -> int:
        return await database.save_application(
            tenant_id=self.tenant_id,
            user_id=user_id,
            submission_key=key,
            username="test",
            full_name="Test User",
            vacancy_key="sales",
            vacancy_title="Sales",
            answers={},
            ai_scores={},
            resume_file_id=None,
            video_file_id=None,
            status="pending",
        )

    async def test_admin_persistent_panel_button_is_not_reply_webapp(self):
        markup = _service_keyboard(self.tenant_id)
        button = markup.keyboard[0][0]
        self.assertEqual(button.text, ADMIN_MENU["panel"])
        self.assertIsNone(button.web_app)

    async def test_admin_panel_text_button_returns_inline_webapp(self):
        message = type("FakeMessage", (), {"answer": AsyncMock()})()
        with (
            patch("admin_bot.handlers_menu.WEBHOOK_BASE_URL", "https://example.test"),
            patch("admin_bot.handlers_menu.MINI_APP_BASE_URL", ""),
        ):
            await service_panel(message, self.tenant_id)
        markup = message.answer.await_args.kwargs["reply_markup"]
        self.assertEqual(
            markup.inline_keyboard[0][0].web_app.url,
            f"https://example.test/miniapp/{self.tenant_id}",
        )

    async def test_submission_key_is_idempotent(self):
        first = await self._save("same-key", user_id=10)
        second = await self._save("same-key", user_id=10)
        self.assertEqual(first, second)
        _, total = await database.list_applications(self.tenant_id, limit=20)
        self.assertEqual(total, 1)

    async def test_trial_limit_is_enforced_inside_save_transaction(self):
        for index in range(5):
            await self._save(f"key-{index}", user_id=100 + index)
        with self.assertRaises(database.ApplicationLimitReached):
            await self._save("sixth", user_id=999)
        _, total = await database.list_applications(self.tenant_id, limit=20)
        self.assertEqual(total, 5)

    async def test_only_one_competing_admin_decision_wins(self):
        app_id = await self._save("decision-key")
        accepted = await database.transition_application_status(
            self.tenant_id, app_id, "accepted", {"pending", "saved"}
        )
        declined = await database.transition_application_status(
            self.tenant_id, app_id, "declined", {"pending", "saved"}
        )
        self.assertTrue(accepted)
        self.assertFalse(declined)
        app = await database.get_application(self.tenant_id, app_id)
        self.assertEqual(app["status"], "accepted")

    async def test_auto_slot_booking_moves_pending_candidate_to_accepted(self):
        app_id = await self._save("slot-key")
        booked = await database.try_book_slot(
            self.tenant_id, app_id, "2026-09-05 10:00", 1
        )
        repeated = await database.try_book_slot(
            self.tenant_id, app_id, "2026-09-05 10:00", 1
        )
        self.assertTrue(booked)
        self.assertTrue(repeated)
        app = await database.get_application(self.tenant_id, app_id)
        self.assertEqual(app["status"], "accepted")
        self.assertEqual(app["selected_slot"], "2026-09-05 10:00")

    async def test_database_healthcheck_is_real(self):
        self.assertTrue(await database.healthcheck())

    def test_webhook_startup_does_not_drop_pending_updates(self):
        source = Path("webhook_app.py").read_text(encoding="utf-8")
        self.assertIn("drop_pending_updates=False", source)
        self.assertNotIn("drop_pending_updates=True", source)


if __name__ == "__main__":
    unittest.main()
'''
write("tests/test_market_ready.py", market_tests)

print("Market-ready hardening patch applied.")
