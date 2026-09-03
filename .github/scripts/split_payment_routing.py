from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"anchor not found: {label}")
    return text.replace(old, new, 1)


# services/payment_automation.py
p = Path("services/payment_automation.py")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    'logger = logging.getLogger("janob_hr_bot")\n\n_NOTIFY_EXCLUDE_KEYWORDS = [',
    'logger = logging.getLogger("janob_hr_bot")\n\n'
    '# Shared-card namespace: Janob HR generated amounts end in 6/7/8/9.\n'
    '# O‘zbek Ovoz AI uses 1/2/3/4. The physical card stays the same.\n'
    '_JANOBHR_AMOUNT_LAST_DIGITS = {6, 7, 8, 9}\n\n'
    '_NOTIFY_EXCLUDE_KEYWORDS = [',
    "payment namespace",
)
s = replace_once(
    s,
    '''async def _pick_unique_amount(base_price: int) -> int:\n    """Bazaviy narxga kichik tasodifiy summa qo'shib, ochiq buyurtmalar\n    orasida noyob ekanini tekshiradi."""\n    for _ in range(25):\n        offset = random.randint(1, 200)\n        candidate = base_price + offset\n        if not await database.get_open_payment_order_by_amount(candidate):\n            return candidate\n    return base_price + random.randint(1, 200)\n''',
    '''async def _pick_unique_amount(base_price: int) -> int:\n    """Janob HR uchun loyiha-imzoli va ochiq orderlar orasida noyob summa."""\n    for _ in range(60):\n        offset = random.randint(1, 200)\n        candidate = base_price + offset\n        if candidate % 10 not in _JANOBHR_AMOUNT_LAST_DIGITS:\n            continue\n        if not await database.get_open_payment_order_by_amount(candidate):\n            return candidate\n\n    for offset in range(1, 201):\n        candidate = base_price + offset\n        if candidate % 10 not in _JANOBHR_AMOUNT_LAST_DIGITS:\n            continue\n        if not await database.get_open_payment_order_by_amount(candidate):\n            return candidate\n    raise RuntimeError("Janob HR uchun noyob to'lov summasi topilmadi")\n''',
    "unique amount",
)
s = replace_once(
    s,
    '''async def handle_payment_notification(\n    raw_text: str, notify_founders, activate_tenant\n) -> dict:\n''',
    '''async def handle_payment_notification(\n    raw_text: str, notify_founders, activate_tenant, *, notify_no_match: bool = True\n) -> dict:\n''',
    "handler signature",
)
s = replace_once(
    s,
    '''    if not candidates:\n        await notify_founders(\n            f"⚠️ Noma'lum kirim: {amount:,} so'm\\n"\n            "Ochiq buyurtmaga mos kelmadi."\n        )\n        logger.warning("[to'lov] Mos kelmadi: amount=%s", amount)\n        return {"status": "no_match", "amount": amount}\n''',
    '''    if not candidates:\n        if notify_no_match:\n            await notify_founders(\n                f"⚠️ Noma'lum kirim: {amount:,} so'm\\n"\n                "Ochiq buyurtmaga mos kelmadi."\n            )\n        logger.info("[to'lov] Mos kelmadi: amount=%s", amount)\n        return {"status": "no_match", "amount": amount}\n''',
    "silent routed no-match",
)
p.write_text(s, encoding="utf-8")


# config.py
p = Path("config.py")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    'CARD_BOT_USERNAME = os.getenv("CARD_BOT_USERNAME", "CardXabarBot").lstrip("@")\n',
    'CARD_BOT_USERNAME = os.getenv("CARD_BOT_USERNAME", "CardXabarBot").lstrip("@")\n\n'
    '# Telegram notification account is listened to by one service only.\n'
    'PAYMENT_LISTENER_ENABLED = os.getenv("PAYMENT_LISTENER_ENABLED", "1").strip().lower() not in {\n'
    '    "0", "false", "no", "off"\n'
    '}\n'
    'PAYMENT_ROUTER_SECRET = os.getenv("PAYMENT_ROUTER_SECRET", "")\n',
    "config router vars",
)
p.write_text(s, encoding="utf-8")


