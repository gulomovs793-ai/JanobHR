from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise RuntimeError(f"Expected block not found in {path}: {old[:160]!r}")
    write(path, text.replace(old, new, 1))


def splice(path: str, start_marker: str, end_marker: str, replacement: str) -> None:
    text = read(path)
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    write(path, text[:start] + replacement + text[end:])


# ---------------------------------------------------------------------------
# Database: reminder candidates must carry plan metadata so the background
# worker can enforce the same feature gate as UI/API.
# ---------------------------------------------------------------------------
replace_once(
    "services/database.py",
    '''            "a.lang, a.selected_slot, a.status, s.starts_at, t.bot_token, t.admin_bot_token, "\n            "t.admin_user_ids FROM applications a "\n''',
    '''            "a.lang, a.selected_slot, a.status, s.starts_at, t.bot_token, t.admin_bot_token, "\n            "t.admin_user_ids, t.plan_code, t.subscription_expires_at FROM applications a "\n''',
)

# ---------------------------------------------------------------------------
# Automatic interview reminders: GROWTH+ only, and not after subscription
# expiry. Manual interview management remains available in START.
# ---------------------------------------------------------------------------
replace_once(
    "services/reminders.py",
    '''from services import database\nfrom services.storage import (\n''',
    '''from services import database\nfrom services.plans import FEATURE_AUTO_INTERVIEW_REMINDERS, has_feature\nfrom services.storage import (\n''',
)
replace_once(
    "services/reminders.py",
    '''    for item in await database.list_interview_followup_candidates():\n        try:\n            starts_at = datetime.fromisoformat(item["starts_at"])\n''',
    '''    for item in await database.list_interview_followup_candidates():\n        plan_code = item.get("plan_code")\n        if not has_feature(plan_code, FEATURE_AUTO_INTERVIEW_REMINDERS):\n            continue\n        if plan_code not in {"trial", "legacy"}:\n            expires_at = item.get("subscription_expires_at")\n            try:\n                expiry = datetime.fromisoformat(expires_at) if expires_at else None\n                if expiry is None or expiry <= now:\n                    continue\n            except (TypeError, ValueError):\n                continue\n        try:\n            starts_at = datetime.fromisoformat(item["starts_at"])\n''',
)

# ---------------------------------------------------------------------------
# Mini App API: premium intelligence endpoints are server-side gated. Billing
# returns feature labels so users can see why higher plans cost more.
# ---------------------------------------------------------------------------
replace_once(
    "miniapp_api.py",
    '''from services.plans import PUBLIC_PLAN_CODES, get_plan, get_plan_transition\n''',
    '''from services.plans import (\n    FEATURE_FUNNEL_ANALYTICS,\n    FEATURE_RISK_SIGNALS,\n    FEATURE_TOP_CANDIDATE_COMPARE,\n    PUBLIC_PLAN_CODES,\n    feature_label,\n    get_plan,\n    get_plan_transition,\n    has_feature,\n    market_feature_labels,\n    minimum_plan_for_feature,\n)\n''',
)
replace_once(
    "miniapp_api.py",
    '''    bucket.append(time.monotonic())\n    return tenant, auth\n\n\ndef _candidate_summary(app: dict) -> dict:\n''',
    '''    bucket.append(time.monotonic())\n    return tenant, auth\n\n\nasync def _feature_enabled_for_tenant(tenant_id: int, feature: str) -> bool:\n    usage = await database.get_subscription_usage(tenant_id)\n    return not usage["expired"] and has_feature(usage["plan"].code, feature)\n\n\nasync def _require_feature(tenant_id: int, feature: str) -> None:\n    if await _feature_enabled_for_tenant(tenant_id, feature):\n        return\n    required_code = minimum_plan_for_feature(feature)\n    required = get_plan(required_code).name\n    raise web.HTTPForbidden(\n        text=f"{feature_label(feature)} — {required} tarifidan boshlab mavjud."\n    )\n\n\ndef _candidate_summary(app: dict) -> dict:\n''',
)
replace_once(
    "miniapp_api.py",
    '''            "risk_signals": candidate_risks(app, vacancy),\n''',
    '''            "risk_signals": (\n                candidate_risks(app, vacancy)\n                if await _feature_enabled_for_tenant(tenant["id"], FEATURE_RISK_SIGNALS)\n                else []\n            ),\n''',
)
replace_once(
    "miniapp_api.py",
    '''async def analytics_funnel(request: web.Request):\n    tenant, _ = await _authorize(request)\n    try:\n''',
    '''async def analytics_funnel(request: web.Request):\n    tenant, _ = await _authorize(request)\n    await _require_feature(tenant["id"], FEATURE_FUNNEL_ANALYTICS)\n    try:\n''',
)
replace_once(
    "miniapp_api.py",
    '''async def compare_top_candidates(request: web.Request):\n    tenant, _ = await _authorize(request)\n    vacancy_key = (request.query.get("vacancy_key") or "").strip()\n''',
    '''async def compare_top_candidates(request: web.Request):\n    tenant, _ = await _authorize(request)\n    await _require_feature(tenant["id"], FEATURE_TOP_CANDIDATE_COMPARE)\n    vacancy_key = (request.query.get("vacancy_key") or "").strip()\n''',
)
replace_once(
    "miniapp_api.py",
    '''                    "vacancies": get_plan(code).vacancy_limit,\n                    "purchase_state": get_plan_transition(\n''',
    '''                    "vacancies": get_plan(code).vacancy_limit,\n                    "features": market_feature_labels(code),\n                    "purchase_state": get_plan_transition(\n''',
)

