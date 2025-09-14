#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from typing import Dict, Optional, Callable

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, AIORateLimiter

from config import Config, TELEGRAM_CHAT_IDS
from selenium_controller import AIBVBookingBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("TG-RUNNER")

HELP = (
    "AIBV-jaarlijks bot:\n"
    "/book <nummerplaat>|<dd/mm/jjjj> – starten\n"
    "/stop  – stop de huidige run\n"
    "/status – status en config\n"
    "/whoami – jouw chat ID\n"
    "/help  – deze hulp\n"
)

active_tasks: Dict[int, asyncio.Task] = {}
active_status: Dict[int, str] = {}
Config.STOP_FLAG = False  # globale stop-vlag

def is_authorized(update: Update) -> bool:
    return str(update.effective_chat.id) in TELEGRAM_CHAT_IDS


async def _typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass


def make_notifier(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> Callable[[str], None]:
    """Sync -> async bridge om meldingen vanuit selenium_controller door te sturen naar Telegram."""
    async def send_async(msg: str):
        try:
            await _typing(context, chat_id)
            await context.bot.send_message(chat_id=chat_id, text=msg, disable_web_page_preview=True)
        except Exception as e:
            log.error(f"[notify] Telegram send failed: {e}")

    def notify(msg: str):
        asyncio.get_event_loop().create_task(send_async(msg))

    return notify


# ---------------- Commands ----------------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")
    await update.message.reply_text(HELP)


async def whoami_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Jouw chat ID is: {update.effective_chat.id}")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")
    chat_id = update.effective_chat.id
    running = "🟢 actief" if (t := active_tasks.get(chat_id)) and not t.done() else "⚪️ niet actief"
    step = active_status.get(chat_id, "idle")
    await update.message.reply_text(
        f"Status: {running}\n"
        f"Stap: {step}\n"
        f"STOP_FLAG={Config.STOP_FLAG}\n"
        f"TEST_MODE={Config.TEST_MODE}  BOOKING_ENABLED={Config.BOOKING_ENABLED}\n"
        f"STATION_ID={Config.STATION_ID}  DESIRED_BD={Config.DESIRED_BUSINESS_DAYS}\n"
        f"(Monitoren heeft GEEN tijdslimiet; stopt alleen bij /stop of bij succes.)"
    )


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")
    Config.STOP_FLAG = True
    task = active_tasks.get(update.effective_chat.id)
    if task and not task.done():
        await update.message.reply_text("⏹️ Stopverzoek verstuurd. De huidige actie rondt af…")
    else:
        await update.message.reply_text("ℹ️ Geen actieve run.")


async def book_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")

    chat_id = update.effective_chat.id

    if not context.args:
        return await update.message.reply_text("Gebruik: /book <nummerplaat>|<dd/mm/jjjj>")

    raw_arg = " ".join(context.args).strip()
    if "|" not in raw_arg:
        return await update.message.reply_text("Gebruik: /book <nummerplaat>|<dd/mm/jjjj>")

    plate, first_reg_date = [x.strip() for x in raw_arg.split("|", 1)]

    # Reset stop-flag vóór elke nieuwe run (fix voor spook-'/stop')
    Config.STOP_FLAG = False

    # Eén run tegelijk per chat
    old = active_tasks.get(chat_id)
    if old and not old.done():
        return await update.message.reply_text("⏳ Er draait al een run. Gebruik /stop of wacht tot deze klaar is.")

    await update.message.reply_text(
        f"🚀 Start flow voor <b>{plate}</b> ({first_reg_date})…\n"
        f"TEST_MODE={Config.TEST_MODE}  BOOKING_ENABLED={Config.BOOKING_ENABLED}\n"
        f"(Monitor blijft lopen tot /stop of succes — geen tijdslimiet.)",
        parse_mode="HTML",
    )

    async def run_flow():
        bot: Optional[AIBVBookingBot] = None
        try:
            active_status[chat_id] = "🔧 Driver initialiseren"
            bot = AIBVBookingBot()
            bot.notify_func = make_notifier(context, chat_id)
            bot.setup_driver()

            active_status[chat_id] = "🔐 Inloggen"
            bot.login()

            active_status[chat_id] = "🚗 Voertuig"
            bot.select_vehicle(plate, first_reg_date)

            active_status[chat_id] = "📍 Station"
            bot.select_station()

            active_status[chat_id] = "🕑 Monitoren"
            await context.bot.send_message(
                chat_id=chat_id,
                text=(f"🕑 Monitor gestart. Venster: {Config.DESIRED_BUSINESS_DAYS} werkdagen. "
                      f"Refresh elke {Config.REFRESH_DELAY}s. "
                      f"{'🧪 TEST_MODE: er wordt niet echt geboekt.' if Config.TEST_MODE or not Config.BOOKING_ENABLED else '🟢 Boeken ingeschakeld.'}\n"
                      f"⏱️ Geen tijdslimiet: ik zoek door tot /stop of succes.")
            )

            result = bot.monitor_and_book()

            ok = bool(result.get("success")) if isinstance(result, dict) else bool(result)
            if ok:
                label = result.get("slot") if isinstance(result, dict) else ""
                extra = " (niet bevestigd: BOOKING_ENABLED=false)" if isinstance(result, dict) and result.get("booking_disabled") else ""
                await context.bot.send_message(chat_id=chat_id, text=f"🎉 Resultaat: ✅ gelukt {label}{extra}")
            else:
                err = (result or {}).get("error") if isinstance(result, dict) else None
                await context.bot.send_message(chat_id=chat_id, text=f"❌ Resultaat: niet gelukt. {f'Reden: {err}' if err else ''}")

        except Exception as e:
            log.exception("Fout in booking runner")
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Fout: {e}")
        finally:
            active_status[chat_id] = "opruimen"
            try:
                if bot:
                    bot.close()
            except Exception:
                pass
            active_status[chat_id] = "idle"

    task = asyncio.create_task(run_flow())
    active_tasks[chat_id] = task


def main():
    # Reset stop-flag bij opstart
    Config.STOP_FLAG = False
    log.info(
        "[CONFIG] TEST_MODE=%s BOOKING_ENABLED=%s STATION_ID=%s TELEGRAM_CHAT_IDS=%s DESIRED_BD=%s",
        Config.TEST_MODE, Config.BOOKING_ENABLED, Config.STATION_ID, TELEGRAM_CHAT_IDS, Config.DESIRED_BUSINESS_DAYS
    )

    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).rate_limiter(AIORateLimiter()).build()
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("whoami", whoami_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("book", book_cmd))
    app.run_polling()


if __name__ == "__main__":
    main()
