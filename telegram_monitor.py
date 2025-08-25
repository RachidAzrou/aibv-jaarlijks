import logging
import asyncio
from typing import Dict

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, AIORateLimiter

from config import Config
from selenium_controller import AIBVBookingBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("TG-MON")

HELP = (
    "Monitor bot:\n"
    "/monitor – start monitoring (geen boeking)\n"
    "/stop    – stop monitoring\n"
    "/help    – toon hulp\n"
)

active_tasks: Dict[int, asyncio.Task] = {}
Config.STOP_FLAG = False

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 AIBV Jaarlijks Monitor klaar.\n" + HELP)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    Config.STOP_FLAG = True
    task = active_tasks.get(update.effective_chat.id)
    if task and not task.done():
        await update.message.reply_text("⏹️ Monitoring wordt gestopt…")
    else:
        await update.message.reply_text("ℹ️ Geen actieve monitoring.")

async def monitor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    task = active_tasks.get(chat_id)
    if task and not task.done():
        return await update.message.reply_text("⏳ Er loopt al monitoring. Gebruik /stop of wacht.")

    Config.STOP_FLAG = False
    await update.message.reply_text("🔍 Start monitoring (meldt zodra er een slot is)…")

    async def runner():
        bot = AIBVBookingBot()
        try:
            bot.setup_driver()
            bot.login()
            bot.select_eu_vehicle()
            bot.select_station()

            start = asyncio.get_event_loop().time()
            while not Config.STOP_FLAG and (asyncio.get_event_loop().time() - start) < Config.MONITOR_MAX_SECONDS:
                best = bot.find_earliest_within_3_business_days()
                if best:
                    dt, _, label = best
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ Slot gevonden: {label}")
                    break
                bot.driver.refresh()
                bot.wait_dom_idle()
                await asyncio.sleep(Config.REFRESH_DELAY)
        except Exception as e:
            log.exception("Fout in monitor-runner")
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
    app.add_handler(CommandHandler("monitor", monitor_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()