# ---------------------------------------------------------------------------
# Admin candidate cards: START keeps AI scoring but premium risk/red-flag
# interpretation is hidden until GROWTH. AI outage warnings stay visible.
# ---------------------------------------------------------------------------
replace_once(
    "handlers/admin.py",
    '''from services.ai_scoring import aggregate_scores, get_ai_unavailable_keys\nfrom vacancies import build_questions\n''',
    '''from services.ai_scoring import aggregate_scores, get_ai_unavailable_keys\nfrom services.plans import FEATURE_RISK_SIGNALS, has_feature\nfrom vacancies import build_questions\n''',
)
replace_once(
    "handlers/admin.py",
    '''def format_candidate_card(app: dict) -> str:\n''',
    '''def format_candidate_card(app: dict, *, show_risks: bool = True) -> str:\n''',
)
replace_once(
    "handlers/admin.py",
    '''    risk = "Aniq xavf aniqlanmadi."\n    if aggregate and aggregate.get("red_flags"):\n        risk = _RED_FLAG_LABELS.get(\n            aggregate["red_flags"][0], aggregate["red_flags"][0]\n        )\n    elif weakest and weakest.get("score", 100) < 70:\n        risk = weakest.get("izoh") or "Ayrim javoblari yetarlicha aniq emas."\n''',
    '''    risk = "Risk signallari GROWTH tarifida mavjud."\n    if show_risks:\n        risk = "Aniq xavf aniqlanmadi."\n        if aggregate and aggregate.get("red_flags"):\n            risk = _RED_FLAG_LABELS.get(\n                aggregate["red_flags"][0], aggregate["red_flags"][0]\n            )\n        elif weakest and weakest.get("score", 100) < 70:\n            risk = weakest.get("izoh") or "Ayrim javoblari yetarlicha aniq emas."\n''',
)
replace_once(
    "handlers/admin.py",
    '''    tenant_id = app["tenant_id"]\n\n    for key, value in app["answers"].items():\n''',
    '''    tenant_id = app["tenant_id"]\n    usage = await database.get_subscription_usage(tenant_id)\n    show_risks = not usage["expired"] and has_feature(\n        usage["plan"].code, FEATURE_RISK_SIGNALS\n    )\n\n    for key, value in app["answers"].items():\n''',
)
replace_once(
    "handlers/admin.py",
    '''        if aggregate["red_flags"]:\n            flag_labels = [_RED_FLAG_LABELS.get(f, f) for f in aggregate["red_flags"]]\n            lines.append("🚩 Bayroqlar: " + "; ".join(flag_labels))\n\n    suspect_keys = app.get("ai_suspect_flags") or []\n    if suspect_keys and vacancy:\n''',
    '''        if aggregate["red_flags"] and show_risks:\n            flag_labels = [_RED_FLAG_LABELS.get(f, f) for f in aggregate["red_flags"]]\n            lines.append("🚩 Bayroqlar: " + "; ".join(flag_labels))\n        elif aggregate["red_flags"]:\n            lines.append("🔒 Red flag tahlili GROWTH tarifidan boshlab ochiladi.")\n\n    suspect_keys = app.get("ai_suspect_flags") or []\n    if suspect_keys and vacancy and show_risks:\n''',
)
replace_once(
    "handlers/admin.py",
    '''    text = format_candidate_card(app)\n    builder = InlineKeyboardBuilder()\n''',
    '''    usage = await database.get_subscription_usage(tenant_id)\n    text = format_candidate_card(\n        app,\n        show_risks=not usage["expired"]\n        and has_feature(usage["plan"].code, FEATURE_RISK_SIGNALS),\n    )\n    builder = InlineKeyboardBuilder()\n''',
)

