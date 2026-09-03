from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise RuntimeError(f"Expected block not found in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def splice(path: str, start_marker: str, end_marker: str, replacement: str) -> None:
    text = read(path)
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    write(path, text[:start] + replacement + text[end:])


# ---------------------------------------------------------------------------
# 1) Database business rules: vacancy quotas, interview slot integrity,
#    payment expiry on reads/reminders, and clean trial provisioning.
# ---------------------------------------------------------------------------
replace_once(
    "services/database.py",
    '''class ApplicationLimitReached(RuntimeError):\n    """Tarif ariza limiti atomik saqlash paytida tugagan."""\n\n\n''',
    '''class ApplicationLimitReached(RuntimeError):\n    """Tarif ariza limiti atomik saqlash paytida tugagan."""\n\n\nclass VacancyLimitReached(RuntimeError):\n    """Faol vakansiyalar limiti DB transaction ichida tugagan."""\n\n\nclass InterviewSlotConflict(RuntimeError):\n    """Bir tenant ichida bir xil faol suhbat vaqti qayta yaratildi."""\n\n\nclass InterviewSlotBooked(RuntimeError):\n    """Band qilingan suhbat vaqtini o'chirishga urinish."""\n\n\n''',
)

# New customer bots should not start above the trial vacancy limit with generic
# demo vacancies. Keep schema/examples in code for legacy compatibility, but do
# not seed them into new customer accounts.
old_create_tenant = '''async def create_tenant(\n    company_name: str,\n    bot_token: str,\n    admin_bot_token: str,\n    admin_user_ids: list[int],\n    contact_name: str = "",\n    contact_phone: str = "",\n    contact_username: str = "",\n) -> int:\n    """Yangi mijoz yaratadi va unga standart 3 ta namunaviy vakansiyani urug'laydi.\n    Ikkita alohida token oladi: `bot_token` — nomzod-bot uchun, `admin_bot_token` —\n    faqat shu mijozning administratorlari ishlatadigan Admin panel-bot uchun."""\n    created_at = datetime.now(timezone.utc).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        cursor = await db.execute(\n            "INSERT INTO tenants (company_name, bot_token, admin_bot_token, admin_user_ids, "\n            "contact_name, contact_phone, contact_username, status, created_at) "\n            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",\n            (\n                company_name,\n                bot_token,\n                admin_bot_token,\n                json.dumps(admin_user_ids),\n                contact_name,\n                contact_phone,\n                contact_username,\n                created_at,\n            ),\n        )\n        tenant_id = cursor.lastrowid\n\n        for v in _DEFAULT_VACANCIES:\n            await db.execute(\n                "INSERT INTO vacancies (tenant_id, key, title, reject_message, questions, "\n                "resume_required, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",\n                (\n                    tenant_id,\n                    v["key"],\n                    v["title"],\n                    v["reject_message"],\n                    json.dumps(v["questions"], ensure_ascii=False),\n                    int(v["resume_required"]),\n                    created_at,\n                ),\n            )\n        await db.commit()\n    logger.info("Yangi mijoz yaratildi: id=%s, %s", tenant_id, company_name)\n    return tenant_id\n\n\n'''
new_create_tenant = '''async def create_tenant(\n    company_name: str,\n    bot_token: str,\n    admin_bot_token: str,\n    admin_user_ids: list[int],\n    contact_name: str = "",\n    contact_phone: str = "",\n    contact_username: str = "",\n) -> int:\n    """Yangi mijozni toza workspace bilan yaratadi.\n\n    Trial 1 ta faol vakansiyaga ruxsat beradi. Avvalgi 3 ta umumiy demo\n    vakansiyani avtomatik aktiv yaratish yangi tenantni tug'ilishi bilan limitdan\n    oshirib qo'yardi va mijoz o'z vakansiyasini yaratolmasdi. Endi tenant bo'sh\n    boshlanadi; birinchi vakansiyani Admin bot yoki Mini App onboarding yaratadi.\n    """\n    created_at = datetime.now(timezone.utc).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        cursor = await db.execute(\n            "INSERT INTO tenants (company_name, bot_token, admin_bot_token, admin_user_ids, "\n            "contact_name, contact_phone, contact_username, status, created_at) "\n            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",\n            (\n                company_name,\n                bot_token,\n                admin_bot_token,\n                json.dumps(admin_user_ids),\n                contact_name,\n                contact_phone,\n                contact_username,\n                created_at,\n            ),\n        )\n        tenant_id = cursor.lastrowid\n        await db.commit()\n    logger.info("Yangi mijoz yaratildi: id=%s, %s", tenant_id, company_name)\n    return tenant_id\n\n\n'''
replace_once("services/database.py", old_create_tenant, new_create_tenant)

new_get_payment_order = '''async def get_payment_order_for_tenant(tenant_id: int, order_code: str) -> dict | None:\n    now_iso = datetime.now(timezone.utc).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        db.row_factory = aiosqlite.Row\n        # UI polling eski orderni hali ham "kutilmoqda" deb ko'rsatmasin.\n        await db.execute(\n            "UPDATE payment_orders SET status='expired', "\n            "decided_at=COALESCE(decided_at, ?) "\n            "WHERE tenant_id=? AND UPPER(order_code)=UPPER(?) "\n            "AND status='awaiting_payment' AND expires_at<=?",\n            (now_iso, tenant_id, order_code.strip(), now_iso),\n        )\n        cursor = await db.execute(\n            "SELECT * FROM payment_orders WHERE tenant_id=? AND UPPER(order_code)=UPPER(?) LIMIT 1",\n            (tenant_id, order_code.strip()),\n        )\n        row = await cursor.fetchone()\n        await db.commit()\n    return dict(row) if row else None\n\n\n'''
splice(
    "services/database.py",
    "async def get_payment_order_for_tenant(tenant_id: int, order_code: str) -> dict | None:\n",
    "async def list_due_lead_reminders(",
    new_get_payment_order,
)

new_list_unpaid = '''async def list_unpaid_orders_older_than(minutes: int) -> list[dict]:\n    now = datetime.now(timezone.utc)\n    now_iso = now.isoformat()\n    cutoff = (now - timedelta(minutes=minutes)).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        db.row_factory = aiosqlite.Row\n        # Reminder sikli payment parser ishlamasa ham TTLni o'zi hurmat qiladi.\n        await db.execute(\n            "UPDATE payment_orders SET status='expired', "\n            "decided_at=COALESCE(decided_at, ?) "\n            "WHERE status='awaiting_payment' AND expires_at<=?",\n            (now_iso, now_iso),\n        )\n        cursor = await db.execute(\n            "SELECT p.*, t.company_name, t.contact_phone FROM payment_orders p "\n            "JOIN tenants t ON t.id=p.tenant_id "\n            "WHERE p.status='awaiting_payment' AND p.created_at <= ? AND p.expires_at > ? "\n            "ORDER BY p.created_at LIMIT 100",\n            (cutoff, now_iso),\n        )\n        rows = [dict(row) for row in await cursor.fetchall()]\n        await db.commit()\n        return rows\n\n\n'''
splice(
    "services/database.py",
    "async def list_unpaid_orders_older_than(minutes: int) -> list[dict]:\n",
    "async def mark_lead_reminded(",
    new_list_unpaid,
)

new_create_vacancy = '''async def create_vacancy(\n    *,\n    tenant_id: int,\n    key: str,\n    title: str,\n    reject_message: str,\n    questions: list,\n    resume_required: bool,\n    profile: dict | None = None,\n) -> None:\n    """Faol vakansiyani tarif limitiga nisbatan atomik yaratadi."""\n    from services.plans import get_plan\n\n    created_at = datetime.now(timezone.utc).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:\n        await db.execute("PRAGMA busy_timeout=5000")\n        await db.execute("BEGIN IMMEDIATE")\n        try:\n            cursor = await db.execute(\n                "SELECT plan_code, subscription_expires_at FROM tenants WHERE id=?",\n                (tenant_id,),\n            )\n            tenant = await cursor.fetchone()\n            if not tenant:\n                raise ValueError("Mijoz topilmadi")\n            plan = get_plan(tenant[0])\n            expires_at = tenant[1]\n            expired = bool(\n                plan.code not in {"trial", "legacy"}\n                and (not expires_at or expires_at <= created_at)\n            )\n            if expired:\n                raise VacancyLimitReached("Tarif muddati tugagan")\n            if plan.vacancy_limit is not None:\n                cursor = await db.execute(\n                    "SELECT COUNT(*) FROM vacancies WHERE tenant_id=? AND active=1",\n                    (tenant_id,),\n                )\n                used = (await cursor.fetchone())[0]\n                if used >= plan.vacancy_limit:\n                    raise VacancyLimitReached("Tarifdagi vakansiya limiti tugagan")\n\n            await db.execute(\n                "INSERT INTO vacancies (tenant_id, key, title, reject_message, questions, "\n                "resume_required, active, profile_json, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",\n                (\n                    tenant_id,\n                    key,\n                    title,\n                    reject_message,\n                    json.dumps(questions, ensure_ascii=False),\n                    int(resume_required),\n                    json.dumps(profile or {}, ensure_ascii=False),\n                    created_at,\n                ),\n            )\n            await db.commit()\n        except Exception:\n            await db.rollback()\n            raise\n\n\nasync def set_vacancy_active(tenant_id: int, key: str, active: bool) -> bool:\n    """Vakansiyani atomik faollashtiradi/faolsizlantiradi va quota bypassni yopadi."""\n    from services.plans import get_plan\n\n    now_iso = datetime.now(timezone.utc).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:\n        await db.execute("PRAGMA busy_timeout=5000")\n        await db.execute("BEGIN IMMEDIATE")\n        try:\n            cursor = await db.execute(\n                "SELECT active FROM vacancies WHERE tenant_id=? AND key=?",\n                (tenant_id, key),\n            )\n            row = await cursor.fetchone()\n            if not row:\n                await db.rollback()\n                return False\n            current = bool(row[0])\n            if current == bool(active):\n                await db.commit()\n                return True\n\n            if active:\n                cursor = await db.execute(\n                    "SELECT plan_code, subscription_expires_at FROM tenants WHERE id=?",\n                    (tenant_id,),\n                )\n                tenant = await cursor.fetchone()\n                if not tenant:\n                    raise ValueError("Mijoz topilmadi")\n                plan = get_plan(tenant[0])\n                expires_at = tenant[1]\n                expired = bool(\n                    plan.code not in {"trial", "legacy"}\n                    and (not expires_at or expires_at <= now_iso)\n                )\n                if expired:\n                    raise VacancyLimitReached("Tarif muddati tugagan")\n                if plan.vacancy_limit is not None:\n                    cursor = await db.execute(\n                        "SELECT COUNT(*) FROM vacancies WHERE tenant_id=? AND active=1",\n                        (tenant_id,),\n                    )\n                    used = (await cursor.fetchone())[0]\n                    if used >= plan.vacancy_limit:\n                        raise VacancyLimitReached("Tarifdagi vakansiya limiti tugagan")\n\n            cursor = await db.execute(\n                "UPDATE vacancies SET active=? WHERE tenant_id=? AND key=?",\n                (int(bool(active)), tenant_id, key),\n            )\n            await db.commit()\n            return cursor.rowcount > 0\n        except Exception:\n            await db.rollback()\n            raise\n\n\n'''
splice(
    "services/database.py",
    "async def create_vacancy(\n",
    "async def update_vacancy(",
    new_create_vacancy,
)

new_slot_functions = '''async def add_interview_slot(\n    tenant_id: int, label: str, capacity: int = 1, starts_at: str | None = None\n) -> int:\n    label = str(label or "").strip()\n    if not 3 <= len(label) <= 80:\n        raise ValueError("Suhbat vaqti nomi 3–80 belgi bo'lishi kerak")\n    if not 1 <= int(capacity) <= 100:\n        raise ValueError("Suhbat sig'imi 1–100 oralig'ida bo'lishi kerak")\n    created_at = datetime.now(timezone.utc).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:\n        await db.execute("PRAGMA busy_timeout=5000")\n        await db.execute("BEGIN IMMEDIATE")\n        try:\n            cursor = await db.execute(\n                "SELECT 1 FROM interview_slots WHERE tenant_id=? AND active=1 "\n                "AND LOWER(label)=LOWER(?) LIMIT 1",\n                (tenant_id, label),\n            )\n            if await cursor.fetchone():\n                raise InterviewSlotConflict("Bu suhbat vaqti allaqachon mavjud")\n            cursor = await db.execute(\n                "INSERT INTO interview_slots (tenant_id, label, capacity, starts_at, active, created_at) "\n                "VALUES (?, ?, ?, ?, 1, ?)",\n                (tenant_id, label, int(capacity), starts_at, created_at),\n            )\n            await db.commit()\n            return cursor.lastrowid\n        except Exception:\n            await db.rollback()\n            raise\n\n\nasync def delete_interview_slot(tenant_id: int, slot_id: int) -> bool:\n    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:\n        await db.execute("PRAGMA busy_timeout=5000")\n        await db.execute("BEGIN IMMEDIATE")\n        try:\n            cursor = await db.execute(\n                "SELECT label FROM interview_slots WHERE id=? AND tenant_id=?",\n                (slot_id, tenant_id),\n            )\n            row = await cursor.fetchone()\n            if not row:\n                await db.rollback()\n                return False\n            label = row[0]\n            cursor = await db.execute(\n                "SELECT COUNT(*) FROM applications WHERE tenant_id=? AND selected_slot=?",\n                (tenant_id, label),\n            )\n            booked = (await cursor.fetchone())[0]\n            if booked:\n                raise InterviewSlotBooked("Bu vaqtni nomzod tanlagan")\n            cursor = await db.execute(\n                "DELETE FROM interview_slots WHERE id=? AND tenant_id=?",\n                (slot_id, tenant_id),\n            )\n            await db.commit()\n            return cursor.rowcount > 0\n        except Exception:\n            await db.rollback()\n            raise\n\n\n'''
splice(
    "services/database.py",
    "async def add_interview_slot(\n",
    "async def get_available_interview_slots(",
    new_slot_functions,
)

# ---------------------------------------------------------------------------
# 2) Admin billing must obey the same transition rules as Mini App/payment.
# ---------------------------------------------------------------------------
replace_once(
    "admin_bot/handlers_billing.py",
    "from services.plans import PUBLIC_PLAN_CODES, format_som, get_plan\n",
    "from services.plans import PUBLIC_PLAN_CODES, format_som, get_plan, get_plan_transition\n",
)
replace_once(
    "admin_bot/handlers_billing.py",
    '''    plan = get_plan(code)\n    order = await create_payment_order(tenant_id, plan.price, plan_code=code)\n''',
    '''    usage = await database.get_subscription_usage(tenant_id)\n    transition = get_plan_transition(\n        usage["plan"].code, code, current_expired=usage["expired"]\n    )\n    if transition == "blocked":\n        expiry = (usage.get("expires_at") or "")[:10]\n        suffix = f" ({expiry} gacha)" if expiry else ""\n        await callback.answer(\n            f"{usage['plan'].name} tarifi{suffix} faol. Past tarifni muddat tugagach tanlang.",\n            show_alert=True,\n        )\n        return\n    plan = get_plan(code)\n    order = await create_payment_order(tenant_id, plan.price, plan_code=code)\n''',
)
replace_once(
    "admin_bot/handlers_billing.py",
    '''        "cancelled": "❌ Buyurtma bekor qilingan",\n    }\n''',
    '''        "cancelled": "❌ Buyurtma bekor qilingan",\n        "expired": "⌛ Buyurtma muddati tugagan — yangi buyurtma oching",\n    }\n''',
)

# ---------------------------------------------------------------------------
# 3) Vacancy UI must not bypass quota when reactivating or finalizing.
# ---------------------------------------------------------------------------
replace_once(
    "admin_bot/handlers_vacancy_list.py",
    '''    await database.update_vacancy(tenant_id, key, active=not vacancy["active"])\n    await _show_vacancy_detail(callback, tenant_id, key)\n''',
    '''    try:\n        await database.set_vacancy_active(tenant_id, key, not vacancy["active"])\n    except database.VacancyLimitReached:\n        await callback.answer(\n            "Tarifdagi faol vakansiya limiti tugagan. Avval boshqa vakansiyani yoping yoki tarifni oshiring.",\n            show_alert=True,\n        )\n        return\n    await _show_vacancy_detail(callback, tenant_id, key)\n''',
)
replace_once(
    "admin_bot/handlers_vacancy_list.py",
    '''    "rejected_irrelevant": "❌ Mavzuga mos kelmadi",\n}\n''',
    '''    "rejected_irrelevant": "❌ Mavzuga mos kelmadi",\n    "rejected_ai_generated": "❌ Shubhali javob",\n    "saved": "🟡 Keyin ko'rish",\n    "hired": "✅ Ishga olindi",\n    "not_hired": "❌ Ishga olinmadi",\n    "no_show": "🚫 Suhbatga kelmadi",\n}\n''',
)
replace_once(
    "admin_bot/handlers_candidates.py",
    '''    "rejected_ai_generated": "⛔ Shubhali javob",\n}\n''',
    '''    "rejected_ai_generated": "⛔ Shubhali javob",\n    "hired": "✅ Ishga olindi",\n    "not_hired": "❌ Ishga olinmadi",\n    "no_show": "🚫 Suhbatga kelmadi",\n}\n''',
)

replace_once(
    "admin_bot/handlers_vacancy_edit.py",
    '''        await database.create_vacancy(\n            tenant_id=tenant_id,\n            key=key,\n            title=title,\n            reject_message=_DEFAULT_REJECT_MESSAGE,\n            questions=questions,\n            resume_required=True,\n        )\n        result_text = (\n''',
    '''        try:\n            await database.create_vacancy(\n                tenant_id=tenant_id,\n                key=key,\n                title=title,\n                reject_message=_DEFAULT_REJECT_MESSAGE,\n                questions=questions,\n                resume_required=True,\n            )\n        except database.VacancyLimitReached:\n            await state.clear()\n            builder = InlineKeyboardBuilder()\n            builder.button(text="💳 Tarif va limitlar", callback_data="menu:billing")\n            builder.button(text="📋 Vakansiyalar", callback_data="menu:vacancies")\n            builder.adjust(1)\n            await message.answer(\n                "🔒 Bu orada faol vakansiya limiti band bo'ldi. Boshqa vakansiyani yoping yoki tarifni oshiring.",\n                reply_markup=builder.as_markup(),\n            )\n            return\n        result_text = (\n''',
)
replace_once(
    "admin_bot/handlers_vacancy_edit.py",
    '"🔒 <b>Vakansiya limiti tugagan</b>\\n\\nTarifni yangilang yoki mavjud vakansiyalardan birini o\'chiring.",\n',
    '"🔒 <b>Vakansiya limiti tugagan</b>\\n\\nTarifni oshiring yoki mavjud faol vakansiyalardan birini vaqtincha yoping.",\n',
)

# ---------------------------------------------------------------------------
# 4) Interview decisions/slots must have the same semantics in both UIs.
# ---------------------------------------------------------------------------
replace_once(
    "admin_bot/handlers_decisions.py",
    '''    if action == "accept":\n        new_status = "accepted"\n        result_label = "✅ Suhbatga chaqirildi"\n''',
    '''    if action == "accept":\n        if not await database.get_available_interview_slots(tenant_id):\n            await callback.answer(\n                "Avval 📅 Suhbatlar bo'limidan kamida bitta bo'sh vaqt qo'shing.",\n                show_alert=True,\n            )\n            return\n        new_status = "accepted"\n        result_label = "✅ Suhbatga chaqirildi"\n''',
)

replace_once(
    "handlers/sell.py",
    '''    app = await database.get_application(tenant_id, app_id)\n    lang = (app or {}).get("lang", DEFAULT_LANG)\n\n    all_slots = await database.list_interview_slots(tenant_id, active_only=True)\n''',
    '''    app = await database.get_application(tenant_id, app_id)\n    lang = (app or {}).get("lang", DEFAULT_LANG)\n    if (\n        not app\n        or app.get("user_id") != callback.from_user.id\n        or app.get("status") not in {"pending", "saved", "accepted"}\n    ):\n        await callback.answer("Bu suhbat taklifi endi faol emas.", show_alert=True)\n        try:\n            await callback.message.edit_reply_markup(reply_markup=None)\n        except Exception:\n            logger.exception("Eski suhbat tugmasini olib tashlab bo'lmadi (app_id=%s).", app_id)\n        return\n\n    all_slots = await database.list_interview_slots(tenant_id, active_only=True)\n''',
)

replace_once(
    "admin_bot/handlers_interview.py",
    '''async def receive_slot_label(message: Message, state: FSMContext):\n    await state.update_data(new_slot_label=message.text.strip())\n    await message.answer("Bu vaqtga nechta nomzod qabul qilinishi mumkin? (Odatda: 1)")\n''',
    '''async def receive_slot_label(message: Message, state: FSMContext):\n    label = message.text.strip()\n    if not 3 <= len(label) <= 80:\n        await message.answer("Sana/vaqtni 3–80 belgi oralig'ida aniq yozing.")\n        return\n    await state.update_data(new_slot_label=label)\n    await message.answer("Bu vaqtga nechta nomzod qabul qilinishi mumkin? (Odatda: 1)")\n''',
)
replace_once(
    "admin_bot/handlers_interview.py",
    '''    if not text.isdigit() or int(text) < 1:\n        await message.answer("Iltimos, musbat butun son kiriting (masalan: 1).")\n        return\n\n    data = await state.get_data()\n    await database.add_interview_slot(\n        tenant_id, data["new_slot_label"], capacity=int(text)\n    )\n    await message.answer(f"✅ Qo'shildi: {data['new_slot_label']} (sig'imi: {text})")\n''',
    '''    if not text.isdigit() or not 1 <= int(text) <= 100:\n        await message.answer("Sig'im 1 dan 100 gacha butun son bo'lishi kerak.")\n        return\n\n    data = await state.get_data()\n    try:\n        await database.add_interview_slot(\n            tenant_id, data["new_slot_label"], capacity=int(text)\n        )\n    except database.InterviewSlotConflict:\n        await message.answer("Bu suhbat vaqti allaqachon mavjud. Boshqa vaqt yozing.")\n        await state.set_state(InterviewForm.adding_slot_label)\n        return\n    await message.answer(f"✅ Qo'shildi: {data['new_slot_label']} (sig'imi: {text})")\n''',
)
replace_once(
    "admin_bot/handlers_interview.py",
    '''    slot_id = int(callback.data.split(":")[2])\n    await database.delete_interview_slot(tenant_id, slot_id)\n    await callback.answer("O'chirildi.")\n''',
    '''    try:\n        slot_id = int(callback.data.split(":")[2])\n    except (ValueError, IndexError):\n        await callback.answer("Noto'g'ri vaqt.", show_alert=True)\n        return\n    try:\n        deleted = await database.delete_interview_slot(tenant_id, slot_id)\n    except database.InterviewSlotBooked:\n        await callback.answer(\n            "Bu vaqtni nomzod tanlagan. Band suhbat vaqtini o'chirib bo'lmaydi.",\n            show_alert=True,\n        )\n        return\n    if not deleted:\n        await callback.answer("Bu vaqt allaqachon o'chirilgan.", show_alert=True)\n        return\n    await callback.answer("O'chirildi.")\n''',
)

# ---------------------------------------------------------------------------
# 5) Mini App mirrors the same vacancy/interview rules.
# ---------------------------------------------------------------------------
replace_once(
    "miniapp_api.py",
    '''    allowed = {None, "pending", "saved", "accepted", "declined"}\n''',
    '''    allowed = {\n        None,\n        "pending",\n        "saved",\n        "accepted",\n        "declined",\n        "rejected_hard_filter",\n        "rejected_irrelevant",\n        "rejected_ai_generated",\n        "hired",\n        "not_hired",\n        "no_show",\n    }\n''',
)
replace_once(
    "miniapp_api.py",
    '''    existing = await database.list_interview_slots(tenant["id"], active_only=True)\n    if any(item["label"].casefold() == label.casefold() for item in existing):\n        raise web.HTTPConflict(text="Bu suhbat vaqti allaqachon mavjud.")\n    if starts_at:\n        slot_id = await database.add_interview_slot(\n            tenant["id"], label, capacity, starts_at=starts_at\n        )\n    else:\n        # Eski erkin-format slotlar ham ishlashda davom etadi.\n        slot_id = await database.add_interview_slot(tenant["id"], label, capacity)\n''',
    '''    existing = await database.list_interview_slots(tenant["id"], active_only=True)\n    if any(item["label"].casefold() == label.casefold() for item in existing):\n        raise web.HTTPConflict(text="Bu suhbat vaqti allaqachon mavjud.")\n    try:\n        if starts_at:\n            slot_id = await database.add_interview_slot(\n                tenant["id"], label, capacity, starts_at=starts_at\n            )\n        else:\n            # Eski erkin-format slotlar ham ishlashda davom etadi.\n            slot_id = await database.add_interview_slot(tenant["id"], label, capacity)\n    except database.InterviewSlotConflict as exc:\n        raise web.HTTPConflict(text="Bu suhbat vaqti allaqachon mavjud.") from exc\n''',
)
replace_once(
    "miniapp_api.py",
    '''    await database.delete_interview_slot(tenant["id"], slot_id)\n    return web.json_response({"ok": True})\n''',
    '''    try:\n        deleted = await database.delete_interview_slot(tenant["id"], slot_id)\n    except database.InterviewSlotBooked as exc:\n        raise web.HTTPConflict(\n            text="Bu vaqtni nomzod tanlagan. Avval suhbatni boshqa vaqtga ko'chiring."\n        ) from exc\n    if not deleted:\n        raise web.HTTPNotFound(text="Suhbat vaqti topilmadi.")\n    return web.json_response({"ok": True})\n''',
)
replace_once(
    "miniapp_api.py",
    '''    new_status = {"accept": "accepted", "save": "saved", "reject": "declined"}[action]\n    changed = await database.transition_application_status(\n''',
    '''    if action == "accept" and not await database.get_available_interview_slots(tenant["id"]):\n        raise web.HTTPConflict(\n            text="Avval Suhbatlar bo'limidan kamida bitta bo'sh vaqt qo'shing."\n        )\n    new_status = {"accept": "accepted", "save": "saved", "reject": "declined"}[action]\n    changed = await database.transition_application_status(\n''',
)
replace_once(
    "miniapp_api.py",
    '''    if app["status"] != "accepted":\n        raise web.HTTPConflict(text="Faqat suhbatdagi nomzodni yakunlash mumkin.")\n    changed = await database.transition_application_status(\n''',
    '''    if app["status"] != "accepted":\n        raise web.HTTPConflict(text="Faqat suhbatdagi nomzodni yakunlash mumkin.")\n    if outcome == "no_show" and not app.get("selected_slot"):\n        raise web.HTTPConflict(text="Suhbat vaqti tanlanmagan nomzodni 'kelmadi' deb belgilab bo'lmaydi.")\n    changed = await database.transition_application_status(\n''',
)
replace_once(
    "miniapp_api.py",
    '''    await database.create_vacancy(\n        tenant_id=tenant["id"],\n        key=key,\n        title=role,\n        reject_message=(\n            "Arizangiz uchun rahmat. Hozircha ushbu vakansiya bo'yicha keyingi bosqichga "\n            "o'tmadingiz. Sizga muvaffaqiyat tilaymiz!"\n        ),\n        questions=questions,\n        resume_required=False,\n        profile=profile,\n    )\n''',
    '''    try:\n        await database.create_vacancy(\n            tenant_id=tenant["id"],\n            key=key,\n            title=role,\n            reject_message=(\n                "Arizangiz uchun rahmat. Hozircha ushbu vakansiya bo'yicha keyingi bosqichga "\n                "o'tmadingiz. Sizga muvaffaqiyat tilaymiz!"\n            ),\n            questions=questions,\n            resume_required=False,\n            profile=profile,\n        )\n    except database.VacancyLimitReached as exc:\n        raise web.HTTPPaymentRequired(text="Tarifdagi vakansiya limiti tugagan.") from exc\n''',
)
replace_once(
    "miniapp_api.py",
    '''    await database.create_vacancy(\n        tenant_id=tenant["id"],\n        key=key,\n        title=title,\n        reject_message=reject_message,\n        questions=questions,\n        resume_required=bool(body.get("resume_required")),\n    )\n    return web.json_response({"ok": True, "key": key}, status=201)\n''',
    '''    try:\n        await database.create_vacancy(\n            tenant_id=tenant["id"],\n            key=key,\n            title=title,\n            reject_message=reject_message,\n            questions=questions,\n            resume_required=bool(body.get("resume_required")),\n        )\n    except database.VacancyLimitReached as exc:\n        raise web.HTTPPaymentRequired(text="Tarifdagi vakansiya limiti tugagan.") from exc\n    return web.json_response({"ok": True, "key": key}, status=201)\n''',
)
replace_once(
    "miniapp_api.py",
    '''    await database.update_vacancy(tenant["id"], key, active=not vacancy["active"])\n    return web.json_response({"ok": True, "active": not vacancy["active"]})\n''',
    '''    target = not vacancy["active"]\n    try:\n        changed = await database.set_vacancy_active(tenant["id"], key, target)\n    except database.VacancyLimitReached as exc:\n        raise web.HTTPPaymentRequired(\n            text="Tarifdagi faol vakansiya limiti tugagan. Boshqa vakansiyani yoping yoki tarifni oshiring."\n        ) from exc\n    if not changed:\n        raise web.HTTPNotFound(text="Vakansiya topilmadi.")\n    return web.json_response({"ok": True, "active": target})\n''',
)

# ---------------------------------------------------------------------------
# 6) Expired payment UI must explicitly say not to pay an old amount.
# ---------------------------------------------------------------------------
replace_once(
    "miniapp/app.js",
    "const labels={awaiting_payment:'To‘lov kutilmoqda',approved:'To‘lov qabul qilindi',needs_review:'Qo‘lda tekshirilmoqda',cancelled:'Buyurtma bekor qilingan'};",
    "const labels={awaiting_payment:'To‘lov kutilmoqda',approved:'To‘lov qabul qilindi',needs_review:'Qo‘lda tekshirilmoqda',cancelled:'Buyurtma bekor qilingan',expired:'Buyurtma muddati tugagan'};",
)
replace_once(
    "miniapp/app.js",
    '''<p class="payment-note">Aynan ko‘rsatilgan summani yuboring. Tizim to‘lovni avtomatik aniqlab tarifni yoqadi.</p><button class="payment-check" data-check-order="${esc(order.order_code)}">To‘lovni tekshirish</button>''',
    '''${order.status==='expired'?'<p class="payment-note">Bu buyurtma muddati tugagan. Eski summaga to‘lov qilmang — yangi buyurtma yarating.</p>':`<p class="payment-note">Aynan ko‘rsatilgan summani yuboring. Tizim to‘lovni avtomatik aniqlab tarifni yoqadi.</p><button class="payment-check" data-check-order="${esc(order.order_code)}">To‘lovni tekshirish</button>`}''',
)

# ---------------------------------------------------------------------------
# 7) Reminder copy reflects the real behavior: admin stays accessible, but
#    NEW applications stop when the paid plan expires.
# ---------------------------------------------------------------------------
replace_once(
    "services/reminders.py",
    '''                        body = (\n                            "Botlar ishlashini davom ettirish uchun tarifni yangilang."\n                        )\n''',
    '''                        body = (\n                            "Yangi nomzod arizalarini yana qabul qilish uchun tarifni yangilang."\n                        )\n''',
)
replace_once(
    "services/reminders.py",
    '''                        body = "Uzilish bo'lmasligi uchun tarifni bugun yangilang."\n''',
    '''                        body = "Yangi arizalar to'xtab qolmasligi uchun tarifni bugun yangilang."\n''',
)
replace_once(
    "services/reminders.py",
    '''                        body = "Botlar to'xtab qolmasligi uchun tarifni yangilang."\n''',
    '''                        body = "Yangi arizalar qabul qilish to'xtamasligi uchun tarifni yangilang."\n''',
)

# ---------------------------------------------------------------------------
# 8) Provisioning success must tell a clean new tenant what the next logical
#    step is now that generic demo vacancies are no longer auto-seeded.
# ---------------------------------------------------------------------------
replace_once(
    "handlers/create_bot.py",
    '''        "🎁 Birinchi 5 ta ariza bepul va botlaringiz hozirdanoq faol.\\n"\n        f"Tarif va limitlarni @{activated_admin_username} ichidagi <b>💳 Tarif va limitlar</b> bo'limidan boshqarasiz."\n''',
    '''        "🎁 Birinchi 5 ta ariza bepul va botlaringiz hozirdanoq faol.\\n\\n"\n        f"⚙️ <b>Keyingi qadam:</b> @{activated_admin_username} ga /start yuboring, "\n        "Boshqaruv panelida o'zingizning birinchi vakansiyangizni yarating. "\n        "Shundan keyin u nomzod-botda ko'rinadi.\\n\\n"\n        f"Tarif va limitlarni @{activated_admin_username} ichidagi <b>💳 Tarif va limitlar</b> bo'limidan boshqarasiz."\n''',
)

# ---------------------------------------------------------------------------
# Regression tests for the business rules above.
# ---------------------------------------------------------------------------
tests = r'''import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import aiosqlite
from aiohttp import web

from admin_bot import handlers_billing
from miniapp_api import candidate_decision
from services import database
from services.plans import get_plan


class LogicReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "logic.db")
        self.db_patch = patch.object(database, "SQLITE_PATH", self.db_path)
        self.db_patch.start()
        await database.init_db()
        self.tenant_id = await database.create_tenant(
            "Logic Test", "candidate-token", "admin-token", [777]
        )

    async def asyncTearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    async def _save_app(self, key: str = "app") -> int:
        return await database.save_application(
            tenant_id=self.tenant_id,
            user_id=123,
            submission_key=key,
            username="user",
            full_name="Test Candidate",
            vacancy_key="sales",
            vacancy_title="Sales",
            answers={},
            ai_scores={},
            resume_file_id=None,
            video_file_id=None,
            status="pending",
        )

    async def test_new_trial_tenant_starts_with_clean_vacancy_workspace(self):
        active = await database.list_vacancies(self.tenant_id, active_only=True)
        self.assertEqual(active, [])
        usage = await database.get_subscription_usage(self.tenant_id)
        self.assertEqual(usage["vacancies_used"], 0)
        self.assertTrue(usage["vacancies_available"])

    async def test_vacancy_limit_cannot_be_bypassed_by_create_or_reactivate(self):
        await database.create_vacancy(
            tenant_id=self.tenant_id,
            key="one",
            title="One",
            reject_message="Rahmat, hozircha mos kelmadi.",
            questions=[{"key": "q1", "text": "Savol?"}],
            resume_required=False,
        )
        with self.assertRaises(database.VacancyLimitReached):
            await database.create_vacancy(
                tenant_id=self.tenant_id,
                key="two",
                title="Two",
                reject_message="Rahmat, hozircha mos kelmadi.",
                questions=[{"key": "q1", "text": "Savol?"}],
                resume_required=False,
            )
        self.assertTrue(await database.set_vacancy_active(self.tenant_id, "one", False))
        await database.create_vacancy(
            tenant_id=self.tenant_id,
            key="two",
            title="Two",
            reject_message="Rahmat, hozircha mos kelmadi.",
            questions=[{"key": "q1", "text": "Savol?"}],
            resume_required=False,
        )
        with self.assertRaises(database.VacancyLimitReached):
            await database.set_vacancy_active(self.tenant_id, "one", True)

    async def test_duplicate_slot_and_booked_slot_delete_are_blocked(self):
        slot_id = await database.add_interview_slot(
            self.tenant_id, "2026-09-05 10:00", capacity=1
        )
        with self.assertRaises(database.InterviewSlotConflict):
            await database.add_interview_slot(
                self.tenant_id, "2026-09-05 10:00", capacity=2
            )
        app_id = await self._save_app("slot-app")
        self.assertTrue(
            await database.try_book_slot(
                self.tenant_id, app_id, "2026-09-05 10:00", 1
            )
        )
        with self.assertRaises(database.InterviewSlotBooked):
            await database.delete_interview_slot(self.tenant_id, slot_id)

    async def test_expired_payment_order_is_expired_on_read_and_not_reminded(self):
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO payment_orders "
                "(tenant_id, order_code, base_amount, amount, plan_code, billing_months, "
                "status, created_at, expires_at) VALUES (?, ?, ?, ?, 'start', 1, "
                "'awaiting_payment', ?, ?)",
                (
                    self.tenant_id,
                    "JH-OLD",
                    299000,
                    299006,
                    (now - timedelta(hours=1)).isoformat(),
                    (now - timedelta(minutes=30)).isoformat(),
                ),
            )
            await db.commit()
        order = await database.get_payment_order_for_tenant(self.tenant_id, "JH-OLD")
        self.assertEqual(order["status"], "expired")
        self.assertEqual(await database.list_unpaid_orders_older_than(minutes=30), [])

    async def test_admin_bot_blocks_active_plan_downgrade_before_order_creation(self):
        callback = type(
            "Callback",
            (),
            {
                "data": "billing:buy:start",
                "answer": AsyncMock(),
                "message": type("Message", (), {"edit_text": AsyncMock()})(),
            },
        )()
        usage = {
            "plan": get_plan("business"),
            "expired": False,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        }
        with (
            patch.object(handlers_billing, "PAYMENT_CARD_NUMBER", "8600"),
            patch.object(database, "get_subscription_usage", AsyncMock(return_value=usage)),
            patch.object(handlers_billing, "create_payment_order", AsyncMock()) as create_order,
        ):
            await handlers_billing.billing_buy(callback, self.tenant_id)
        create_order.assert_not_awaited()
        self.assertTrue(callback.answer.await_args.kwargs["show_alert"])

    async def test_miniapp_cannot_accept_candidate_without_interview_slot(self):
        request = type(
            "Request",
            (),
            {
                "match_info": {"app_id": "9"},
                "json": AsyncMock(return_value={"action": "accept"}),
            },
        )()
        app = {"id": 9, "status": "pending", "user_id": 123, "lang": "uz"}
        tenant = {"id": self.tenant_id, "bot_token": "token"}
        with (
            patch("miniapp_api._authorize", AsyncMock(return_value=(tenant, {}))),
            patch.object(database, "get_application", AsyncMock(return_value=app)),
            patch.object(database, "get_available_interview_slots", AsyncMock(return_value=[])),
            patch.object(database, "transition_application_status", AsyncMock()) as transition,
        ):
            with self.assertRaises(web.HTTPConflict):
                await candidate_decision(request)
        transition.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
'''
write("tests/test_logic_release.py", tests)

print("Logical release hardening applied.")
