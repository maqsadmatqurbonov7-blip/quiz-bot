# 📚 Telegram Quiz Bot

150 ta savol (Axborot xavfsizligi + IoT) — Telegram Poll (viktorina) formatida.

## 🚀 O'rnatish

```bash
# 1. Kerakli kutubxonalarni o'rnatish
pip install -r requirements.txt

# 2. .env faylni sozlash
cp .env.example .env
# BOT_TOKEN=sizning_token_ingiz
```

## ▶️ Ishga tushirish

```bash
python quiz_bot.py
```

## 📋 Buyruqlar

| Buyruq | Tavsif |
|--------|--------|
| `/start` | Botni boshlash, mavjud quizlar ro'yxati |
| `/quiz1` | 1–50 savollar |
| `/quiz2` | 51–100 savollar |
| `/quiz3` | 101–150 savollar |
| `/quizall` | Barcha 150 ta savolni ketma-ket yuborish |

## 📝 Savollarni yangilash

Savollar `make_questions.py` ichida hardcode qilingan. O'zgartirish uchun:

1. `make_questions.py` ni tahrirlang
2. `python make_questions.py` ni ishga tushiring
3. `questions.json` yangilanadi

## ⚙️ Texnik tafsilotlar

- **Kutubxona:** `python-telegram-bot` v20.7
- **Format:** Telegram Quiz Poll (`is_anonymous=False`)
- **Javoblar:** Har safar aralashtiriladi (`random.shuffle`)
- **Kechikish:** Savollar orasida 1.2 soniya
- **Cheklov:** Savol matni 300 belgigacha, variant 100 belgigacha
