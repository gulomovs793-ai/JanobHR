from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected block not found in {path}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Main self-service /create_bot flow: two valid tokens must immediately
# provision the free trial. Previously the tenant stayed `pending` forever
# until a founder/payment action happened, despite the UI saying "bot ready".
replace_once(
    "handlers/create_bot.py",
    "from services import bot_registry, database\n",
    "from services import bot_registry, database\nfrom services.tenant_activation import activate_tenant\n",
)

replace_once(
    "handlers/create_bot.py",
    '''        if data.get("business_lead_id"):\n            await database.attach_business_lead_to_tenant(\n                data["business_lead_id"], tenant_id\n            )\n    except Exception:\n        logger.exception("Mijozni bazaga yozishda kutilmagan xato.")\n        await wait_msg.edit_text(\n            "⚠️ Texnik xatolik yuz berdi. Iltimos, /create_bot bilan qayta urinib ko'ring."\n        )\n        return\n\n    await wait_msg.edit_text(\n        f"✅ Tabriklaymiz! Ikkala botingiz ham tayyor:\\n\\n"\n''',
    '''        if data.get("business_lead_id"):\n            await database.attach_business_lead_to_tenant(\n                data["business_lead_id"], tenant_id\n            )\n    except Exception:\n        logger.exception("Mijozni bazaga yozishda kutilmagan xato.")\n        await wait_msg.edit_text(\n            "⚠️ Texnik xatolik yuz berdi. Iltimos, /create_bot bilan qayta urinib ko'ring."\n        )\n        return\n\n    # Birinchi 5 ariza bepul trial bo'lgani uchun payment kutmaymiz.\n    # Ikki token tasdiqlanishi bilan candidate/admin webhooklari va Admin Mini App\n    # shu zahoti ulanadi. activate_tenant idempotent: retry xavfsiz.\n    activation = await activate_tenant(tenant_id)\n    if not activation.get("ok"):\n        logger.error(\n            "Trial provisioning muvaffaqiyatsiz: tenant_id=%s error=%s",\n            tenant_id,\n            activation.get("error"),\n        )\n        await wait_msg.edit_text(\n            "⚠️ Tokenlaringiz saqlandi, lekin botlarni serverga ulashda texnik xato yuz berdi.\\n\\n"\n            f"Buyurtma raqami: <code>{tenant_id}</code>\\n"\n            "Iltimos, birozdan so'ng qayta urinib ko'ring yoki @F45746 ga shu raqamni yuboring."\n        )\n        await _send_to_janob_hr_admin(\n            "⚠️ <b>Trial botlarni faollashtirishda xato</b>\\n\\n"\n            f"Mijoz №{tenant_id} — {escape(data['company_name'])}\\n"\n            f"Xato: {escape(str(activation.get('error') or 'noma’lum'))}"\n        )\n        await state.clear()\n        return\n\n    candidate_username = activation.get("candidate_username") or data["candidate_bot_username"]\n    activated_admin_username = activation.get("admin_username") or admin_username\n\n    await wait_msg.edit_text(\n        f"✅ Tabriklaymiz! Ikkala botingiz ham ishga tushdi:\\n\\n"\n''',
)

replace_once(
    "handlers/create_bot.py",
    '''        f"1️⃣ Nomzod-bot: @{data['candidate_bot_username']}\\n"\n        f"2️⃣ Admin panel-bot: @{admin_username}\\n\\n"\n        f"Buyurtma raqamingiz: <code>{tenant_id}</code>\\n\\n"\n        "Birinchi 5 ta ariza bepul. Bot faollashgach tarif va limitlarni "\n        f"@{admin_username} ichidagi <b>💳 Tarif va limitlar</b> bo'limidan boshqarasiz."\n''',
    '''        f"1️⃣ Nomzod-bot: @{candidate_username}\\n"\n        f"2️⃣ Admin panel-bot: @{activated_admin_username}\\n\\n"\n        f"Buyurtma raqamingiz: <code>{tenant_id}</code>\\n\\n"\n        "🎁 Birinchi 5 ta ariza bepul va botlaringiz hozirdanoq faol.\\n"\n        f"Tarif va limitlarni @{activated_admin_username} ichidagi <b>💳 Tarif va limitlar</b> bo'limidan boshqarasiz."\n''',
)

# Standalone setup bot must follow the exact same provisioning rule.
replace_once(
    "setup_bot.py",
    "from config import FOUNDER_USER_IDS, SETUP_BOT_TOKEN\n",
    "from config import FOUNDER_USER_IDS, SETUP_BOT_TOKEN\nfrom services.tenant_activation import activate_tenant\n",
)

