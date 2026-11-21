import os, re, time, requests, base64
from datetime import datetime, date

API = "https://kbw-personal-services.butlerapp2.de/api/book?exclude=trainer,appointments,extra_prices,forms&perPage=50&page={page}"
TARGETS = ("yaounde_deutsch_b2", "douala_deutsch_b2")
# ponytail: 40 pages is the ceiling. Upgrade path: stop on the API total count if Butlerapp adds one.
MAX_PAGES = 40
BOT_TOKEN = os.getenv("TG_TOKEN", "")
CHAT_IDS = ["8806922221", "-5434725968"]

notifie_libre_aujourdhui = {}
FULL = re.compile(r"fully booked|ausgebucht|déjà complet|keine freien|no places left|déjà complets", re.I)
PAY = re.compile(r"obligation de paiement|Kostenpflichtig buchen|Book with costs|Zahlungspflichtig", re.I)
ERROR = re.compile(r"erreur|error|fehler|invalid|invalide|est requis", re.I)
STEP = re.compile(r"Suivant|Weiter|Next|Passer à la caisse|Zur Kasse|Checkout", re.I)
CONSENTS = (
    re.compile(r"verbindlich abschicken", re.I),
    re.compile(r"nächste Buchung speichern|Save data for next booking|prochaine réservation|prochaine reservation", re.I),
)


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
    mine = [s for s in slots if s["course"] in TARGETS and s["places"] > 0 and s["when"].date() >= today]
    if not mine:
        return None
    return min(mine, key=lambda s: s["when"])


def _self_check():
    today = date(2026, 11, 20)
    slots = [
        {"course": "yaounde_deutsch_b2", "places": -2, "when": datetime(2026, 12, 1), "label": "dec-full"},
        {"course": "yaounde_deutsch_b2", "places": 3, "when": datetime(2026, 11, 24), "label": "nov"},
        {"course": "yaounde_deutsch_b2", "places": 1, "when": datetime(2026, 12, 9), "label": "dec-late"},
        {"course": "yaounde_deutsch_b2", "places": 5, "when": datetime(2026, 12, 2), "label": "dec-early"},
        {"course": "douala_deutsch_b2", "places": 2, "when": datetime(2026, 11, 22), "label": "douala"},
        {"course": "douala_deutsch_b1", "places": 4, "when": datetime(2026, 11, 21), "label": "other"},
    ]
    assert choisir(slots, today)["label"] == "douala"
    only_december = [s for s in slots if s["label"].startswith("dec")]
    assert choisir(only_december, today)["label"] == "dec-early"
    assert choisir([s for s in slots if s["course"] not in TARGETS or s["places"] < 0], today) is None
    assert PAY.search("Réserver avec obligation de paiement")
    assert PAY.search("Kostenpflichtig buchen")
    assert PAY.search("Book with costs")
    assert not PAY.search("Suivant »")
    assert STEP.search("Suivant »") and STEP.search("Weiter »") and STEP.search("Next »")
    assert _confirmed("Merci beaucoup ! Nous avons reçu votre réservation")
    assert _confirmed("merci beaucoups ! nous avons recu votre reservation")
    assert not _confirmed("Réservation réussie")
    assert not _confirmed("Merci beaucoup")
    assert CONSENTS[0].search("Ich möchte meine Anmeldung verbindlich abschicken")
    assert CONSENTS[1].search("Enregistrer les données pour la prochaine réservation.")
    assert CONSENTS[1].search("Save data for next booking.")
    assert _as_form_date("1990-04-21") == "21.04.1990"
    assert _as_form_date("21.04.1990") == "21.04.1990"
    print("self-check ok")


def _as_form_date(value):
    value = (value or "").strip()
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return value
    return f"{match.group(3)}.{match.group(2)}.{match.group(1)}"


def _fill_label(page, pattern, value):
    if not value:
        return False
    try:
        field = page.get_by_label(pattern).first
        if field.count() > 0:
            field.fill(value)
            return True
    except Exception:
        return False
    return False


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
    try:
        salutation = page.get_by_label(re.compile(r"anrede|salutation", re.I)).first
        if salutation.count() > 0:
            for label in (anrede, gender, "male", "female"):
                try:
                    salutation.select_option(label=label)
                    break
                except Exception:
                    try:
                        salutation.select_option(value=label)
                        break
                    except Exception:
                        continue
    except Exception:
        pass
    vorname = os.getenv("KBW_VORNAME", "")
    nachname = os.getenv("KBW_NACHNAME", "")
    _fill_label(page, re.compile(r"first name|vorname|prénom", re.I), vorname)
    _fill(page, ['input[name*="first_name" i]', 'input[name*="vorname" i]'], vorname)
    _fill_label(page, re.compile(r"last name|nachname", re.I), nachname)
    _fill(page, ['input[name*="last_name" i]', 'input[name*="nachname" i]'], nachname)
    email = os.getenv("KBW_EMAIL", "")
    _fill_label(page, re.compile(r"e-?mail", re.I), email)
    _fill(page, ['input[name*="email" i]', 'input[type="email"]'], email)
    _fill(page, ['input[type="tel"]', 'input[name*="telefon" i]'], os.getenv("KBW_TELEFON", ""))
    naissance = _as_form_date(os.getenv("KBW_GEBURTSDATUM", ""))
    _fill_label(page, re.compile(r"geburtstag|anniversaire|date de naissance", re.I), naissance)
    _fill(page, ['input[name*="geburtstag" i]', 'input[name*="geburt" i]', 'input[placeholder="dd.mm.yyyy"]'], naissance)
    ort_naissance = os.getenv("KBW_GEBURTSORT", "")
    _fill_label(page, re.compile(r"geburtsort|lieu de naissance", re.I), ort_naissance)
    _fill(page, ['input[name*="geburtsort" i]'], ort_naissance)
    land = os.getenv("KBW_LAND", "Cameroun")
    _fill_label(page, re.compile(r"geburtsland|pays de naissance", re.I), land)
    _fill(page, ['input[name*="geburtsland" i]'], land)
    langue = os.getenv("KBW_MUTTERSPRACHE", "")
    _fill_label(page, re.compile(r"muttersprache|langue maternelle", re.I), langue)
    _fill(page, ['input[name*="muttersprache" i]'], langue)
    _fill(page, ['input[name*="strasse" i]', 'input[name*="adresse" i]'], os.getenv("KBW_STRASSE", ""))
    _fill(page, ['input[name*="plz" i]'], os.getenv("KBW_PLZ", ""))
    ville = os.getenv("KBW_ORT", "")
    _fill_label(page, re.compile(r"wohnort|lieu de résidence", re.I), ville)
    _fill(page, ['input[name*="wohnort" i]', 'input[name*="stadt" i]'], ville)
    _select(
        page,
        ['select[name*="country_id" i]', 'select[name*="country" i]'],
        [land, "Cameroun", "Cameroon", "Kamerun"],
    )
    _upload_pass(page)


