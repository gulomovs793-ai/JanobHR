"""Canonical referral-link construction for the Partner Bot and Mini App."""

import os
import re


def normalize_username(value: str | None) -> str:
    return (value or "").strip().lstrip("@").strip()


def configured_main_bot_username() -> str:
    """Return the configured public Janob HR bot, never a guessed fallback."""
    for key in ("JANOBHR_MAIN_BOT_USERNAME", "PARTNER_REFERRAL_TARGET_USERNAME"):
        username = normalize_username(os.getenv(key))
        if username:
            return username
    return ""


def build_referral_link(username: str | None, referral_code: str | None) -> str:
    target = normalize_username(username)
    code = re.sub(r"[^A-Za-z0-9_-]", "", referral_code or "")
    if not target or not code:
        return ""
    return f"https://t.me/{target}?start=ref_{code}"
