from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise AssertionError(f"anchor not found: {label}")
    return text.replace(old, new, 1)


# --- services/ai_scoring.py -------------------------------------------------
p = Path("services/ai_scoring.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    "direktor kabi 3 mezon bo'yicha (Natijadorlik, Mas'uliyat, Aniqlik) baholaydi,",
    "direktor kabi 3 mezon bo'yicha (Natijadorlik, Amaliylik, Aniqlik) baholaydi,",
    1,
)
s = replace_once(
    s,
    """    natijadorlik: int
    masuliyat: int
    aniqlik: int""",
    """    natijadorlik: int
    amaliylik: int
    masuliyat: int  # legacy alias; mazmuni Amaliylik
    aniqlik: int""",
    "ScoreResult metrics",
)
old_criteria = """Javob relevant bo'lsa, uni 3 ta qat'iy mezon bo'yicha 0 dan 100 gacha bahola:
1. natijadorlik — Matnda aniq raqamlar, foizlar, muddatlar bormi, yoki faqat quruq umumiy gaplarmi?
2. masuliyat — Muammo haqida gapirganda, nomzod boshqalarni/vaziyatni ayblaydimi (\"Biz\",
   \"Bozor yomon edi\", \"Rahbarim ahmoq edi\"), yoki o'z harakatiga mas'uliyat oladimi (\"Men qildim\")?
3. aniqlik — Savolga to'g'ridan-to'g'ri va tushunarli javob berdimi, yoki chalg'itib,
   umumiy gapirdimi?"""
new_criteria = """Javob relevant bo'lsa, uni 3 ta qat'iy mezon bo'yicha 0 dan 100 gacha bahola:
1. natijadorlik — Javob natijaga yo'naltirilganmi? Savol natija/yutuq haqida bo'lsa raqam,
   foiz, muddat va o'lchanadigan natijani qidir. Savol reja yoki vaziyat haqida bo'lsa,
   muvaffaqiyatni qanday o'lchashi va natijaga olib boradigan mezonlarni bahola. Savolning
   o'zi raqam talab qilmasa, raqam yo'qligi uchungina ballni sun'iy pasaytirma.
2. amaliylik — Javob real ishda bajariladigan aniq harakat, ketma-ket qadam, vosita yoki
   shaxsiy hissa bilan ochilganmi? Quruq nazariya va umumiy gapga past, real vaziyatda
   bajarish mumkin bo'lgan yondashuvga yuqori ball ber.
3. aniqlik — Savolga to'g'ridan-to'g'ri va tushunarli javob berdimi, yoki chalg'itib,
   umumiy gapirdimi?"""
