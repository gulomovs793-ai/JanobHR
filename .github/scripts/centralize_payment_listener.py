from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"anchor not found: {label}")
    return text.replace(old, new, 1)


# config.py: destination for O'zbek Ovoz forwarded notifications.
p = Path("config.py")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    'PAYMENT_ROUTER_SECRET = os.getenv("PAYMENT_ROUTER_SECRET", "")\n',
    'PAYMENT_ROUTER_SECRET = os.getenv("PAYMENT_ROUTER_SECRET", "")\n'
    'OVOZ_PAYMENT_URL = os.getenv("OVOZ_PAYMENT_URL", "").strip()\n',
    "OVOZ_PAYMENT_URL config",
)
p.write_text(s, encoding="utf-8")


# userbot.py: Janob HR becomes the ONLY always-on CardXabar listener.
p = Path("userbot.py")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    "import asyncio\nimport logging\n",
    "import asyncio\nimport logging\n\nimport aiohttp\n",
    "aiohttp import",
)
s = replace_once(
    s,
    '''from config import (\n    CARD_BOT_USERNAME,\n    FOUNDER_USER_IDS,\n    ORDER_TTL_MINUTES,\n    TELEGRAM_API_HASH,\n    TELEGRAM_API_ID,\n    TELEGRAM_USERBOT_SESSION,\n)\n''',
    '''from config import (\n    CARD_BOT_USERNAME,\n    FOUNDER_USER_IDS,\n    ORDER_TTL_MINUTES,\n    OVOZ_PAYMENT_URL,\n    PAYMENT_ROUTER_SECRET,\n    TELEGRAM_API_HASH,\n    TELEGRAM_API_ID,\n    TELEGRAM_USERBOT_SESSION,\n)\n''',
    "config imports",
)
s = replace_once(
    s,
    "from services.payment_automation import handle_payment_notification\n",
    "from services.payment_automation import handle_payment_notification, parse_notification_amount\n",
    "payment imports",
)

insert_anchor = 'logger = logging.getLogger("janob_hr_userbot")\n\n\n'
insert_block = '''logger = logging.getLogger("janob_hr_userbot")\n\n\n_OVOZ_LAST_DIGITS = {1, 2, 3, 4}\n_JANOBHR_LAST_DIGITS = {6, 7, 8, 9}\n\n\nasync def _forward_to_ovoz(raw_text: str, amount: int | None) -> dict:\n    """Forward one signed bank notification to the O'zbek Ovoz payment engine.\n\n    The Ovoz service may be on Render Free and asleep. The long timeout plus\n    retry lets the incoming HTTP request wake it without losing the payment.\n    """\n    if not OVOZ_PAYMENT_URL or not PAYMENT_ROUTER_SECRET:\n        logger.error("[payment-router] OVOZ_PAYMENT_URL/PAYMENT_ROUTER_SECRET sozlanmagan.")\n        return {"status": "router_not_configured", "amount": amount, "_project": "ovoz"}\n\n    headers = {\n        "X-Payment-Router-Secret": PAYMENT_ROUTER_SECRET,\n        "Content-Type": "application/json",\n    }\n    timeout = aiohttp.ClientTimeout(total=95, connect=15)\n    retryable = {429, 502, 503, 504}\n    last_status = None\n    for attempt in range(1, 4):\n        try:\n            async with aiohttp.ClientSession(timeout=timeout) as session:\n                async with session.post(\n                    OVOZ_PAYMENT_URL,\n                    headers=headers,\n                    json={"raw_text": raw_text, "source": "janobhr-web"},\n                ) as response:\n                    last_status = response.status\n                    body = await response.json(content_type=None)\n                    if 200 <= response.status < 300:\n                        result = body if isinstance(body, dict) else {"status": "ok"}\n                        result["_project"] = "ovoz"\n                        logger.info(\n                            "[payment-router] Ovoz natija: %s, summa=%s",\n                            result.get("status"), amount,\n                        )\n                        return result\n                    if response.status not in retryable:\n                        logger.error(\n                            "[payment-router] Ovoz HTTP %s: %s", response.status, str(body)[:300]\n                        )\n                        return {\n                            "status": "router_error",\n                            "http_status": response.status,\n                            "amount": amount,\n                            "_project": "ovoz",\n                        }\n        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:\n            logger.warning(\n                "[payment-router] Ovoz urinish %s/3 muvaffaqiyatsiz: %s", attempt, exc\n            )\n        if attempt < 3:\n            await asyncio.sleep(8 * attempt)\n\n    return {\n        "status": "router_error",\n        "http_status": last_status,\n        "amount": amount,\n        "_project": "ovoz",\n    }\n\n\nasync def _route_payment_notification(raw_text: str) -> dict:\n    """One physical card, two isolated payment engines.\n\n    New Ovoz amounts end in 1/2/3/4 and Janob HR in 6/7/8/9. Legacy 0/5\n    and old orders are still given a fallback chance in the other engine.\n    """\n    amount = parse_notification_amount(raw_text)\n\n    async def local(*, notify_no_match: bool = False) -> dict:\n        result = await handle_payment_notification(\n            raw_text,\n            _notify_founders,\n            _activate_tenant_wrapper,\n            notify_no_match=notify_no_match,\n        )\n        result["_project"] = "janobhr"\n        return result\n\n    if amount is None:\n        return await local(notify_no_match=False)\n\n    last_digit = amount % 10\n    if last_digit in _OVOZ_LAST_DIGITS:\n        routed = await _forward_to_ovoz(raw_text, amount)\n        if routed.get("status") not in {"no_match", "router_error", "router_not_configured"}:\n            return routed\n        # Legacy Janob HR order may predate the namespace split.\n        legacy = await local(notify_no_match=False)\n        if legacy.get("status") != "no_match":\n            return legacy\n        return routed\n\n    # Janob HR namespace (and legacy/reserved digits): local engine first.\n    result = await local(notify_no_match=False)\n    if result.get("status") != "no_match":\n        return result\n\n    # A legacy Ovoz order may use an old last digit.\n    routed = await _forward_to_ovoz(raw_text, amount)\n    if routed.get("status") in {"router_error", "router_not_configured"}:\n        # If neither engine can be checked, surface the unknown incoming payment\n        # to founders instead of silently dropping it.\n        return await local(notify_no_match=True)\n    return routed\n\n\n'''
s = replace_once(s, insert_anchor, insert_block, "router helpers")

old_process = '''            result = await handle_payment_notification(\n                text, _notify_founders, _activate_tenant_wrapper\n            )\n            logger.info("[userbot] Natija: %s", result.get("status"))\n            if result.get("status") == "approved":\n                await _notify_tenant_payment_approved(result)\n'''
new_process = '''            result = await _route_payment_notification(text)\n            logger.info(\n                "[userbot] Natija: %s (%s)",\n                result.get("status"),\n                result.get("_project", "unknown"),\n            )\n            if result.get("status") == "approved" and result.get("_project") == "janobhr":\n                await _notify_tenant_payment_approved(result)\n'''
s = replace_once(s, old_process, new_process, "message routing")
p.write_text(s, encoding="utf-8")
