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


def insert_before(path: str, marker: str, payload: str) -> None:
    text = read(path)
    if marker not in text:
        raise RuntimeError(f"Marker not found in {path}: {marker[:120]!r}")
    write(path, text.replace(marker, payload + marker, 1))


# ---------------------------------------------------------------------------
# AI scoring: every score must carry evidence; expand non-blocking red flags.
# ---------------------------------------------------------------------------
replace_once(
    "services/ai_scoring.py",
    '''    red_flags: list[str]\n    izoh: str  # 1 gapli qisqa xulosa\n''',
    '''    red_flags: list[str]\n    izoh: str  # 1 gapli qisqa xulosa\n    evidence: str  # bahoni asoslaydigan nomzod javobidagi aniq dalil\n''',
)
replace_once(
    "services/ai_scoring.py",
    '''3. aniqlik — Savolga to'g'ridan-to'g'ri va tushunarli javob berdimi, yoki chalg'itib,\n   umumiy gapirdimi?\n\nQuyidagi "qizil bayroqlarni" alohida qidir''',
    '''3. aniqlik — Savolga to'g'ridan-to'g'ri va tushunarli javob berdimi, yoki chalg'itib,\n   umumiy gapirdimi?\n\nHar bir bahoga "evidence" ham yoz: nomzodning AYNAN shu javobidan bahoni asoslaydigan\neng kuchli fakt, raqam, qadam yoki da'voni 25 so'zdan oshirmay qayta ifodala. Hech qachon\nnomzod aytmagan faktni o'ylab topma. Dalil bo'lmasa "Dalil yetarli emas" deb yoz.\n\nQuyidagi "qizil bayroqlarni" alohida qidir''',
)
replace_once(
    "services/ai_scoring.py",
    '''  bilimdon odam ham yaxshi yoza olishi mumkin, shuning uchun faqat bir nechta belgi\n  birga uchraganda ushbu bayroqni qo'sh, yolg'iz "yaxshi yozilgan" bo'lgani uchun emas.\n\nUchala mezon''',
    '''  bilimdon odam ham yaxshi yoza olishi mumkin, shuning uchun faqat bir nechta belgi\n  birga uchraganda ushbu bayroqni qo'sh, yolg'iz "yaxshi yozilgan" bo'lgani uchun emas.\n- "natija_isbotsiz" — nomzod katta natija da'vo qiladi, lekin raqam, vaziyat yoki o'z hissasini\n  tushuntiradigan dalil bermaydi.\n- "tajriba_shubhali" — amaliy tajriba da'vosi bor, lekin sohaga xos oddiy tafsilotni ham\n  tushuntira olmaydi yoki javob yodlangan umumiy ta'rifga o'xshaydi.\n- "tez_tez_ish_almashtirish" — aynan ish barqarorligi haqida javobda bir necha qisqa muddatli\n  ish joyi va asoslanmagan tez ketishlar ko'rinadi.\n- "javob_zid" — bitta javobning o'zida bir-biriga zid fakt yoki raqamlar bor.\n\nMUHIM: bu bayroqlar admin uchun SIGNAL, avtomatik rad hukmi emas. Faqat relevant=false yoki\njiddiy sifatsiz javob yakuniy qizil verdictga sabab bo'lishi mumkin.\n\nUchala mezon''',
)
replace_once(
    "services/ai_scoring.py",
    '''"verdict": "<yashil|sariq|qizil>", "red_flags": [<satrlar ro'yxati>], \\\n"izoh": "<15 so'zdan oshmagan, o'zbek tilida qisqa xulosa>"}\n''',
    '''"verdict": "<yashil|sariq|qizil>", "red_flags": [<satrlar ro'yxati>], \\\n"izoh": "<15 so'zdan oshmagan, o'zbek tilida qisqa xulosa>", \\\n"evidence": "<nomzod javobidagi 25 so'zgacha aniq dalil>"}\n''',
)
replace_once(
    "services/ai_scoring.py",
    '''        izoh = str(parsed.get("izoh", "")).strip()[:200]\n\n        return ScoreResult(\n''',
    '''        izoh = str(parsed.get("izoh", "")).strip()[:200]\n        evidence = str(parsed.get("evidence") or parsed.get("dalil") or "").strip()[:300]\n\n        return ScoreResult(\n''',
)
replace_once(
    "services/ai_scoring.py",
    '''            red_flags=[str(f) for f in red_flags],\n            izoh=izoh,\n        )\n''',
    '''            red_flags=[str(f) for f in red_flags],\n            izoh=izoh,\n            evidence=evidence,\n        )\n''',
)
replace_once(
    "services/ai_scoring.py",
    '''8. Savollar orasidan ENG MUHIM bittasini (ko'pi bilan ikkitasini) — odatda "scorecard"\n   yoki "yutuq" turidagi savolni — "voice": true deb ham belgila. Bu savolga nomzod\n   OVOZLI xabar orqali javob berishi MAJBURIY bo'ladi (yozib emas, gapirib). Bu javob\n   AI orqali baholanmaydi — audio fayl to'g'ridan-to'g'ri ish beruvchiga (adminga)\n   yuboriladi, u shaxsan tinglab baholaydi. Maqsad — tayyorlab, ChatGPT yordamida\n   yozib olingan javoblarni emas, jonli va tabiiy javobni olish.\n\nFAQAT quyidagi JSON''',
    '''8. Savollar orasidan ENG MUHIM bittasini (ko'pi bilan ikkitasini) — odatda "scorecard"\n   yoki "yutuq" turidagi savolni — "voice": true deb ham belgila. Bu savolga nomzod\n   OVOZLI xabar orqali javob berishi MAJBURIY bo'ladi (yozib emas, gapirib). Bu javob\n   AI orqali baholanmaydi — audio fayl to'g'ridan-to'g'ri ish beruvchiga (adminga)\n   yuboriladi, u shaxsan tinglab baholaydi. Maqsad — tayyorlab, ChatGPT yordamida\n   yozib olingan javoblarni emas, jonli va tabiiy javobni olish.\n9. Bitta savol ish barqarorligini tekshirsin: oxirgi 2-3 ish joyida qancha ishlagani va\n   nima sabab ketganini so'ra. Bu savolga "ai_score": true qo'y.\n10. Bitta qisqa savol nomzodning kutilayotgan oylik maoshini taxminiy raqamda so'rasin.\n\nFAQAT quyidagi JSON''',
)
replace_once(
    "services/ai_scoring.py",
    '''        _SYSTEM_PROMPT, f"Savol: {question}\\nNomzod javobi: {answer}", max_tokens=260\n''',
    '''        _SYSTEM_PROMPT, f"Savol: {question}\\nNomzod javobi: {answer}", max_tokens=320\n''',
)


