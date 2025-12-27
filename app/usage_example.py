#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests


# ================== CONFIG FISSA ==================
BASE_URL  = "http://localhost:8333"      # dove gira la tua wrapper FastAPI
ROOT_PATH = "/myrent-wrapper-api"        # root_path del server FastAPI
API_KEY   = "MYRENT-DEMO-KEY"            # API key della WRAPPER (NON MyRent!)
TIMEOUT   = 30.0                         # timeout HTTP

SOURCE = "MYRENT"                        # <-- qui forziamo datasource MYRENT

# ==== INPUT IDENTICI AL demo.py (SDK) ====
PICKUP  = "BRI"
DROPOFF = "BRI"
AGE     = 35

# Nel demo: start = now (min=0,sec=0) + 5 giorni; end = start + 3 giorni
START_PLUS_DAYS = 5
RENTAL_DAYS     = 3

# Channel del demo (quello che MyRent riconosce/abilita)
CHANNEL = "RENTAL_PREMIUM_POA"   # oppure "RENTAL_PREMIUM_PREPAID" se quello è abilitato

SHOW_PICS              = True
SHOW_OPTIONAL_IMAGE    = True
SHOW_VEHICLE_PARAMETER = True
SHOW_VEHICLE_EXTRA_IMG = False
SHOW_BOOKING_DISCOUNT  = True

AGREEMENT_COUPON = None
DISCOUNT_WO_VAT  = "0"
MACRO_DESC       = None
# =======================================


def api_url(path: str) -> str:
    base = BASE_URL.rstrip("/")
    root = ROOT_PATH.strip("/")
    p = path.lstrip("/")
    return f"{base}/{root}/{p}" if root else f"{base}/{p}"


def header() -> Dict[str, str]:
    return {"X-API-Key": API_KEY, "Content-Type": "application/json"}


def jprint(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def hrule(title: Optional[str] = None) -> None:
    print("\n" + "=" * 90)
    if title:
        print(title)
        print("-" * 90)


def iso_no_tz_seconds(dt: datetime) -> str:
    """Replica il demo.py: 'YYYY-MM-DDTHH:MM:SS' (senza Z, senza timezone)."""
    return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def get_vs_total_charge(vs: dict) -> Dict[str, Any]:
    """Compat: può arrivare come TotalCharge oppure total_charge, dipende dalla serializzazione."""
    tc = vs.get("TotalCharge") or vs.get("total_charge") or {}
    return tc if isinstance(tc, dict) else {}


def best_offer_from_vehicles(vehicles: List[dict]) -> Optional[Tuple[dict, float, float]]:
    """Trova miglior offerta usando Vehicles[*].TotalCharge (est total)."""
    def _to_float(v: Any) -> Optional[float]:
        try:
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    candidates = []
    for vs in vehicles:
        tc = get_vs_total_charge(vs)
        est = _to_float(tc.get("EstimatedTotalAmount"))
        pre = _to_float(tc.get("RateTotalAmount"))
        if est is not None and pre is not None:
            candidates.append((vs, est, pre))

    if not candidates:
        return None

    avail = [c for c in candidates if c[0].get("Status") == "Available"]
    pool = avail if avail else candidates
    return min(pool, key=lambda x: x[1])


def test_health() -> None:
    hrule("TEST 1: /health")
    url = api_url("/health")
    r = requests.get(url, headers=header(), timeout=TIMEOUT)
    print(f"GET {url} -> {r.status_code}")
    r.raise_for_status()
    jprint(r.json())


def test_locations_myrent() -> List[dict]:
    hrule(f"TEST 2: /api/v1/touroperator/locations?source={SOURCE}")
    url = api_url("/api/v1/touroperator/locations")
    r = requests.get(url, headers=header(), params={"source": SOURCE}, timeout=TIMEOUT)
    print(f"GET {r.url} -> {r.status_code}")
    if r.status_code >= 400:
        print("Errore payload:")
        jprint(safe_json(r))
    r.raise_for_status()

    data = r.json()
    if not isinstance(data, list):
        print("Payload locations inatteso (attesa lista). Ecco il contenuto:")
        jprint(data)
        return []

    print(f"Locations trovate: {len(data)}")
    for i, loc in enumerate(data[:20], start=1):
        code = loc.get("locationCode")
        name = loc.get("locationName")
        city = loc.get("locationCity")
        print(f"  {i:2d}) {code} - {name} ({city})")
    return data


def build_demo_like_payload() -> Dict[str, Any]:
    """Costruisce lo stesso input del demo.py ma nel formato wrapper."""
    start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=START_PLUS_DAYS)
    end = start + timedelta(days=RENTAL_DAYS)

    payload = {
        "pickupLocation": PICKUP,
        "dropOffLocation": DROPOFF,
        "startDate": iso_no_tz_seconds(start),
        "endDate": iso_no_tz_seconds(end),
        "age": AGE,

        # CHIAVE: questo è il “CompanyName” (Source0.RequestorID.CompanyName) lato MyRent
        "channel": CHANNEL,

        "showPics": bool(SHOW_PICS),
        "showOptionalImage": bool(SHOW_OPTIONAL_IMAGE),
        "showVehicleParameter": bool(SHOW_VEHICLE_PARAMETER),
        "showVehicleExtraImage": bool(SHOW_VEHICLE_EXTRA_IMG),

        "agreementCoupon": AGREEMENT_COUPON,
        "discountValueWithoutVat": DISCOUNT_WO_VAT,

        "macroDescription": MACRO_DESC,
        "showBookingDiscount": bool(SHOW_BOOKING_DISCOUNT),

        "isYoungDriverAge": None,
        "isSeniorDriverAge": None,
    }
    return payload


