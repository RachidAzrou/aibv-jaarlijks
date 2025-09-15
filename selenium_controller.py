import os
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


# Bevestigen (voorbeeld selector)
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
time.sleep(Config.REFRESH_DELAY)


except TimeoutException:
# Soms valt de kalender weg → soft refresh
try:
self.driver.refresh()
except Exception:
pass
self.wait_dom_idle()
time.sleep(min(5, Config.REFRESH_DELAY))
except Exception as e:
log.warning(f"⚠️ Fout in monitoring: {e}")
try:
self.driver.refresh()
except Exception:
pass
self.wait_dom_idle()
time.sleep(min(5, Config.REFRESH_DELAY * 2))


return {"success": False, "stopped": True}


def close(self):
try:
if self.driver:
self.driver.quit()
except Exception:
pass
