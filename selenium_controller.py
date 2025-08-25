import os
import time
import logging
import sys
from datetime import datetime, timedelta

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

    # ---------------- Helpers ----------------
    def _stop_requested(self) -> bool:
        return bool(getattr(Config, "STOP_FLAG", False))

    def wait(self, cond, timeout=None):
        """Generic explicit wait with window recovery."""
        try:
            return WebDriverWait(self.driver, timeout or Config.POSTBACK_TIMEOUT).until(cond)
        except NoSuchWindowException:
            if self.switch_to_latest_window():
                return WebDriverWait(self.driver, timeout or Config.POSTBACK_TIMEOUT).until(cond)
            raise

    def wait_dom_idle(self, timeout=Config.POSTBACK_TIMEOUT):
        """Wacht tot document klaar is."""
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

    # ------- input helpers -------
    def type_by_id(self, element_id: str, value: str, timeout: int = 20):
        el = WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((By.ID, element_id))
        )
        el.clear()
        el.click()
        el.send_keys(value)
        return el

    def click_by_id(self, element_id: str, timeout: int = 20):
        el = WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((By.ID, element_id))
        )
        el.click()
        self.wait_dom_idle()
        return el

    def safe_click_by_id(self, element_id: str, timeout: int = 25):
        """Scroll → normal click → JS click fallback → wait DOM idle."""
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

    # ---------------- Flow ----------------
    def login(self):
        d = self.driver
        d.get(Config.LOGIN_URL)
        self.wait_dom_idle()

        # login
        self.type_by_id("txtUser", Config.AIBV_USERNAME)
        self.type_by_id("txtPassWord", Config.AIBV_PASSWORD)
        self.click_by_id("Button1")
        self.wait_dom_idle()

        # naar 'Reservatie aanmaken'
        self.safe_click_by_id("MainContent_cmdReservatieAutokeuringAanmaken")
        self.wait_dom_idle()

        # wachten op pagina met 'Voertuig toevoegen' (of direct invoervelden)
        WebDriverWait(d, 20).until(
            EC.presence_of_element_located((By.ID, "MainContent_btnVoertuigToevoegen"))
        )
        return True

    # 🚨 Jaarlijkse/periodieke flow (vervangt oude EU-flow)
    def select_eu_vehicle(self):
        """
        Jaarlijkse/periodieke keuring:
        - evtl. 'Voertuig toevoegen'
        - nummerplaat + datum 1e inschrijving invullen
        - Zoeken → Reservatie aanmaken → Volgende
        - Radiobutton periodieke/jaarlijkse → Volgende
        Daarna verschijnt de stationkeuze.
        """
        assert AIBV_PLATE, "AIBV_PLATE ontbreekt (.env)"
        assert AIBV_FIRST_REG_DATE, "AIBV_FIRST_REG_DATE ontbreekt (.env) (dd/mm/jjjj)"

        d = self.driver

        # Zorg dat we op de juiste stap zitten
        try:
            d.find_element(By.ID, "MainContent_txtPlaat")
        except NoSuchElementException:
            try:
                self.safe_click_by_id("MainContent_btnVoertuigToevoegen", timeout=25)
            except Exception:
                pass

        WebDriverWait(d, 30).until(
            EC.presence_of_element_located((By.ID, "MainContent_txtPlaat"))
        )

        # Vul velden
        self.type_by_id("MainContent_txtPlaat", AIBV_PLATE)
        self.type_by_id("MainContent_txtDatumIndienststelling", AIBV_FIRST_REG_DATE)

        # Zoek voertuig
        self.safe_click_by_id("MainContent_cmdZoeken", timeout=30)

        # Reservatie aanmaken
        WebDriverWait(d, 30).until(
            EC.presence_of_element_located((By.ID, "MainContent_cmdReservatieMaken"))
        )
        self.safe_click_by_id("MainContent_cmdReservatieMaken", timeout=25)

        # Volgende
        self.safe_click_by_id("MainContent_cmdVolgendeStap1", timeout=25)

        # Radiobutton + Volgende
        WebDriverWait(d, 30).until(
            EC.presence_of_element_located((By.ID, AIBV_JAARLIJKS_RADIO_ID))
        )
        self.safe_click_by_id(AIBV_JAARLIJKS_RADIO_ID, timeout=20)
        self.safe_click_by_id("MainContent_btnBevestig", timeout=20)

        # Stationlijst zichtbaar
        WebDriverWait(d, 30).until(
            EC.presence_of_element_located((By.ID, f"MainContent_rblStation_{Config.STATION_ID}"))
        )
        return True

    def select_station(self):
        # Station selecteren
        self.safe_click_by_id(f"MainContent_rblStation_{Config.STATION_ID}", timeout=20)

        # Week-dropdown aanwezig
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "MainContent_lbSelectWeek"))
        )
        self.wait_dom_idle()

        # Zet week op "week van morgen"
        self.ensure_filters_once()

        self.filters_initialized = True
        return True

    # ---------------- Week/filters ----------------
    def _get_week_options(self):
        """Geef (Select, [(value, text), ...]) terug."""
        dd = self.driver.find_element(By.ID, "MainContent_lbSelectWeek")
        sel = Select(dd)
        opts = [(o.get_attribute("value"), o.text.strip()) for o in sel.options]
        return sel, opts

    def ensure_filters_once(self):
        """Selecteer de week waarin 'morgen' valt, eenmaal na stationselectie."""
        try:
            sel, opts = self._get_week_options()
        except Exception:
            return

        tomorrow = datetime.now() + timedelta(days=1)
        target_ddmm = tomorrow.strftime("%d/%m")

        chosen_value = None
        for val, txt in opts:
            if target_ddmm in txt:
                chosen_value = val
                break

        if chosen_value is None and opts:
            chosen_value = opts[0][0]

        try:
            sel.select_by_value(chosen_value)
            self.wait_dom_idle()
        except Exception:
            try:
                sel.select_by_index(0)
                self.wait_dom_idle()
            except Exception:
                pass

    def _ensure_station_selected(self) -> bool:
        """Herbevestig station na refresh indien nodig."""
        try:
            radio = self.driver.find_element(By.ID, f"MainContent_rblStation_{Config.STATION_ID}")
            checked = self.driver.execute_script("return arguments[0].checked === true;", radio)
            if not checked:
                radio.click()
                self.wait_dom_idle()
            return True
        except Exception:
            return False

    # ---------------- Slot scraping/booking ----------------
    def _collect_slots(self):
        """
        Leest de dag/timeslot radio's op de pagina.
        Verwacht IDs zoals:
          - MainContent_LabelDatum{i}
          - MainContent_rblTijdstip{i} met <label><input type="radio">
        Retourneert lijst van tuples (datetime, radio_id, label_text).
        """
        results = []
        for i in range(1, 8):  # tot 7 dagkolommen
            # daglabel
            try:
                label_el = self.driver.find_element(By.ID, f"MainContent_LabelDatum{i}")
                label = label_el.text.strip()  # bijv "wo 10/09"
            except NoSuchElementException:
                continue
            if not label:
                continue

            day_prefix = label.split()[0].lower()  # ma/di/wo/do/vr/za/zo
            if day_prefix not in ("ma", "di", "wo", "do", "vr"):
                continue  # weekend overslaan

            # timeslots in deze kolom
            try:
                time_span = self.driver.find_element(By.ID, f"MainContent_rblTijdstip{i}")
                labels = time_span.find_elements(By.TAG_NAME, "label")
            except NoSuchElementException:
                continue

            for lb in labels:
                txt = lb.text.strip()  # bijv "08:40"
                if not txt:
                    continue
                # radio input id ophalen
                try:
                    input_el = lb.find_element(By.TAG_NAME, "input")
                    rid = input_el.get_attribute("id")
                except Exception:
                    rid = None

                # Datum bepalen (site toont dd/mm); we reconstrueren jaar uit huidige week
                try:
                    _, ddmm = label.split()
                    day = datetime.strptime(ddmm, "%d/%m").replace(year=datetime.now().year)
                    slot_dt = datetime.strptime(txt, "%H:%M")
                    dt = day.replace(hour=slot_dt.hour, minute=slot_dt.minute)
                except Exception:
                    dt = None

                results.append((dt, rid, f"{label} {txt}"))
        return results

    def find_earliest_within_3_business_days(self):
        """Zoek de vroegste weekdag-slot binnen 3 werkdagen."""
        slots = self._collect_slots()
        best = None
        for (dt, rid, label) in slots:
            if not dt:
                continue
            if is_within_n_business_days(dt, 3):
                if best is None or dt < best[0]:
                    best = (dt, rid, label)
        return best

    def book_slot(self, radio_id: str) -> bool:
        """Klik het timeslot en bevestig."""
        try:
            self.safe_click_by_id(radio_id)
        except Exception:
            return False

        # bevestig-knoppen (afhankelijk van site verschillen de ids/volgorde)
        for btn_id in ("MainContent_btnBevestig", "MainContent_cmdVolgendeStap2", "MainContent_btnFinaliseer"):
            try:
                self.safe_click_by_id(btn_id, timeout=15)
            except Exception:
                pass

        return True

    def monitor_and_book(self) -> bool:
        """
        Refresh-loop: blijf zoeken tot er een slot binnen 3 werkdagen is gevonden.
        - Als BOOKING_ENABLED=true → boek en stop.
        - Als BOOKING_ENABLED=false → meld gevonden en stop (zoals in je afsprakenrobot-loop).
        """
        start = time.time()

        # Eénmaal de juiste week zetten als dat nog niet gebeurde
        try:
            if not self.filters_initialized:
                self.ensure_filters_once()
                self.filters_initialized = True
        except Exception:
            pass

        while time.time() - start < Config.MONITOR_MAX_SECONDS:
            if self._stop_requested():
                log.info("Stopverzoek ontvangen; beëindig monitoring.")
                return False

            # Zekerheid: station geselecteerd houden
            try:
                self._ensure_station_selected()
            except Exception:
                pass

            # Sloten lezen
            best = self.find_earliest_within_3_business_days()
            if best:
                dt, radio_id, label = best
                log.info(f"🎯 Kandidaten-slot binnen 3 werkdagen: {label}")

                if Config.BOOKING_ENABLED and radio_id:
                    ok = self.book_slot(radio_id)
                    log.info(f"🧾 Boeking {'gelukt' if ok else 'mislukt'} voor {label}")
                    return bool(ok)
                else:
                    log.info("BOOKING_ENABLED=false → slot gevonden, niet geboekt (stoppen).")
                    return True

            # Geen slot → refresh en opnieuw
            try:
                self.driver.refresh()
                self.wait_dom_idle()
            except Exception as e:
                log.warning(f"Refresh-fout: {e}")

            time.sleep(Config.REFRESH_DELAY)

        log.info("⏳ MONITOR_MAX_SECONDS bereikt, stoppen (niets gevonden).")
        return False

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