s = replace_once(s, old_criteria, new_criteria, "scoring criteria")
s = replace_once(
    s,
    '{"relevant": <true yoki false>, "natijadorlik": <son>, "masuliyat": <son>, "aniqlik": <son>, \\\n',
    '{"relevant": <true yoki false>, "natijadorlik": <son>, "amaliylik": <son>, "aniqlik": <son>, \\\n',
    "scoring JSON key",
)
s = replace_once(
    s,
    """        natijadorlik = max(0, min(100, int(parsed.get("natijadorlik", 0))))
        masuliyat = max(0, min(100, int(parsed.get("masuliyat", 0))))
        aniqlik = max(0, min(100, int(parsed.get("aniqlik", 0))))
        avg = round((natijadorlik + masuliyat + aniqlik) / 3)""",
    """        natijadorlik = max(0, min(100, int(parsed.get("natijadorlik", 0))))
        amaliylik = max(
            0,
            min(100, int(parsed.get("amaliylik", parsed.get("masuliyat", 0)))),
        )
        # Eski yozuvlar va integratsiyalar buzilmasligi uchun legacy alias ham saqlanadi.
        masuliyat = amaliylik
        aniqlik = max(0, min(100, int(parsed.get("aniqlik", 0))))
        avg = round((natijadorlik + amaliylik + aniqlik) / 3)""",
    "score parse",
)
s = replace_once(
    s,
    """            natijadorlik=natijadorlik,
            masuliyat=masuliyat,
            aniqlik=aniqlik,""",
    """            natijadorlik=natijadorlik,
            amaliylik=amaliylik,
            masuliyat=masuliyat,
            aniqlik=aniqlik,""",
    "score result",
)
s = replace_once(
    s,
    """    avg_natijadorlik: int
    avg_masuliyat: int
    avg_aniqlik: int""",
    """    avg_natijadorlik: int
    avg_amaliylik: int
    avg_masuliyat: int  # legacy alias
    avg_aniqlik: int""",
    "aggregate typed dict",
)
s = replace_once(
    s,
    """    avg_natijadorlik = round(sum(v.get("natijadorlik", 0) for v in valid) / len(valid))
    avg_masuliyat = round(sum(v.get("masuliyat", 0) for v in valid) / len(valid))
    avg_aniqlik = round(sum(v.get("aniqlik", 0) for v in valid) / len(valid))""",
    """    avg_natijadorlik = round(sum(v.get("natijadorlik", 0) for v in valid) / len(valid))
    avg_amaliylik = round(
        sum(v.get("amaliylik", v.get("masuliyat", 0)) for v in valid) / len(valid)
    )
    avg_masuliyat = avg_amaliylik
    avg_aniqlik = round(sum(v.get("aniqlik", 0) for v in valid) / len(valid))""",
    "aggregate metrics",
)
s = replace_once(
    s,
    """    has_qizil = any(v.get("verdict") == "qizil" for v in valid)
    if has_qizil or avg_score < 50:
        verdict = "qizil"
    elif all_flags or avg_score < 75:
        verdict = "sariq"
    else:
        verdict = "yashil"
""",
    """    # Bitta zaif savol butun nomzodni avtomatik qizilga tushirmaydi.
    # Bayroqlar signal bo'lib qoladi; umumiy hukm kompetensiya o'rtachasiga tayanadi.
    if avg_score < 50:
        verdict = "qizil"
    elif all_flags or avg_score < 75:
        verdict = "sariq"
    else:
        verdict = "yashil"
""",
    "aggregate verdict",
)
s = replace_once(
    s,
    """        avg_natijadorlik=avg_natijadorlik,
        avg_masuliyat=avg_masuliyat,
        avg_aniqlik=avg_aniqlik,""",
    """        avg_natijadorlik=avg_natijadorlik,
        avg_amaliylik=avg_amaliylik,
        avg_masuliyat=avg_masuliyat,
        avg_aniqlik=avg_aniqlik,""",
    "aggregate result",
)
p.write_text(s, encoding="utf-8")


