from selenium_controller import AIBVBookingBot
from config import Config

def main():
    print("🤖 AIBV Jaarlijkse BOOKING TEST")
    bot = AIBVBookingBot()
    try:
        bot.setup_driver()
        bot.login()
        bot.select_eu_vehicle()
        bot.select_station()
        ok = bot.monitor_and_book()  # blijft refreshen tot slot, dan boeken (indien BOOKING_ENABLED=true)
        print("Resultaat:", "✅ gelukt" if ok else "❌ niet gelukt")
    finally:
        bot.close()

if __name__ == "__main__":
    main()
