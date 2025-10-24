#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from datetime import datetime, timedelta, timezone
import requests
import sys
from collections import Counter

# ================== CONFIG FISSA ==================
BASE_URL  = "http://localhost:8333"      # es. http://localhost:8000 se serve
ROOT_PATH = "/myrent-wrapper-api"        # come nel server FastAPI (root_path)
API_KEY   = "MYRENT-DEMO-KEY"            # chiave mock fissa come nel server
TIMEOUT   = 15.0                         # secondi per timeout HTTP
# =================================================

def api_url(path: str) -> str:
    """
    Compose full URL honoring ROOT_PATH without duplicating slashes.
    path must start with '/' (e.g. '/health', '/api/v1/...').
    """
    base = BASE_URL.rstrip("/")
    root = ROOT_PATH.strip("/")
    p = path.lstrip("/")
    return f"{base}/{root}/{p}" if root else f"{base}/{p}"

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
    """
    Ritorna una riga compatta per veicoli di /quotations,
    includendo anche Vehicle.id se presente.
    """
    calc = get_calc(vs)
    v = vs.get("Vehicle", {})
    vid = v.get("id")
    code = v.get("Code")
    vmms = v.get("VehMakeModel") or v.get("veh_make_models")
    name = vmms[0].get("Name") if isinstance(vmms, list) and vmms else v.get("model")
    status = vs.get("Status")
    total = calc.get("total")
    base_daily = calc.get("base_daily")
    return f"[{status}] id={vid} {code} - {name} | base_daily={base_daily} | total={total}"

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
    url = api_url("/health")
    r = requests.get(url, headers=header(), timeout=TIMEOUT)
    print(f"GET {url} -> {r.status_code}")
    r.raise_for_status()
    jprint(r.json())

def test_locations():
    hrule("TEST: /api/v1/touroperator/locations")
    url = api_url("/api/v1/touroperator/locations")
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

def assert_quotation_ids(resp_json: dict):
    """
    Controlla che ogni Vehicle di /quotations abbia 'id' popolato.
    Stampa un mini-report e ritorna lista di (id, code, name).
    """
    d = resp_json.get("data", {}) if isinstance(resp_json, dict) else {}
    vehicles = d.get("Vehicles", [])
    missing = 0
    summary = []
    for vs in vehicles:
        v = vs.get("Vehicle", {})
        vid = v.get("id")
        code = v.get("Code")
        vmms = v.get("VehMakeModel") or v.get("veh_make_models")
        name = vmms[0].get("Name") if isinstance(vmms, list) and vmms else v.get("model")
        summary.append((vid, code, name))
        if vid in (None, ""):
            missing += 1
    if missing == 0:
        print("✔ Tutti i veicoli in /quotations hanno un 'id'.")
    else:
        print(f"✘ ATTENZIONE: {missing} veicoli in /quotations senza 'id'.")
    return summary

def test_quotations(payload, title):
    hrule(f"TEST: /api/v1/touroperator/quotations — {title}")
    url = api_url("/api/v1/touroperator/quotations")
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

    # verifica presenza ID
    assert_quotation_ids(data)
    return data

def test_damages(plate="GF962VG"):
    hrule(f"TEST: /api/v1/touroperator/damages/{plate}")
    url = api_url(f"/api/v1/touroperator/damages/{plate}")
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
    url = api_url("/api/v1/touroperator/vehicles")
    params = {"skip": skip, "page_size": page_size}
    if location:
        params["location"] = location
    r = requests.get(url, headers=header(), params=params, timeout=TIMEOUT)
    print(f"GET {r.url} -> {r.status_code}")
    r.raise_for_status()
    return r.json()

def fetch_vehicle_by_id(vehicle_id):
    url = api_url(f"/api/v1/touroperator/vehicles/{vehicle_id}")
    r = requests.get(url, headers=header(), timeout=TIMEOUT)
    print(f"GET {r.url} -> {r.status_code}")
    r.raise_for_status()
    return r.json()