# --- handlers/admin.py ------------------------------------------------------
p = Path("handlers/admin.py")
s = p.read_text(encoding="utf-8")
start = s.index("def format_candidate_card(")
end = s.index("\n\nasync def format_application_full_text", start)
new_card = '''def _short(value: object, limit: int = 220) -> str:
    text = str(value or "—").strip() or "—"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _question_title(value: object, limit: int = 76) -> str:
    text = " ".join(str(value or "Savol").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_candidate_analysis(
    app: dict,
    vacancy: dict | None = None,
    *,
    show_risks: bool = True,
) -> dict:
    """Admin bot va Mini App uchun bitta mantiqdagi qisqa HR xulosasi."""
    ai_scores = app.get("ai_scores") or {}
    aggregate = aggregate_scores(ai_scores)
    unavailable_keys = get_ai_unavailable_keys(ai_scores)

    question_map: dict[str, str] = {}
    if vacancy:
        try:
            question_map = {
                q["key"]: q["text"]
                for q in build_questions(vacancy, app.get("lang") or "uz")
            }
        except Exception:
            logger.exception("Tahlil uchun vakansiya savollarini o'qib bo'lmadi")

    scored = [
        (key, value)
        for key, value in ai_scores.items()
        if isinstance(value, dict) and isinstance(value.get("score"), (int, float))
    ]
    strongest = max(scored, key=lambda item: item[1]["score"], default=None)
    weakest = min(scored, key=lambda item: item[1]["score"], default=None)

    selected = []
    if weakest:
        selected.append(weakest)
    if strongest and (not weakest or strongest[0] != weakest[0]):
        selected.append(strongest)
    insights = [
        {
            "key": key,
            "title": _question_title(question_map.get(key) or key.replace("_", " ")),
            "score": int(result.get("score", 0)),
            "summary": _short(result.get("izoh") or "AI izohi mavjud emas.", 260),
        }
        for key, result in selected
    ]

    strength = "Javoblarini to'liq ko'rib chiqing."
    if strongest:
        strength = _short(
            strongest[1].get("evidence") or strongest[1].get("izoh") or strength,
            300,
        )

    if not show_risks:
        risk = "Risk signallari GROWTH tarifida mavjud."
    elif aggregate and aggregate.get("red_flags"):
        labels = [
            _RED_FLAG_LABELS.get(flag, str(flag).replace("_", " "))
            for flag in aggregate["red_flags"][:2]
        ]
        risk = "; ".join(labels)
    elif weakest and int(weakest[1].get("score", 100)) < 70:
        risk = _short(weakest[1].get("izoh") or "Ayrim javoblarni aniqlashtirish kerak.", 300)
    else:
        risk = "Jiddiy xavf signali aniqlanmadi."

    if aggregate:
        score = int(aggregate["avg_score"])
        if score >= 75:
            recommendation = "🟢 Suhbatga tavsiya qilinadi."
        elif score >= 55:
            recommendation = "🟡 Suhbatga chaqirish mumkin. Ayrim joylarni aniqlashtirish kerak."
        else:
            recommendation = "🔴 Hozircha ehtiyotkorlik bilan yondashish kerak."
        metrics = {
            "natijadorlik": int(aggregate["avg_natijadorlik"]),
            "amaliylik": int(aggregate.get("avg_amaliylik", aggregate["avg_masuliyat"])),
            "aniqlik": int(aggregate["avg_aniqlik"]),
        }
    else:
        score = None
        metrics = None
        recommendation = "⚪ AI tahlili vaqtincha to'liq chiqmagan."
        strength = "AI tahlili mavjud emas — javoblarni qo'lda ko'ring."
        if show_risks:
            risk = "AI tahlili mavjud emas — xavfni qo'lda tekshiring."

    return {
        "score": score,
        "metrics": metrics,
        "insights": insights,
        "strength": strength,
        "risk": risk,
        "recommendation": recommendation,
        "partial_ai": bool(unavailable_keys),
        "missing_ai_count": len(unavailable_keys),
    }


def format_candidate_card(
    app: dict,
    *,
    vacancy: dict | None = None,
    show_risks: bool = True,
) -> str:
    analysis = build_candidate_analysis(app, vacancy, show_risks=show_risks)
    score_text = (
        f"<b>{analysis['score']}/100</b>"
        if analysis["score"] is not None
        else "<b>Baholanmagan</b>"
    )
    lines = [
        "📊 <b>Nomzod tahlili</b>",
        "",
        f"Janob HR bahosi: {score_text}",
        "",
        "👤 <b>Nomzod profili</b>",
        f"Ism: <b>{escape(str(app['full_name']))}</b>",
        f"Vakansiya: {escape(str(app['vacancy_title']))}",
        f"Telefon: <code>{escape(str(app.get('phone_number') or '—'))}</code>",
    ]
    if analysis["insights"]:
        lines += ["", "🧠 <b>AI tahlili</b>"]
        for item in analysis["insights"]:
            lines += [
                "",
                f"<b>{escape(item['title'])} — {item['score']}/100</b>",
                escape(item["summary"]),
            ]
    if analysis["metrics"]:
        m = analysis["metrics"]
        lines += [
            "",
            "<b>Baholash</b>",
            f"📈 Natijadorlik: <b>{m['natijadorlik']}</b>",
            f"🛠 Amaliylik: <b>{m['amaliylik']}</b>",
            f"🎯 Aniqlik: <b>{m['aniqlik']}</b>",
        ]
    lines += [
        "",
        "✅ <b>Kuchli tomon</b>",
        escape(analysis["strength"]),
        "",
        "⚠️ <b>Tekshirish kerak</b>",
        escape(analysis["risk"]),
        "",
        "🏁 <b>Janob HR tavsiyasi</b>",
        escape(analysis["recommendation"]),
    ]
    if analysis["partial_ai"]:
        lines += ["", f"⚠️ AI tahlili {analysis['missing_ai_count']} ta savolda ishlamadi."]
    return "\\n".join(lines)
'''
s = s[:start] + new_card + s[end:]