# ---------------------------------------------------------------------------
# Database: onboarding profile, vacancy profile and structured interview time.
# ---------------------------------------------------------------------------
replace_once(
    "services/database.py",
    '''    subscription_started_at TEXT,\n    subscription_expires_at TEXT,\n    created_at TEXT NOT NULL\n''',
    '''    subscription_started_at TEXT,\n    subscription_expires_at TEXT,\n    industry TEXT,\n    onboarding_profile TEXT NOT NULL DEFAULT '{}',\n    onboarding_completed_at TEXT,\n    created_at TEXT NOT NULL\n''',
)
replace_once(
    "services/database.py",
    '''    resume_required INTEGER NOT NULL DEFAULT 0,\n    active INTEGER NOT NULL DEFAULT 1,\n    created_at TEXT NOT NULL,\n''',
    '''    resume_required INTEGER NOT NULL DEFAULT 0,\n    active INTEGER NOT NULL DEFAULT 1,\n    profile_json TEXT NOT NULL DEFAULT '{}',\n    created_at TEXT NOT NULL,\n''',
)
replace_once(
    "services/database.py",
    '''    label TEXT NOT NULL,\n    capacity INTEGER NOT NULL DEFAULT 1,\n    active INTEGER NOT NULL DEFAULT 1,\n''',
    '''    label TEXT NOT NULL,\n    capacity INTEGER NOT NULL DEFAULT 1,\n    starts_at TEXT,\n    active INTEGER NOT NULL DEFAULT 1,\n''',
)
replace_once(
    "services/database.py",
    '''        tenant_migrations = {\n            "plan_code": "TEXT NOT NULL DEFAULT 'trial'",\n            "subscription_started_at": "TEXT",\n            "subscription_expires_at": "TEXT",\n        }\n''',
    '''        tenant_migrations = {\n            "plan_code": "TEXT NOT NULL DEFAULT 'trial'",\n            "subscription_started_at": "TEXT",\n            "subscription_expires_at": "TEXT",\n            "industry": "TEXT",\n            "onboarding_profile": "TEXT NOT NULL DEFAULT '{}'",\n            "onboarding_completed_at": "TEXT",\n        }\n''',
)
insert_before(
    "services/database.py",
    '''        cursor = await db.execute("PRAGMA table_info(payment_orders)")\n''',
    '''        cursor = await db.execute("PRAGMA table_info(vacancies)")\n        vacancy_columns = {row[1] for row in await cursor.fetchall()}\n        if "profile_json" not in vacancy_columns:\n            await db.execute("ALTER TABLE vacancies ADD COLUMN profile_json TEXT NOT NULL DEFAULT '{}'")\n\n        cursor = await db.execute("PRAGMA table_info(interview_slots)")\n        slot_columns = {row[1] for row in await cursor.fetchall()}\n        if "starts_at" not in slot_columns:\n            await db.execute("ALTER TABLE interview_slots ADD COLUMN starts_at TEXT")\n\n''',
)
replace_once(
    "services/database.py",
    '''    t = dict(row)\n    t["admin_user_ids"] = json.loads(t["admin_user_ids"])\n    return t\n''',
    '''    t = dict(row)\n    t["admin_user_ids"] = json.loads(t["admin_user_ids"])\n    try:\n        t["onboarding_profile"] = json.loads(t.get("onboarding_profile") or "{}")\n    except (TypeError, json.JSONDecodeError):\n        t["onboarding_profile"] = {}\n    return t\n''',
)
replace_once(
    "services/database.py",
    '''        t = dict(row)\n        t["admin_user_ids"] = json.loads(t["admin_user_ids"])\n        result.append(t)\n''',
    '''        t = dict(row)\n        t["admin_user_ids"] = json.loads(t["admin_user_ids"])\n        try:\n            t["onboarding_profile"] = json.loads(t.get("onboarding_profile") or "{}")\n        except (TypeError, json.JSONDecodeError):\n            t["onboarding_profile"] = {}\n        result.append(t)\n''',
)
replace_once(
    "services/database.py",
    '''    v["questions"] = json.loads(v["questions"])\n    v["resume_required"] = bool(v["resume_required"])\n''',
    '''    v["questions"] = json.loads(v["questions"])\n    try:\n        v["profile"] = json.loads(v.get("profile_json") or "{}")\n    except (TypeError, json.JSONDecodeError):\n        v["profile"] = {}\n    v["resume_required"] = bool(v["resume_required"])\n''',
)
replace_once(
    "services/database.py",
    '''    questions: list,\n    resume_required: bool,\n) -> None:\n''',
    '''    questions: list,\n    resume_required: bool,\n    profile: dict | None = None,\n) -> None:\n''',
)
replace_once(
    "services/database.py",
    '''            "INSERT INTO vacancies (tenant_id, key, title, reject_message, questions, "\n            "resume_required, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",\n''',
    '''            "INSERT INTO vacancies (tenant_id, key, title, reject_message, questions, "\n            "resume_required, active, profile_json, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",\n''',
)
replace_once(
    "services/database.py",
    '''                json.dumps(questions, ensure_ascii=False),\n                int(resume_required),\n                created_at,\n''',
    '''                json.dumps(questions, ensure_ascii=False),\n                int(resume_required),\n                json.dumps(profile or {}, ensure_ascii=False),\n                created_at,\n''',
)
replace_once(
    "services/database.py",
    '''        "resume_required",\n        "active",\n    }\n''',
    '''        "resume_required",\n        "active",\n        "profile",\n    }\n''',
)
replace_once(
    "services/database.py",
    '''        if field == "questions":\n            value = json.dumps(value, ensure_ascii=False)\n        elif field in ("resume_required", "active"):\n''',
    '''        if field == "questions":\n            value = json.dumps(value, ensure_ascii=False)\n        elif field == "profile":\n            field = "profile_json"\n            value = json.dumps(value or {}, ensure_ascii=False)\n        elif field in ("resume_required", "active"):\n''',
)
replace_once(
    "services/database.py",
    '''async def add_interview_slot(tenant_id: int, label: str, capacity: int = 1) -> int:\n    created_at = datetime.now(timezone.utc).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        cursor = await db.execute(\n            "INSERT INTO interview_slots (tenant_id, label, capacity, active, created_at) VALUES (?, ?, ?, 1, ?)",\n            (tenant_id, label, capacity, created_at),\n        )\n''',
    '''async def add_interview_slot(\n    tenant_id: int, label: str, capacity: int = 1, starts_at: str | None = None\n) -> int:\n    created_at = datetime.now(timezone.utc).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        cursor = await db.execute(\n            "INSERT INTO interview_slots (tenant_id, label, capacity, starts_at, active, created_at) "\n            "VALUES (?, ?, ?, ?, 1, ?)",\n            (tenant_id, label, capacity, starts_at, created_at),\n        )\n''',
)

