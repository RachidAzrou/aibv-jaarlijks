#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
from typing import Optional, Callable, List

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

from config import Config

log = logging.getLogger("AIBV-Selenium")


class AIBVBookingBot:
    """
    End-to-end flow controller voor AIBV:
      - driver opzetten (Heroku + lokaal)
      - inloggen
      - voertuig selecteren
      - station/product selecteren
      - slots monitoren en (optioneel) bevestigen
    Alle user-facing meldingen gaan via self._notify(...) (wordt door Telegram-runner gezet).
    """

    def __init__(self):
        self.driver: Optional[webdriver.Chrome] = None
        self.notify_func: Optional[Callable[[str], None]] = None

    # ---------------- Driver ----------------
    def setup_driver(self):
        """Maak een Chrome-driver klaar voor Heroku (headless) of lokaal."""
        opts = ChromeOptions()

        # Heroku/new headless (stabieler)
        if Config.TEST_MODE:
            opts.add_argument("--window-size=1366,900")
        else:
            opts.add_argument("--headless=new")
            opts.add_argument("--window-size=1366,900")

        # Stabiliteit flags
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-features=VizDisplayCompositor")
        opts.add_argument("--disable-background-timer-throttling")
        opts.add_argument("--disable-renderer-backgrounding")

        # Geen password prompts
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        opts.add_experimental_option("prefs", prefs)

        # Heroku buildpacks variabelen (indien aanwezig)
        chrome_bin = os.environ.get("GOOGLE_CHROME_BIN") or os.environ.get("CHROME_BIN")
        driver_path = os.environ.get("CHROMEDRIVER_PATH")

        if chrome_bin:
            opts.binary_location = chrome_bin

        if driver_path and os.path.exists(driver_path):
            service = ChromeService(executable_path=driver_path)
        else:
            # Lokaal of fallback
            from webdriver_manager.chrome import ChromeDriverManager
            service = ChromeService(ChromeDriverManager().install())

        self.driver = webdriver.Chrome(service=service, options=opts)
        self.driver.set_page_load_timeout(60)
        return self.driver

    # ---------------- Notifier ----------------
    def set_notifier(self, fn: Callable[[str], None]):
        self.notify_func = fn

    def _notify(self, msg: str):
        try:
            if self.notify_func:
                self.notify_func(msg)
        except Exception:
            pass

    # ---------------- Helpers ----------------
    def wait_dom_idle(self, timeout=20):
        WebDriverWait(self.driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

    def click_by_id(self, element_id, timeout=20):
        el = WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((By.ID, element_id))
        )
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        except Exception:
            pass
        el.click()
        self.wait_dom_idle()
        return el

    def type_by_id(self, element_id, value, timeout=20):
        el = WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((By.ID, element_id))
        )
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        except Exception:
            pass
        el.clear()
        el.send_keys(value)
        return el

    # ---------------- Error detectie ----------------
    ERROR_XPATHS: List[str] = [
        "//*[@id='MainContent_ErrorLabel']",
        "//*[@id='MainContent_pnlErrorMessage']//span",
        "//*[contains(@id,'Error') and not(self::script)][not(self::style)]",
        "//*[contains(@class,'error') and not(self::script)][not(self::style)]",
        "//*[contains(normalize-space(.), 'Een dubbele reservatie')]",
        "//*[contains(normalize-space(.), 'dubbele reservatie')]",
        "//*[contains(normalize-space(.), 'reeds een reservatie')]",
        "//*[contains(normalize-space(.), 'niet toegestaan')]",
    ]

    def _find_error_text(self) -> Optional[str]:
        d = self.driver
        for xp in self.ERROR_XPATHS:
            try:
                el = d.find_element(By.XPATH, xp)
                if el and el.is_displayed():
                    txt = el.text.strip()
                    if txt:
                        return txt
            except Exception:
                pass
        return None

    # ---------------- Cookie banner ----------------
    def _dismiss_cookies(self):
        d = self.driver
        candidates = [
            # veel voorkomende knoppen/labels
            "//button[contains(., 'Akkoord')]",
            "//button[contains(., 'Accepteer')]",
            "//button[contains(., 'Accept')]",
            "//button[contains(., 'OK')]",
            "//input[@type='button' and contains(@value,'Akkoord')]",
            "//input[@type='submit' and contains(@value,'Akkoord')]",
        ]
        for xp in candidates:
            try:
                el = WebDriverWait(d, 2).until(EC.element_to_be_clickable((By.XPATH, xp)))
                d.execute_script("arguments[0].click();", el)
                time.sleep(0.2)
                return True
            except Exception:
                continue
        return False

    # ---------------- Login ----------------
    def fill_login_fields(self, username, password):
        d = self.driver
        # username
        try:
            self.type_by_id("txtUser", username)
        except Exception:
            el = WebDriverWait(d, 15).until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//input[@type='text' or @name='txtUser' or contains(@id,'User')][1]")
                )
            )
            el.clear()
            el.send_keys(username)
        # password
        try:
            self.type_by_id("txtPassWord", password)
        except Exception:
            el = WebDriverWait(d, 15).until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//input[@type='password' or @name='txtPassWord' or contains(@id,'Pass')][1]")
                )
            )
            el.clear()
            el.send_keys(password)

    def login(self):
        d = self.driver
        self._notify("🔐 Inloggen…")
        d.get(Config.LOGIN_URL)
        self.wait_dom_idle()

        # cookie banner wegklikken indien aanwezig
        try:
            self._dismiss_cookies()
        except Exception:
            pass

        # velden invullen en submitten
        self.fill_login_fields(Config.AIBV_USERNAME, Config.AIBV_PASSWORD)

        # klik op login (meerdere mogelijke selectors)
        clicked = False
        for locator in [
            (By.ID, "Button1"),
            (By.XPATH, "//button[contains(., 'Login') or contains(., 'Aanmelden') or contains(@id,'Button')]"),
            (By.XPATH, "//input[@type='submit' and (contains(@value,'Login') or contains(@value,'Aanmelden'))]"),
        ]:
            try:
                btn = WebDriverWait(d, 10).until(EC.element_to_be_clickable(locator))
                d.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                d.execute_script("arguments[0].click();", btn)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            raise TimeoutException("Kon de login-knop niet vinden/klikken (mogelijk gewijzigde pagina)")

        # wachten op success/fout
        try:
            WebDriverWait(d, 20).until(
                lambda drv: (
                    drv.find_elements(By.ID, "MainContent_btnVoertuigToevoegen")
                    or drv.find_elements(By.XPATH, "//*[contains(.,'Reservatie')]")
                    or self._find_error_text() is not None
                )
            )
        except TimeoutException:
            raise TimeoutException("Inloggen lijkt niet te voltooien (timeout). Controleer credentials of cookie-banner.")

        err = self._find_error_text()
        if err:
            raise RuntimeError(f"Login mislukt: {err}")

        WebDriverWait(d, 20).until(
            EC.presence_of_element_located((By.ID, "MainContent_btnVoertuigToevoegen"))
        )
        self._notify("✅ Ingelogd en klaar om voertuig te selecteren.")
        return True

    # ---------------- Flow-stappen ----------------
    def select_vehicle(self, plate: str, first_reg_date_str: str):
        self._notify(f"🚗 Voertuig selecteren: {plate} / {first_reg_date_str}")
        d = self.driver

        self.click_by_id("MainContent_btnVoertuigToevoegen", timeout=30)
        self.wait_dom_idle()

        self.type_by_id("MainContent_txtNummerplaat", plate, timeout=30)
        self.type_by_id("MainContent_txtDatumEersteInschrijving", first_reg_date_str, timeout=30)
        self.click_by_id("MainContent_cmdZoekVoertuig", timeout=30)

        WebDriverWait(d, 30).until(
            EC.presence_of_element_located((By.ID, "MainContent_grdVoertuigen"))
        )
        # Kies eerste resultaat
        try:
            row = WebDriverWait(d, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//table[@id='MainContent_grdVoertuigen']//tr[td]/td/a"))
            )
            d.execute_script("arguments[0].click();", row)
        except TimeoutException:
            raise RuntimeError("Geen voertuigresultaten gevonden voor de ingegeven gegevens.")

        self.wait_dom_idle()
        self._notify("✅ Voertuig geselecteerd.")

    def select_station(self):
        self._notify("🏢 Station selecteren…")
        d = self.driver

        # Station
        try:
            sel = WebDriverWait(d, 30).until(
                EC.presence_of_element_located((By.ID, "MainContent_ddlStations"))
            )
            Select(sel).select_by_value(str(Config.STATION_ID))
        except Exception:
            raise RuntimeError("Stationselectie mislukt — controleer STATION_ID in env.")

        # Product (bv. B-keuring)
        try:
            sel = WebDriverWait(d, 30).until(
                EC.presence_of_element_located((By.ID, "MainContent_ddlProduct"))
            )
            # Pas aan indien ander product nodig is
            Select(sel).select_by_value("B")
        except Exception:
            raise RuntimeError("Productselectie mislukt — id 'B' niet gevonden.")

        # Doorgaan naar kalender
        for locator in [
            (By.ID, "MainContent_cmdReservatieAutokeuringAanmaken"),
            (By.XPATH, "//input[@type='submit' and contains(@value,'Reservatie')]"),
        ]:
            try:
                btn = WebDriverWait(d, 10).until(EC.element_to_be_clickable(locator))
                d.execute_script("arguments[0].click();", btn)
                break
            except Exception:
                continue

        # Wachten tot de kalender/volgende pagina is geladen (hier: we zien de 'VoertuigToevoegen' knop vaak terug)
        WebDriverWait(d, 20).until(
            EC.presence_of_element_located((By.ID, "MainContent_btnVoertuigToevoegen"))
        )
        self._notify("✅ Station geselecteerd.")

    # ---------------- Monitor & boek ----------------
    def _visible_slots(self):
        d = self.driver
        slots = []
        try:
            cells = d.find_elements(By.XPATH, "//table[contains(@id,'Kalender')]//td[not(contains(@class,'disabled'))]")
            for c in cells:
                if c.is_displayed() and c.text.strip():
                    slots.append(c)
        except Exception:
            pass
        return slots

    def _slot_label(self, cell):
        try:
            return cell.text.strip()
        except Exception:
            return ""

    def _select_slot_if_in_window(self, cell) -> Optional[str]:
        label = self._slot_label(cell)
        if not label:
            return None
        # Deze helper verwacht dat je in Config een functie hebt die beslist of de slot binnen de venster-criteria valt:
        # def is_within_n_business_days(label: str, n: int) -> bool: ...
        try:
            ok = Config.is_within_n_business_days(label, Config.DESIRED_BUSINESS_DAYS)
        except Exception:
            # Fallback: accepteer alles
            ok = True
        if not ok:
            return None

        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cell)
        except Exception:
            pass
        cell.click()
        self.wait_dom_idle()
        return label

    def monitor_and_book(self):
        d = self.driver
        self._notify("🕑 Monitoren gestart…")

        while not Config.STOP_FLAG:
            try:
                # 1) Check zichtbare slots
                for cell in self._visible_slots():
                    if Config.STOP_FLAG:
                        return {"success": False, "stopped": True}
                    label = self._select_slot_if_in_window(cell)
                    if label:
                        if not Config.BOOKING_ENABLED:
                            self._notify(f"🎯 Gevonden binnen venster: {label} — maar BOOKING_ENABLED=false, geen bevestiging.")
                            return {"success": True, "slot": label, "booking_disabled": True}

                        # Bevestigen (voorbeeld selector; pas aan als needed)
                        try:
                            btn = WebDriverWait(d, 20).until(
                                EC.element_to_be_clickable((By.XPATH, "//input[@type='submit' and contains(@value,'Bevestig')]"))
                            )
                            d.execute_script("arguments[0].click();", btn)
                            self.wait_dom_idle()
                        except Exception:
                            raise RuntimeError("Slot kon niet bevestigd worden — knop niet gevonden.")

                        self._notify(f"✅ Bevestigd: {label}")
                        return {"success": True, "slot": label}

                # 2) Geen slot → refresh + wacht
                self._notify("⏳ Nog geen slot binnen venster… blijf zoeken")
                try:
                    self.driver.refresh()
                except Exception:
                    pass
                self.wait_dom_idle()
                time.sleep(max(1, int(Config.REFRESH_DELAY)))

            except TimeoutException:
                # Soms valt de kalender weg → soft refresh
                try:
                    self.driver.refresh()
                except Exception:
                    pass
                self.wait_dom_idle()
                time.sleep(min(5, max(1, int(Config.REFRESH_DELAY))))
            except Exception as e:
                log.warning(f"⚠️ Fout in monitoring: {e}")
                try:
                    self.driver.refresh()
                except Exception:
                    pass
                self.wait_dom_idle()
                time.sleep(min(5, max(1, int(Config.REFRESH_DELAY) * 2)))

        return {"success": False, "stopped": True}

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass

