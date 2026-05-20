import asyncio
import random
import os
import sys
import json
import logging
import signal
import time
import threading
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import InputPollOption, Update
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler
from telegram.error import NetworkError, TimedOut, RetryAfter, TelegramError

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHUNK = 50
TIMEOUT = 20  # soniya — javob bermasa keyingisiga o'tadi

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

with open("questions.json", encoding="utf-8") as f:
    questions = json.load(f)

total = len(questions)
num_chunks = (total + CHUNK - 1) // CHUNK

# Aktiv sessiyalar: {chat_id: session_data}
sessions = {}
# Poll ID -> chat_id xaritalash
poll_to_chat = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [f"📚 Salom! Jami *{total}* ta savol mavjud.\n"]
    for i in range(num_chunks):
        s = i * CHUNK + 1
        e = min((i + 1) * CHUNK, total)
        lines.append(f"/quiz{i+1} — {s}–{e} savollar")
    lines.append(f"\n/quizall — Barcha {total} ta savolni yuborish")
    lines.append("/stop — Testni to'xtatish")
    lines.append(f"\n✏️ Savollar *bittadan* yuboriladi.")
    lines.append(f"⏱ Javob bermasangiz, *{TIMEOUT} soniya*dan keyin keyingisiga o'tiladi.")
    lines.append("✅ Javob bersangiz, darhol keyingi savol keladi.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def send_question(chat_id, context, session):
    """Bitta savol yuborish va timeout o'rnatish."""
    idx = session["current_index"]
    chunk_end = session["chunk_end"]
    chunk_start = session["chunk_start"]

    # Blok tugadimi?
    if idx >= chunk_end:
        correct = session["correct_count"]
        wrong = session["wrong_count"]
        skipped = session["skipped_count"]
        total_q = chunk_end - chunk_start

        await context.bot.send_message(
            chat_id,
            f"🏁 *{chunk_start+1}–{chunk_end}* savollar tugadi!\n\n"
            f"📊 *Natijangiz:*\n"
            f"✅ To'g'ri: *{correct}* ta\n"
            f"❌ Noto'g'ri: *{wrong}* ta\n"
            f"⏭ Javob berilmagan: *{skipped}* ta\n"
            f"📝 Jami: *{total_q}* ta\n\n"
            f"🎯 Ball: *{correct}/{total_q}* ({round(correct/total_q*100)}%)",
            parse_mode="Markdown"
        )
        # Sessiyani tozalash
        old_polls = [pid for pid, cid in poll_to_chat.items() if cid == chat_id]
        for pid in old_polls:
            poll_to_chat.pop(pid, None)
        sessions.pop(chat_id, None)
        return

    q = questions[idx]
    opts = q["options"][:]
    correct_text = opts[q["correct_id"]]
    random.shuffle(opts)
    new_correct = opts.index(correct_text)

    q_text = q["question"][:299]
    poll_options = [InputPollOption(o[:100]) for o in opts]

    try:
        msg = await context.bot.send_poll(
            chat_id=chat_id,
            question=f"❓ {idx+1}/{total}. {q_text}",
            options=poll_options,
            type="quiz",
            correct_option_id=new_correct,
            is_anonymous=False,
            open_period=TIMEOUT,
        )

        poll_id = msg.poll.id
        session["current_poll_id"] = poll_id
        session["correct_option_id"] = new_correct
        session["answered"] = False
        poll_to_chat[poll_id] = chat_id

        # Timeout — javob bermasa keyingisiga o'tish
        task = asyncio.create_task(
            auto_advance(chat_id, context, poll_id)
        )
        session["timeout_task"] = task

    except RetryAfter as e:
        logger.warning(f"Telegram flood control: {e.retry_after}s kutish")
        await asyncio.sleep(e.retry_after)
        await send_question(chat_id, context, session)
    except (NetworkError, TimedOut) as ex:
        logger.warning(f"Tarmoq xatosi savol {idx+1}: {ex}, 5s kutib qayta urinish")
        await asyncio.sleep(5)
        await send_question(chat_id, context, session)
    except Exception as ex:
        logger.warning(f"Savol {idx+1} yuborilmadi: {ex}")
        session["current_index"] += 1
        await asyncio.sleep(1)
        await send_question(chat_id, context, session)


async def auto_advance(chat_id, context, poll_id):
    """Timeout bo'lsa avtomatik keyingi savolga o'tish."""
    await asyncio.sleep(TIMEOUT + 1)

    session = sessions.get(chat_id)
    if not session:
        return

    if session.get("current_poll_id") == poll_id and not session.get("answered"):
        session["skipped_count"] += 1
        session["current_index"] += 1
        poll_to_chat.pop(poll_id, None)
        await send_question(chat_id, context, session)


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi javob berganda — darhol keyingi savolga o'tish."""
    poll_answer = update.poll_answer
    poll_id = poll_answer.poll_id

    chat_id = poll_to_chat.get(poll_id)
    if not chat_id:
        return

    session = sessions.get(chat_id)
    if not session:
        return

    if session.get("current_poll_id") == poll_id and not session.get("answered"):
        session["answered"] = True

        # Timeout ni bekor qilish
        timeout_task = session.get("timeout_task")
        if timeout_task:
            timeout_task.cancel()

        # To'g'ri javobni tekshirish
        selected = poll_answer.option_ids[0] if poll_answer.option_ids else -1
        if selected == session.get("correct_option_id"):
            session["correct_count"] += 1
        else:
            session["wrong_count"] += 1

        poll_to_chat.pop(poll_id, None)

        # Keyingi savolga o'tish
        session["current_index"] += 1
        await asyncio.sleep(0.5)
        await send_question(chat_id, context, session)


async def start_chunk(update, context, chunk_idx):
    """Quiz blokini boshlash."""
    chat_id = update.effective_chat.id

    # Agar aktiv sessiya bo'lsa — bekor qilish
    if chat_id in sessions:
        old_task = sessions[chat_id].get("timeout_task")
        if old_task:
            old_task.cancel()
        old_polls = [pid for pid, cid in poll_to_chat.items() if cid == chat_id]
        for pid in old_polls:
            poll_to_chat.pop(pid, None)

    s = chunk_idx * CHUNK
    e = min(s + CHUNK, total)

    session = {
        "chunk_start": s,
        "chunk_end": e,
        "current_index": s,
        "correct_count": 0,
        "wrong_count": 0,
        "skipped_count": 0,
        "answered": False,
        "current_poll_id": None,
        "correct_option_id": None,
        "timeout_task": None,
    }
    sessions[chat_id] = session

    await update.message.reply_text(
        f"🚀 *{s+1}–{e}* savollar boshlanmoqda...\n"
        f"⏱ Har bir savol uchun *{TIMEOUT} soniya* vaqt.\n"
        f"✅ Javob bersangiz — darhol keyingisi keladi.",
        parse_mode="Markdown"
    )

    await asyncio.sleep(1)
    await send_question(chat_id, context, session)


async def quiz_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Barcha savollarni ketma-ket (bittadan) yuborish."""
    chat_id = update.effective_chat.id

    if chat_id in sessions:
        old_task = sessions[chat_id].get("timeout_task")
        if old_task:
            old_task.cancel()

    session = {
        "chunk_start": 0,
        "chunk_end": total,
        "current_index": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "skipped_count": 0,
        "answered": False,
        "current_poll_id": None,
        "correct_option_id": None,
        "timeout_task": None,
    }
    sessions[chat_id] = session

    await update.message.reply_text(
        f"🚀 *Barcha {total} ta savol boshlanmoqda!*\n"
        f"⏱ Har bir savol uchun *{TIMEOUT} soniya* vaqt.",
        parse_mode="Markdown"
    )

    await asyncio.sleep(1)
    await send_question(chat_id, context, session)


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testni to'xtatish."""
    chat_id = update.effective_chat.id
    session = sessions.get(chat_id)

    if not session:
        await update.message.reply_text("❌ Hozir aktiv test yo'q.")
        return

    # Tozalash
    timeout_task = session.get("timeout_task")
    if timeout_task:
        timeout_task.cancel()
    old_polls = [pid for pid, cid in poll_to_chat.items() if cid == chat_id]
    for pid in old_polls:
        poll_to_chat.pop(pid, None)

    correct = session["correct_count"]
    wrong = session["wrong_count"]
    done = correct + wrong + session["skipped_count"]

    sessions.pop(chat_id, None)

    await update.message.reply_text(
        f"⏹ Test to'xtatildi.\n\n"
        f"📊 *Natijangiz:*\n"
        f"✅ To'g'ri: *{correct}* ta\n"
        f"❌ Noto'g'ri: *{wrong}* ta\n"
        f"📝 Jami javob berilgan: *{done}* ta",
        parse_mode="Markdown"
    )


def make_handler(chunk_idx: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await start_chunk(update, context, chunk_idx)
    return handler


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global xatolikni ushlash — bot to'xtamasdan davom etadi."""
    logger.error(f"Xatolik yuz berdi: {context.error}", exc_info=context.error)

    if isinstance(context.error, RetryAfter):
        logger.warning(f"Flood control: {context.error.retry_after}s kutish")
        await asyncio.sleep(context.error.retry_after)
    elif isinstance(context.error, (NetworkError, TimedOut)):
        logger.warning("Tarmoq xatosi — bot davom etadi...")
        await asyncio.sleep(3)
    elif isinstance(context.error, TelegramError):
        logger.error(f"Telegram API xatosi: {context.error}")


# ===== HEALTH CHECK SERVER (bepul hosting uchun) =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - Quiz Bot is running")

    def log_message(self, format, *args):
        pass  # Health check loglarini yashirish


def start_health_server():
    """Background HTTP server — platformaning health check uchun."""
    port = int(os.getenv("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"🌐 Health check server :{port} portda ishlamoqda")
    server.serve_forever()


def keep_alive():
    """Har 5 daqiqada o'z URL ini ping qiladi — Render uxlab qolmaydi."""
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        logger.warning("⚠️ RENDER_EXTERNAL_URL topilmadi — self-ping ishlamaydi")
        return

    ping_url = url.rstrip("/") + "/"
    logger.info(f"🏓 Keep-alive ishga tushdi: har 5 daqiqada {ping_url} ping qilinadi")

    while True:
        time.sleep(300)  # 5 daqiqa
        try:
            req = urllib.request.Request(ping_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.debug(f"🏓 Self-ping: {resp.status}")
        except Exception as e:
            logger.warning(f"🏓 Self-ping xatosi: {e}")


def run_bot():
    """Botni auto-restart bilan ishga tushirish."""
    # Health check serverni background threadda ishga tushirish
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    # Self-ping — Render uxlab qolishdan saqlaydi
    ping_thread = threading.Thread(target=keep_alive, daemon=True)
    ping_thread.start()

    retry_delay = 5  # Boshlang'ich kutish (soniya)
    max_delay = 300  # Maksimal kutish (5 daqiqa)
    retry_count = 0

    while True:
        try:
            logger.info(f"🚀 Bot ishga tushmoqda... (urinish #{retry_count + 1})")

            app = Application.builder().token(BOT_TOKEN).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("stop", stop))
            app.add_handler(CommandHandler("quizall", quiz_all))
            app.add_handler(PollAnswerHandler(handle_poll_answer))

            for i in range(num_chunks):
                app.add_handler(CommandHandler(f"quiz{i+1}", make_handler(i)))

            # Global error handler — bot crashdan himoyalanadi
            app.add_error_handler(error_handler)

            cmds = ", ".join([f"/quiz{i+1}" for i in range(num_chunks)])
            logger.info(f"✅ Bot ishga tushdi! {total} ta savol | {num_chunks} ta blok")
            logger.info(f"Buyruqlar: /start, {cmds}, /quizall, /stop")

            app.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                close_loop=False,
            )

        except KeyboardInterrupt:
            logger.info("⏹ Bot foydalanuvchi tomonidan to'xtatildi.")
            sys.exit(0)

        except Exception as e:
            retry_count += 1
            current_delay = min(retry_delay * (2 ** min(retry_count, 6)), max_delay)
            logger.error(
                f"❌ Bot crashga uchradi: {e}\n"
                f"🔄 {current_delay} soniyadan keyin qayta ishga tushadi...",
                exc_info=True
            )
            time.sleep(current_delay)
            # Sessiyalarni tozalash
            sessions.clear()
            poll_to_chat.clear()
            logger.info("🔄 Qayta ishga tushmoqda...")

        else:
            # run_polling normal tugadi (to'xtatildi)
            logger.info("Bot polling to'xtadi. Qayta ishga tushmoqda...")
            retry_count = 0
            time.sleep(5)


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN topilmadi! .env faylni tekshiring.")
        sys.exit(1)

    run_bot()
