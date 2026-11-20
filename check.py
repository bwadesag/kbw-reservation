import os, re, time, requests, base64
from datetime import datetime, date

API = "https://kbw-personal-services.butlerapp2.de/api/book?exclude=trainer,appointments,extra_prices,forms&perPage=50&page={page}"
TARGET = "yaounde_deutsch_b2"
# ponytail: 40 pages is the ceiling. Upgrade path: stop on the API total count if Butlerapp adds one.
MAX_PAGES = 40
BOT_TOKEN = os.getenv("TG_TOKEN", "")
CHAT_IDS = ["8806922221", "-5434725968"]

notifie_libre_aujourdhui = {}
FULL = re.compile(r"fully booked|ausgebucht|déjà complet|keine freien|no places left", re.I)
OK = re.compile(r"buchung erfolgreich|vielen dank|thank you for your|inscription réussie|successfully registered|booking was successful|Buchungsnummer", re.I)
NEXT = re.compile(r"Next|Weiter|Suivant|abschicken|Anmelden|Bezahlen|Buchen|Book", re.I)


def notify(text):
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for cid in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": safe, "parse_mode": "HTML"},
                timeout=15,
            )
        except Exception:
            pass
    print(text)


def fetch_slots():
    courses = {}
    found = {}
    pages = 0
    for page in range(1, MAX_PAGES + 1):
        response = requests.get(API.format(page=page), timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        body = response.json()["body"]["entities"]["body"]
        for course in body.get("courses") or []:
            attr = course["attributes"]
            courses[attr["id"]] = attr
        spans = body.get("course_timespans") or []
        pages = page
        if not spans:
            break
        for span in spans:
            attr = span["attributes"]
            course_id = (span.get("related") or {}).get("courses", {}).get("value", [None])[0]
            course = courses.get(course_id, {})
            when = datetime.strptime(attr["from"]["date"][:19], "%Y-%m-%d %H:%M:%S")
            title = course.get("title") or attr.get("shortcut") or ""
            found[attr["id"]] = {
                "id": attr["id"],
                "course": course.get("name") or "",
                "title": title,
                "when": when,
                "places": attr.get("places_left") or 0,
                "label": f"{title} — {when.strftime('%d.%m.%Y %H:%M')}",
                "url": (span.get("presented") or {}).get("apiBookUrl")
                or f"https://kbw-personal-services.butlerapp2.de/demo#/bookcart?ftimespans={attr['id']}",
            }
        if len(spans) < 50:
            break
    return list(found.values()), pages


def choisir(slots, today):
    mine = [s for s in slots if s["course"] == TARGET and s["places"] > 0 and s["when"].date() >= today]
    december = [s for s in mine if s["when"].year == 2026 and s["when"].month == 12]
    if december:
        return max(december, key=lambda s: s["when"])
    if not mine:
        return None
    return min(mine, key=lambda s: s["when"])


def _self_check():
    today = date(2026, 11, 20)
    slots = [
        {"course": TARGET, "places": -2, "when": datetime(2026, 12, 1), "label": "dec-full"},
        {"course": TARGET, "places": 3, "when": datetime(2026, 11, 24), "label": "nov"},
        {"course": TARGET, "places": 1, "when": datetime(2026, 12, 9), "label": "dec-late"},
        {"course": TARGET, "places": 5, "when": datetime(2026, 12, 2), "label": "dec-early"},
        {"course": "douala_deutsch_b1", "places": 4, "when": datetime(2026, 11, 21), "label": "other"},
    ]
    assert choisir(slots, today)["label"] == "dec-late"
    no_december = [s for s in slots if not s["label"].startswith("dec")]
    assert choisir(no_december, today)["label"] == "nov"
    assert choisir([s for s in slots if s["places"] < 0 or s["course"] != TARGET], today) is None
    print("self-check ok")


def _fill(page, selectors, value):
    if not value:
        return False
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                el.fill(value)
                return True
        except Exception:
            continue
    return False


def _select(page, selectors, labels):
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() == 0:
                continue
            for label in labels:
                if not label:
                    continue
                try:
                    el.select_option(label=label)
                    return True
                except Exception:
                    pass
                try:
                    el.select_option(value=label)
                    return True
                except Exception:
                    pass
        except Exception:
            continue
    return False


def remplir_formulaire(page):
    try:
        b64 = os.getenv("KBW_PASS_B64_1", "") + os.getenv("KBW_PASS_B64_2", "")
        if not b64:
            b64 = os.getenv("KBW_PASS_B64", "")
        if b64 and not os.path.exists("pass.jpg"):
            with open("pass.jpg", "wb") as handle:
                handle.write(base64.b64decode(b64.strip()))
            print("  Passeport reconstruit")
    except Exception as exc:
        print(f"  Erreur passeport: {exc}")

    anrede = os.getenv("KBW_ANREDE", "Herr")
    gender = {"herr": "male", "frau": "female", "mr": "male", "mrs": "female"}.get(anrede.strip().lower(), anrede)
    _select(page, ['select[name*="anrede" i]', 'select[name*="salutation" i]'], [anrede, gender, "Herr", "Frau", "male", "female"])
    _fill(page, ['input[name="first_name"]', 'input[name*="vorname" i]'], os.getenv("KBW_VORNAME", ""))
    _fill(page, ['input[name="last_name"]', 'input[name*="nachname" i]'], os.getenv("KBW_NACHNAME", ""))
    _fill(page, ['input[name="email"]', 'input[type="email"]'], os.getenv("KBW_EMAIL", ""))
    _fill(page, ['input[type="tel"]', 'input[name*="telefon" i]'], os.getenv("KBW_TELEFON", ""))
    _fill(page, ['input[name*="geburtstag" i]', 'input[name*="geburt" i]'], os.getenv("KBW_GEBURTSDATUM", ""))
    _fill(page, ['input[name*="geburtsort" i]'], os.getenv("KBW_GEBURTSORT", ""))
    _fill(page, ['input[name*="geburtsland" i]'], os.getenv("KBW_LAND", "Cameroun"))
    _fill(page, ['input[name*="muttersprache" i]'], os.getenv("KBW_MUTTERSPRACHE", ""))
    _fill(page, ['input[name*="strasse" i]', 'input[name*="adresse" i]'], os.getenv("KBW_STRASSE", ""))
    _fill(page, ['input[name*="plz" i]'], os.getenv("KBW_PLZ", ""))
    _fill(page, ['input[name*="wohnort" i]', 'input[name*="ort" i]', 'input[name*="stadt" i]'], os.getenv("KBW_ORT", ""))
    land = os.getenv("KBW_LAND", "Cameroun")
    _select(
        page,
        ['select[name="country_id"]', 'select[name*="land" i]', 'select[name*="country" i]'],
        [land, "Cameroun", "Cameroon", "Kamerun"],
    )
    try:
        if os.path.exists("pass.jpg"):
            file_input = page.locator('input[type="file"]')
            if file_input.count() > 0:
                file_input.first.set_input_files("pass.jpg")
                print("  Passeport uploadé")
    except Exception:
        pass


def _check_boxes(page):
    boxes = page.locator('input[type="checkbox"]')
    for i in range(boxes.count()):
        try:
            box = boxes.nth(i)
            if not box.is_checked():
                box.check()
        except Exception:
            continue


def auto_book(page, slot):
    for tentative in range(1, 9):
        print(f"\nAUTO-BOOK #{tentative} : {slot['label']}")
        notify(f"Tentative #{tentative}\n{slot['label']}")
        try:
            page.goto(slot["url"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
        except Exception as exc:
            print(f"  goto: {exc}")
            time.sleep(3)
            continue
        booked = False
        for _ in range(8):
            body = page.locator("body").inner_text()
            if FULL.search(body):
                print("  creneau complet")
                return False
            if OK.search(body):
                booked = True
                break
            remplir_formulaire(page)
            _check_boxes(page)
            button = page.locator("button").filter(has_text=NEXT)
            if button.count() == 0:
                break
            try:
                button.last.click()
                page.wait_for_timeout(4000)
            except Exception:
                time.sleep(2)
                break
            body = page.locator("body").inner_text()
            if re.search(r"erreur technique|technical error", body, re.I):
                print(f"  erreur technique #{tentative}")
                break
            if OK.search(body):
                booked = True
                break
        if booked:
            notify(f"INSCRIPTION REUSSIE - {slot['label']} - Bot s'arrete")
            with open("SUCCESS.txt", "w", encoding="utf-8") as handle:
                handle.write(slot["label"])
            return True
        time.sleep(3)
    return False


def _signaler(slots, today):
    for slot in slots:
        if slot["places"] <= 0 or slot["when"].date() < today:
            continue
        if notifie_libre_aujourdhui.get(slot["id"]) == today:
            continue
        notify(f"LIBRE ({slot['places']} places) {slot['label']}")
        notifie_libre_aujourdhui[slot["id"]] = today


def run():
    from playwright.sync_api import sync_playwright

    notify("BOT DEMARRE - toutes les pages - Yaounde B2, decembre en priorite")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        start = time.time()
        max_dur = 20700 if os.getenv("GITHUB_ACTIONS") == "true" else 999999999
        while time.time() - start < max_dur:
            print("\nPHASE 1 : PAGES")
            try:
                slots, pages = fetch_slots()
            except Exception as exc:
                print(f"  API: {exc}")
                time.sleep(5)
                continue
            today = date.today()
            cible = choisir(slots, today)
            free = [s for s in slots if s["places"] > 0 and s["when"].date() >= today]
            print(f"  -> {pages} pages, {len(slots)} creneaux, {len(free)} libres")
            _signaler(free, today)
            if not cible:
                time.sleep(5)
                continue
            print(f"CIBLE : {cible['label']}")
            if auto_book(page, cible):
                break


if __name__ == "__main__":
    if os.getenv("SELF_CHECK") == "1":
        _self_check()
    else:
        run()