def test_quotations_myrent(payload: Dict[str, Any]) -> Dict[str, Any]:
    hrule(f"TEST 3: /api/v1/touroperator/quotations?source={SOURCE} — DEMO-like payload")
    url = api_url("/api/v1/touroperator/quotations")

    print("Payload inviato alla WRAPPER (che verrà convertito dall’adapter verso MyRent):")
    jprint(payload)

    r = requests.post(url, headers=header(), params={"source": SOURCE}, data=json.dumps(payload), timeout=TIMEOUT)
    print(f"POST {r.url} -> {r.status_code}")

    data = safe_json(r)
    if r.status_code >= 400:
        print("Errore payload:")
        jprint(data)
    r.raise_for_status()

    # La wrapper risponde in formato wrapper: data.total + data.Vehicles
    d = data.get("data", {}) if isinstance(data, dict) else {}
    vehicles = d.get("Vehicles", []) or []

    print(f"PickUp:  {d.get('PickUpLocation')}  Return: {d.get('ReturnLocation')}")
    print(f"Periodo: {d.get('PickUpDateTime')} -> {d.get('ReturnDateTime')}")
    print(f"Veicoli trovati: {d.get('total')}")

    best = best_offer_from_vehicles(vehicles)
    if best:
        _, est, pre = best
        print(f"Miglior prezzo (da Vehicles[*].TotalCharge): est/pre = {est} / {pre}")
    else:
        print("Miglior prezzo: non disponibile (manca TotalCharge per veicolo).")

    # stampa prime righe
    print("\nPrime 3 offerte (riassunto):")
    for vs in vehicles[:3]:
        v = vs.get("Vehicle", {})
        vid = v.get("id")
        code = v.get("Code")
        name = None
        vmm = v.get("VehMakeModel")
        if isinstance(vmm, list) and vmm and isinstance(vmm[0], dict):
            name = vmm[0].get("Name")
        if not name:
            name = v.get("model")
        tc = get_vs_total_charge(vs)
        print(
            f" - [{vs.get('Status')}] id={vid} {code} {name} | "
            f"TotalCharge={tc.get('EstimatedTotalAmount')}/{tc.get('RateTotalAmount')} | "
            f"optionals={len(vs.get('optionals') or [])}"
        )

    return data


def main() -> None:
    try:
        test_health()

        locs = test_locations_myrent()

        # check rapido che PICKUP/DROPOFF siano presenti (non modifica i valori “demo-like”)
        codes = {str(x.get("locationCode")).upper() for x in (locs or []) if isinstance(x, dict)}
        if PICKUP.upper() not in codes or DROPOFF.upper() not in codes:
            hrule("ATTENZIONE")
            print(
                f"Nel payload stai usando PICKUP={PICKUP}, DROPOFF={DROPOFF}, "
                "ma non risultano presenti nella lista locations MYRENT."
            )
            print("Codici presenti:", sorted(list(codes))[:50])

        payload = build_demo_like_payload()
        test_quotations_myrent(payload)

        hrule("FINE ✅")
        print("Test MYRENT via WRAPPER completato.")
    except requests.HTTPError as e:
        hrule("ERRORE HTTP")
        print(e)
        if e.response is not None:
            print("Status:", e.response.status_code)
            jprint(safe_json(e.response))
        sys.exit(1)
    except Exception as e:
        hrule("ERRORE GENERICO")
        print(repr(e))
        sys.exit(2)


if __name__ == "__main__":
    main()
