#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Eenvoudige end-to-end test voor de AIBVBookingBot.

Gebruik:
  python test_booking.py
  python test_booking.py --plate 1PFE128 --first-reg 17/02/2016

Tip:
  - In TEST_MODE (aanbevolen lokaal) wordt nooit definitief geboekt.
  - Zet BOOKING_ENABLED=false in je .env voor veilige tests.
"""

import os
import sys
import argparse
from selenium_controller import AIBVBookingBot
from config import Config


def parse_args():
    parser = argparse.ArgumentParser(
        description="Lokale test voor AIBVBookingBot (Selenium)."
    )
    parser.add_argument(
        "--plate",
        default=os.getenv("TEST_PLATE", "1PFE128"),
        help="Nummerplaat (bv. 1PFE128).",
    )
    parser.add_argument(
        "--first-reg",
        dest="first_reg",
        default=os.getenv("TEST_FIRST_REG_DATE", "17/02/2016"),
        help="Eerste inschrijvingsdatum in dd/mm/jjjj (bv. 17/02/2016).",
    )
    parser.add_argument(
        "--station-id",
        type=int,
        default=int(os.getenv("STATION_ID", getattr(Config, "STATION_ID", 8))),
        help="Station ID (numeric). Valt terug op Config.STATION_ID of 8.",
    )
    return parser.parse_args()


def pretty_print_result(result: dict):
    success = bool(result.get("success"))
    print("\n— Testresultaat —")
    if success:
        print("✅ Gelukt")
    else:
        print("❌ Niet gelukt")
    # Toon extra context indien aanwezig
    for key in ("error", "message", "slot", "station", "when"):
        if key in result and result[key]:
            print(f"{key}: {result[key]}")


def main():
    args = parse_args()

    print("🤖 AIBV Jaarlijkse BOOKING TEST (lokaal)")
    print(f"TEST_MODE={os.getenv('TEST_MODE', 'true')}  BOOKING_ENABLED={os.getenv('BOOKING_ENABLED', 'false')}")
    print(f"Gebruikte gegevens: plate={args.plate}  first_reg={args.first_reg}  station_id={args.station_id}")

    bot = AIBVBookingBot()

    try:
        bot.setup_driver()
        bot.login()
        # Nieuwe correcte call (bestaat in selenium_controller):
        bot.select_vehicle(args.plate, args.first_reg)

        # Indien jouw implementatie een aparte stationselectie vereist:
        # Sommige versies gebruiken Config.STATION_ID intern; we geven het hier
        # expliciet mee als jouw select_station signature dit ondersteunt.
        try:
            bot.select_station(args.station_id)
        except TypeError:
            # Backwards compat: oudere signature zonder argumenten
            bot.select_station()

        result = bot.monitor_and_book()
        if not isinstance(result, dict):
            # Fallback voor oudere implementaties die True/False teruggeven
            result = {"success": bool(result)}

        pretty_print_result(result)

    finally:
        bot.close()


if __name__ == "__main__":
    # Zorg dat stdout direct flusht voor heldere logs in terminals/CI
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    main()