# Candidate detail opened later in Admin bot must use the same gate as the
# initial notification card.
replace_once(
    "admin_bot/handlers_candidates.py",
    '''from services.ai_scoring import aggregate_scores\n''',
    '''from services.ai_scoring import aggregate_scores\nfrom services.plans import FEATURE_RISK_SIGNALS, has_feature\n''',
)
replace_once(
    "admin_bot/handlers_candidates.py",
    '''    text = format_candidate_card(app)\n    text += f"\\n\\n📌 {_STATUS.get(app['status'], app['status'])}"\n''',
    '''    usage = await database.get_subscription_usage(tenant_id)\n    text = format_candidate_card(\n        app,\n        show_risks=not usage["expired"]\n        and has_feature(usage["plan"].code, FEATURE_RISK_SIGNALS),\n    )\n    text += f"\\n\\n📌 {_STATUS.get(app['status'], app['status'])}"\n''',
)

# ---------------------------------------------------------------------------
# Admin statistics becomes the main visible differentiation:
# START = basic stats; GROWTH = vacancy breakdown + funnel + top-3 compare;
# BUSINESS = conversion-rate reporting + priority support.
# ---------------------------------------------------------------------------
replace_once(
    "admin_bot/handlers_menu.py",
    '''from services import database\n\nrouter = Router(name="admin_menu")\n''',
    '''from services import database\nfrom services.hiring_intelligence import compare_candidates, hiring_funnel\nfrom services.plans import (\n    FEATURE_ADVANCED_REPORTING,\n    FEATURE_FUNNEL_ANALYTICS,\n    FEATURE_PER_VACANCY_REPORTING,\n    FEATURE_PRIORITY_SUPPORT,\n    FEATURE_TOP_CANDIDATE_COMPARE,\n    get_plan,\n    has_feature,\n)\n\nrouter = Router(name="admin_menu")\n''',
)
new_stats = '''@router.callback_query(F.data == "menu:stats")\nasync def show_stats(callback: CallbackQuery, tenant_id: int):\n    text, markup = await _stats_content(tenant_id)\n    await callback.message.edit_text(text, reply_markup=markup)\n    await callback.answer()\n\n\nasync def _stats_content(tenant_id: int):\n    usage = await database.get_subscription_usage(tenant_id)\n    plan_code = usage["plan"].code\n    premium_active = not usage["expired"]\n    overall = await database.get_overall_stats(tenant_id)\n\n    lines = [\n        f"📊 <b>Hisobot · {usage['plan'].name}</b>",\n        "",\n        f"📥 Jami ariza: <b>{overall['total']}</b>",\n        f"⏳ Kutilmoqda: {overall['pending']}",\n        f"✅ Suhbatga: {overall['accepted']}",\n        f"❌ Rad etilgan: {overall['rejected_total']}",\n    ]\n    builder = InlineKeyboardBuilder()\n\n    if premium_active and has_feature(plan_code, FEATURE_PER_VACANCY_REPORTING):\n        per_vacancy = await database.get_vacancy_stats(tenant_id)\n        if per_vacancy:\n            lines.extend(["", "<b>Vakansiyalar bo'yicha:</b>"])\n            for item in per_vacancy:\n                lines.append(\n                    f"• <b>{item['vacancy_title']}</b>: {item['total']} ariza · "\n                    f"{item['accepted']} suhbat · {item['rejected']} rad"\n                )\n\n    funnel = None\n    if premium_active and has_feature(plan_code, FEATURE_FUNNEL_ANALYTICS):\n        apps = await database.list_funnel_applications(tenant_id, days=30)\n        funnel = hiring_funnel(apps)\n        lines.extend(\n            [\n                "",\n                "<b>30 kunlik hiring funnel:</b>",\n                f"Ariza: {funnel['applications']} → Filtrdan o'tdi: {funnel['passed_filter']} "\n                f"→ Kuchli: {funnel['strong']} → Suhbat: {funnel['interview']} "\n                f"→ Ishga olindi: {funnel['hired']}",\n            ]\n        )\n\n    if (\n        funnel\n        and premium_active\n        and has_feature(plan_code, FEATURE_ADVANCED_REPORTING)\n    ):\n        rates = funnel["rates"]\n        lines.extend(\n            [\n                "",\n                "<b>BUSINESS conversion:</b>",\n                f"Filtrdan o'tish: <b>{rates['filter_pass']}%</b>",\n                f"Kuchli nomzod: <b>{rates['strong']}%</b>",\n                f"Suhbatga o'tish: <b>{rates['interview']}%</b>",\n                f"Suhbatdan hire: <b>{rates['hire']}%</b>",\n                f"No-show: <b>{funnel['no_show']}</b>",\n            ]\n        )\n\n    if premium_active and has_feature(plan_code, FEATURE_TOP_CANDIDATE_COMPARE):\n        vacancies = await database.list_vacancies(tenant_id, active_only=False)\n        active = [item for item in vacancies if item.get("active")]\n        if active:\n            lines.extend(["", "🏆 <b>Top-3 taqqoslash uchun vakansiyani tanlang:</b>"])\n            for vacancy in active[:10]:\n                builder.button(\n                    text=f"🏆 {vacancy['title']}",\n                    callback_data=f"intel:top:{vacancy['key']}",\n                )\n\n    if not premium_active or not has_feature(plan_code, FEATURE_FUNNEL_ANALYTICS):\n        lines.extend(\n            [\n                "",\n                "🔒 Funnel, Top-3 va risk analytics GROWTH tarifidan boshlab mavjud.",\n            ]\n        )\n\n    builder.button(text="⬅️ Orqaga", callback_data="menu:main")\n    builder.adjust(1)\n    return "\\n".join(lines), builder.as_markup()\n\n\n@router.callback_query(F.data.startswith("intel:top:"))\nasync def top_candidates(callback: CallbackQuery, tenant_id: int):\n    usage = await database.get_subscription_usage(tenant_id)\n    if usage["expired"] or not has_feature(\n        usage["plan"].code, FEATURE_TOP_CANDIDATE_COMPARE\n    ):\n        await callback.answer(\n            "Top nomzodlarni taqqoslash GROWTH tarifidan boshlab mavjud.",\n            show_alert=True,\n        )\n        return\n    vacancy_key = callback.data.split(":", 2)[2]\n    vacancy = await database.get_vacancy(tenant_id, vacancy_key)\n    if not vacancy:\n        await callback.answer("Vakansiya topilmadi.", show_alert=True)\n        return\n    apps = await database.list_funnel_applications(\n        tenant_id, days=90, vacancy_key=vacancy_key\n    )\n    comparison = compare_candidates(apps, vacancy, limit=3)\n    lines = [f"🏆 <b>{vacancy['title']} · Top nomzodlar</b>", ""]\n    if not comparison["items"]:\n        lines.append("Taqqoslash uchun yetarli faol nomzod yo'q.")\n    else:\n        for item in comparison["items"]:\n            score = item["score"] if item["score"] is not None else "—"\n            lines.append(f"<b>{item['rank']}. {item['full_name']}</b> · {score}/100")\n            lines.append(f"   Kuchli tomon: {item['strength']['summary']}")\n            if item["risks"]:\n                risk_text = "; ".join(risk["label"] for risk in item["risks"][:2])\n                lines.append(f"   ⚠️ {risk_text}")\n        if comparison.get("recommendation"):\n            lines.extend(["", f"🎯 {comparison['recommendation']['text']}"])\n\n    builder = InlineKeyboardBuilder()\n    builder.button(text="⬅️ Hisobot", callback_data="menu:stats")\n    await callback.message.edit_text("\\n".join(lines), reply_markup=builder.as_markup())\n    await callback.answer()\n\n\nasync def _send_stats(message: Message, tenant_id: int):\n    text, markup = await _stats_content(tenant_id)\n    await message.answer(text, reply_markup=markup)\n\n\n'''
splice(
    "admin_bot/handlers_menu.py",
    '@router.callback_query(F.data == "menu:stats")\nasync def show_stats',
    '@router.message(F.text == ADMIN_MENU["new"])',
    new_stats,
)
replace_once(
    "admin_bot/handlers_menu.py",
    '''@router.message(F.text == ADMIN_MENU["help"])\nasync def service_help(message: Message):\n    await message.answer(\n        "☎️ <b>Yordam</b>\\n\\nSavol yoki muammo bo'lsa, <b>@F45746</b> ga yozing."\n    )\n''',
    '''@router.message(F.text == ADMIN_MENU["help"])\nasync def service_help(message: Message, tenant_id: int):\n    usage = await database.get_subscription_usage(tenant_id)\n    if not usage["expired"] and has_feature(\n        usage["plan"].code, FEATURE_PRIORITY_SUPPORT\n    ):\n        text = (\n            "⚡ <b>BUSINESS Priority Support</b>\\n\\n"\n            "Savol yoki muammo bo'lsa, <b>@F45746</b> ga yozing. "\n            "BUSINESS murojaatlari ustuvor ko'rib chiqiladi."\n        )\n    else:\n        text = "☎️ <b>Yordam</b>\\n\\nSavol yoki muammo bo'lsa, <b>@F45746</b> ga yozing."\n    await message.answer(text)\n''',
)