DB_HELPERS = '''async def update_tenant_onboarding(\n    tenant_id: int, *, industry: str, profile: dict, completed: bool = True\n) -> None:\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        await db.execute(\n            "UPDATE tenants SET industry=?, onboarding_profile=?, onboarding_completed_at=? WHERE id=?",\n            (\n                industry,\n                json.dumps(profile or {}, ensure_ascii=False),\n                datetime.now(timezone.utc).isoformat() if completed else None,\n                tenant_id,\n            ),\n        )\n        await db.commit()\n\n\nasync def deactivate_empty_vacancies(tenant_id: int) -> None:\n    """Arizasi bo'lmagan eski demo vakansiyalarni onboarding oldidan yopadi."""\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        await db.execute(\n            "UPDATE vacancies SET active=0 WHERE tenant_id=? AND key NOT IN "\n            "(SELECT DISTINCT vacancy_key FROM applications WHERE tenant_id=?)",\n            (tenant_id, tenant_id),\n        )\n        await db.commit()\n\n\nasync def clear_unbooked_interview_slots(tenant_id: int) -> None:\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        await db.execute(\n            "DELETE FROM interview_slots WHERE tenant_id=? AND label NOT IN "\n            "(SELECT DISTINCT selected_slot FROM applications WHERE tenant_id=? AND selected_slot IS NOT NULL)",\n            (tenant_id, tenant_id),\n        )\n        await db.commit()\n\n\nasync def list_funnel_applications(\n    tenant_id: int, *, days: int = 30, vacancy_key: str | None = None\n) -> list[dict]:\n    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()\n    sql = "SELECT * FROM applications WHERE tenant_id=? AND created_at>=?"\n    params: list = [tenant_id, cutoff]\n    if vacancy_key:\n        sql += " AND vacancy_key=?"\n        params.append(vacancy_key)\n    sql += " ORDER BY id DESC"\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        db.row_factory = aiosqlite.Row\n        rows = await (await db.execute(sql, params)).fetchall()\n    return [_parse_app_row(row) for row in rows]\n\n\nasync def list_interview_followup_candidates() -> list[dict]:\n    now = datetime.now(timezone.utc)\n    lower = (now - timedelta(hours=24)).isoformat()\n    upper = (now + timedelta(hours=26)).isoformat()\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        db.row_factory = aiosqlite.Row\n        cursor = await db.execute(\n            "SELECT a.id AS app_id, a.tenant_id, a.user_id, a.full_name, a.vacancy_title, "\n            "a.lang, a.selected_slot, a.status, s.starts_at, t.bot_token, t.admin_bot_token, "\n            "t.admin_user_ids FROM applications a "\n            "JOIN interview_slots s ON s.tenant_id=a.tenant_id AND s.label=a.selected_slot "\n            "JOIN tenants t ON t.id=a.tenant_id "\n            "WHERE a.status='accepted' AND s.starts_at IS NOT NULL "\n            "AND s.starts_at>=? AND s.starts_at<=? AND t.status='active'",\n            (lower, upper),\n        )\n        rows = await cursor.fetchall()\n    result = []\n    for row in rows:\n        item = dict(row)\n        try:\n            item["admin_user_ids"] = json.loads(item.get("admin_user_ids") or "[]")\n        except (TypeError, json.JSONDecodeError):\n            item["admin_user_ids"] = []\n        result.append(item)\n    return result\n\n\n'''
insert_before(
    "services/database.py",
    "# ============================= STATISTIKA (admin bot) =============================\n",
    DB_HELPERS,
)