replace_once(
    "setup_bot.py",
    '''    await wait_msg.edit_text(\n        "✅ Tabriklaymiz! Ikkala bot ham ro'yxatdan o'tkazildi.\\n\\n"\n        f"Nomzod-bot: <b>@{data['candidate_bot_username']}</b>\\n"\n        f"Admin-bot: <b>@{admin_me.username}</b>\\n\\n"\n        f"Mijoz raqamingiz: <code>{tenant_id}</code>\\n\\n"\n        "Birinchi 5 ta ariza bepul. Bot faollashgach tarif va limitlarni "\n        f"@{admin_me.username} ichidagi <b>💳 Tarif va limitlar</b> bo'limidan boshqarasiz."\n    )\n    await state.clear()\n''',
    '''    activation = await activate_tenant(tenant_id)\n    if not activation.get("ok"):\n        logger.error(\n            "Setup trial provisioning muvaffaqiyatsiz: tenant_id=%s error=%s",\n            tenant_id,\n            activation.get("error"),\n        )\n        await wait_msg.edit_text(\n            "⚠️ Tokenlaringiz saqlandi, lekin botlarni serverga ulashda texnik xato yuz berdi.\\n\\n"\n            f"Mijoz raqamingiz: <code>{tenant_id}</code>\\n"\n            "Iltimos, @F45746 ga shu raqamni yuboring."\n        )\n        await state.clear()\n        return\n\n    candidate_username = activation.get("candidate_username") or data["candidate_bot_username"]\n    activated_admin_username = activation.get("admin_username") or admin_me.username\n    await wait_msg.edit_text(\n        "✅ Tabriklaymiz! Ikkala botingiz ham ishga tushdi.\\n\\n"\n        f"Nomzod-bot: <b>@{candidate_username}</b>\\n"\n        f"Admin-bot: <b>@{activated_admin_username}</b>\\n\\n"\n        f"Mijoz raqamingiz: <code>{tenant_id}</code>\\n\\n"\n        "🎁 Birinchi 5 ta ariza bepul va botlaringiz hozirdanoq faol.\\n"\n        f"Tarif va limitlarni @{activated_admin_username} ichidagi <b>💳 Tarif va limitlar</b> bo'limidan boshqarasiz."\n    )\n    await state.clear()\n''',
)

# Clean two lint issues introduced by the recent payment-listener centralization
# so the provisioning release can pass the normal CI gate.
replace_once(
    "userbot.py",
    "import asyncio\nimport logging\n\nimport aiohttp\nfrom datetime import datetime, timedelta, timezone\n",
    "import asyncio\nimport logging\nfrom datetime import datetime, timedelta, timezone\n\nimport aiohttp\n",
)
replace_once(
    "userbot.py",
    "from services.payment_automation import handle_payment_notification, parse_notification_amount\n",
    "from services.payment_automation import (\n    handle_payment_notification,\n    parse_notification_amount,\n)\n",
)
replace_once(
    "userbot.py",
    '''            async with aiohttp.ClientSession(timeout=timeout) as session:\n                async with session.post(\n                    OVOZ_PAYMENT_URL,\n                    headers=headers,\n                    json={"raw_text": raw_text, "source": "janobhr-web"},\n                ) as response:\n                    last_status = response.status\n                    body = await response.json(content_type=None)\n''',
    '''            async with (\n                aiohttp.ClientSession(timeout=timeout) as session,\n                session.post(\n                    OVOZ_PAYMENT_URL,\n                    headers=headers,\n                    json={"raw_text": raw_text, "source": "janobhr-web"},\n                ) as response,\n            ):\n                last_status = response.status\n                body = await response.json(content_type=None)\n''',
)

# Focused regression guard: code paths that collect two tokens must call the
# shared activator before claiming success.
test_path = Path("tests/test_trial_provisioning.py")
test_path.write_text(
    '''import unittest\nfrom pathlib import Path\n\n\nclass TrialProvisioningRegressionTests(unittest.TestCase):\n    def test_create_bot_activates_after_two_tokens(self):\n        source = Path("handlers/create_bot.py").read_text(encoding="utf-8")\n        self.assertIn("activation = await activate_tenant(tenant_id)", source)\n        self.assertIn("Ikkala botingiz ham ishga tushdi", source)\n        self.assertIn("if not activation.get(\\\"ok\\\")", source)\n\n    def test_setup_bot_activates_after_two_tokens(self):\n        source = Path("setup_bot.py").read_text(encoding="utf-8")\n        self.assertIn("activation = await activate_tenant(tenant_id)", source)\n        self.assertIn("Ikkala botingiz ham ishga tushdi", source)\n        self.assertIn("if not activation.get(\\\"ok\\\")", source)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)

print("Trial provisioning fix applied.")