# ---------------------------------------------------------------------------
# Billing UI clearly shows what each paid tier unlocks.
# ---------------------------------------------------------------------------
replace_once(
    "miniapp/app.js",
    '''<p>${p.applications} ariza · ${p.vacancies} vakansiya</p></div></div><div class="price">''',
    '''<p>${p.applications} ariza · ${p.vacancies} vakansiya</p>${(p.features||[]).length?`<ul class="plan-features">${p.features.map(item=>`<li>✓ ${esc(item)}</li>`).join('')}</ul>`:''}</div></div><div class="price">''',
)
css_path = Path("miniapp/app.css")
css = css_path.read_text(encoding="utf-8")
if ".plan-features{" not in css:
    css += '''\n\n.plan-features{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:6px;font-size:13px;line-height:1.35}.plan-features li{opacity:.82}.price-card.popular .plan-features li{opacity:.92}\n'''
    css_path.write_text(css, encoding="utf-8")

# ---------------------------------------------------------------------------
# Regression tests for feature matrix and visible risk gating.
# ---------------------------------------------------------------------------
Path("tests/test_plan_features.py").write_text(
    '''import unittest\n\nfrom handlers.admin import format_candidate_card\nfrom services.plans import (\n    FEATURE_ADVANCED_REPORTING,\n    FEATURE_AUTO_INTERVIEW_REMINDERS,\n    FEATURE_FUNNEL_ANALYTICS,\n    FEATURE_RISK_SIGNALS,\n    FEATURE_TOP_CANDIDATE_COMPARE,\n    has_feature,\n    market_feature_labels,\n    minimum_plan_for_feature,\n)\n\n\ndef scored(score: int, flags=None) -> dict:\n    return {\n        "score": score,\n        "verdict": "yashil" if score >= 75 else "sariq",\n        "natijadorlik": score,\n        "masuliyat": score,\n        "aniqlik": score,\n        "relevant": True,\n        "red_flags": flags or [],\n        "izoh": "Qisqa izoh",\n        "evidence": "Aniq natija",\n    }\n\n\nclass PlanFeatureTests(unittest.TestCase):\n    def test_start_keeps_core_but_not_growth_intelligence(self):\n        self.assertFalse(has_feature("start", FEATURE_RISK_SIGNALS))\n        self.assertFalse(has_feature("start", FEATURE_TOP_CANDIDATE_COMPARE))\n        self.assertFalse(has_feature("start", FEATURE_FUNNEL_ANALYTICS))\n        self.assertFalse(has_feature("start", FEATURE_AUTO_INTERVIEW_REMINDERS))\n\n    def test_growth_unlocks_intelligence_but_not_business_reporting(self):\n        self.assertTrue(has_feature("growth", FEATURE_RISK_SIGNALS))\n        self.assertTrue(has_feature("growth", FEATURE_TOP_CANDIDATE_COMPARE))\n        self.assertTrue(has_feature("growth", FEATURE_FUNNEL_ANALYTICS))\n        self.assertTrue(has_feature("growth", FEATURE_AUTO_INTERVIEW_REMINDERS))\n        self.assertFalse(has_feature("growth", FEATURE_ADVANCED_REPORTING))\n\n    def test_business_unlocks_advanced_reporting(self):\n        self.assertTrue(has_feature("business", FEATURE_ADVANCED_REPORTING))\n        self.assertEqual(minimum_plan_for_feature(FEATURE_ADVANCED_REPORTING), "business")\n\n    def test_billing_feature_lists_are_differentiated(self):\n        start = market_feature_labels("start")\n        growth = market_feature_labels("growth")\n        business = market_feature_labels("business")\n        self.assertGreater(len(growth), len(start))\n        self.assertNotEqual(growth, business)\n        self.assertIn("Priority support", business)\n\n    def test_start_card_does_not_expose_red_flag_details(self):\n        app = {\n            "full_name": "Test Nomzod",\n            "vacancy_title": "Sotuvchi",\n            "phone_number": "+998",\n            "ai_scores": {"q": scored(82, ["qurbon_sindromi"])},\n        }\n        locked = format_candidate_card(app, show_risks=False)\n        premium = format_candidate_card(app, show_risks=True)\n        self.assertIn("GROWTH", locked)\n        self.assertNotIn("Qurbon sindromi", locked)\n        self.assertIn("Qurbon sindromi", premium)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)

print("Feature pricing differentiation applied.")
