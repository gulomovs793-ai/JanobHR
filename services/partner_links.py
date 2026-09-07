"""Canonical referral-link construction for the Partner Bot and Mini App."""

import logging
import os
import re

logger = logging.getLogger("janob_hr_partner")
_BOT_USERNAME_CACHE: dict[str, str] = {}
_MAIN_BOT_USERNAME_CACHE = ""

def normalize_username(value: str | None) -> str:
    return (value or "").strip().lstrip("@").strip()


def configured_main_bot_username() -> str:
    """Return the configured public Janob HR bot, never a guessed fallback."""
    for key in ("JANOBHR_MAIN_BOT_USERNAME", "PARTNER_REFERRAL_TARGET_USERNAME"):
        username = normalize_username(os.getenv(key))
        if username:
            return username
    return ""


async def _username_from_token(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return ""
    if token in _BOT_USERNAME_CACHE:
        return _BOT_USERNAME_CACHE[token]
    from aiogram import Bot

    bot = Bot(token=token)
    try:
        me = await bot.get_me()
        username = normalize_username(me.username)
    except Exception:
        logger.exception("Bot username token orqali aniqlanmadi")
        return ""
    finally:
        await bot.session.close()
    if username:
        _BOT_USERNAME_CACHE[token] = username
    return username


async def resolve_main_bot_username(
    *, current_partner_username: str | None = None
) -> str | None:
    """Resolve the public main bot once for both partner surfaces.

    The explicit username is preferred, while ``BOT_TOKEN`` is a safe fallback
    when Render omitted the username variable. The partner bot username is
    checked before either value is returned so a referral can never point back
    to the partner bot.
    """
    global _MAIN_BOT_USERNAME_CACHE
    partner_username = normalize_username(current_partner_username)
    partner_token = (os.getenv("PARTNER_BOT_TOKEN") or "").strip()
    if not partner_username and partner_token:
        partner_username = await _username_from_token(partner_token)

    if _MAIN_BOT_USERNAME_CACHE:
        if not partner_username or _MAIN_BOT_USERNAME_CACHE.casefold() != partner_username.casefold():
            return _MAIN_BOT_USERNAME_CACHE
        _MAIN_BOT_USERNAME_CACHE = ""

    configured = configured_main_bot_username()
    if configured and (
        not partner_username or configured.casefold() != partner_username.casefold()
    ):
        _MAIN_BOT_USERNAME_CACHE = configured
        return configured

    main_token = (os.getenv("BOT_TOKEN") or "").strip()
    if main_token and main_token != partner_token:
        username = await _username_from_token(main_token)
        if username and (
            not partner_username or username.casefold() != partner_username.casefold()
        ):
            _MAIN_BOT_USERNAME_CACHE = username
            return username
    return None


def build_referral_link(username: str | None, referral_code: str | None) -> str:
    target = normalize_username(username)
    code = re.sub(r"[^A-Za-z0-9_-]", "", referral_code or "")
    if not target or not code:
        return ""
    return f"https://t.me/{target}?start=ref_{code}"