def page_table_rows(items):
    rows = []
    for g in items:
        rows.append([
            str(g.get("id", "")),
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
    seen_keys = set()  # dedup preferibilmente per id; se mancante, fallback su codice+nome
    skip = 0

    while True:
        data = fetch_vehicles_page(location=location, skip=skip, page_size=page_size)
        total = data.get("total", 0)
        items = data.get("items", [])
        has_next = bool(data.get("has_next"))
        next_skip = data.get("next_skip")

        print(f"Pagina: skip={data.get('skip')} size={data.get('page_size')} "
              f"items={len(items)} total={total} has_next={has_next}")

        # tabella compatta per la pagina
        headers = ["ID", "ACRISS", "Display name", "Macro", "Type", "€/day", "Locations"]
        widths  = [8, 8, 30, 12, 10, 8, 25]
        rows = page_table_rows(items)
        print_table(headers, rows, widths)

        # accumulo + dedup
        for g in items:
            gid = g.get("id")
            if gid not in (None, ""):
                key = f"id:{gid}"
            else:
                key = f"{g.get('international_code')}|{g.get('display_name')}"
            if key not in seen_keys:
                seen_keys.add(key)
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

def test_vehicle_detail_by_id(pick_ids):
    """
    Esercita /api/v1/touroperator/vehicles/{id} su una piccola selezione di id.
    Stampa risultato e fa un mini-confronto con la voce catalogo (se passata come dict).
    """
    hrule("TEST: /api/v1/touroperator/vehicles/{id} — dettaglio per ID")
    results = []
    for pid in pick_ids:
        print(f"\nRichiedo dettaglio per id={pid}")
        detail = fetch_vehicle_by_id(pid)
        # stampa compatta + JSON completo
        compact = {
            "id": detail.get("id"),
            "international_code": detail.get("international_code"),
            "display_name": detail.get("display_name"),
            "locations": detail.get("locations"),
            "daily_rate": detail.get("daily_rate"),
        }
        print("Compatto:")
        jprint(compact)
        print("JSON completo:")
        jprint(detail)
        results.append(detail)
    return results

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

        # 3) vehicles catalog — tutte le location, page_size piccolo per mostrare la paginazione
        all_items_no_filter = test_catalog(location=None, page_size=5)

        # 4) vehicles catalog — filtro per location (es. FCO)
        all_items_fco = test_catalog(location="FCO", page_size=4)

        # 5) detail by id — prendo 2-3 id dal catalogo generale e chiamo l'endpoint di dettaglio
        sample_ids = [g.get("id") for g in all_items_no_filter if g.get("id") is not None][:3]
        if sample_ids:
            test_vehicle_detail_by_id(sample_ids)
        else:
            print("⚠ Nessun 'id' trovato nel catalogo per il test dettaglio per id.")

        # 6) quotations — base
        payload_base = make_quote_payload(
            pickup=pickup, dropoff=dropoff, days=3, start_hour=10, end_hour=12,
            channel="WEB_DEMO", age=30, show_pics=True, macro_desc=None, show_params=False
        )
        test_quotations(payload_base, "BASE (web channel, 30 anni) — verifica id nei veicoli")

        # 7) quotations — filtro macroDescription (SUV) + parametri veicolo
        payload_suv = make_quote_payload(
            pickup=pickup, dropoff=dropoff, days=4, start_hour=11, end_hour=9,
            channel="WEB_DEMO", age=35, show_pics=True, macro_desc="SUV", show_params=True
        )
        test_quotations(payload_suv, "Filtro macroDescription = SUV + parametri veicolo — verifica id")

        # 8) quotations — fuori orario (fee out-of-hours)
        payload_foh = make_quote_payload(
            pickup=pickup, dropoff=dropoff, days=2, start_hour=10, end_hour=10,
            channel="WEB_DEMO", age=40, show_pics=False, macro_desc=None, show_params=False,
            out_of_hours=True
        )
        test_quotations(payload_foh, "Pick-up fuori orario (fee) — verifica id")

        # 9) quotations — giovane guidatore (surcharge)
        payload_young = make_quote_payload(
            pickup=pickup, dropoff=dropoff, days=5, start_hour=9, end_hour=10,
            channel="WEB_DEMO", age=22, show_pics=True, macro_desc="COMPACT", show_params=False
        )
        test_quotations(payload_young, "Giovane guidatore (22 anni) + COMPACT — verifica id")

        # 10) damages — targa presente nei dati demo
        test_damages("GF962VG")

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