# webhook_app.py
p = Path("webhook_app.py")
s = p.read_text(encoding="utf-8")
s = replace_once(s, "import asyncio\nimport logging\nimport os\n", "import asyncio\nimport hmac\nimport logging\nimport os\n", "hmac import")
s = replace_once(
    s,
    "from config import FOUNDER_BOT_TOKEN, MINI_APP_BASE_URL, WEBHOOK_BASE_URL\n",
    "from config import (\n"
    "    FOUNDER_BOT_TOKEN,\n"
    "    MINI_APP_BASE_URL,\n"
    "    PAYMENT_LISTENER_ENABLED,\n"
    "    PAYMENT_ROUTER_SECRET,\n"
    "    WEBHOOK_BASE_URL,\n"
    ")\n",
    "config imports",
)
s = replace_once(
    s,
    '''        if is_userbot_configured():\n            asyncio.create_task(start_userbot())\n            logger.info(\n                "Userbot (to'lovlarni aniqlash) fon vazifasi sifatida ishga tushirildi."\n            )\n        else:\n            logger.info(\n                "Userbot sozlanmagan (TELEGRAM_API_ID/HASH/SESSION yo'q) — o'tkazib yuborildi."\n            )\n''',
    '''        if not PAYMENT_LISTENER_ENABLED:\n            logger.info(\n                "Janob HR Telegram payment listener o'chirilgan — signed router ishlatiladi."\n            )\n        elif is_userbot_configured():\n            asyncio.create_task(start_userbot())\n            logger.info(\n                "Userbot (to'lovlarni aniqlash) fon vazifasi sifatida ishga tushirildi."\n            )\n        else:\n            logger.info(\n                "Userbot sozlanmagan (TELEGRAM_API_ID/HASH/SESSION yo'q) — o'tkazib yuborildi."\n            )\n''',
    "listener startup",
)
handler = '''\n\nasync def internal_payment_notification(request: web.Request) -> web.Response:\n    """Signed notification from the single shared-card Telegram listener."""\n    supplied = request.headers.get("X-Payment-Router-Secret", "")\n    if not PAYMENT_ROUTER_SECRET:\n        logger.error("PAYMENT_ROUTER_SECRET sozlanmagan; routed payment rad etildi.")\n        raise web.HTTPServiceUnavailable(text="payment router not configured")\n    if not supplied or not hmac.compare_digest(supplied, PAYMENT_ROUTER_SECRET):\n        logger.warning("Noto'g'ri payment router secret bilan so'rov rad etildi.")\n        raise web.HTTPUnauthorized(text="unauthorized")\n\n    try:\n        payload = await request.json()\n    except Exception as exc:\n        raise web.HTTPBadRequest(text="invalid json") from exc\n    raw_text = str(payload.get("raw_text") or "").strip()\n    if not raw_text or len(raw_text) > 5000:\n        raise web.HTTPBadRequest(text="invalid notification")\n\n    from services.payment_automation import handle_payment_notification\n    from userbot import (\n        _activate_tenant_wrapper,\n        _notify_founders,\n        _notify_tenant_payment_approved,\n    )\n\n    result = await handle_payment_notification(\n        raw_text,\n        _notify_founders,\n        _activate_tenant_wrapper,\n        notify_no_match=False,\n    )\n    if result.get("status") == "approved":\n        await _notify_tenant_payment_approved(result)\n    logger.info("[payment-router] Natija: %s", result.get("status"))\n    return web.json_response(result)\n'''
s = replace_once(s, "\n\ndef create_app() -> web.Application:\n", handler + "\n\ndef create_app() -> web.Application:\n", "internal route function")
s = replace_once(
    s,
    '''    register_miniapp(app)\n    register_founder_miniapp(app)\n    setup_application(app, dp)\n''',
    '''    register_miniapp(app)\n    register_founder_miniapp(app)\n    app.router.add_post("/internal/payment-notification", internal_payment_notification)\n    setup_application(app, dp)\n''',
    "internal route registration",
)
p.write_text(s, encoding="utf-8")