# ---------------------------------------------------------------------------
# Persistent FSM: track activity so abandoned applications can be reminded.
# ---------------------------------------------------------------------------
replace_once(
    "services/storage.py",
    '''import json\nimport logging\nfrom typing import Any\n''',
    '''import json\nimport logging\nfrom datetime import datetime, timedelta, timezone\nfrom typing import Any\n''',
)
replace_once(
    "services/storage.py",
    '''import aiosqlite\nfrom aiogram.fsm.storage.base import BaseStorage, StorageKey\n''',
    '''import aiosqlite\nfrom aiogram.fsm.storage.base import BaseStorage, StorageKey\n\nfrom config import SQLITE_PATH\n''',
)
replace_once(
    "services/storage.py",
    '''    state TEXT,\n    data TEXT NOT NULL DEFAULT '{}'\n);\n''',
    '''    state TEXT,\n    data TEXT NOT NULL DEFAULT '{}',\n    updated_at TEXT,\n    reminder_stage TEXT\n);\n''',
)
replace_once(
    "services/storage.py",
    '''        async with aiosqlite.connect(self._db_path) as db:\n            await db.execute(_CREATE_TABLE_SQL)\n            await db.commit()\n''',
    '''        async with aiosqlite.connect(self._db_path) as db:\n            await db.execute(_CREATE_TABLE_SQL)\n            cursor = await db.execute("PRAGMA table_info(fsm_storage)")\n            columns = {row[1] for row in await cursor.fetchall()}\n            if "updated_at" not in columns:\n                await db.execute("ALTER TABLE fsm_storage ADD COLUMN updated_at TEXT")\n            if "reminder_stage" not in columns:\n                await db.execute("ALTER TABLE fsm_storage ADD COLUMN reminder_stage TEXT")\n            await db.execute(\n                "UPDATE fsm_storage SET updated_at=COALESCE(updated_at, ?) WHERE state IS NOT NULL",\n                (datetime.now(timezone.utc).isoformat(),),\n            )\n            await db.commit()\n''',
)
replace_once(
    "services/storage.py",
    '''            await db.execute(\n                """\n                INSERT INTO fsm_storage (storage_key, state, data) VALUES (?, ?, '{}')\n                ON CONFLICT(storage_key) DO UPDATE SET state = excluded.state\n                """,\n                (_key_str(key), state_str),\n            )\n''',
    '''            now = datetime.now(timezone.utc).isoformat()\n            await db.execute(\n                """\n                INSERT INTO fsm_storage (storage_key, state, data, updated_at, reminder_stage)\n                VALUES (?, ?, '{}', ?, NULL)\n                ON CONFLICT(storage_key) DO UPDATE SET\n                    state = excluded.state, updated_at = excluded.updated_at, reminder_stage = NULL\n                """,\n                (_key_str(key), state_str, now),\n            )\n''',
)
replace_once(
    "services/storage.py",
    '''            await db.execute(\n                """\n                INSERT INTO fsm_storage (storage_key, state, data) VALUES (?, NULL, ?)\n                ON CONFLICT(storage_key) DO UPDATE SET data = excluded.data\n                """,\n                (_key_str(key), data_json),\n            )\n''',
    '''            now = datetime.now(timezone.utc).isoformat()\n            await db.execute(\n                """\n                INSERT INTO fsm_storage (storage_key, state, data, updated_at, reminder_stage)\n                VALUES (?, NULL, ?, ?, NULL)\n                ON CONFLICT(storage_key) DO UPDATE SET\n                    data = excluded.data, updated_at = excluded.updated_at, reminder_stage = NULL\n                """,\n                (_key_str(key), data_json, now),\n            )\n''',
)
STORAGE_HELPERS = '''\n\nasync def list_stale_candidate_sessions(minutes: int = 30) -> list[dict]:\n    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()\n    try:\n        async with aiosqlite.connect(SQLITE_PATH) as db:\n            db.row_factory = aiosqlite.Row\n            cursor = await db.execute(\n                "SELECT storage_key, state, data, updated_at, reminder_stage FROM fsm_storage "\n                "WHERE state IS NOT NULL AND updated_at IS NOT NULL AND updated_at<=? "\n                "ORDER BY updated_at LIMIT 100",\n                (cutoff,),\n            )\n            rows = await cursor.fetchall()\n    except aiosqlite.OperationalError:\n        return []\n    now = datetime.now(timezone.utc)\n    result = []\n    for row in rows:\n        try:\n            data = json.loads(row["data"] or "{}")\n            tenant_id = int(data.get("tenant_id"))\n            parts = row["storage_key"].split(":")\n            chat_id = int(parts[1])\n            updated = datetime.fromisoformat(row["updated_at"])\n        except (TypeError, ValueError, KeyError, json.JSONDecodeError):\n            continue\n        age_hours = (now - updated).total_seconds() / 3600\n        last = row["reminder_stage"]\n        if age_hours >= 24 and last != "24h":\n            stage = "24h"\n        elif age_hours >= 0.5 and not last:\n            stage = "30m"\n        else:\n            continue\n        result.append({\n            "storage_key": row["storage_key"], "state": row["state"], "data": data,\n            "tenant_id": tenant_id, "chat_id": chat_id, "stage": stage,\n        })\n    return result\n\n\nasync def mark_candidate_session_reminded(storage_key: str, stage: str) -> None:\n    async with aiosqlite.connect(SQLITE_PATH) as db:\n        await db.execute(\n            "UPDATE fsm_storage SET reminder_stage=? WHERE storage_key=?",\n            (stage, storage_key),\n        )\n        await db.commit()\n'''
text = read("services/storage.py")
if "async def list_stale_candidate_sessions" not in text:
    write("services/storage.py", text + STORAGE_HELPERS)


