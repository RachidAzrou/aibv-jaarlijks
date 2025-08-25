import os
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
        result = bot.monitor_and_book()
        print(result)
    finally:
        bot.close()

if __name__ == "__main__":
    main()
