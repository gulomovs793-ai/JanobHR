from pathlib import Path

# 1) AI scoring: slow sequential 12s/provider -> hedged fast failover.
p = Path("services/ai_scoring.py")
s = p.read_text(encoding="utf-8")

if "import asyncio\n" not in s:
    s = s.replace("import json\nimport logging\nimport re\n", "import asyncio\nimport json\nimport logging\nimport re\n", 1)

start = s.index("async def _call_ai(")
end = s.index("\n\nclass ScoreResult", start)
new_call_ai = '''async def _call_ai(system_prompt: str, user_prompt: str, max_tokens: int) -> str | None:
    """AI javobini tez qaytaradi: asosiy provayder darhol boshlanadi, zaxiralar
    esa qisqa kechikish bilan "hedge" sifatida ishga tushadi. Birinchi sog'lom
    javob kelishi bilan qolgan so'rovlar bekor qilinadi.

    Avvalgi ketma-ket 12s + 12s + 12s kutish webhookni uzoq ushlab turardi.
    Bu esa nomzodga kech javob va Telegram webhook retry sabab dubl savollar
    berilishiga olib kelishi mumkin edi.
    """
    active = [(k, b, m, label) for k, b, m, label in _PROVIDERS if k]
    if not active:
        return None

    timeout = aiohttp.ClientTimeout(total=5.0, connect=2.0, sock_read=4.5)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def run_provider(provider, delay: float) -> str | None:
            key, base, model, label = provider
            if delay:
                await asyncio.sleep(delay)

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0,
                "max_tokens": max_tokens,
            }
            try:
                async with session.post(
                    f"{base.rstrip('/')}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {key}"},
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            "AI provayder (%s) xatosi: HTTP %s | %s",
                            label,
                            resp.status,
                            body[:300],
                        )
                        return None

                    data = await resp.json()
                    content = data["choices"][0]["message"].get("content")
                    if not content or not content.strip():
                        finish_reason = data.get("choices", [{}])[0].get("finish_reason")
                        logger.warning(
                            "AI provayder (%s) bo'sh javob qaytardi (finish_reason=%s).",
                            label,
                            finish_reason,
                        )
                        return None
                    return content.strip()
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                logger.warning("AI provayder (%s) 5 soniyada javob bermadi.", label)
                return None
            except Exception:
                logger.exception("AI provayder (%s) so'rovi muvaffaqiyatsiz tugadi.", label)
                return None

        # Odatda asosiy provayder 1.2 soniyadan oldin javob bersa zaxira umuman
        # chaqirilmaydi. Sekinlashsa zaxira-1, keyin zaxira-2 avtomatik poygaga kiradi.
        tasks = [
            asyncio.create_task(run_provider(provider, idx * 1.2))
            for idx, provider in enumerate(active)
        ]
        pending = set(tasks)
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    result = task.result()
                    if result:
                        for other in pending:
                            other.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        return result
            logger.error("Barcha AI provayderlar ishlamadi (%d ta sinaldi).", len(active))
            return None
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
'''
s = s[:start] + new_call_ai + s[end:]

# JSON score uchun 700 token ortiqcha; qisqaroq output tezroq tugaydi.
s = s.replace("max_tokens=700", "max_tokens=260")
p.write_text(s, encoding="utf-8")

# 2) Webhook: Telegram'ga update qabul qilinganini darhol bildir.
p = Path("webhook_app.py")
s = p.read_text(encoding="utf-8")
old = '''    handler = TokenBasedRequestHandler(\n        dispatcher=dp,\n        bot_settings={'''
new = '''    handler = TokenBasedRequestHandler(\n        dispatcher=dp,\n        # AI tahlili bir necha soniya olsa ham Telegram webhook HTTP javobini\n        # kutib turmaydi. Aks holda Telegram bir xil update'ni retry qilib,\n        # nomzodga bir savol ikki marta yuborilishi mumkin.\n        handle_in_background=True,\n        bot_settings={'''
if "handle_in_background=True" not in s:
    assert old in s, "TokenBasedRequestHandler anchor not found"
    s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")

# 3) Candidate text answers: same Telegram message can never be applied twice.
p = Path("handlers/questions.py")
s = p.read_text(encoding="utf-8")
if "import asyncio\n" not in s:
    s = s.replace("import logging\n", "import asyncio\nimport logging\n", 1)

router_anchor = 'router = Router(name="questions")\n'
lock_block = '''router = Router(name="questions")\n\n# Telegram webhook retry yoki bir xil update parallel qayta ishlansa, bitta javob\n# keyingi ikki savolga ketma-ket yozilib qolmasligi uchun chat/user bo'yicha lock.\n_ANSWER_LOCKS: dict[tuple[int, int], asyncio.Lock] = {}\n\n\ndef _answer_lock(message: Message) -> asyncio.Lock:\n    key = (message.chat.id, message.from_user.id)\n    lock = _ANSWER_LOCKS.get(key)\n    if lock is None:\n        lock = asyncio.Lock()\n        _ANSWER_LOCKS[key] = lock\n    return lock\n'''
if "_ANSWER_LOCKS:" not in s:
    assert router_anchor in s, "questions router anchor not found"
    s = s.replace(router_anchor, lock_block, 1)

start = s.index('@router.message(ApplyForm.answering_questions, F.text)')
end = s.index('\n\n@router.message(ApplyForm.answering_questions, F.voice)', start)
new_text_handler = '''@router.message(ApplyForm.answering_questions, F.text)\nasync def handle_text_answer(message: Message, state: FSMContext):\n    async with _answer_lock(message):\n        data = await state.get_data()\n\n        # Telegram aynan shu update'ni qayta yuborgan bo'lsa, ikkinchi marta\n        # savol indeksini siljitmaymiz. Bu qiymat FSM bilan persistent saqlanadi.\n        if data.get("last_answer_message_id") == message.message_id:\n            logger.info(\n                "Dubl candidate update e'tiborsiz qoldirildi: chat=%s message=%s",\n                message.chat.id,\n                message.message_id,\n            )\n            return\n\n        lang = data.get("lang", DEFAULT_LANG)\n        idx = data["question_index"]\n        questions = data["vacancy_questions"]\n\n        if questions[idx].get("voice"):\n            await message.answer(t("voice_required", lang))\n            return\n\n        # Belgini AI chaqiruvidan OLDIN yozamiz: parallel retry lockdan keyin\n        # kirganda shu xabar allaqachon ishlanayotganini ko'radi. Agar kutilmagan\n        # xato bo'lsa, belgini qaytarib tashlaymiz — keyin qayta urinish mumkin.\n        await state.update_data(last_answer_message_id=message.message_id)\n        try:\n            await _process_answer(message, state, message.text.strip())\n        except Exception:\n            current = await state.get_data()\n            if current.get("last_answer_message_id") == message.message_id:\n                await state.update_data(last_answer_message_id=None)\n            raise\n'''
s = s[:start] + new_text_handler + s[end:]
p.write_text(s, encoding="utf-8")

print("Candidate latency + duplicate protection patch applied")
