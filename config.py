"""
Janob HR Bot — konfiguratsiya.
Barcha maxfiy qiymatlar .env faylidan o'qiladi (repo'ga .env qo'shilmasin!).
"""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID", "")

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_BASE = os.getenv("AI_API_BASE", "https://api.openai.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")

FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", "")

SQLITE_PATH = os.getenv("SQLITE_PATH", "data.db")

# Bitta savolga javob uchun belgilar chegarasi. Nomzod bundan uzunroq yozsa,
# bot qisqartirib qayta yozishni so'raydi (o'qish/AI tahlili qulay bo'lishi uchun).
MAX_ANSWER_CHARS = int(os.getenv("MAX_ANSWER_CHARS", "800"))

# --- "Sell" bosqichi: yuqori ball olgan nomzodlarga avtomatik taklif ---
# O'rtacha AI ball shu chegaradan yuqori bo'lsa (va qizil bayroq bo'lmasa),
# nomzodga kompaniya taqdimoti va suhbat vaqtini tanlash tugmalari yuboriladi.
SELL_SCORE_THRESHOLD = int(os.getenv("SELL_SCORE_THRESHOLD", "80"))

COMPANY_PITCH_TEXT = os.getenv(
    "COMPANY_PITCH_TEXT",
    "🎉 <b>Natijalaringiz ajoyib!</b> Siz aynan biz qidirayotgan mutaxassisga o'xshaysiz.\n\n"
    "Jamoamizda: qulay ish sharoiti, o'sish imkoniyati va do'stona muhit sizni kutmoqda.",
)
COMPANY_PITCH_IMAGE_URL = os.getenv("COMPANY_PITCH_IMAGE_URL", "")

# Vergul bilan ajratilgan suhbat vaqti variantlari (nomzod shulardan birini tanlaydi).
INTERVIEW_SLOTS = [
    slot.strip()
    for slot in os.getenv(
        "INTERVIEW_SLOTS", "Ertaga soat 14:00,Ertaga soat 16:00,Bu hafta ichida qulay payt"
    ).split(",")
    if slot.strip()
]

# Har bir vaqt oralig'iga necha nafar nomzod qabul qilinishi mumkin. Standart — 1
# (bir vaqtda faqat bitta suhbat o'tkazish mumkin bo'lgan holat uchun). Guruh
# suhbatlari o'tkaziladigan bo'lsa, buni oshirish mumkin.
SLOT_CAPACITY = int(os.getenv("SLOT_CAPACITY", "1"))

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. .env faylini .env.example asosida yarating va "
        "BotFather'dan olingan tokenni kiriting."
    )
