"""Janob HR Bot — PDF fayldan matn chiqarish (rezyume tahlili uchun)."""

import io
import logging

from pypdf import PdfReader

logger = logging.getLogger("janob_hr_bot")


def extract_pdf_text(file_bytes: bytes, max_pages: int = 5) -> str:
    """PDF baytlaridan matnni chiqaradi. Skanerlangan (rasm asosidagi) PDF'lar uchun
    bo'sh yoki juda qisqa matn qaytishi mumkin — chaqiruvchi buni tekshirishi kerak.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        parts = []
        for page in reader.pages[:max_pages]:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text.strip())
        return "\n".join(parts)
    except Exception:
        logger.exception("PDF'dan matn chiqarib bo'lmadi.")
        return ""
