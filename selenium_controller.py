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

from config import (
    Config,
    is_within_n_business_days,
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
        """
        Start ChromeDriver.
        - Op Heroku: gebruikt GOOGLE_CHROME_BIN + CHROMEDRIVER_PATH (altijd matching versie).
        - Lokaal: valt terug op webdriver_manager.
        """
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
        opts.add_argument("--disable-features=VizDisplayCompositor")
        opts.add_argument("--disable-renderer-backgrounding")
        opts.add_argument("--disable-background-timer-throttling")

        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        opts.add_experimental_option("prefs", prefs)

        chrome_bin = os.environ.get("GOOGLE_CHROME_BIN")
        driver_path = os.environ.get("CHROMEDRIVER_PATH")

        if chrome_bin and driver_path:
            # ✅ Heroku: gebruik buildpack binaries
            opts.binary_location = chrome_bin
            service = ChromeService(executable_path=driver_path)
        else:
            # ✅ Lokaal fallback
            from webdriver_manager.chrome import ChromeDriverManager
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
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        except Exception:
            pass
        for _ in range(2):
            try:
                el.clear()
                el.click()
                el.send_keys(value)
                break
            except StaleElementReferenceException:
                el = WebDriverWait(self.driver, timeout).until(
                    EC.visibility_of_element_located((By.ID, element_id))
                )
        try:
            self.driver.execute_script(
                "var e=document.getElementById(arguments[0]);"
                "if(e){e.dispatchEvent(new Event('input',{bubbles:true}));"
                "e.dispatchEvent(new Event('change',{bubbles:true}));}", element_id
            )
        except Exception:
            pass
        return el

    def click_by_id(self, element_id: str, timeout: int = 15):
        el = WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((By.ID, element_id))
        )
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        except Exception:
            pass
        try:
            el.click()
        except StaleElementReferenceException:
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
        self.switch_to_latest_window(timeout=8)
        self.wait_dom_idle()
        return True

    def select_eu_vehicle(self, plate: str, first_reg_date: str):
        # nummerplaat (zonder streepjes)
        plate = plate.replace("-", "").strip().upper()
        self.type_by_id("MainContent_txtPlaat", plate)
        self.type_by_id("MainContent_txtDatumIndienststelling", first_reg_date)
        self.click_by_id("MainContent_cmdZoeken")
        self.click_by_id("MainContent_cmdReservatieMaken")
        self.click_by_id("MainContent_cmdVolgendeStap1")
        self.driver.find_element(By.ID, AIBV_JAARLIJKS_RADIO_ID).click()
        self.click_by_id("MainContent_btnBevestig")
        return True

    def select_station(self):
        self.click_by_id(f"MainContent_rblStation_{Config.STATION_ID}")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "MainContent_lbSelectWeek"))
        )
        self.wait_dom_idle()
        self.filters_initialized = True
        return True

    # ---------------- Slots ----------------
    def _select_week_value(self, wanted_value: str) -> bool:
        dd = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "MainContent_lbSelectWeek"))
        )
        sel = Select(dd)
        for opt in sel.options:
            if opt.get_attribute("value") == wanted_value:
                try:
                    self.driver.execute_script("arguments[0].selected = true;", opt)
                except Exception:
                    pass
                opt.click()
                self.wait_dom_idle()
                return True
        return False

    def _get_selected_week_value(self) -> str | None:
        try:
            dd = self.driver.find_element(By.ID, "MainContent_lbSelectWeek")
            sel = Select(dd)
            return sel.first_selected_option.get_attribute("value")
        except Exception:
            return None

    def _ensure_station_selected(self) -> bool:
        try:
            radio = self.driver.find_element(By.ID, f"MainContent_rblStation_{Config.STATION_ID}")
            checked = self.driver.execute_script("return arguments[0].checked === true;", radio)
            if not checked:
                radio.click()
                self.wait_dom_idle()
            return True
        except Exception:
            return False

    def _ensure_week_selected(self) -> bool:
        wanted = Config.get_tomorrow_week_monday_str()
        current = self._get_selected_week_value()
        if current == wanted:
            return True
        return self._select_week_value(wanted)

    def ensure_filters_once(self) -> None:
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "MainContent_lbSelectWeek"))
            )
            ok_station = self._ensure_station_selected()
            ok_week = self._ensure_week_selected()
            if ok_station and ok_week:
                self.filters_initialized = True
        except Exception:
            pass

    def find_earliest_within_3_business_days(self):
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
        for dt, radio, label in slots:
            if is_within_n_business_days(dt, 3):
                return dt, radio, label
        return None

    # ---------------- Booking / Monitoring ----------------
    def book_slot(self, radio, human_label: str):
        try:
            radio.click()
        except StaleElementReferenceException:
            radio = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, radio.get_attribute("id")))
            )
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
        log.info(f"🎉 BOEKING: {human_label}")
        return True

    def monitor_and_book(self):
        start = time.time()
        while True:
            if self._stop_requested():
                log.info("⏹️ Gestopt door gebruiker (/stop).")
                return {"success": False, "error": "Gestopt via /stop"}
            elapsed = time.time() - start
            if elapsed >= Config.MONITOR_MAX_SECONDS:
                return {"success": False, "error": "Geen slot gevonden binnen tijdslimiet."}
            try:
                self.ensure_filters_once()
                found = self.find_earliest_within_3_business_days()
                if found:
                    dt, radio, label = found
                    if Config.BOOKING_ENABLED:
                        self.book_slot(radio, label)
                        return {"success": True, "slot": label}
                    else:
                        return {"success": True, "slot": label, "booking_disabled": True}
                self.driver.refresh()
                self.wait_dom_idle()
                time.sleep(Config.REFRESH_DELAY)
            except Exception as e:
                log.warning(f"⚠️  Monitoring fout: {e}")
                self.driver.refresh()
                self.wait_dom_idle()
                time.sleep(min(5, Config.REFRESH_DELAY * 2))

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
