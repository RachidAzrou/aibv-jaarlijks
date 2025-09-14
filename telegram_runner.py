#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import asyncio
import time
from typing import Dict, Callable, Optional

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
    "/status – status van de run\n"
    "/help  – toon deze hulp\n"
    "/whoami – jouw chat ID\n"
)

active_tasks: Dict[int, asyncio.Task] = {}
active_status: Dict[int, str] = {}
Config.STOP_FLAG = False


def is_authorized(update: Update) -> bool:
    return str(update.effective_chat.id) in TELEGRAM_CHAT_IDS


async def _typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")
    await update.message.reply_text("👋 Bot klaar.\n" + HELP)


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
    status = active_status.get(chat_id, "idle")
    running = "🟢 actief" if (t := active_tasks.get(chat_id)) and not t.done() else "⚪️ niet actief"
    await update.message.reply_text(
        f"Status: {running}\nStap: {status}\n"
        f"TEST_MODE={Config.TEST_MODE}  BOOKING_ENABLED={Config.BOOKING_ENABLED}  STATION_ID={Config.STATION_ID}"
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

    # Als er al een run actief is, eerst netjes melden
    old = active_tasks.get(chat_id)
    if old and not old.done():
        return await update.message.reply_text("⏳ Er draait al een run. Gebruik /stop of wacht tot deze klaar is.")

    await update.message.reply_text(
        f"🚀 Start flow voor <b>{plate}</b> ({first_reg_date})…\n"
        f"TEST_MODE={Config.TEST_MODE}  BOOKING_ENABLED={Config.BOOKING_ENABLED}",
        parse_mode="HTML",
    )

    async def send(msg: str):
        await _typing(context, chat_id)
        await context.bot.send_message(chat_id=chat_id, text=msg, disable_web_page_preview=True)

    def stepper(label: str) -> Callable[[str], None]:
        """Helper om status bij te houden en stapmeldingen te sturen via notify_func."""
        def _inner(message: str):
            # Dit wordt vanuit selenium_controller (sync) aangeroepen
            asyncio.get_event_loop().create_task(send(f"{label} {message}"))
        return _inner

    async def run_with_steps():
        start_ts = time.time()
        bot: Optional[AIBVBookingBot] = None

        try:
            # 1) Setup
            active_status[chat_id] = "🔧 Driver initialiseren"
            await send("🔧 Chrome-driver initialiseren… (venster zichtbaar bij TEST_MODE=True)")
            bot = AIBVBookingBot()

            # Stuur interne meldingen van de bot door naar Telegram
            bot.notify_func = lambda msg: asyncio.create_task(send(msg))

            bot.setup_driver()
            await send("✅ Driver klaar.")

            # 2) Login
            active_status[chat_id] = "🔐 Inloggen"
            await send("🔐 Inloggen…")
            bot.login()
            await send("✅ Ingelogd.")

            # 3) Voertuig
            active_status[chat_id] = "🚗 Voertuig selecteren"
            await send(f"🚗 Voertuig selecteren: {plate} (1e inschrijving: {first_reg_date})…")
            bot.select_vehicle(plate, first_reg_date)
            await send("✅ Voertuig geselecteerd.")

            # 4) Station
            active_status[chat_id] = "📍 Station kiezen"
            await send(f"📍 Station kiezen (STATION_ID={Config.STATION_ID})…")
            try:
                bot.select_station()
            except TypeError:
                # Voor oudere signaturen met station_id parameter
                bot.select_station(Config.STATION_ID)
            await send("✅ Station ingesteld.")

            # 5) Monitor & boek
            minutes = getattr(Config, "MONITOR_MAX_SECONDS", 3600) // 60
            active_status[chat_id] = "🕑 Monitoren op vrije slots"
            await send(
                f"🕑 Monitoren gestart (max ~{minutes} min, refresh elke {Config.REFRESH_DELAY}s)…\n"
                f"{'🧪 TEST_MODE actief: er wordt niet echt geboekt.' if Config.TEST_MODE or not Config.BOOKING_ENABLED else '🟢 Boeken ingeschakeld: bevestigt automatisch zodra mogelijk.'}"
            )

            result = bot.monitor_and_book()

            # 6) Resultaat
            ok = bool(result.get("success")) if isinstance(result, dict) else bool(result)
            took = int(time.time() - start_ts)
            if ok:
                details = []
                for key in ("slot", "when", "station", "message"):
                    if isinstance(result, dict) and result.get(key):
                        details.append(f"{key}: {result[key]}")
                extra = ("\n" + "\n".join(details)) if details else ""
                await send(f"🎉 Resultaat: ✅ gelukt in {took}s.{extra}")
            else:
                err = (result or {}).get("error") if isinstance(result, dict) else None
                await send(f"❌ Resultaat: niet gelukt in {took}s.{f' Reden: {err}' if err else ''}")

        except Exception as e:
            log.exception("Fout in booking runner")
            await send(f"⚠️ Fout tijdens stap “{active_status.get(chat_id, 'onbekend')}”: {e}")
        finally:
            active_status[chat_id] = "opruimen"
            try:
                if bot:
                    bot.close()
            except Exception:
                pass
            active_status[chat_id] = "idle"

    task = asyncio.create_task(run_with_steps())
    active_tasks[chat_id] = task


def main():
    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).rate_limiter(AIORateLimiter()).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("whoami", whoami_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("book", book_cmd))
    app.run_polling()


if __name__ == "__main__":
    log.info(
        "[CONFIG] TEST_MODE=%s BOOKING_ENABLED=%s STATION_ID=%s TELEGRAM_CHAT_IDS=%s",
        Config.TEST_MODE, Config.BOOKING_ENABLED, Config.STATION_ID, TELEGRAM_CHAT_IDS
    )
    main()