# ---------------------------------------------------------------------------
# Admin candidate cards: expose evidence and expanded red flag labels.
# ---------------------------------------------------------------------------
replace_once(
    "handlers/admin.py",
    '''    "ai_yozgan": "⚠️ AI/ChatGPT orqali yozilgan bo'lishi shubhali",\n}\n''',
    '''    "ai_yozgan": "⚠️ AI/ChatGPT orqali yozilgan bo'lishi shubhali",\n    "natija_isbotsiz": "Natija aniq dalil yoki raqam bilan tasdiqlanmagan",\n    "tajriba_shubhali": "Amaliy tajriba bo'yicha aniqlashtirish kerak",\n    "tez_tez_ish_almashtirish": "Ish joylarini tez-tez almashtirish signali",\n    "javob_zid": "Javob ichida bir-biriga zid ma'lumot bor",\n    "maosh_budgetdan_yuqori": "Kutilayotgan maosh vakansiya budjetidan yuqori",\n}\n''',
)
replace_once(
    "handlers/admin.py",
    '''    strength = (strongest or {}).get("izoh") or "Javoblarini to'liq ko'rib chiqing."\n''',
    '''    strength = (strongest or {}).get("evidence") or (strongest or {}).get("izoh") or "Javoblarini to'liq ko'rib chiqing."\n''',
)
replace_once(
    "handlers/admin.py",
    '''                lines.append(f"   ↳ {emoji} <i>{score_part}{escape(izoh)}</i>")\n''',
    '''                lines.append(f"   ↳ {emoji} <i>{score_part}{escape(izoh)}</i>")\n                evidence = str(result.get("evidence") or "").strip()\n                if evidence:\n                    lines.append(f"      <b>Dalil:</b> {escape(evidence)}")\n''',
)


