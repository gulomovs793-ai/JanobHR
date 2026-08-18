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

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. .env faylini .env.example asosida yarating va "
        "BotFather'dan olingan tokenni kiriting."
    )
