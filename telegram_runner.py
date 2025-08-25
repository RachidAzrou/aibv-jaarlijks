import logging, asyncio, time
from typing import Dict
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, AIORateLimiter

from config import Config
from selenium_controller import AIBVBookingBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("TG")

HELP = (
    "Gebruik:\n"
    "/book  (start jaarlijkse flow)\n"
    "/stop  (stop huidig proces)\n"
    "/help  (toon hulp)\n"
)

active_tasks: Dict[int, asyncio.Task] = {}
stop_flags: Dict[int, bool] = {}
Config.STOP_FLAG = False

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("AIBV-jaarlijks bot klaar ✅\n" + HELP)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    stop_flags[chat_id] = True
    Config.STOP_FLAG = True
    task = active_tasks.get(chat_id)
    if task and not task.done():
        await update.message.reply_text("⏹️ Stopverzoek ontvangen.")
    else:
        await update.message.reply_text("ℹ️ Geen actief proces.")

async def book_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    task = active_tasks.get(chat_id)
    if task and not task.done():
        return await update.message.reply_text("⏳ Er loopt al een sessie. Gebruik /stop of wacht.")
    stop_flags[chat_id] = False
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
            await context.bot.send_message(chat_id=chat_id, text=f"Resultaat: {result}")
        finally:
            bot.close()
    task = asyncio.create_task(runner())
    active_tasks[chat_id] = task

def main():
    application = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).rate_limiter(AIORateLimiter()).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("stop", stop_cmd))
    application.add_handler(CommandHandler("book", book_cmd))
    application.run_polling()

if __name__ == "__main__":
    main()
