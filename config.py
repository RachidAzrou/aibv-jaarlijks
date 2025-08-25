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
AIBV_JAARLIJKS_RADIO_ID = os.environ.get(
    "AIBV_JAARLIJKS_RADIO_ID",
    "MainContent_f3516e7a-4a45-4df8-8043-643923a65495"  # default uit jouw HTML
)

# Station-ID (numeriek suffix uit de HTML, bv. 8 voor Montignies-sur-Sambre)
STATION_ID = int(os.environ.get("STATION_ID", "8"))

# ---------------- Behavior ----------------
IS_HEROKU = bool(os.environ.get("GOOGLE_CHROME_BIN"))

TEST_MODE = os.environ.get("TEST_MODE", "true").lower() == "true"
if IS_HEROKU:
    TEST_MODE = False  # op Heroku altijd headless

BOOKING_ENABLED = os.environ.get("BOOKING_ENABLED", "false").lower() == "true"

REFRESH_DELAY = int(os.environ.get("REFRESH_DELAY", "15"))  # seconden
MONITOR_MAX_SECONDS = int(os.environ.get("MONITOR_MAX_SECONDS", "3600"))  # max 1 uur
POSTBACK_TIMEOUT = 20


# ---------------- Helpers ----------------
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


# ---------------- Config Class ----------------
class Config:
    TELEGRAM_TOKEN = TELEGRAM_TOKEN
    TELEGRAM_CHAT_IDS = TELEGRAM_CHAT_IDS
    LOGIN_URL = LOGIN_URL
    AIBV_USERNAME = AIBV_USERNAME
    AIBV_PASSWORD = AIBV_PASSWORD
    AIBV_JAARLIJKS_RADIO_ID = AIBV_JAARLIJKS_RADIO_ID
    STATION_ID = STATION_ID
    TEST_MODE = TEST_MODE
    BOOKING_ENABLED = BOOKING_ENABLED
    REFRESH_DELAY = REFRESH_DELAY
    MONITOR_MAX_SECONDS = MONITOR_MAX_SECONDS
    POSTBACK_TIMEOUT = POSTBACK_TIMEOUT
    STOP_FLAG = False

    get_tomorrow_week_monday_str = staticmethod(get_tomorrow_week_monday_str)
    is_within_n_business_days = staticmethod(is_within_n_business_days)


# Debug output bij start
print(
    f"[CONFIG] TEST_MODE={Config.TEST_MODE} BOOKING_ENABLED={Config.BOOKING_ENABLED} "
    f"STATION_ID={Config.STATION_ID} TELEGRAM_CHAT_IDS={Config.TELEGRAM_CHAT_IDS}"
)
