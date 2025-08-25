import logging
import asyncio
from typing import Dict

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, AIORateLimiter

from config import Config, TELEGRAM_CHAT_IDS
from selenium_controller import AIBVBookingBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("TG-MON")

HELP = (
    "Monitor bot:\n"
    "/monitor <nummerplaat>|<dd/mm/jjjj> – start monitoring (geen boeking)\n"
    "/stop    – stop monitoring\n"
    "/help    – hulp\n"
    "/whoami  – toon jouw chat ID\n"
)

active_tasks: Dict[int, asyncio.Task] = {}
Config.STOP_FLAG = False

def is_authorized(update: Update) -> bool:
    return str(update.effective_chat.id) in TELEGRAM_CHAT_IDS

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")
    await update.message.reply_text("👋 AIBV Jaarlijks Monitor klaar.\n" + HELP)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")
    await update.message.reply_text(HELP)

async def whoami_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Jouw chat ID is: {update.effective_chat.id}")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")
    Config.STOP_FLAG = True
    task = active_tasks.get(update.effective_chat.id)
    if task and not task.done():
        await update.message.reply_text("⏹️ Monitoring wordt gestopt…")
    else:
        await update.message.reply_text("ℹ️ Geen actieve monitoring.")

async def monitor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")

    chat_id = update.effective_chat.id
    if not context.args:
        return await update.message.reply_text("Gebruik: /monitor <nummerplaat>|<dd/mm/jjjj>")

    raw_arg = " ".join(context.args).strip()
    if "|" not in raw_arg:
        return await update.message.reply_text("Gebruik: /monitor <nummerplaat>|<dd/mm/jjjj>")

    plate, first_reg_date = [x.strip() for x in raw_arg.split("|", 1)]

    await update.message.reply_text(f"🔍 Start monitoring voor {plate} ({first_reg_date})…")

    async def runner():
        bot = AIBVBookingBot()
        def notify(text: str):
            asyncio.create_task(context.bot.send_message(chat_id=chat_id, text=text))
        try:
            bot.set_notifier(notify)

            await context.bot.send_message(chat_id=chat_id, text="🧰 Driver starten…")
            bot.setup_driver()
            await context.bot.send_message(chat_id=chat_id, text="✅ Driver klaar.")

            await context.bot.send_message(chat_id=chat_id, text="🔐 Inloggen…")
            bot.login()
            await context.bot.send_message(chat_id=chat_id, text="✅ Ingelogd.")

            await context.bot.send_message(chat_id=chat_id, text="🚗 Voertuig & keuringstype…")
            bot.select_eu_vehicle(plate, first_reg_date)
            await context.bot.send_message(chat_id=chat_id, text="✅ Voertuig bevestigd.")

            await context.bot.send_message(chat_id=chat_id, text="🏢 Station kiezen…")
            bot.select_station()
            await context.bot.send_message(chat_id=chat_id, text="✅ Station klaar.")

            # Monitoring maar geen boeking erzef → forceren indien nodig
            orig = Config.BOOKING_ENABLED
            Config.BOOKING_ENABLED = False
            result = bot.monitor_and_book()
            Config.BOOKING_ENABLED = orig

            if result.get("success"):
                await context.bot.send_message(chat_id=chat_id, text=f"✅ Slot gevonden: {result.get('slot')} (niet geboekt).")
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"❌ Niet gelukt: {result.get('error')}")

        except Exception as e:
            log.exception("Fout in monitor-runner")
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Fout: {e}")
        finally:
            bot.close()

    active_tasks[chat_id] = asyncio.create_task(runner())

def main():
    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).rate_limiter(AIORateLimiter()).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("whoami", whoami_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("monitor", monitor_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()
