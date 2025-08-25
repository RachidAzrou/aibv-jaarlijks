import logging
import asyncio
from typing import Dict

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, AIORateLimiter

from config import Config
from selenium_controller import AIBVBookingBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("TG-MON")

HELP = (
    "Monitor bot commando’s:\n"
    "/monitor  (start monitoring, geen auto-boeking)\n"
    "/stop     (stop huidige monitoring)\n"
    "/help     (toon hulp)\n"
)

# actieve monitor taken
active_tasks: Dict[int, asyncio.Task] = {}
stop_flags: Dict[int, bool] = {}
Config.STOP_FLAG = False


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 AIBV Jaarlijks Monitor klaar.\n" + HELP)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    stop_flags[chat_id] = True
    Config.STOP_FLAG = True
    task = active_tasks.get(chat_id)
    if task and not task.done():
        await update.message.reply_text("⏹️ Monitoring wordt gestopt…")
    else:
        await update.message.reply_text("ℹ️ Geen actieve monitoring.")


async def monitor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    task = active_tasks.get(chat_id)
    if task and not task.done():
        return await update.message.reply_text("⏳ Er loopt al monitoring. Gebruik /stop of wacht.")

    stop_flags[chat_id] = False
    Config.STOP_FLAG = False
    await update.message.reply_text("🔍 Start monitoring slots (GEEN auto-boeking)…")

    async def runner():
        bot = AIBVBookingBot()
        try:
            bot.setup_driver()
            bot.login()
            # jaarlijkse flow
            bot.select_eu_vehicle()
            bot.select_station()

            # monitor loop: zoekt enkel slots en meldt, boekt niet
            while not Config.STOP_FLAG:
                found = bot.find_earliest_within_3_business_days()
                if found:
                    dt, _, label = found
                    msg = f"✅ Slot gevonden: {label}"
                    await context.bot.send_message(chat_id=chat_id, text=msg)
                    break

                bot.driver.refresh()
                bot.wait_dom_idle()
                await asyncio.sleep(Config.REFRESH_DELAY)
        except Exception as e:
            log.exception("Fout in monitor-runner")
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Fout: {e}")
        finally:
            bot.close()

    task = asyncio.create_task(runner())
    active_tasks[chat_id] = task


def main():
    application = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).rate_limiter(AIORateLimiter()).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("stop", stop_cmd))
    application.add_handler(CommandHandler("monitor", monitor_cmd))
    application.run_polling()


if __name__ == "__main__":
    main()
