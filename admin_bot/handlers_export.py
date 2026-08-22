"""Admin bot — nomzodlar ro'yxatini Excel (.xlsx) fayl sifatida eksport qilish."""
import io
import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery
from openpyxl import Workbook
from openpyxl.styles import Font

from services import database
from services.ai_scoring import aggregate_scores

logger = logging.getLogger("janob_hr_bot")

router = Router(name="admin_export")

_STATUS_LABELS = {
    "pending": "Kutilmoqda",
    "accepted": "Qabul qilingan",
    "declined": "Rad etilgan (admin)",
    "rejected_hard_filter": "Talabga javob bermadi",
    "rejected_irrelevant": "Mavzuga mos kelmadi",
}

_HEADERS = [
    "#", "Ism-familiya", "Username", "Telefon", "AI ball", "Verdikt",
    "Holat", "Ariza sanasi", "Tanlagan suhbat vaqti", "Javoblar",
]


@router.callback_query(F.data.startswith("vacexport:"))
async def export_candidates_excel(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return

    await callback.answer("Excel fayl tayyorlanmoqda...")

    apps = await database.get_applications_for_vacancy(tenant_id, key)

    rows = []
    for app in apps:
        aggregate = aggregate_scores(app.get("ai_scores") or {})
        score = aggregate["avg_score"] if aggregate else None
        verdict = aggregate["verdict"] if aggregate else ""
        answers_text = " | ".join(str(v) for v in app["answers"].values())
        rows.append((score, verdict, answers_text, app))

    # Eng yuqori AI ball birinchi bo'lib chiqadi (ball bo'lmaganlar oxirida).
    rows.sort(key=lambda r: (r[0] is None, -(r[0] or 0)))

    wb = Workbook()
    ws = wb.active
    ws.title = "Nomzodlar"
    ws.append(_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for i, (score, verdict, answers_text, app) in enumerate(rows, 1):
        created = (app.get("created_at") or "")[:16].replace("T", " ")
        ws.append([
            i,
            app["full_name"],
            app["username"] or "",
            app.get("phone_number") or "",
            score if score is not None else "",
            verdict,
            _STATUS_LABELS.get(app["status"], app["status"]),
            created,
            app.get("selected_slot") or "",
            answers_text,
        ])

    # Ustun kengliklarini o'qishga qulay qilib sozlaymiz.
    widths = [4, 22, 16, 16, 9, 9, 20, 16, 20, 80]
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    safe_title = "".join(c if c.isalnum() else "_" for c in vacancy["title"])[:40]
    filename = f"{safe_title}_nomzodlar.xlsx"

    await callback.message.answer_document(
        BufferedInputFile(buffer.read(), filename=filename),
        caption=f"📊 <b>{vacancy['title']}</b> — {len(rows)} ta nomzod (AI ball bo'yicha saralangan)",
    )
