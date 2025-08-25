# selenium_controller.py
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
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    NoSuchWindowException,
)

from webdriver_manager.chrome import ChromeDriverManager

from config import (
    Config,
    is_within_n_business_days,
    AIBV_PLATE,
    AIBV_FIRST_REG_DATE,
    AIBV_JAARLIJKS_RADIO_ID,
)

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

    # ---------------- Driver ----------------
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

        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        opts.add_experimental_option("prefs", prefs)

        chrome_bin = os.environ.get("GOOGLE_CHROME_BIN") or os.environ.get("CHROME_BIN")
        driver_path = os.environ.get("CHROMEDRIVER_PATH")

        if chrome_bin:
            opts.binary_location = chrome_bin

        if driver_path and os.path.exists(driver_path):
            service = ChromeService(executable_path=driver_path)
        else:
            service = ChromeService(ChromeDriverManager().install())

        self.driver = webdriver.Chrome(service=service, options=opts)
        self.driver.set_page_load_timeout(45)
        return self.driver

    # ---------------- Helpers ----------------
    def _stop_requested(self) -> bool:
        return bool(getattr(Config, "STOP_FLAG", False))

    def wait(self, cond, timeout=None):
        try:
            return WebDriverWait(self.driver, timeout or Config.POSTBACK_TIMEOUT).until(cond)
        except NoSuchWindowException:
            if self.switch_to_latest_window():
                return WebDriverWait(self.driver, timeout or Config.POSTBACK_TIMEOUT).until(cond)
            raise

    def wait_dom_idle(self, timeout=Config.POSTBACK_TIMEOUT):
        end = time.time() + timeout
        while time.time() < end:
            try:
                overlay = self._find_overlay()
                state = self.driver.execute_script("return document.readyState")
                if overlay is None and state == "complete":
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def _find_overlay(self):
        try:
            return self.driver.find_element(By.XPATH, "//*[contains(., 'Even geduld')]")
        except NoSuchElementException:
            return None

    def switch_to_latest_window(self, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            try:
                handles = self.driver.window_handles
                if handles:
                    self.driver.switch_to.window(handles[-1])
                    return True
            except NoSuchWindowException:
                pass
            time.sleep(0.2)
        return False

    def type_by_id(self, element_id: str, value: str, timeout: int = 15):
        el = WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((By.ID, element_id))
        )
        el.clear()
        el.click()
        el.send_keys(value)
        return el

    def click_by_id(self, element_id: str, timeout: int = 15):
        el = WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((By.ID, element_id))
        )
        el.click()
        self.wait_dom_idle()
        return el

    # ---------------- Flow ----------------
    def login(self):
        d = self.driver
        d.get(Config.LOGIN_URL)
        self.wait_dom_idle()

        self.type_by_id("txtUser", Config.AIBV_USERNAME)
        self.type_by_id("txtPassWord", Config.AIBV_PASSWORD)

        self.click_by_id("Button1")
        self.wait_dom_idle()

        # Klik "Reservatie aanmaken"
        self.click_by_id("MainContent_cmdReservatieAutokeuringAanmaken")
        self.wait_dom_idle()

        WebDriverWait(d, 15).until(
            EC.presence_of_element_located((By.ID, "MainContent_btnVoertuigToevoegen"))
        )
        return True

    # 🚨 Jaarlijkse flow vervangt oude EU-flow
    def select_eu_vehicle(self):
        """Jaarlijkse/periodieke keuring"""
        assert AIBV_PLATE, "AIBV_PLATE ontbreekt (.env)"
        assert AIBV_FIRST_REG_DATE, "AIBV_FIRST_REG_DATE ontbreekt (.env)"

        self.type_by_id("MainContent_txtPlaat", AIBV_PLATE)
        self.type_by_id("MainContent_txtDatumIndienststelling", AIBV_FIRST_REG_DATE)
        self.click_by_id("MainContent_cmdZoeken")
        self.click_by_id("MainContent_cmdReservatieMaken")
        self.click_by_id("MainContent_cmdVolgendeStap1")
        self.click_by_id(AIBV_JAARLIJKS_RADIO_ID)
        self.click_by_id("MainContent_btnBevestig")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, f"MainContent_rblStation_{Config.STATION_ID}"))
        )
        return True

    def select_station(self):
        self.click_by_id(f"MainContent_rblStation_{Config.STATION_ID}")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "MainContent_lbSelectWeek"))
        )
        self.wait_dom_idle()
        self.filters_initialized = True
        return True

    # ... (rest van week-selectie, slot-collectie, monitor_and_book, book_slot, close)
