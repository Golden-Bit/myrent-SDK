#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from datetime import datetime, timedelta, timezone
import requests
import sys
from collections import Counter

# ================== CONFIG FISSA ==================
BASE_URL = "http://localhost:8333"     # modifica se il server gira altrove (es. 8000)
API_KEY  = "MYRENT-DEMO-KEY"           # chiave mock fissa come nel server
TIMEOUT  = 15.0                        # secondi per timeout HTTP
# =================================================

def jprint(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))

def header():
    return {"X-API-Key": API_KEY, "Content-Type": "application/json"}

def iso_z(dt: datetime) -> str:
    """Ritorna ISO 8601 con suffisso 'Z' (UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

def hrule(title=None):
    print("\n" + "=" * 78)
    if title:
        print(title)
        print("-" * 78)

def get_calc(vs: dict):
    try:
        return vs.get("Reference", {}).get("calculated", {}) or {}
    except Exception:
        return {}

def short_vehicle_row(vs: dict):
    calc = get_calc(vs)
    v = vs.get("Vehicle", {})
    code = v.get("Code")
    # il backend usa "VehMakeModel"; aggiungo fallback "veh_make_models" per robustezza
    vmms = v.get("VehMakeModel") or v.get("veh_make_models")
    name = vmms[0].get("Name") if isinstance(vmms, list) and vmms else None
    status = vs.get("Status")
    total = calc.get("total")
    base_daily = calc.get("base_daily")
    return f"[{status}] {code} - {name} | base_daily={base_daily} | total={total}"

# ---------- Helpers grafici/ASCII ----------
def _truncate(s, maxlen):
    s = "" if s is None else str(s)
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"

def print_table(headers, rows, widths):
    # widths: lista con larghezza max per colonna
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    def fmt_row(values):
        cells = []
        for v, w in zip(values, widths):
            cells.append(" " + _truncate(v, w).ljust(w) + " ")
        return "|" + "|".join(cells) + "|"

    print(sep)
    print(fmt_row(headers))
    print(sep)
    for r in rows:
        print(fmt_row(r))
    print(sep)

def print_bar_chart(counter: Counter, title: str, width: int = 40):
    if not counter:
        print(f"{title}: (vuoto)")
        return
    hrule(title)
    max_v = max(counter.values())
    for k, v in counter.most_common():
        bar_len = 0 if max_v == 0 else int((v / max_v) * width)
        bar = "█" * bar_len
        label = k if k is not None else "(None)"
        print(f"{label:<18} {bar} {v}")

# ------------------ TESTS ESISTENTI ------------------
def test_health():
    hrule("TEST: /health")
    url = f"{BASE_URL}/health"
    r = requests.get(url, headers=header(), timeout=TIMEOUT)
    print(f"GET {url} -> {r.status_code}")
    r.raise_for_status()
    jprint(r.json())

def test_locations():
    hrule("TEST: /api/v1/touroperator/locations")
    url = f"{BASE_URL}/api/v1/touroperator/locations"
    r = requests.get(url, headers=header(), timeout=TIMEOUT)
    print(f"GET {url} -> {r.status_code}")
    r.raise_for_status()
    data = r.json()
    print(f"Locations trovate: {len(data)}")
    for i, loc in enumerate(data[:3], start=1):
        code = loc.get("locationCode")
        name = loc.get("locationName")
        city = loc.get("locationCity")
        print(f"  {i}) {code} - {name} ({city})")
    return data

def make_quote_payload(pickup="FCO", dropoff="MXP", days=3, start_hour=10, end_hour=12,
                       channel="WEB_DEMO", age=30, show_pics=True,
                       macro_desc=None, show_params=False, out_of_hours=False):
    now = datetime.now(timezone.utc)
    start = (now + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
    end   = (now + timedelta(days=1+days)).replace(hour=end_hour, minute=0, second=0, microsecond=0)

    if out_of_hours:
        start = start.replace(hour=6, minute=30)  # forza fee fuori orario

    payload = {
        "dropOffLocation": dropoff,
        "endDate": iso_z(end),
        "pickupLocation": pickup,
        "startDate": iso_z(start),
        "age": age,
        "channel": channel,
        "showPics": bool(show_pics),
        "showOptionalImage": True,
        "showVehicleParameter": bool(show_params),
        "showVehicleExtraImage": False,
        "agreementCoupon": None,
        "discountValueWithoutVat": None,
        "macroDescription": macro_desc,   # es: "SUV", "COMPACT", "ECONOMY", "LUXURY", "MINI"
        "showBookingDiscount": False,
        "isYoungDriverAge": None,
        "isSeniorDriverAge": None
    }
    return payload

def test_quotations(payload, title):
    hrule(f"TEST: /api/v1/touroperator/quotations — {title}")
    url = f"{BASE_URL}/api/v1/touroperator/quotations"
    r = requests.post(url, headers=header(), data=json.dumps(payload), timeout=TIMEOUT)
    print(f"POST {url} -> {r.status_code}")
    r.raise_for_status()
    data = r.json()
    d = data.get("data", {})
    print(f"PickUp: {d.get('PickUpLocation')}  Return: {d.get('ReturnLocation')}")
    print(f"Periodo: {d.get('PickUpDateTime')} -> {d.get('ReturnDateTime')}")
    print(f"Veicoli trovati: {d.get('total')}")
    total_charge = d.get("TotalCharge") or d.get("total_charge")
    if total_charge:
        print("Miglior prezzo (totale stimato / pre-IVA):",
              total_charge.get("EstimatedTotalAmount"),
              "/",
              total_charge.get("RateTotalAmount"))

    vehicles = d.get("Vehicles", [])
    print("\nTop 5 veicoli (se disponibili):")
    for vs in vehicles[:5]:
        print("  -", short_vehicle_row(vs))
    return data

def test_damages(plate="GF962VG"):
    hrule(f"TEST: /api/v1/touroperator/damages/{plate}")
    url = f"{BASE_URL}/api/v1/touroperator/damages/{plate}"
    r = requests.get(url, headers=header(), timeout=TIMEOUT)
    print(f"GET {url} -> {r.status_code}")
    r.raise_for_status()
    data = r.json()
    damages = data.get("data", {}).get("damages", [])
    print(f"Damages trovati per {plate}: {len(damages)}")
    for i, d in enumerate(damages[:3], start=1):
        print(f"  {i}) {d.get('damageType')} - {d.get('description')}")
    return data

# ------------------ NUOVO: TEST CATALOGO VEICOLI ------------------

def fetch_vehicles_page(location=None, skip=0, page_size=25):
    url = f"{BASE_URL}/api/v1/touroperator/vehicles"
    params = {"skip": skip, "page_size": page_size}
    if location:
        params["location"] = location
    r = requests.get(url, headers=header(), params=params, timeout=TIMEOUT)
    print(f"GET {r.url} -> {r.status_code}")
    r.raise_for_status()
    return r.json()

def page_table_rows(items):
    rows = []
    for g in items:
        rows.append([
            g.get("international_code", ""),
            g.get("display_name", ""),
            g.get("vendor_macro", ""),
            g.get("vehicle_type", ""),
            str(g.get("daily_rate", "")),
            ",".join(g.get("locations", []) or []),
        ])
    return rows

def test_catalog(location=None, page_size=5):
    label = "TUTTE LE LOCATION" if not location else f"location={location}"
    hrule(f"TEST: /api/v1/touroperator/vehicles — {label} — page_size={page_size}")

    all_items = []
    seen_ids = set()  # per sicurezza, dedup su 'international_code' + 'display_name'
    skip = 0

    while True:
        data = fetch_vehicles_page(location=location, skip=skip, page_size=page_size)
        total = data.get("total", 0)
        items = data.get("items", [])
        has_next = bool(data.get("has_next"))
        next_skip = data.get("next_skip")
        prev_skip = data.get("prev_skip")

        print(f"Pagina: skip={data.get('skip')} size={data.get('page_size')} "
              f"items={len(items)} total={total} has_next={has_next}")

        # tabella compatta per la pagina
        headers = ["ACRISS", "Display name", "Macro", "Type", "€/day", "Locations"]
        widths  = [8, 30, 10, 10, 8, 25]
        rows = page_table_rows(items)
        print_table(headers, rows, widths)

        # accumulo + dedup
        for g in items:
            key = f"{g.get('international_code')}|{g.get('display_name')}"
            if key not in seen_ids:
                seen_ids.add(key)
                all_items.append(g)

        if not has_next:
            break
        # fallback: se server non fornisce next_skip, calcolo io
        skip = next_skip if next_skip is not None else (skip + page_size)

    # riepilogo finale
    hrule("RIEPILOGO CATALOGO — CONTEGGI")
    print(f"Totale veicoli raccolti: {len(all_items)}")
    by_macro = Counter([g.get("vendor_macro") for g in all_items])
    by_loc = Counter(l for g in all_items for l in (g.get("locations") or []))
    print_bar_chart(by_macro, "Per Macrogruppo (vendor_macro)")
    print_bar_chart(by_loc, "Per Location")

    # mostra tutti i veicoli in JSON (TUTTI I CAMPI, nessuno escluso)
    hrule("CATALOGO COMPLETO (JSON, tutti i campi)")
    jprint(all_items)

    return all_items

# ------------------ MAIN ------------------
def main():
    try:
        # 1) health
        test_health()

        # 2) locations
        locations = test_locations()
        codes = [loc.get("locationCode") for loc in locations] if isinstance(locations, list) else []
        pickup = "FCO" if "FCO" in codes else (codes[0] if codes else "FCO")
        dropoff = "MXP" if "MXP" in codes else (codes[-1] if codes else "MXP")

        # 3) quotations — base
        payload_base = make_quote_payload(
            pickup=pickup, dropoff=dropoff, days=3, start_hour=10, end_hour=12,
            channel="WEB_DEMO", age=30, show_pics=True, macro_desc=None, show_params=False
        )
        test_quotations(payload_base, "BASE (web channel, 30 anni)")

        # 4) quotations — filtro macroDescription (SUV)
        payload_suv = make_quote_payload(
            pickup=pickup, dropoff=dropoff, days=4, start_hour=11, end_hour=9,
            channel="WEB_DEMO", age=35, show_pics=True, macro_desc="SUV", show_params=True
        )
        test_quotations(payload_suv, "Filtro macroDescription = SUV + parametri veicolo")

        # 5) quotations — fuori orario (fee out-of-hours)
        payload_foh = make_quote_payload(
            pickup=pickup, dropoff=dropoff, days=2, start_hour=10, end_hour=10,
            channel="WEB_DEMO", age=40, show_pics=False, macro_desc=None, show_params=False,
            out_of_hours=True
        )
        test_quotations(payload_foh, "Pick-up fuori orario (fee)")

        # 6) quotations — giovane guidatore (surcharge)
        payload_young = make_quote_payload(
            pickup=pickup, dropoff=dropoff, days=5, start_hour=9, end_hour=10,
            channel="WEB_DEMO", age=22, show_pics=True, macro_desc="COMPACT", show_params=False
        )
        test_quotations(payload_young, "Giovane guidatore (22 anni) + COMPACT")

        # 7) damages — targa presente nei dati demo
        test_damages("GF962VG")

        # 8) vehicles catalog — tutte le location, page_size piccolo per mostrare la paginazione
        test_catalog(location=None, page_size=5)

        # 9) vehicles catalog — filtro per location (es. FCO)
        test_catalog(location="FCO", page_size=4)

        hrule("DEMO COMPLETATA ✅")
        print("Tutti i test sono stati eseguiti senza eccezioni.")
    except requests.HTTPError as e:
        hrule("ERRORE HTTP")
        print(e)
        if e.response is not None:
            print("Status:", e.response.status_code)
            try:
                jprint(e.response.json())
            except Exception:
                print(e.response.text)
        sys.exit(1)
    except Exception as e:
        hrule("ERRORE GENERICO")
        print(repr(e))
        sys.exit(2)

if __name__ == "__main__":
    main()
