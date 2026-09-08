from pathlib import Path

path = Path("partner_bot.py")
text = path.read_text(encoding="utf-8")
start = text.index("def main_menu() -> ")
end = text.index("\n\ndef founder_review_keyboard", start)
new = '''def main_menu() -> ReplyKeyboardMarkup:
    """Hamkorning chat ichidagi asosiy menyusi.

    Ko'k Telegram «Boshqaruv paneli» WebApp tugmasi alohida qoladi; shu sabab
    reply menyuda u takrorlanmaydi.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="💰 Komissiya")],
            [KeyboardButton(text="🔗 Referral link"), KeyboardButton(text="🎟 Promo kod")],
            [KeyboardButton(text="💸 Pul yechish")],
            [KeyboardButton(text="📦 Reklama materiallari")],
            [
                KeyboardButton(text="❓ Tez-tez so'raladigan savollar"),
                KeyboardButton(text="🆘 Yordam"),
            ],
        ],
        resize_keyboard=True,
    )
'''
path.write_text(text[:start] + new + text[end:], encoding="utf-8")
print("Partner reply menu restored")
