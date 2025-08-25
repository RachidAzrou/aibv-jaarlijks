import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ---------------- Telegram ----------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_IDS = [
    cid.strip()
    for cid in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",")
    if cid.strip()
]

# ---------------- AIBV ----------------
LOGIN_URL = "https://planning.aibv.be/Reservaties/Login.aspx"
AIBV_USERNAME = os.environ.get("AIBV_USERNAME", "")
AIBV_PASSWORD = os.environ.get("AIBV_PASSWORD", "")

# ID van de radiobutton voor jaarlijkse/periodieke keuring
# ⚠️ controleer of dit ID klopt in de HTML van de keuringstypepagina
AIBV_JAARLIJKS_RADIO_ID = "MainContent_f3516e7a-4a45-4df8-8043-643923a65495"

# Station-ID (numeriek suffix uit de HTML)
STATION_ID = int(os.environ.get("STATION_ID", "0"))

# ---------------- Behavior ----------------
# Op Heroku altijd headless (TEST_MODE wordt geforceerd op False)
IS_HEROKU = bool(os.environ.get("GOOGLE_CHROME_BIN"))
TEST_MODE = os.environ.get("TEST_MODE", "true").lower() == "true"
if IS_HEROKU:
    TEST_MODE = False

BOOKING_ENABLED = os.environ.get("BOOKING_ENABLED", "false").lower() == "true"

# Refresh loop instellingen
REFRESH_DELAY = int(os.environ.get("REFRESH_DELAY", "15"))  # seconden
MONITOR_MAX_SECONDS = int(os.environ.get("MONITOR_MAX_SECONDS", "3600"))  # max 1 uur
POSTBACK_TIMEOUT = 20

# ---------------- Helpers ----------------
WEEKDAY_NAMES_NL = ["ma", "di", "wo", "do", "vr", "za", "zo"]


def get_tomorrow_week_monday_str():
    """Return de 'week value' string van maandag van de week van morgen."""
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    monday = tomorrow - timedelta(days=tomorrow.weekday())
    return monday.strftime("%d/%m/%Y")


def is_within_n_business_days(dt: datetime, n: int) -> bool:
    """Controleer of datetime dt binnen n werkdagen vanaf nu valt."""
    now = datetime.now()
    days = 0
    current = now
    while days < n:
        current += timedelta(days=1)
        if current.weekday() < 5:  # ma-vr
            days += 1
    return dt <= current


# Debug output bij start
print(
    f"[CONFIG] TEST_MODE={TEST_MODE} BOOKING_ENABLED={BOOKING_ENABLED} "
    f"STATION_ID={STATION_ID} TELEGRAM_CHAT_IDS={TELEGRAM_CHAT_IDS}"
)
