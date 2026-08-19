"""Admin bot — qo'lda kiritilgan savollar matnini tuzilgan ro'yxatga aylantirish."""
from services.database import make_vacancy_key

MANUAL_FORMAT_HELP = (
    "Har bir qatorga bitta savol yozing. Qator oxiriga (ixtiyoriy) belgi qo'shishingiz mumkin:\n"
    "  <code>| filter</code> — bu savol majburiy filtr (salbiy javobda nomzod avtomatik rad etiladi)\n"
    "  <code>| score</code> — bu javob AI orqali chuqur tahlil qilinadi\n\n"
    "Misol:\n"
    "<code>Tajribangiz bormi? (Ha/Yo'q) | filter\n"
    "Eng katta yutug'ingiz nima? | score\n"
    "Qanday dasturlardan foydalanasiz?</code>"
)


def parse_manual_questions(text: str) -> list[dict]:
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    questions: list[dict] = []
    seen_keys: set[str] = set()

    for line in lines:
        content = line
        hard_filter = False
        ai_score = False

        if "|" in line:
            content, marker = line.rsplit("|", 1)
            content = content.strip()
            marker = marker.strip().lower()
            if marker == "filter":
                hard_filter = True
            elif marker == "score":
                ai_score = True

        if not content:
            continue

        base_key = make_vacancy_key(content)[:30] or f"savol_{len(questions) + 1}"
        key = base_key
        n = 2
        while key in seen_keys:
            key = f"{base_key}_{n}"
            n += 1
        seen_keys.add(key)

        q = {"key": key, "text": content}
        if hard_filter:
            q["hard_filter"] = True
        if ai_score:
            q["ai_score"] = True
        questions.append(q)

    return questions


def format_questions_preview(questions: list[dict], limit: int = 20) -> str:
    lines = []
    for i, q in enumerate(questions[:limit], 1):
        marker = ""
        if q.get("hard_filter"):
            marker += " 🔒"
        if q.get("ai_score"):
            marker += " 🤖"
        lines.append(f"{i}. {q['text']}{marker}")
    if len(questions) > limit:
        lines.append(f"… va yana {len(questions) - limit} ta savol")
    return "\n".join(lines)


def to_manual_format(questions: list[dict]) -> str:
    """Savollar ro'yxatini qo'lda tahrirlash uchun matn formatiga o'giradi
    (mavjud vakansiyani tahrirlashda, admin buni nusxalab, o'zgartirib qayta yuborishi uchun)."""
    lines = []
    for q in questions:
        marker = ""
        if q.get("hard_filter"):
            marker = " | filter"
        elif q.get("ai_score"):
            marker = " | score"
        lines.append(f"{q['text']}{marker}")
    return "\n".join(lines)
