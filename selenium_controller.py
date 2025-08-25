import os
import time
import logging
import sys
from datetime import datetime
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

from config import Config, is_within_n_business_days

log = logging.getLogger("AIBV")


class AIBVBookingBot:
    def __init__(self):
        self.driver: Optional[webdriver.Chrome] = None
        self.filters_initialized = False
        self.notify_func = None  # wordt door Telegram-runner gezet

    # ---------------- Driver ----------------
    def setup_driver(self):
        opts = ChromeOptions()

        if Config.TEST_MODE:
            opts.add_argument("--auto-open-devtools-for-tabs")
            opts.add_argument("--window-size=1366,900")
        else:
            opts.add_argument("--headless=new")
            opts.add_argument("--window-size=1366,900")

        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-features=VizDisplayCompositor")
        opts.add_argument("--disable-background-timer-throttling")
        opts.add_argument("--disable-renderer-backgrounding")

        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        opts.add_experimental_option("prefs", prefs)

        chrome_bin = os.environ.get("GOOGLE_CHROME_BIN")
        driver_path = os.environ.get("CHROMEDRIVER_PATH")

        if chrome_bin and driver_path:
            opts.binary_location = chrome_bin
            service = ChromeService(executable_path=driver_path)
        else:
            from webdriver_manager.chrome import ChromeDriverManager
            service = ChromeService(ChromeDriverManager().install())

        self.driver = webdriver.Chrome(service=service, options=opts)
        self.driver.set_page_load_timeout(45)
        return self.driver

    # ---------------- Helpers ----------------
    def _notify(self, msg: str):
        log.info(msg)
        if self.notify_func:
            try:
                self.notify_func(msg)
            except Exception:
                pass

    def _stop_requested(self) -> bool:
        return bool(getattr(Config, "STOP_FLAG", False))

    def wait_dom_idle(self, timeout=20):
        """wacht tot document.readyState = complete en overlay 'Even geduld' weg is"""
        end = time.time() + timeout
        while time.time() < end:
            try:
                state = self.driver.execute_script("return document.readyState")
                if state == "complete":
                    # check of overlay weg is
                    if not self.driver.find_elements(By.XPATH, "//*[contains(., 'Even geduld')]"):
                        return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def click_by_id(self, element_id, timeout=15):
        el = WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((By.ID, element_id))
        )
        el.click()
        self.wait_dom_idle()
        return el

    def type_by_id(self, element_id, value, timeout=15):
        el = WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((By.ID, element_id))
        )
        el.clear()
        el.send_keys(value)
        return el

    # ---------------- Flow ----------------
    def login(self):
        d = self.driver
        self._notify("🔐 Inloggen…")
        d.get(Config.LOGIN_URL)
        self.wait_dom_idle()

        self.fill_login_fields(Config.AIBV_USERNAME, Config.AIBV_PASSWORD)

        self.click_by_id("Button1")

        try:
            WebDriverWait(d, 6).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(.,'Reservatie') or contains(@id,'MainContent_btnVoertuigToevoegen')]")
                )
            )
        except TimeoutException:
            try:
                btn = d.find_element(By.ID, "Button1")
                d.execute_script("arguments[0].click();", btn)
            except Exception:
                pass

        self.wait_dom_idle()

        # Klik "Reservatie aanmaken"
        try:
            self.click_by_id("MainContent_cmdReservatieAutokeuringAanmaken")
        except Exception:
            d.get("https://planning.aibv.be/Reservaties/ReservatieOverzicht.aspx?lang=nl")
            self.wait_dom_idle()
            try:
                btn = WebDriverWait(d, 10).until(
                    EC.element_to_be_clickable((By.ID, "MainContent_cmdReservatieAutokeuringAanmaken"))
                )
                d.execute_script("arguments[0].click();", btn)
            except TimeoutException:
                btn = WebDriverWait(d, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@type='submit' and contains(@value,'Reservatie')]"))
                )
                d.execute_script("arguments[0].click();", btn)

        WebDriverWait(d, 15).until(
            EC.presence_of_element_located((By.ID, "MainContent_btnVoertuigToevoegen"))
        )
        self._notify("✅ Ingelogd en klaar om voertuig te selecteren.")
        return True

    def fill_login_fields(self, username, password):
        self.type_by_id("txtUser", username)
        self.type_by_id("txtPassWord", password)

    def select_vehicle(self, plate: str, first_reg_date: str):
        self._notify("🚗 Voertuig selecteren…")

        plate = plate.replace("-", "").replace(" ", "").upper().strip()
        self.type_by_id("MainContent_txtPlaat", plate)
        self.type_by_id("MainContent_txtDatumIndienststelling", first_reg_date)

        self._notify("🔎 Zoeken naar voertuig…")
        self.click_by_id("MainContent_cmdZoeken")

        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, "MainContent_cmdReservatieMaken"))
        )
        self.click_by_id("MainContent_cmdReservatieMaken")
        self.click_by_id("MainContent_cmdVolgendeStap1")

        self._notify("📋 Keuringstype kiezen…")
        radio = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, Config.AIBV_JAARLIJKS_RADIO_ID))
        )
        radio.click()
        self.click_by_id("MainContent_btnBevestig")
        self._notify("✅ Voertuig en keuringstype bevestigd.")
        return True

    def select_station(self):
        self._notify("🏢 Station selecteren…")
        self.click_by_id(f"MainContent_rblStation_{Config.STATION_ID}")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "MainContent_lbSelectWeek"))
        )
        self.wait_dom_idle()
        self.filters_initialized = True
        self._notify("✅ Station geselecteerd.")
        return True

    # ---------------- Week & Slots ----------------
    def _select_week_value(self, wanted_value: str) -> bool:
        dd = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "MainContent_lbSelectWeek"))
        )
        sel = Select(dd)
        for opt in sel.options:
            if opt.get_attribute("value") == wanted_value:
                opt.click()
                self.wait_dom_idle()
                return True
        return False

    def _get_selected_week_value(self) -> Optional[str]:
        try:
            dd = self.driver.find_element(By.ID, "MainContent_lbSelectWeek")
            sel = Select(dd)
            return sel.first_selected_option.get_attribute("value")
        except Exception:
            return None

    def _ensure_station_selected(self):
        try:
            radio = self.driver.find_element(By.ID, f"MainContent_rblStation_{Config.STATION_ID}")
            if not radio.is_selected():
                radio.click()
                self.wait_dom_idle()
            return True
        except Exception:
            return False

    def _ensure_week_selected(self):
        wanted = Config.get_tomorrow_week_monday_str()
        current = self._get_selected_week_value()
        if current == wanted:
            return True
        return self._select_week_value(wanted)

    def ensure_filters_once(self):
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "MainContent_lbSelectWeek"))
            )
            self._ensure_station_selected()
            self._ensure_week_selected()
            self.filters_initialized = True
        except Exception:
            pass

    def _collect_slots(self):
        slots = []
        now = datetime.now()
        for i in range(1, 8):
            try:
                label_el = self.driver.find_element(By.ID, f"MainContent_LabelDatum{i}")
                label = label_el.text.strip()
            except NoSuchElementException:
                continue
            if not label:
                continue
            day_prefix = label.split()[0].lower()
            if day_prefix not in ("ma", "di", "wo", "do", "vr"):
                continue
            try:
                time_span = self.driver.find_element(By.ID, f"MainContent_rblTijdstip{i}")
            except NoSuchElementException:
                continue
            full_date = time_span.get_attribute("title")
            if not full_date:
                continue
            radios = time_span.find_elements(By.CSS_SELECTOR, "input[type='radio'][id^='MainContent_rblTijdstip']")
            for r in radios:
                try:
                    label_el = r.find_element(By.XPATH, "./following-sibling::label")
                    text_time = label_el.text.strip()
                    dt = datetime.strptime(full_date + " " + text_time, "%d/%m/%Y %H:%M")
                    if dt <= now:
                        continue
                    slots.append((dt, r, f"{full_date} {text_time}"))
                except Exception:
                    continue
        slots.sort(key=lambda x: x[0])
        return slots

    def find_earliest_within_3_business_days(self):
        for dt, radio, label in self._collect_slots():
            if is_within_n_business_days(dt, 3):
                return dt, radio, label
        return None

    # ---------------- Booking / Monitoring ----------------
    def book_slot(self, radio, human_label: str):
        self._notify(f"🧾 Boeken: {human_label}")
        radio.click()
        self.wait_dom_idle()
        try:
            cb = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "MainContent_CheckBoxAlgemeneVoorwaarden"))
            )
            if not cb.is_selected():
                cb.click()
        except TimeoutException:
            pass
        self.click_by_id("MainContent_cmdBevestigen")
        self._notify(f"🎉 Boeking bevestigd: {human_label}")
        return True

    def monitor_and_book(self):
        start = time.time()
        LOG_PERIOD = 300
        next_log_at = start + LOG_PERIOD

        if not self.filters_initialized:
            self.ensure_filters_once()

        while True:
            if self._stop_requested():
                self._notify("⏹️ Gestopt via /stop")
                return {"success": False, "error": "Gestopt via /stop"}

            elapsed = time.time() - start
            if elapsed >= 3600:
                self._notify("⌛ Geen slot binnen 60 min")
                return {"success": False, "error": "Geen slot gevonden"}

            try:
                self._ensure_week_selected()
                found = self.find_earliest_within_3_business_days()
                if found:
                    dt, radio, label = found
                    self._notify(f"✅ Slot gevonden: {label}")
                    if Config.BOOKING_ENABLED:
                        self.book_slot(radio, label)
                        return {"success": True, "slot": label}
                    else:
                        return {"success": True, "slot": label, "booking_disabled": True}

                self.driver.refresh()
                self.wait_dom_idle()
                time.sleep(Config.REFRESH_DELAY)

                if time.time() >= next_log_at:
                    next_log_at += LOG_PERIOD
                    self._notify("⏳ Nog geen slot… blijf zoeken")

            except Exception as e:
                log.warning(f"⚠️ Fout in monitoring: {e}")
                self.driver.refresh()
                self.wait_dom_idle()
                time.sleep(min(5, Config.REFRESH_DELAY * 2))

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass

