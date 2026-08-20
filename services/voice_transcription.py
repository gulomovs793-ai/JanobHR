"""
Janob HR Bot — ovozli xabarlarni matnga o'girish (Groq Whisper API orqali).

Bu funksiya AI_API_KEY_2 (Groq) sozlangan bo'lishini talab qiladi — chunki
uchta AI provayderimizdan (Gemini, Groq, DeepSeek) faqat Groq alohida,
maxsus nutqni-matnga-o'girish (Whisper) endpointiga ega. Agar Groq
sozlanmagan bo'lsa, funksiya None qaytaradi va chaqiruvchi bu savolni
oddiy matnli savol sifatida davom ettirishi kerak.
"""
import logging

import aiohttp

from config import AI_API_BASE_2, AI_API_KEY_2

logger = logging.getLogger("janob_hr_bot")

_WHISPER_MODEL = "whisper-large-v3"


async def transcribe_voice(audio_bytes: bytes, lang: str = "uz") -> str | None:
    """Ovozli xabar baytlarini (OGG/Opus) matnga o'giradi.

    `lang` — "uz" yoki "ru" (Whisper'ga qaysi tilda ekanini maslahat sifatida
    beradi, aniqlikni oshiradi). Muvaffaqiyatsiz bo'lsa yoki Groq
    sozlanmagan bo'lsa, None qaytaradi.
    """
    if not AI_API_KEY_2:
        logger.warning("Ovozli xabarni transkripsiya qilib bo'lmadi: Groq (AI_API_KEY_2) sozlanmagan.")
        return None

    form = aiohttp.FormData()
    form.add_field("file", audio_bytes, filename="voice.ogg", content_type="audio/ogg")
    form.add_field("model", _WHISPER_MODEL)
    form.add_field("language", lang)
    form.add_field("response_format", "text")

    url = f"{AI_API_BASE_2.rstrip('/')}/audio/transcriptions"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                data=form,
                headers={"Authorization": f"Bearer {AI_API_KEY_2}"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("Whisper transkripsiya xatosi: HTTP %s | %s", resp.status, body[:300])
                    return None
                text = (await resp.text()).strip()
                return text or None
    except Exception:
        logger.exception("Ovozli xabarni transkripsiya qilishda xato yuz berdi.")
        return None