# ---------------------------------------------------------------------------
# Mini App API: compare, funnel, quick onboarding, evidence risks, hired follow-up.
# ---------------------------------------------------------------------------
replace_once(
    "miniapp_api.py",
    '''import logging\nimport time\nfrom collections import defaultdict, deque\n''',
    '''import logging\nimport time\nfrom collections import defaultdict, deque\nfrom datetime import datetime, timezone\n''',
)
replace_once(
    "miniapp_api.py",
    '''from services.ai_scoring import aggregate_scores\n''',
    '''from services.ai_scoring import aggregate_scores, generate_questions\nfrom services.candidate_followup import notify_candidate_outcome\nfrom services.hiring_intelligence import candidate_risks, compare_candidates, hiring_funnel\n''',
)
replace_once(
    "miniapp_api.py",
    '''    result = _candidate_summary(app)\n    result.update(\n''',
    '''    result = _candidate_summary(app)\n    vacancy = await database.get_vacancy(tenant["id"], app["vacancy_key"])\n    result.update(\n''',
)
replace_once(
    "miniapp_api.py",
    '''            "has_voice": bool(app.get("voice_answers")),\n        }\n''',
    '''            "has_voice": bool(app.get("voice_answers")),\n            "risk_signals": candidate_risks(app, vacancy),\n        }\n''',
)
replace_once(
    "miniapp_api.py",
    '''    if not changed:\n        raise web.HTTPConflict(text="Nomzod holati boshqa joydan o'zgartirilgan.")\n    return web.json_response({"ok": True, "status": outcome})\n\n\nasync def vacancies''',
    '''    if not changed:\n        raise web.HTTPConflict(text="Nomzod holati boshqa joydan o'zgartirilgan.")\n    await notify_candidate_outcome(tenant["id"], app_id, outcome)\n    return web.json_response({"ok": True, "status": outcome})\n\n\nasync def analytics_funnel(request: web.Request):\n    tenant, _ = await _authorize(request)\n    try:\n        days = max(1, min(90, int(request.query.get("days", "30"))))\n    except ValueError:\n        raise web.HTTPBadRequest(text="Davr noto'g'ri.")\n    vacancy_key = (request.query.get("vacancy_key") or "").strip() or None\n    apps = await database.list_funnel_applications(\n        tenant["id"], days=days, vacancy_key=vacancy_key\n    )\n    return web.json_response({"period_days": days, "funnel": hiring_funnel(apps)})\n\n\nasync def compare_top_candidates(request: web.Request):\n    tenant, _ = await _authorize(request)\n    vacancy_key = (request.query.get("vacancy_key") or "").strip()\n    if not vacancy_key:\n        raise web.HTTPBadRequest(text="Vakansiyani tanlang.")\n    vacancy = await database.get_vacancy(tenant["id"], vacancy_key)\n    if not vacancy:\n        raise web.HTTPNotFound(text="Vakansiya topilmadi.")\n    try:\n        limit = max(2, min(5, int(request.query.get("limit", "3"))))\n    except ValueError:\n        limit = 3\n    apps = await database.get_applications_for_vacancy(tenant["id"], vacancy_key, limit=500)\n    return web.json_response(\n        {\n            "vacancy": {"key": vacancy["key"], "title": vacancy["title"]},\n            "comparison": compare_candidates(apps, vacancy, limit=limit),\n        }\n    )\n\n\nasync def onboarding_status(request: web.Request):\n    tenant, _ = await _authorize(request)\n    stats = await database.get_overall_stats(tenant["id"])\n    return web.json_response(\n        {\n            "completed": bool(tenant.get("onboarding_completed_at")),\n            "can_quick_setup": stats["total"] == 0,\n            "industry": tenant.get("industry"),\n            "profile": tenant.get("onboarding_profile") or {},\n        }\n    )\n\n\ndef _normalise_starts_at(value: str | None) -> str | None:\n    value = str(value or "").strip()\n    if not value:\n        return None\n    try:\n        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))\n    except ValueError as exc:\n        raise web.HTTPBadRequest(text="Suhbat vaqti noto'g'ri formatda.") from exc\n    if parsed.tzinfo is None:\n        parsed = parsed.replace(tzinfo=timezone.utc)\n    return parsed.astimezone(timezone.utc).isoformat()\n\n\nasync def quick_setup(request: web.Request):\n    tenant, _ = await _authorize(request)\n    try:\n        body = await request.json()\n    except (json.JSONDecodeError, TypeError):\n        raise web.HTTPBadRequest(text="Onboarding ma'lumoti noto'g'ri.")\n    industry = str(body.get("industry") or "").strip()\n    role = str(body.get("role_title") or "").strip()\n    ideal = str(body.get("ideal_candidate") or "").strip()\n    try:\n        question_count = int(body.get("question_count", 9))\n        salary_budget = body.get("salary_budget_max")\n        salary_budget = int(salary_budget) if salary_budget not in (None, "", 0) else None\n    except (TypeError, ValueError):\n        raise web.HTTPBadRequest(text="Savol yoki maosh qiymati noto'g'ri.")\n    if not 2 <= len(industry) <= 100 or not 2 <= len(role) <= 100:\n        raise web.HTTPBadRequest(text="Biznes sohasi va lavozimni to'liq yozing.")\n    if not 5 <= len(ideal) <= 700:\n        raise web.HTTPBadRequest(text="Ideal xodim tavsifini aniqroq yozing.")\n    if not 5 <= question_count <= 12:\n        raise web.HTTPBadRequest(text="Savollar soni 5 dan 12 gacha bo'lishi kerak.")\n    if salary_budget is not None and not 100_000 <= salary_budget <= 1_000_000_000:\n        raise web.HTTPBadRequest(text="Maosh budjeti noto'g'ri.")\n\n    raw_slots = body.get("interview_slots") or []\n    if not isinstance(raw_slots, list) or len(raw_slots) > 10:\n        raise web.HTTPBadRequest(text="Suhbat vaqtlari noto'g'ri.")\n    clean_slots = []\n    for raw in raw_slots:\n        if not isinstance(raw, dict):\n            continue\n        label = str(raw.get("label") or "").strip()[:80]\n        starts_at = _normalise_starts_at(raw.get("starts_at"))\n        try:\n            capacity = max(1, min(20, int(raw.get("capacity", 1))))\n        except (TypeError, ValueError):\n            capacity = 1\n        if label and starts_at:\n            clean_slots.append({"label": label, "starts_at": starts_at, "capacity": capacity})\n\n    description = (\n        f"Biznes sohasi: {industry}. Ideal xodim: {ideal}. "\n        + (f"Oylik budjeti {salary_budget:,} so'mgacha. " if salary_budget else "")\n        + "Savollar real amaliy tajriba, natijadorlik, barqarorlik va mas'uliyatni ajratsin."\n    )\n    questions = await generate_questions(role, description, count=question_count)\n    if not questions:\n        raise web.HTTPServiceUnavailable(\n            text="AI savollarni tayyorlay olmadi. Birozdan keyin qayta urinib ko'ring."\n        )\n\n    stats = await database.get_overall_stats(tenant["id"])\n    if stats["total"] == 0:\n        await database.deactivate_empty_vacancies(tenant["id"])\n        await database.clear_unbooked_interview_slots(tenant["id"])\n    else:\n        usage = await database.get_subscription_usage(tenant["id"])\n        if not usage["vacancies_available"]:\n            raise web.HTTPPaymentRequired(text="Tarifdagi vakansiya limiti tugagan.")\n\n    key = database.make_vacancy_key(role)\n    base = key\n    suffix = 2\n    while await database.get_vacancy(tenant["id"], key):\n        key = f"{base[:36]}_{suffix}"\n        suffix += 1\n    profile = {\n        "industry": industry,\n        "ideal_candidate": ideal,\n        "salary_budget_max": salary_budget,\n        "question_count": question_count,\n    }\n    await database.create_vacancy(\n        tenant_id=tenant["id"],\n        key=key,\n        title=role,\n        reject_message=(\n            "Arizangiz uchun rahmat. Hozircha ushbu vakansiya bo'yicha keyingi bosqichga "\n            "o'tmadingiz. Sizga muvaffaqiyat tilaymiz!"\n        ),\n        questions=questions,\n        resume_required=False,\n        profile=profile,\n    )\n    for slot in clean_slots:\n        await database.add_interview_slot(\n            tenant["id"], slot["label"], slot["capacity"], starts_at=slot["starts_at"]\n        )\n    location = str(body.get("location_text") or "").strip()[:240]\n    if location:\n        await database.update_interview_settings(tenant["id"], location_text=location)\n    await database.update_tenant_onboarding(\n        tenant["id"], industry=industry, profile={**profile, "primary_vacancy_key": key}\n    )\n    return web.json_response({"ok": True, "vacancy_key": key, "questions": len(questions)})\n\n\nasync def vacancies''',
)
replace_once(
    "miniapp_api.py",
    '''        label = str(body.get("label") or "").strip()\n        capacity = int(body.get("capacity", 1))\n''',
    '''        label = str(body.get("label") or "").strip()\n        capacity = int(body.get("capacity", 1))\n        starts_at = _normalise_starts_at(body.get("starts_at"))\n        if not starts_at and label:\n            try:\n                starts_at = _normalise_starts_at(label)\n            except web.HTTPBadRequest:\n                starts_at = None\n''',
)
replace_once(
    "miniapp_api.py",
    '''    slot_id = await database.add_interview_slot(tenant["id"], label, capacity)\n    return web.json_response(\n        {"ok": True, "slot": {"id": slot_id, "label": label, "capacity": capacity, "booked": 0}}\n''',
    '''    slot_id = await database.add_interview_slot(\n        tenant["id"], label, capacity, starts_at=starts_at\n    )\n    return web.json_response(\n        {\n            "ok": True,\n            "slot": {\n                "id": slot_id, "label": label, "capacity": capacity,\n                "booked": 0, "starts_at": starts_at,\n            },\n        }\n''',
)
insert_before(
    "miniapp_api.py",
    '''    app.router.add_get("/api/miniapp/{tenant_id}/candidates", candidates)\n''',
    '''    app.router.add_get("/api/miniapp/{tenant_id}/analytics/funnel", analytics_funnel)\n    app.router.add_get(\n        "/api/miniapp/{tenant_id}/intelligence/compare", compare_top_candidates\n    )\n    app.router.add_get("/api/miniapp/{tenant_id}/onboarding/status", onboarding_status)\n    app.router.add_post(\n        "/api/miniapp/{tenant_id}/onboarding/quick-setup", quick_setup\n    )\n''',
)


