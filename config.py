"""
Janob HR Bot — konfiguratsiya.
Barcha maxfiy qiymatlar .env faylidan o'qiladi (repo'ga .env qo'shilmasin!).
"""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# ESKIRGAN: nomzod arizalari endi Admin bot orqali (ADMIN_BOT_TOKEN +
# ADMIN_USER_IDS) yuboriladi, guruh/kanal endi ishlatilmaydi. Bu o'zgaruvchi
# faqat orqaga moslik uchun qoldirilgan, kodda hech qayerda o'qilmaydi.
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID", "")

# --- Admin bot (vakansiyalarni boshqarish, statistika) ---
# Alohida Telegram bot — @BotFather'dan yangi bot yaratib, tokenini shu yerga
# qo'ying. Bo'sh qoldirilsa, admin bot ishga tushmaydi (asosiy nomzod-bot
# muammosiz davom etadi).
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "")
# Vergul bilan ajratilgan Telegram user ID'lar ro'yxati — faqat shu ID'lar admin
# botdan foydalana oladi. O'z ID'ingizni bilish uchun @userinfobot'ga /start yuboring.
ADMIN_USER_IDS = {
    int(uid.strip()) for uid in os.getenv("ADMIN_USER_IDS", "").split(",") if uid.strip().isdigit()
}

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_BASE = os.getenv("AI_API_BASE", "https://api.openai.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")

# --- Zaxira AI provayderlar ---
# Asosiy provayder (yuqoridagi) ishlamay qolsa (kredit tugasa, limit yoki server
# xatosi bo'lsa), bot avtomatik navbatdagi provayderga o'tadi — bir xil JSON
# formatida tahlil davom etadi, nomzod buni sezmaydi. Kalit bo'sh bo'lsa, o'sha
# provayder shunchaki o'tkazib yuboriladi.
#
# Zaxira 1 — Groq (standart: OpenAI-compatible, tez va bepul tarifi saxiy).
AI_API_KEY_2 = os.getenv("AI_API_KEY_2", "")
AI_API_BASE_2 = os.getenv("AI_API_BASE_2", "https://api.groq.com/openai/v1")
AI_MODEL_2 = os.getenv("AI_MODEL_2", "openai/gpt-oss-120b")

# Zaxira 2 — DeepSeek (standart: OpenAI-compatible, juda arzon).
AI_API_KEY_3 = os.getenv("AI_API_KEY_3", "")
AI_API_BASE_3 = os.getenv("AI_API_BASE_3", "https://api.deepseek.com/v1")
AI_MODEL_3 = os.getenv("AI_MODEL_3", "deepseek-v4-flash")

FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", "")

SQLITE_PATH = os.getenv("SQLITE_PATH", "data.db")

# Ko'p mijozli (multi-tenant) webhook rejimi uchun — bu server tashqi dunyoga
# qaysi manzil orqali ko'rinishini bildiradi (masalan Render xizmat manzili).
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "")

# Yangi mijozlar o'zini ro'yxatdan o'tkazadigan alohida "sozlash boti".
SETUP_BOT_TOKEN = os.getenv("SETUP_BOT_TOKEN", "")

# Faqat asoschi(lar) ishlatadigan "Bosh boshqaruv" boti — yangi mijozlarni
# ko'rib chiqish va to'lovdan keyin faollashtirish uchun.
FOUNDER_BOT_TOKEN = os.getenv("FOUNDER_BOT_TOKEN", "")

# Yangi mijoz ro'yxatdan o'tganda, shaxsan xabar beriladigan asoschi ID'lari
# (bir nechta bo'lishi mumkin, vergul bilan ajratilgan).
FOUNDER_USER_IDS = {
    int(uid.strip()) for uid in os.getenv("FOUNDER_USER_ID", "").split(",") if uid.strip().isdigit()
}

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

# ESKIRGAN: suhbat vaqtlari, sig'imi, manzil va intervyuchi kontakti endi
# ma'lumotlar bazasida (Admin bot > 📅 Suhbat vaqtlari orqali) boshqariladi.

# ESLATMA: BOT_TOKEN majburiyligi tekshiruvi endi shu yerda emas, bot.py'ning
# o'zida — chunki config.py endi bir nechta mustaqil kirish nuqtasi
# (bot.py, setup_bot.py, webhook_app.py) tomonidan bo'lishiladi, va ularning
# har biriga BOT_TOKEN shart emas.
