#!/usr/bin/env python3
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
f"{'🧪 TEST_MODE: er wordt niet echt geboekt.' if Config.TEST_MODE or not Config.BOOKING_ENABLED else '🟢 Boeken ingeschakeld.'}\n"
f"⏱️ Geen tijdslimiet: ik zoek door tot /stop of succes."
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
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(CommandHandler("whoami", whoami_cmd))
app.add_handler(CommandHandler("status", status_cmd))
app.add_handler(CommandHandler("stop", stop_cmd))
app.add_handler(CommandHandler("book", book_cmd))
app.run_polling()




if __name__ == "__main__":
main()