# ---------------------------------------------------------------------------
# Automated follow-up: unfinished applications + structured interview reminders.
# ---------------------------------------------------------------------------
replace_once(
    "services/reminders.py",
    '''from datetime import datetime, timezone\n''',
    '''from datetime import datetime, timezone\n''',
)
replace_once(
    "services/reminders.py",
    '''from services import database\n''',
    '''from services import database\nfrom services.storage import list_stale_candidate_sessions, mark_candidate_session_reminded\n''',
)
REMINDER_FUNCS = '''\n\nasync def _send_abandoned_application_reminders() -> None:\n    for session in await list_stale_candidate_sessions(minutes=30):\n        tenant = await database.get_tenant(session["tenant_id"])\n        if not tenant or tenant.get("status") != "active":\n            continue\n        lang = (session.get("data") or {}).get("lang", "uz")\n        if session["stage"] == "24h":\n            text = (\n                "Ваша анкета ещё не завершена. Можете продолжить с того же места или отправить /cancel."\n                if lang == "ru"\n                else "Arizangiz hali yakunlanmagan. Shu yerdan davom ettirishingiz yoki /cancel bilan bekor qilishingiz mumkin."\n            )\n        else:\n            text = (\n                "Вы остановились на середине анкеты. Продолжите с последнего вопроса — ответы уже сохранены."\n                if lang == "ru"\n                else "Arizangiz yarim qolib ketdi. Oxirgi savoldan davom eting — oldingi javoblaringiz saqlangan."\n            )\n        bot = Bot(token=tenant["bot_token"])\n        try:\n            await bot.send_message(session["chat_id"], text)\n            await mark_candidate_session_reminded(session["storage_key"], session["stage"])\n        except Exception:\n            logger.exception("Yarim qolgan ariza eslatmasi yuborilmadi: tenant=%s", tenant["id"])\n        finally:\n            await bot.session.close()\n\n\nasync def _send_interview_automatic_followups() -> None:\n    now = datetime.now(timezone.utc)\n    for item in await database.list_interview_followup_candidates():\n        try:\n            starts_at = datetime.fromisoformat(item["starts_at"])\n            if starts_at.tzinfo is None:\n                starts_at = starts_at.replace(tzinfo=timezone.utc)\n        except (TypeError, ValueError):\n            continue\n        minutes = (starts_at - now).total_seconds() / 60\n        if minutes > 0:\n            if minutes <= 120:\n                stage = "2h"\n                text = f"⏰ Suhbatga taxminan 2 soat qoldi. Vaqt: {item['selected_slot']}"\n            elif minutes <= 1440:\n                stage = "24h"\n                text = f"📅 Eslatma: ertaga suhbat bor. Vaqt: {item['selected_slot']}"\n            else:\n                continue\n            key = f"interview:{item['app_id']}:{stage}"\n            if await database.was_system_notification_sent(key):\n                continue\n            bot = Bot(token=item["bot_token"])\n            try:\n                await bot.send_message(item["user_id"], text)\n                await database.mark_system_notification_sent(key)\n            except Exception:\n                logger.exception("Suhbat eslatmasi yuborilmadi: app=%s", item["app_id"])\n            finally:\n                await bot.session.close()\n            continue\n\n        # Suhbat o'tganidan keyin adminni natijani belgilashga chaqiramiz.\n        if minutes < -1440 or not item.get("admin_bot_token"):\n            continue\n        key = f"interview:{item['app_id']}:outcome_prompt"\n        if await database.was_system_notification_sent(key):\n            continue\n        builder = InlineKeyboardBuilder()\n        builder.button(text="✅ Ishga olindi", callback_data=f"ivoutcome:{item['app_id']}:hired")\n        builder.button(text="❌ Ishga olinmadi", callback_data=f"ivoutcome:{item['app_id']}:not_hired")\n        builder.button(text="🚫 Kelmadi", callback_data=f"ivoutcome:{item['app_id']}:no_show")\n        builder.adjust(1)\n        bot = Bot(token=item["admin_bot_token"])\n        sent = False\n        try:\n            for admin_id in item.get("admin_user_ids") or []:\n                await bot.send_message(\n                    admin_id,\n                    f"📋 <b>Suhbat natijasini belgilang</b>\\n\\n"\n                    f"Nomzod: <b>{item['full_name']}</b>\\n"\n                    f"Lavozim: {item['vacancy_title']}\\nVaqt: {item['selected_slot']}",\n                    reply_markup=builder.as_markup(),\n                    parse_mode=ParseMode.HTML,\n                )\n                sent = True\n        except Exception:\n            logger.exception("Suhbat natijasi prompti yuborilmadi: app=%s", item["app_id"])\n        finally:\n            await bot.session.close()\n        if sent:\n            await database.mark_system_notification_sent(key)\n'''
insert_before("services/reminders.py", "\n\nasync def run_reminders_forever() -> None:\n", REMINDER_FUNCS)
replace_once(
    "services/reminders.py",
    '''            await _send_unpaid_order_reminders()\n        except Exception:\n            logger.exception("Eslatmalar siklida xato")\n        await asyncio.sleep(600)\n''',
    '''            await _send_unpaid_order_reminders()\n            await _send_abandoned_application_reminders()\n            await _send_interview_automatic_followups()\n        except Exception:\n            logger.exception("Eslatmalar siklida xato")\n        await asyncio.sleep(300)\n''',
)


