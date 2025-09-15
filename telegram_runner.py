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
    "/help  – deze help\n"
    "/whoami – toon je chat ID\n"
    "/status – status van de huidige run\n"
    "/book <plaat>|<dd/mm/jjjj> – start\n"
    "/stop  – stop de huidige run\n"
)

active_tasks: Dict[int, asyncio.Task] = {}
active_status: Dict[int, str] = {}
active_bots: Dict[int, AIBVBookingBot] = {}
notify_locks: Dict[int, asyncio.Lock] = {}
notify_enabled: Dict[int, bool] = {}
run_tokens: Dict[int, int] = {}


def _bump_token(chat_id: int) -> int:
    run_tokens[chat_id] = run_tokens.get(chat_id, 0) + 1
    return run_tokens[chat_id]


# Globale stop-vlag (gelezen door selenium_controller)
Config.STOP_FLAG = False


def is_authorized(update: Update) -> bool:
    return str(update.effective_chat.id) in TELEGRAM_CHAT_IDS


def _status_line(chat_id: int) -> str:
    t = active_tasks.get(chat_id)
    running = "🟢 actief" if (t and not t.done()) else "⚪️ niet actief"
    step = active_status.get(chat_id, "idle")
    return (
        f"Status: {running}\n"
        f"Stap: {step}\n"
        f"STOP_FLAG={Config.STOP_FLAG}\n"
        f"TEST_MODE={Config.TEST_MODE}  BOOKING_ENABLED={Config.BOOKING_ENABLED}\n"
        f"STATION_ID={Config.STATION_ID}  DESIRED_BD={Config.DESIRED_BUSINESS_DAYS}"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")
    await update.message.reply_text(HELP)


async def whoami_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Jouw chat ID is: {update.effective_chat.id}")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")
    await update.message.reply_text(_status_line(update.effective_chat.id))


# ------- Notifier (stuurt meldingen sequentieel en annuleerbaar) -------
def make_notifier(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> Callable[[str], None]:
    if chat_id not in notify_locks:
        notify_locks[chat_id] = asyncio.Lock()
    notify_enabled[chat_id] = True
    token = _bump_token(chat_id)

    async def send_async(text: str):
        if not notify_enabled.get(chat_id, True):
            return
        async with notify_locks[chat_id]:
            # token-check: ongeldig maken van oude sends
            if token != run_tokens.get(chat_id):
                return
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await context.bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
            except Exception as e:
                log.error("[notify] Telegram send failed: %s", e)

    def notify(msg: str):
        # Gebruik PTB-application event loop
        try:
            context.application.create_task(send_async(msg))
        except Exception:
            asyncio.get_event_loop().create_task(send_async(msg))

    return notify


# ---------------- Commands ----------------
async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return await update.message.reply_text("🚫 Geen toegang tot deze bot.")
    chat_id = update.effective_chat.id

    # 1) direct stoppen & alle oude meldingen ongeldig maken
    Config.STOP_FLAG = True
    notify_enabled[chat_id] = False
    _bump_token(chat_id)  # invalideer alle nog hangende sends

    # 2) browser hard sluiten (optioneel maar effectief)
    bot = active_bots.get(chat_id)
    if bot:
        try:
            await asyncio.to_thread(bot.close)
        except Exception:
            pass

    # 3) taak annuleren (indien nog actief)
    task = active_tasks.get(chat_id)
    if task and not task.done():
        task.cancel()

    # 4) onmiddellijke feedback
    await update.message.reply_text("⏹️ Stopverzoek ontvangen. Ik rond af…")


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

    # Reset stop-flag + notificaties vóór nieuwe run
    Config.STOP_FLAG = False
    notify_enabled[chat_id] = True
    _bump_token(chat_id)

    # Eén run tegelijk per chat
    old = active_tasks.get(chat_id)
    if old and not old.done():
        return await update.message.reply_text("⏳ Er draait al een run. Gebruik /stop of wacht tot deze klaar is.")

    async def run_flow():
        bot: Optional[AIBVBookingBot] = None
        try:
            active_status[chat_id] = "driver"
            bot = AIBVBookingBot()
            active_bots[chat_id] = bot

            notify = make_notifier(context, chat_id)
            bot.set_notifier(notify)

            # --- alles met Selenium in een thread ---
            await asyncio.to_thread(bot.setup_driver)

            active_status[chat_id] = "login"
            if Config.STOP_FLAG:
                return
            await asyncio.to_thread(bot.login)

            active_status[chat_id] = "voertuig"
            if Config.STOP_FLAG:
                return
            await asyncio.to_thread(bot.select_vehicle, plate, first_reg_date)

            active_status[chat_id] = "station"
            if Config.STOP_FLAG:
                return
            try:
                await asyncio.to_thread(bot.select_station)
            except RuntimeError as e:
                await context.bot.send_message(chat_id=chat_id, text=(
                    f"❌ Kan niet verder: {e}\n(Er is waarschijnlijk al een reservatie voor dit voertuig.)"
                ))
                return

            active_status[chat_id] = "monitor"
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🕑 Monitor gestart. Venster: {Config.DESIRED_BUSINESS_DAYS} werkdagen. "
                    f"Refresh elke {Config.REFRESH_DELAY}s. "
                    f"{'🧪 TEST_MODE: er wordt niet echt geboekt.' if (Config.TEST_MODE or not Config.BOOKING_ENABLED) else '🟢 Boeken ingeschakeld.'}\n"
                    "⏱️ Geen tijdslimiet: ik zoek door tot /stop of succes."
                )
            )

            result = await asyncio.to_thread(bot.monitor_and_book)

            ok = bool(result.get("success")) if isinstance(result, dict) else bool(result)
            if ok:
                label = result.get("slot") if isinstance(result, dict) else ""
                extra = " (niet bevestigd: BOOKING_ENABLED=false)" if (isinstance(result, dict) and result.get("booking_disabled")) else ""
                await context.bot.send_message(chat_id=chat_id, text=f"🎉 Resultaat: ✅ gelukt {label}{extra}")
            else:
                if isinstance(result, dict) and result.get("stopped"):
                    await context.bot.send_message(chat_id=chat_id, text="⏹️ Gestopt op verzoek.")
                else:
                    err = (result or {}).get("error") if isinstance(result, dict) else None
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ Resultaat: niet gelukt. {f'Reden: {err}' if err else ''}")

        except asyncio.CancelledError:
            # nette stop
            raise
        except Exception as e:
            log.exception("Fout in booking runner")
            try:
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Fout: {e}")
            except Exception:
                pass
        finally:
            active_status[chat_id] = "opruimen"
            try:
                if bot:
                    await asyncio.to_thread(bot.close)
            except Exception:
                pass
            active_bots.pop(chat_id, None)
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

    # (optioneel) ping bij opstart naar eerste admin-id — handig om te zien dat polling draait
    try:
        admin_id = int(TELEGRAM_CHAT_IDS[0])
        async def _ping(_app):
            try:
                await _app.bot.send_message(chat_id=admin_id, text="✅ Bot online (polling actief).")
            except Exception as e:
                log.warning("Kon start-ping niet sturen: %s", e)
        app.post_init(_ping)
    except Exception:
        pass

    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("whoami", whoami_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("book", book_cmd))

    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()

