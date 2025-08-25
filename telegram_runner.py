import logging
import asyncio
from typing import Dict

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, AIORateLimiter

from config import Config
from selenium_controller import AIBVBookingBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("TG")

HELP = (
    "AIBV-jaarlijks bot:\n"
    "/book  – start flow (monitor tot slot; boekt als BOOKING_ENABLED=true)\n"
    "/stop  – stop de huidige run\n"
    "/help  – toon deze hulp\n"
)

active_tasks: Dict[int, asyncio.Task] = {}
Config.STOP_FLAG = False

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 AIBV Jaarlijkse bot klaar.\n" + HELP)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    Config.STOP_FLAG = True
    task = active_tasks.get(update.effective_chat.id)
    if task and not task.done():
        await update.message.reply_text("⏹️ Bezig met stoppen…")
    else:
        await update.message.reply_text("ℹ️ Er draait niets op dit moment.")

async def book_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    task = active_tasks.get(chat_id)
    if task and not task.done():
        return await update.message.reply_text("⏳ Er loopt al een sessie. Gebruik /stop of wacht even.")

    Config.STOP_FLAG = False
    await update.message.reply_text("🚀 Start jaarlijkse keuring flow…")

    async def runner():
        bot = AIBVBookingBot()
        try:
            bot.setup_driver()
            bot.login()
            bot.select_eu_vehicle()
            bot.select_station()
            result = bot.monitor_and_book()
            await context.bot.send_message(chat_id=chat_id, text=f"Resultaat: {'✅ gelukt' if result else '❌ niet gelukt'}")
        except Exception as e:
            log.exception("Fout in booking runner")
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Fout: {e}")
        finally:
            bot.close()

    t = asyncio.create_task(runner())
    active_tasks[chat_id] = t

def main():
    if not Config.TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN ontbreekt in .env")
    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).rate_limiter(AIORateLimiter()).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("book", book_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()