# Admin interview result callback: same state transition as Mini App.
replace_once(
    "admin_bot/handlers_interview.py",
    '''from services import database\n''',
    '''from services import database\nfrom services.candidate_followup import notify_candidate_outcome\n''',
)
ADMIN_OUTCOME = '''\n\n@router.callback_query(F.data.startswith("ivoutcome:"))\nasync def interview_outcome(callback: CallbackQuery, tenant_id: int):\n    try:\n        _, app_id_raw, outcome = callback.data.split(":", 2)\n        app_id = int(app_id_raw)\n    except (TypeError, ValueError):\n        await callback.answer("Noto'g'ri amal.", show_alert=True)\n        return\n    if outcome not in {"hired", "not_hired", "no_show"}:\n        await callback.answer("Noto'g'ri natija.", show_alert=True)\n        return\n    changed = await database.transition_application_status(\n        tenant_id, app_id, outcome, {"accepted"}\n    )\n    if not changed:\n        await callback.answer("Bu suhbat natijasi allaqachon belgilangan.", show_alert=True)\n        return\n    await notify_candidate_outcome(tenant_id, app_id, outcome)\n    labels = {"hired": "Ishga olindi", "not_hired": "Ishga olinmadi", "no_show": "Suhbatga kelmadi"}\n    try:\n        await callback.message.edit_reply_markup(reply_markup=None)\n    except Exception:\n        pass\n    await callback.answer(f"✅ {labels[outcome]}")\n'''
text = read("admin_bot/handlers_interview.py")
if "async def interview_outcome" not in text:
    write("admin_bot/handlers_interview.py", text + ADMIN_OUTCOME)


# ---------------------------------------------------------------------------
# Mini App assets + structured datetime input.
# ---------------------------------------------------------------------------
replace_once(
    "miniapp/index.html",
    '''  <link rel="stylesheet" href="/miniapp-assets/app.css">\n''',
    '''  <link rel="stylesheet" href="/miniapp-assets/app.css">\n  <link rel="stylesheet" href="/miniapp-assets/janobhr2.css">\n''',
)
replace_once(
    "miniapp/index.html",
    '''<input id="slot-label" maxlength="80" required placeholder="Masalan: 5-sentabr, 14:00">''',
    '''<input id="slot-label" type="datetime-local" maxlength="80" required>''',
)
replace_once(
    "miniapp/index.html",
    '''  <script src="/miniapp-assets/app.js" defer></script>\n''',
    '''  <script src="/miniapp-assets/app.js" defer></script>\n  <script src="/miniapp-assets/janobhr2.js" defer></script>\n''',
)

print("Janob HR 2.0 feature patch applied.")