# Hide Telegram username/id from client admin text.
s = replace_once(
    s,
    '''    lines = [
        f"🆕 <b>Yangi anketa</b> — {escape(str(app['vacancy_title']))}",
        (
            f"👤 {escape(str(app['full_name']))} "
            f"(@{escape(str(app['username'] or '—'))}, id: {app['user_id']})"
        ),
    ]''',
    '''    lines = [
        f"🆕 <b>Yangi anketa</b> — {escape(str(app['vacancy_title']))}",
        f"👤 <b>{escape(str(app['full_name']))}</b>",
    ]''',
    "admin identity privacy",
)

# Fetch vacancy before rendering answers so every answer is linked to its real question.
s = replace_once(
    s,
    '''    for key, value in app["answers"].items():
        text = escape(str(value))''',
    '''    vacancy = await database.get_vacancy(tenant_id, app["vacancy_key"])
    question_texts = (
        {q["key"]: q["text"] for q in build_questions(vacancy, app.get("lang") or "uz")}
        if vacancy
        else {}
    )

    for key, value in app["answers"].items():
        if question_texts.get(key):
            lines.append(f"❓ <b>{escape(_short(question_texts[key], 350))}</b>")
        text = escape(str(value))''',
    "question answer linkage",
)
s = replace_once(
    s,
    '''    vacancy = await database.get_vacancy(tenant_id, app["vacancy_key"])
    expected_keys = (''',
    '''    expected_keys = (''',
    "remove duplicate vacancy fetch",
)
s = s.replace(
    '''            f"Mas'uliyat: {aggregate['avg_masuliyat']} | "''',
    '''            f"Amaliylik: {aggregate.get('avg_amaliylik', aggregate['avg_masuliyat'])} | "''',
    1,
)
s = replace_once(
    s,
    '''    suspect_keys = app.get("ai_suspect_flags") or []''',
    '''    analysis = build_candidate_analysis(app, vacancy, show_risks=show_risks)
    lines.append("")
    lines.append(f"✅ <b>Kuchli tomon:</b> {escape(analysis['strength'])}")
    lines.append(f"⚠️ <b>Tekshirish kerak:</b> {escape(analysis['risk'])}")
    lines.append(f"🏁 <b>Janob HR tavsiyasi:</b> {escape(analysis['recommendation'])}")

    suspect_keys = app.get("ai_suspect_flags") or []''',
    "full text summary",
)
s = replace_once(
    s,
    '''    usage = await database.get_subscription_usage(tenant_id)
    text = format_candidate_card(
        app,
        show_risks=not usage["expired"]
        and has_feature(usage["plan"].code, FEATURE_RISK_SIGNALS),
    )''',
    '''    usage = await database.get_subscription_usage(tenant_id)
    vacancy = await database.get_vacancy(tenant_id, app["vacancy_key"])
    text = format_candidate_card(
        app,
        vacancy=vacancy,
        show_risks=not usage["expired"]
        and has_feature(usage["plan"].code, FEATURE_RISK_SIGNALS),
    )''',
    "notify card vacancy",
)
s = replace_once(
    s,
    '''    if voice_answers:
        vacancy = await database.get_vacancy(tenant_id, app["vacancy_key"])
        if vacancy:''',
    '''    if voice_answers:
        if vacancy:''',
    "reuse vacancy",
)
p.write_text(s, encoding="utf-8")


# --- admin_bot/handlers_candidates.py --------------------------------------
p = Path("admin_bot/handlers_candidates.py")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    '''    usage = await database.get_subscription_usage(tenant_id)
    text = format_candidate_card(
        app,
        show_risks=not usage["expired"]
        and has_feature(usage["plan"].code, FEATURE_RISK_SIGNALS),
    )''',
    '''    usage = await database.get_subscription_usage(tenant_id)
    vacancy = await database.get_vacancy(tenant_id, app["vacancy_key"])
    text = format_candidate_card(
        app,
        vacancy=vacancy,
        show_risks=not usage["expired"]
        and has_feature(usage["plan"].code, FEATURE_RISK_SIGNALS),
    )''',
    "admin candidate vacancy context",
)
p.write_text(s, encoding="utf-8")


