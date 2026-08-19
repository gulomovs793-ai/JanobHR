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

## AI-HR tizimi: "A-Player" filtri

Bot oddiy anketa yig'uvchidan farqli o'laroq, quyidagi bosqichlarni avtomatik bajaradi
("Who" va "Work Rules!" kitoblaridagi tamoyillar asosida):

1. **Scorecard savollari** — `ai_score: True` belgilangan savollar orqali nomzod
   aniq raqam va reja bilan javob berishi kutiladi.
2. **AI tahlil (Natijadorlik / Mas'uliyat / Aniqlik)** — har bir AI-baholanadigan
   javob 3 mezon bo'yicha 0-100 ballga baholanadi va 🟢/🟡/🔴 verdikt chiqariladi.
3. **Qizil bayroqlar** — AI "qurbon sindromi", "abstrakt javob" va ortiqcha
   "men"chilikni avtomatik aniqlaydi va admin guruhga ko'rsatadi.
4. **Topgrading ("Haqiqat zardobi")** — barcha vakansiyalarga oxirida avtomatik
   qo'shiladigan reference-check savoli; noloyiq nomzodlar odatda shu yerda
   botni tark etadi.
5. **Sell bosqichi** — o'rtacha ball `SELL_SCORE_THRESHOLD` dan yuqori (standart: 80)
   va jiddiy bayroqsiz bo'lgan nomzodlarga bot avtomatik kompaniya taqdimoti va
   suhbat vaqtini tanlash tugmalarini yuboradi (`.env`dagi `COMPANY_PITCH_TEXT`,
   `COMPANY_PITCH_IMAGE_URL`, `INTERVIEW_SLOTS` orqali sozlanadi).

Bu tizim to'liq ishlashi uchun `AI_API_KEY` (va OpenAI-compatible bo'lmagan
provayderlar uchun `AI_API_BASE`/`AI_MODEL`) sozlangan bo'lishi shart.

## Admin bot — vakansiyalarni boshqarish va statistika

Nomzod-botdan tashqari, **alohida admin bot** mavjud (bitta xizmat ichida, bir xil
ma'lumotlar bazasini baham ko'radi):

- **📋 Vakansiyalar** — barcha vakansiyalarni ko'rish, faollashtirish/faolsizlantirish,
  o'chirish.
- **➕ Yangi vakansiya** — istalgan kasb uchun (quruvchi, buxgalter, haydovchi va h.k.)
  yangi vakansiya yaratish. Savollar AI orqali Scorecard/Behavioral metodologiyasi
  bo'yicha avtomatik taklif qilinadi, yoki admin ularni to'liq qo'lda kiritishi mumkin.
- **📊 Statistika** — umumiy va har bir vakansiya bo'yicha: jami ariza, qabul qilingan,
  rad etilgan (sabab bo'yicha taqsimlangan).

### Sozlash

1. @BotFather'da `/newbot` bilan **ikkinchi** bot yarating.
2. @userinfobot orqali o'z Telegram user ID'ingizni oling.
3. `.env`ga (yoki Render Environment'ga) qo'shing:
   ```
   ADMIN_BOT_TOKEN=<yangi bot tokeni>
   ADMIN_USER_IDS=<sizning user ID'ingiz>
   ```
4. Qayta deploy qiling. Yangi botga `/start` yuboring.

## Yangi vakansiya qo'shish

Endi vakansiyalar `vacancies.py`da emas, ma'lumotlar bazasida saqlanadi va
yuqoridagi **Admin bot** orqali (➕ Yangi vakansiya) qo'shiladi/tahrirlanadi —
kodga tegishning hojati yo'q.

## Mijozga sotish uchun eslatma

Ushbu bot — MVP asosi. $400+ narxni oqlash uchun har bir mijoz uchun:
- brend nomi/logotipi va matnlarni moslashtiring,
- kerakli vakansiya va savollarni sozlang,
- admin guruhni mijozning haqiqiy jamoasiga ulang,
- (xohlasa) Google Sheets eksportini qo'shib bering.

Demo sifatida bitta aniq soha (masalan restoranlar tarmog'i yoki savdo
kompaniyasi) uchun to'liq ishlaydigan namunani tayyorlab, video-taqdimot
bilan potentsial mijozlarga ko'rsatish tavsiya etiladi.
