# Janob HR — B2B HR Assistant Telegram Bot

Nomzodlarni avtomatik qabul qiladigan, saralaydigan (hard filter), AI orqali
baholaydigan va HR/tadbirkorga tayyor "dashboard" (admin guruh) ko'rinishida
yetkazib beradigan Telegram bot. `aiogram 3` (FSM) asosida yozilgan.

## Tizim qanday ishlaydi

1. Nomzod `/start` bosadi -> vakansiyani tanlaydi (Sotuv menejeri / Dizayner / SMM).
2. Bot shu vakansiya uchun sozlangan savollarni ketma-ket beradi.
3. Agar nomzod "hard filter" savoliga salbiy javob bersa (masalan "Yo'q"),
   bot uni darhol, xushmuomalalik bilan rad etadi va keyingi savollarga o'tkazmaydi.
4. Savollar tugagach, nomzoddan rezyume (PDF) yoki video-vizitka so'raladi.
5. Ochiq savollardagi javoblar (agar `AI_API_KEY` sozlangan bo'lsa) AI orqali
   0-100 ball bilan baholanadi.
6. Yakuniy anketa strukturalangan holda:
   - lokal `data.db` (SQLite) fayliga,
   - agar sozlansa — Firebase Firestore'ga,
   - va admin Telegram guruhiga (✅ Suhbatga chaqirish / ❌ Rad etish tugmalari bilan)
   yuboriladi.
7. Admin guruhda tugma bosilganda, nomzodga avtomatik xabar boradi va status
   ma'lumotlar bazasida yangilanadi.

## 1-qadam: Bot yaratish (BotFather)

1. Telegram'da [@BotFather](https://t.me/BotFather) ga o'ting.
2. `/newbot` yuboring, botga nom va username bering.
3. BotFather bergan tokenni saqlab qo'ying (masalan `123456:AAExxxxx...`).

## 2-qadam: Admin guruh yaratish

1. Yangi Telegram guruh yarating (masalan "Janob HR — Yangi anketalar").
2. Botni shu guruhga admin sifatida qo'shing.
3. Guruh ID'sini olish uchun [@userinfobot](https://t.me/userinfobot) yoki
   [@RawDataBot](https://t.me/RawDataBot) botini guruhga qo'shib, chiqqan
   `Chat ID` qiymatini oling (odatda `-100` bilan boshlanadi).

## 3-qadam: Loyihani sozlash

```bash
cd janob_hr_bot
python3 -m venv .venv && source .venv/bin/activate   # (ixtiyoriy, lekin tavsiya etiladi)
pip install -r requirements.txt

cp .env.example .env
# .env faylini oching va quyidagilarni to'ldiring:
#   BOT_TOKEN=...        (majburiy)
#   ADMIN_GROUP_ID=...   (majburiy — anketalar shu yerga tushadi)
#   AI_API_KEY=...       (ixtiyoriy — AI baholash uchun)
#   FIREBASE_CREDENTIALS_PATH=...  (ixtiyoriy)
```

## 4-qadam: Ishga tushirish

```bash
python3 bot.py
```

Konsolda `Janob HR bot ishga tushdi ✅` ko'rinsa — tayyor. Telegram'da botga
`/start` yuboring.

## AI baholashni yoqish (ixtiyoriy, lekin $400+ narx uchun tavsiya etiladi)

`.env` faylida:
```
AI_API_KEY=sk-...
AI_API_BASE=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
```
Bu yerga OpenAI formatiga mos har qanday provayderni qo'yish mumkin
(OpenAI, Groq, DeepSeek va h.k.). Kalit bo'sh bo'lsa, bot AI baholashsiz
ishlayveradi — hech narsa buzilmaydi.

## Firebase'ni yoqish (ixtiyoriy)

1. [Firebase Console](https://console.firebase.google.com/) -> yangi loyiha.
2. Firestore Database'ni yoqing.
3. Project Settings -> Service Accounts -> "Generate new private key" -> JSON
   faylni yuklab oling va loyiha papkasiga joylashtiring (masalan
   `firebase-credentials.json`, u `.gitignore`'da allaqachon bor).
4. `.env`: `FIREBASE_CREDENTIALS_PATH=firebase-credentials.json`

Sozlanmasa — bot avtomatik faqat lokal SQLite (`data.db`) bilan ishlaydi,
demo/test qilish uchun bu yetarli.

## Serverga (24/7) joylashtirish

Eng oson yo'llar:
- **VPS** (masalan Timeweb, Contabo, DigitalOcean): loyihani serverga
  yuklab, `screen`/`tmux` yoki `systemd` service orqali `python3 bot.py`ni
  doimiy ishlatish.
- **Railway.app / Render.com**: repo'ni ulaysiz, `Start command`ga
  `python bot.py` yozasiz, Environment Variables bo'limiga `.env`
  qiymatlarini kiritasiz — bepul/arzon tarifda ishlaydi.

## GitHub'ga yuklash

```bash
git init
git add .
git commit -m "Janob HR bot - dastlabki versiya"
# GitHub'da yangi (bo'sh) repository oching, so'ng:
git branch -M main
git remote add origin https://github.com/<username>/janob-hr-bot.git
git push -u origin main
```

`.env` va `data.db` fayllari `.gitignore`da bo'lgani uchun repo'ga tushmaydi
— tokenlaringiz xavfsiz qoladi.

## Yangi vakansiya qo'shish

`vacancies.py` faylidagi `VACANCIES` lug'atiga yangi kalit qo'shing —
boshqa hech qanday kodni o'zgartirish shart emas:

```python
"backend_dev": {
    "title": "💻 Backend dasturchi",
    "reject_message": "...",
    "questions": [
        {"key": "stack", "text": "Qaysi texnologik stackda ishlaysiz?"},
        {"key": "exp", "text": "Kasbiy tajribangiz bormi? (Ha/Yo'q)", "hard_filter": True},
        {"key": "project", "text": "Eng murakkab loyihangizni tasvirlab bering.", "ai_score": True},
    ],
    "resume_required": True,
},
```

## Mijozga sotish uchun eslatma

Ushbu bot — MVP asosi. $400+ narxni oqlash uchun har bir mijoz uchun:
- brend nomi/logotipi va matnlarni moslashtiring,
- kerakli vakansiya va savollarni sozlang,
- admin guruhni mijozning haqiqiy jamoasiga ulang,
- (xohlasa) Google Sheets eksportini qo'shib bering.

Demo sifatida bitta aniq soha (masalan restoranlar tarmog'i yoki savdo
kompaniyasi) uchun to'liq ishlaydigan namunani tayyorlab, video-taqdimot
bilan potentsial mijozlarga ko'rsatish tavsiya etiladi.