# --- miniapp_api.py ---------------------------------------------------------
p = Path("miniapp_api.py")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    "from handlers.sell import send_slot_offer",
    "from handlers.admin import build_candidate_analysis\nfrom handlers.sell import send_slot_offer",
    "miniapp analysis import",
)
s = s.replace('        "username": app.get("username"),\n', "", 1)
s = replace_once(
    s,
    '''    result = _candidate_summary(app)
    vacancy = await database.get_vacancy(tenant["id"], app["vacancy_key"])
    result.update(
        {
            "answers": app.get("answers") or {},
            "ai_scores": app.get("ai_scores") or {},
            "suspect_flags": app.get("ai_suspect_flags") or [],
            "has_resume": bool(app.get("resume_file_id")),
            "has_voice": bool(app.get("voice_answers")),
            "risk_signals": (
                candidate_risks(app, vacancy)
                if await _feature_enabled_for_tenant(tenant["id"], FEATURE_RISK_SIGNALS)
                else []
            ),
        }
    )''',
    '''    result = _candidate_summary(app)
    vacancy = await database.get_vacancy(tenant["id"], app["vacancy_key"])
    show_risks = await _feature_enabled_for_tenant(tenant["id"], FEATURE_RISK_SIGNALS)
    result.update(
        {
            "answers": app.get("answers") or {},
            "ai_scores": app.get("ai_scores") or {},
            "analysis": build_candidate_analysis(app, vacancy, show_risks=show_risks),
            "suspect_flags": app.get("ai_suspect_flags") or [],
            "has_resume": bool(app.get("resume_file_id")),
            "has_voice": bool(app.get("voice_answers")),
            "risk_signals": candidate_risks(app, vacancy) if show_risks else [],
        }
    )''',
    "miniapp candidate analysis",
)
s = s.replace("barqarorlik va mas'uliyatni ajratsin", "barqarorlik va amaliylikni ajratsin")
p.write_text(s, encoding="utf-8")


# --- miniapp/janobhr2.js ----------------------------------------------------
p = Path("miniapp/janobhr2.js")
s = p.read_text(encoding="utf-8")
s = s.replace("</b>Mas’uliyat</span>", "</b>Amaliylik</span>")
fn_start = s.index("  async function enhanceCandidateDetail(id) {")
fn_end = s.index("\n\n  function refreshForView", fn_start)
new_fn = '''  async function enhanceCandidateDetail(id) {
    if (!id || detailEnhancing) return;
    const root = document.querySelector('#candidate-detail');
    if (!root || root.querySelector('.jh2-insights')) return;
    detailEnhancing = true;
    try {
      const c = await api(`/candidates/${id}`);
      const a = c.analysis || {};
      const insights = (a.insights || []).map(item => `<div class="jh2-evidence"><b>${esc(item.title)} · ${item.score==null?'—':esc(item.score)+'/100'}</b><p>${esc(item.summary||'')}</p></div>`).join('');
      const metrics = a.metrics ? `<div class="jh2-metrics"><span><b>${esc(a.metrics.natijadorlik)}</b>Natijadorlik</span><span><b>${esc(a.metrics.amaliylik)}</b>Amaliylik</span><span><b>${esc(a.metrics.aniqlik)}</b>Aniqlik</span></div>` : '';
      const risks = (c.risk_signals || []).map(r=>`<span class="jh2-risk">${esc(r.label)}</span>`).join('');
      const html = `<section class="jh2-insights"><h3>Janob HR tahlili</h3>${insights}${metrics}<div class="jh2-evidence"><b>✅ Kuchli tomon</b><p>${esc(a.strength||'Javoblarni ko‘rib chiqing.')}</p></div><div class="jh2-evidence"><b>⚠️ Tekshirish kerak</b><p>${esc(a.risk||'Jiddiy xavf signali aniqlanmadi.')}</p>${risks?`<div>${risks}</div>`:''}</div><div class="jh2-recommend"><b>🏁 Janob HR tavsiyasi</b><br>${esc(a.recommendation||'AI xulosasi mavjud emas.')}</div></section>`;
      root.querySelector('.detail-card')?.insertAdjacentHTML('beforeend', html);
    } catch {} finally { detailEnhancing = false; }
  }'''
s = s[:fn_start] + new_fn + s[fn_end:]
p.write_text(s, encoding="utf-8")

print("tenant candidate analysis patch applied")