def _upload_pass(page):
    if not os.path.exists("pass.jpg"):
        return False
    target = page.locator('input[type="file"]')
    if target.count() == 0:
        try:
            label = page.get_by_text(re.compile(r"Upload Pass", re.I)).first
            if label.count() > 0:
                target = label.locator("xpath=ancestor::*[.//input[@type='file']][1]//input[@type='file']")
        except Exception:
            return False
    if target.count() == 0:
        return False
    try:
        target.first.set_input_files("pass.jpg")
        print("  Passeport uploadé dans Upload Pass")
        return True
    except Exception as exc:
        print(f"  Upload Pass: {exc}")
        return False


def _check_one(box):
    try:
        if not box.is_checked():
            box.check(force=True)
    except Exception:
        return False
    return True


def _check_boxes(page):
    boxes = page.locator('input[type="checkbox"]')
    for i in range(boxes.count()):
        _check_one(boxes.nth(i))
    for pattern in CONSENTS:
        node = page.get_by_text(pattern)
        if node.count() == 0:
            continue
        box = node.first.locator("xpath=ancestor::*[.//input[@type='checkbox']][1]//input[@type='checkbox']").first
        try:
            if box.count() > 0:
                _check_one(box)
                continue
        except Exception:
            pass
        try:
            node.first.click()
        except Exception:
            pass


def _confirmed(text):
    return bool(
        re.search(r"merci beaucoups?", text, re.I)
        and re.search(r"re[cç]u votre r[eé]servation", text, re.I)
    )


def _click_named(page, pattern):
    found = page.locator("button").filter(has_text=pattern)
    for i in range(found.count() - 1, -1, -1):
        button = found.nth(i)
        try:
            if button.is_enabled():
                button.click()
                return True
        except Exception:
            continue
    return False


def _done(slot):
    notify(f"INSCRIPTION REUSSIE - {slot['label']} - Bot s'arrete")
    with open("SUCCESS.txt", "w", encoding="utf-8") as handle:
        handle.write(slot["label"])
    return True


def _pay_until_confirmed(page, slot):
    # ponytail: no attempt cap. The Actions job (~6h) is the ceiling; the workflow restarts after that.
    n = 0
    while True:
        body = page.locator("body").inner_text()
        if _confirmed(body):
            return _done(slot)
        pay = page.locator("button").filter(has_text=PAY)
        if FULL.search(body) and pay.count() == 0:
            print("  creneau complet")
            return False
        if _has_error(body) or pay.count() > 0:
            _check_boxes(page)
            _click_named(page, PAY)
            n += 1
            print(f"  Réserver #{n}")
            if n == 1:
                notify(f"Paiement en cours\n{slot['label']}")
        page.wait_for_timeout(3000)


def _has_error(text):
    return bool(ERROR.search(text))


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
        for _ in range(8):
            body = page.locator("body").inner_text()
            if _confirmed(body):
                return _done(slot)
            if FULL.search(body):
                print("  creneau complet")
                return False
            if page.locator("button").filter(has_text=PAY).count() > 0:
                return _pay_until_confirmed(page, slot)
            remplir_formulaire(page)
            _check_boxes(page)
            if not _click_named(page, STEP):
                break
            page.wait_for_timeout(4000)
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

    notify("BOT DEMARRE - Yaounde et Douala B2, date la plus proche")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_context(locale="fr-FR").new_page()
        start = time.time()
        last_alive = start
        last_report = "pas encore de catalogue"
        max_dur = 20700 if os.getenv("GITHUB_ACTIONS") == "true" else 999999999
        while time.time() - start < max_dur:
            if time.time() - last_alive >= 7200:
                notify(f"BOT EN VIE - {last_report}")
                last_alive = time.time()
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
            yao = len([s for s in free if s["course"] == "yaounde_deutsch_b2"])
            dou = len([s for s in free if s["course"] == "douala_deutsch_b2"])
            last_report = f"{pages} pages, {len(slots)} creneaux, {yao} Yaounde B2 libres, {dou} Douala B2 libres"
            print(f"  -> {last_report}, {len(free)} libres au total")
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
