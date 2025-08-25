import os
import time
import logging
import sys
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    NoSuchWindowException,
)

from webdriver_manager.chrome import ChromeDriverManager

from config import Config, is_within_n_business_days, AIBV_JAARLIJKS_RADIO_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("AIBV")

class AIBVBookingBot:
    def __init__(self):
        self.driver = None
        self.filters_initialized = False

    # ---------- driver ----------
    def setup_driver(self):
        opts = ChromeOptions()
        if Config.TEST_MODE:
            opts.add_argument("--window-size=1366,900")
        else:
            opts.add_argument("--headless=new")
            opts.add_argument("--window-size=1366,900")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")

        chrome_bin = os.environ.get("GOOGLE_CHROME_BIN") or os.environ.get("CHROME_BIN")
        if chrome_bin:
            opts.binary_location = chrome_bin

        driver_path = os.environ.get("CHROMEDRIVER_PATH")
        if driver_path and os.path.exists(driver_path):
            service = ChromeService(executable_path=driver_path)
        else:
            service = ChromeService(ChromeDriverManager().install())

        self.driver = webdriver.Chrome(service=service, options=opts)
        self.driver.set_page_load_timeout(60)
        return self.driver

    # ---------- helpers ----------
    def wait_dom_idle(self, timeout=Config.POSTBACK_TIMEOUT):
        end = time.time() + timeout
        while time.time() < end:
            try:
                state = self.driver.execute_script("return document.readyState")
                if state == "complete":
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def type_by_id(self, element_id: str, value: str, timeout: int = 20):
        el = WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((By.ID, element_id))
        )
        el.clear()
        el.send_keys(value)
        return el

    def safe_click_by_id(self, element_id: str, timeout: int = 25):
        el = WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((By.ID, element_id))
        )
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        except Exception:
            pass
        try:
            el.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", el)
        self.wait_dom_idle()
        return el

    # ---------- flow ----------
    def login(self):
        d = self.driver
        d.get(Config.LOGIN_URL)
        self.wait_dom_idle()
        self.type_by_id("txtUser", Config.AIBV_USERNAME)
        self.type_by_id("txtPassWord", Config.AIBV_PASSWORD)
        self.safe_click_by_id("Button1")
        self.wait_dom_idle()
        self.safe_click_by_id("MainContent_cmdReservatieAutokeuringAanmaken")
        self.wait_dom_idle()
        WebDriverWait(d, 20).until(
            EC.presence_of_element_located((By.ID, "MainContent_btnVoertuigToevoegen"))
        )
        return True

    def select_eu_vehicle(self, plate: str, first_reg_date: str):
        """Nummerplaat + datum eerste inschrijving ingeven, daarna jaarlijkse flow."""
        # nummerplaat normaliseren: geen streepjes/spaties
        plate = plate.replace("-", "").replace(" ", "")
        if not plate or not first_reg_date:
            raise ValueError("Plate en datum verplicht")

        d = self.driver
        try:
            d.find_element(By.ID, "MainContent_txtPlaat")
        except NoSuchElementException:
            try:
                self.safe_click_by_id("MainContent_btnVoertuigToevoegen", timeout=25)
            except Exception:
                pass

        WebDriverWait(d, 30).until(EC.presence_of_element_located((By.ID, "MainContent_txtPlaat")))
        self.type_by_id("MainContent_txtPlaat", plate)
        self.type_by_id("MainContent_txtDatumIndienststelling", first_reg_date)

        self.safe_click_by_id("MainContent_cmdZoeken", timeout=30)
        self.safe_click_by_id("MainContent_cmdReservatieMaken", timeout=25)
        self.safe_click_by_id("MainContent_cmdVolgendeStap1", timeout=25)
        self.safe_click_by_id(AIBV_JAARLIJKS_RADIO_ID, timeout=20)
        self.safe_click_by_id("MainContent_btnBevestig", timeout=20)

        WebDriverWait(d, 30).until(
            EC.presence_of_element_located((By.ID, f"MainContent_rblStation_{Config.STATION_ID}"))
        )
        return True

    # (select_station, _collect_slots, find_earliest_within_3_business_days,
    #  book_slot, monitor_and_book, close blijven hetzelfde als in de vorige versie)
    # ...
