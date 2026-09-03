from pathlib import Path

path = Path("webhook_app.py")
text = path.read_text(encoding="utf-8")
old = '''    from services.reminders import run_reminders_forever\n\n    asyncio.create_task(run_reminders_forever())\n    tenants = await database.list_tenants(status="active")\n'''
new = '''    from services.reminders import run_reminders_forever\n    from services.tenant_activation import activate_tenant\n\n    asyncio.create_task(run_reminders_forever())\n\n    # Eski self-service bug sabab ikki tokeni saqlangan, ammo `pending`da\n    # qolib ketgan trial mijozlarni avtomatik tiklaymiz. Trial uchun payment\n    # talab qilinmaydi: birinchi 5 ariza bepul. activate_tenant idempotent,\n    # shuning uchun restartda qayta urinish xavfsiz.\n    pending_trials = await database.list_tenants(status="pending")\n    for pending in pending_trials:\n        if pending.get("plan_code") != "trial":\n            continue\n        result = await activate_tenant(pending["id"])\n        if result.get("ok"):\n            logger.info(\n                "Pending trial avtomatik faollashtirildi: tenant_id=%s",\n                pending["id"],\n            )\n        else:\n            logger.warning(\n                "Pending trialni avtomatik faollashtirib bo'lmadi: tenant_id=%s error=%s",\n                pending["id"],\n                result.get("error"),\n            )\n\n    tenants = await database.list_tenants(status="active")\n'''
if old not in text:
    raise RuntimeError("webhook_app.py startup block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

test = Path("tests/test_trial_provisioning.py")
t = test.read_text(encoding="utf-8")
needle = '''    def test_setup_bot_activates_after_two_tokens(self):\n        source = Path("setup_bot.py").read_text(encoding="utf-8")\n        self.assertIn("activation = await activate_tenant(tenant_id)", source)\n        self.assertIn("Ikkala botingiz ham ishga tushdi", source)\n        self.assertIn("if not activation.get(\\"ok\\")", source)\n'''
addition = needle + '''\n    def test_startup_reconciles_old_pending_trials(self):\n        source = Path("webhook_app.py").read_text(encoding="utf-8")\n        self.assertIn('database.list_tenants(status="pending")', source)\n        self.assertIn('result = await activate_tenant(pending["id"])', source)\n        self.assertIn('pending.get("plan_code") != "trial"', source)\n'''
if needle not in t:
    raise RuntimeError("trial provisioning test block not found")
test.write_text(t.replace(needle, addition, 1), encoding="utf-8")

print("Pending trial reconciliation applied.")
