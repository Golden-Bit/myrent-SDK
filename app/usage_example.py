#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests


# =====================================================================================
# CONFIG WRAPPER API
# =====================================================================================

BASE_URL = "http://localhost:8333"          # dove gira la wrapper FastAPI
ROOT_PATH = "/myrent-wrapper-api"           # root_path della wrapper
API_KEY = "MYRENT-DEMO-KEY"                 # API key della WRAPPER (NON MyRent)
TIMEOUT = 30.0
SOURCE = "MYRENT"                           # questa demo usa sempre la sorgente live via adapter

SAVE_OUTPUT_JSON = True
OUTPUT_JSON_PATH = "wrapper_full_flow_output.json"

TEST_INTERNAL_DETAILS_ENDPOINT = True
TEST_BY_CODE_DETAILS_ENDPOINT = True


# =====================================================================================
# CONFIG BUSINESS - ALLINEATA AI DEMO SDK
# =====================================================================================

PICKUP_LOCATION = "NAP"
DROPOFF_LOCATION = "NAP"
CHANNEL = "RENTAL_PREMIUM_POA"
DRIVER_AGE = 35

# Logica demo:
# start = now arrotondato + 5 giorni
# end   = start + 3 giorni
START_PLUS_DAYS = 5
RENTAL_DAYS = 3

# VehicleRequest come nel demo booking SDK
VOUCHER_NUMBER = "TESTDOGMA"
PAYMENT_TRANSACTION_TYPE_CODE = "charge"
VEHICLE_REQUEST_TYPE = "Payment"
FORCE_PAYMENT_TYPE = "---3BONIFICO---3"

# Customer base
CUSTOMER_DATA: Dict[str, Any] = {
    "firstName": "Mario",
    "lastName": "Rossi",
    "email": "mario.rossi@example.com",
    "mobileNumber": "+393331234567",
    "country": "IT",
    "city": "Bari",
    "zip": "70121",
    "street": "Via Roma",
    "num": "1",
    "taxCode": "RSSMRA80A01H501U",
    "birthPlace": "Bari",
    "birthProvince": "BA",
    # birthDate valorizzata dinamicamente
}

# Customer update
CUSTOMER_UPDATE_DATA: Dict[str, Any] = {
    "status": "success",
    "document": "PATENTE",
    "documentNumber": "DC00000000",
    "licenceType": "B",
    "issueBy": "ROMA",
    "releaseDate": "2015-02-09",
    "expiryDate": "2029-02-25",
}

# Se False, la wrapper NON invia driver1/2/3
# e il backend userà set_customer_as_driver1(...)
USE_EXPLICIT_DRIVERS = False

DRIVER1_DATA: Dict[str, Any] = {
    "firstName": "Info",
    "lastName": "Dogma",
    "middleName": "DogmaSystemInfoDriver1",
    "codice": 1,
    "phNum1": "2",
    "mobileNumber": "12345",
    "email": "info@dogmasystems.com",
    "gender": True,
    "document2": "test",
    "documentNumber2": "test1",
    "issueBy2": "test3",
}

DRIVER2_DATA: Dict[str, Any] = {
    "firstName": "Mario",
    "lastName": "Bianchi",
    "middleName": "DriverTwo",
    "mobileNumber": "+393339999999",
    "email": "driver2@example.com",
    "birthDate": "1990-05-10",
    "birthPlace": "Bari",
    "birthProvince": "BA",
    "taxCode": "BNCMRA90E10A662Z",
}

DRIVER3_DATA: Dict[str, Any] = {
    "firstName": "Luigi",
    "lastName": "Verdi",
    "middleName": "DriverThree",
    "mobileNumber": "+393338888888",
    "email": "driver3@example.com",
    "birthDate": "1988-09-20",
    "birthPlace": "Bari",
    "birthProvince": "BA",
    "taxCode": "VRDLGU88P20A662Z",
}

SHOW_PICS = True
SHOW_OPTIONAL_IMAGE = True
SHOW_VEHICLE_PARAMETER = True
SHOW_VEHICLE_EXTRA_IMG = False
SHOW_BOOKING_DISCOUNT = True

AGREEMENT_COUPON: Optional[str] = None
DISCOUNT_WO_VAT = "0"
MACRO_DESC: Optional[str] = None


# =====================================================================================
# HELPERS HTTP / OUTPUT
# =====================================================================================

def api_url(path: str) -> str:
    base = BASE_URL.rstrip("/")
    root = ROOT_PATH.strip("/")
    p = path.lstrip("/")
    return f"{base}/{root}/{p}" if root else f"{base}/{p}"


def headers() -> Dict[str, str]:
    return {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def jprint(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def hrule(title: Optional[str] = None) -> None:
    print("\n" + "=" * 110)
    if title:
        print(title)
        print("-" * 110)


def request_get(path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
    url = api_url(path)
    resp = requests.get(url, headers=headers(), params=params, timeout=TIMEOUT)
    print(f"GET  {resp.url} -> {resp.status_code}")
    data = safe_json(resp)
    if resp.status_code >= 400:
        print("Payload errore:")
        jprint(data)
    resp.raise_for_status()
    return data


def request_post(path: str, payload: Dict[str, Any], *, params: Optional[Dict[str, Any]] = None) -> Any:
    url = api_url(path)
    resp = requests.post(
        url,
        headers=headers(),
        params=params,
        data=json.dumps(payload, ensure_ascii=False),
        timeout=TIMEOUT,
    )
    print(f"POST {resp.url} -> {resp.status_code}")
    data = safe_json(resp)
    if resp.status_code >= 400:
        print("Payload errore:")
        jprint(data)
    resp.raise_for_status()
    return data


# =====================================================================================
# HELPERS GENERICI
# =====================================================================================

def first_non_empty(*values: Any) -> Optional[Any]:
    for v in values:
        if v is None:
            continue
        if isinstance(v, str):
            if v.strip():
                return v.strip()
            continue
        return v
    return None


def normalize_spaces(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def dict_get(d: Optional[Dict[str, Any]], *keys: str) -> Any:
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def nested_get(data: Any, *path: str) -> Any:
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


# =====================================================================================
# HELPERS DATE/TIME
# =====================================================================================

def iso_no_tz_seconds(dt: datetime) -> str:
    return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def parse_iso_any(s: str) -> Optional[datetime]:
    if not isinstance(s, str) or not s.strip():
        return None

    raw = s.strip()

    # "2026-03-23T10:00:00.000Z" -> "2026-03-23T10:00:00.000+00:00"
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(raw)
    except Exception:
        try:
            return datetime.fromisoformat(raw.split(".")[0])
        except Exception:
            return None


def strip_tz_keep_wall_clock(dt_value: datetime) -> datetime:
    """
    Rimuove eventuale timezone SENZA convertire l'orario.
    Esempio:
        2026-03-23T10:00:00+00:00 -> 2026-03-23T10:00:00
    """
    if dt_value.tzinfo is None:
        return dt_value.replace(microsecond=0)
    return dt_value.replace(tzinfo=None, microsecond=0)


def build_start_end_demo_like() -> Tuple[datetime, datetime]:
    start_dt = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=START_PLUS_DAYS)
    end_dt = start_dt + timedelta(days=RENTAL_DAYS)
    return start_dt, end_dt


def make_birth_date_iso(start_dt: datetime, driver_age: int) -> str:
    year = start_dt.year - driver_age
    bd = datetime(year, start_dt.month, min(start_dt.day, 28), 0, 0, 0)
    return bd.isoformat(timespec="seconds")


def date_only_from_any(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None

        dt = parse_iso_any(raw)
        if dt:
            return dt.date().isoformat()

        if "T" in raw:
            return raw.split("T", 1)[0][:10]

        if len(raw) >= 10:
            return raw[:10]

    return None


# =====================================================================================
# HELPERS QUOTATIONS / VEICOLI
# =====================================================================================

def get_vehicles_from_quote(quote_payload: Dict[str, Any]) -> List[dict]:
    data = quote_payload.get("data") or {}
    vehicles = data.get("Vehicles") or []
    return vehicles if isinstance(vehicles, list) else []


def get_vehicle_total_charge(vs: Dict[str, Any]) -> Dict[str, Any]:
    tc = vs.get("TotalCharge") or vs.get("total_charge") or {}
    return tc if isinstance(tc, dict) else {}


def get_vehicle_code(vs: Dict[str, Any]) -> Optional[str]:
    vehicle = vs.get("Vehicle") if isinstance(vs.get("Vehicle"), dict) else {}
    code = vehicle.get("Code")
    if isinstance(code, str) and code.strip():
        return code.strip()
    return None


def get_vehicle_name(vs: Dict[str, Any]) -> Optional[str]:
    vehicle = vs.get("Vehicle") if isinstance(vs.get("Vehicle"), dict) else {}
    vmm = vehicle.get("VehMakeModel")
    if isinstance(vmm, list) and vmm and isinstance(vmm[0], dict):
        name = vmm[0].get("Name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    model = vehicle.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return None


def normalize_optional_for_booking(opt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    equip = opt.get("Equipment") if isinstance(opt.get("Equipment"), dict) else {}
    equip_type = equip.get("EquipType") or opt.get("EquipType")
    if not equip_type:
        return None

    qty = equip.get("Quantity", opt.get("Quantity", 1))
    try:
        qty = int(qty)
    except Exception:
        qty = 1
    if qty <= 0:
        qty = 1

    prepaid = opt.get("Prepaid", False)

    return {
        "EquipType": str(equip_type),
        "Quantity": qty,
        "Selected": True,
        "Prepaid": bool(prepaid),
    }


def extract_required_optionals_for_booking(vs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Include solo optional selezionati o inclusi in tariffa / totale stimato.
    """
    opts = vs.get("optionals")
    if not isinstance(opts, list):
        return []

    out: List[Dict[str, Any]] = []
    for opt in opts:
        if not isinstance(opt, dict):
            continue
        charge = opt.get("Charge") if isinstance(opt.get("Charge"), dict) else {}
        must_include = (
            opt.get("Selected") is True
            or charge.get("IncludedInRate") is True
            or charge.get("IncludedInEstTotalInd") is True
        )
        if not must_include:
            continue
        normalized = normalize_optional_for_booking(opt)
        if normalized:
            out.append(normalized)
    return out


def extract_payment_amount_from_vehicle(vs: Dict[str, Any]) -> float:
    tc = get_vehicle_total_charge(vs)
    for key in ("RateTotalAmount", "EstimatedTotalAmount", "TotalAmount"):
        value = tc.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    return 0.0


def choose_best_available_vehicle(vehicles: List[Dict[str, Any]]) -> Optional[Tuple[Dict[str, Any], float, float]]:
    candidates: List[Tuple[Dict[str, Any], float, float]] = []

    for vs in vehicles:
        tc = get_vehicle_total_charge(vs)
        try:
            est = float(tc.get("EstimatedTotalAmount"))
            pre = float(tc.get("RateTotalAmount"))
            candidates.append((vs, est, pre))
        except Exception:
            continue

    if not candidates:
        return None

    available = [row for row in candidates if str(row[0].get("Status", "")).lower() == "available"]
    pool = available if available else candidates
    return min(pool, key=lambda x: x[1])


def extract_quote_canonical_booking_datetimes(
    quote_payload: Dict[str, Any],
    fallback_start: datetime,
    fallback_end: datetime,
) -> Tuple[datetime, datetime]:
    """
    Estrae le date canoniche dalla quotation SENZA shift timezone.
    Se la quotation restituisce:
        2026-03-23T10:00:00.000Z
    il risultato deve restare:
        2026-03-23T10:00:00
    e NON 11:00:00.
    """
    data = quote_payload.get("data") or {}
    pu_raw = data.get("PickUpDateTime")
    ret_raw = data.get("ReturnDateTime")

    pu_dt = parse_iso_any(pu_raw) if isinstance(pu_raw, str) else None
    ret_dt = parse_iso_any(ret_raw) if isinstance(ret_raw, str) else None

    if pu_dt and ret_dt:
        return strip_tz_keep_wall_clock(pu_dt), strip_tz_keep_wall_clock(ret_dt)

    return fallback_start, fallback_end


# =====================================================================================
# BUILD PAYLOADS WRAPPER
# =====================================================================================

def build_quotation_payload(start_dt: datetime, end_dt: datetime) -> Dict[str, Any]:
    return {
        "pickupLocation": PICKUP_LOCATION,
        "dropOffLocation": DROPOFF_LOCATION,
        "startDate": iso_no_tz_seconds(start_dt),
        "endDate": iso_no_tz_seconds(end_dt),
        "age": DRIVER_AGE,
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


def build_compose_payload(
    selected_vehicle: Dict[str, Any],
    booking_start_dt: datetime,
    booking_end_dt: datetime,
) -> Dict[str, Any]:
    vehicle_code = get_vehicle_code(selected_vehicle)
    if not vehicle_code:
        raise RuntimeError("VehicleCode assente nel veicolo selezionato")

    optionals = extract_required_optionals_for_booking(selected_vehicle)
    payment_amount = extract_payment_amount_from_vehicle(selected_vehicle)
    birth_date_iso = make_birth_date_iso(booking_start_dt, DRIVER_AGE)

    customer_payload = dict(CUSTOMER_DATA)
    customer_payload["birthDate"] = birth_date_iso

    payload: Dict[str, Any] = {
        "booking": {
            "pickupLocation": PICKUP_LOCATION,
            "dropOffLocation": DROPOFF_LOCATION,
            "startDate": iso_no_tz_seconds(booking_start_dt),
            "endDate": iso_no_tz_seconds(booking_end_dt),
            "vehicleCode": vehicle_code,
            "channel": CHANNEL,
            "optionals": optionals,
            "youngDriverFee": None,
            "seniorDriverFee": None,
            "seniorDriverFeeDesc": None,
            "youngDriverFeeDesc": None,
            "onlineUser": None,
            "insuranceId": None,
            "agreementCoupon": AGREEMENT_COUPON,
            "TransactionStatusCode": None,
            "PayNowDis": None,
            "isYoungDriverAge": None,
            "isSeniorDriverAge": None,
            "vehicleRequest": {
                "paymentType": FORCE_PAYMENT_TYPE,
                "type": VEHICLE_REQUEST_TYPE,
                "paymentAmount": payment_amount,
                "paymentTransactionTypeCode": PAYMENT_TRANSACTION_TYPE_CODE,
                "voucherNumber": VOUCHER_NUMBER,
            },
        },
        "customer": customer_payload,
        "customerUpdate": CUSTOMER_UPDATE_DATA,
    }

    if USE_EXPLICIT_DRIVERS:
        payload["driver1"] = DRIVER1_DATA
        payload["driver2"] = DRIVER2_DATA
        payload["driver3"] = DRIVER3_DATA

    return payload


# =====================================================================================
# HELPERS RESERVATION LOOKUP BY-CODE
# =====================================================================================

def extract_reservation_code_for_lookup(
    compose_payload: Dict[str, Any],
    compose_response: Dict[str, Any],
    reservation_details_internal: Optional[Dict[str, Any]] = None,
) -> str:
    candidates = [
        compose_response.get("booking_id"),
        nested_get(reservation_details_internal, "booking_id"),
        nested_get(reservation_details_internal, "reservation_web_checkin", "num_pref_code"),
    ]

    value = first_non_empty(*candidates)
    if not value:
        raise RuntimeError("Impossibile determinare reservationCode per il nuovo endpoint by-code")

    return normalize_spaces(str(value))


def extract_customer_email_for_lookup(
    compose_payload: Dict[str, Any],
    compose_response: Dict[str, Any],
    reservation_details_internal: Optional[Dict[str, Any]] = None,
) -> str:
    candidates = [
        nested_get(compose_payload, "customer", "email"),
        nested_get(compose_response, "customer_after_update", "email"),
        nested_get(compose_response, "customer_before_update", "email"),
        nested_get(reservation_details_internal, "customer", "email"),
        nested_get(reservation_details_internal, "booking_detail", "customer_email"),
        nested_get(reservation_details_internal, "reservation_web_checkin", "customer_email"),
    ]

    value = first_non_empty(*candidates)
    if not value:
        raise RuntimeError("Impossibile determinare customerEmail per il nuovo endpoint by-code")

    return str(value).strip().lower()


def extract_reservation_date_for_lookup(
    compose_payload: Dict[str, Any],
    compose_response: Dict[str, Any],
    reservation_details_internal: Optional[Dict[str, Any]] = None,
) -> str:
    candidates = [
        nested_get(compose_payload, "booking", "startDate"),
        nested_get(compose_response, "booking_detail", "pick_up_date_time"),
        nested_get(compose_response, "booking_detail", "pickUpDateTime"),
        nested_get(compose_response, "booking_detail", "pick_up_date"),
        nested_get(compose_response, "booking_detail", "pickUpDate"),
        nested_get(reservation_details_internal, "booking_detail", "pick_up_date_time"),
        nested_get(reservation_details_internal, "booking_detail", "pickUpDateTime"),
        nested_get(reservation_details_internal, "booking_detail", "pick_up_date"),
        nested_get(reservation_details_internal, "booking_detail", "pickUpDate"),
        nested_get(reservation_details_internal, "reservation_web_checkin", "pick_up_date"),
        nested_get(reservation_details_internal, "reservation_web_checkin", "pickUpDate"),
    ]

    for c in candidates:
        value = date_only_from_any(c)
        if value:
            return value

    raise RuntimeError("Impossibile determinare reservationDate per il nuovo endpoint by-code")


# =====================================================================================
# STEP TEST
# =====================================================================================

def test_health() -> Dict[str, Any]:
    hrule("STEP 1 - HEALTH")
    data = request_get("/health")
    jprint(data)
    return data


def test_locations() -> List[Dict[str, Any]]:
    hrule(f"STEP 2 - LOCATIONS (source={SOURCE})")
    data = request_get(
        "/api/v1/touroperator/locations",
        params={"source": SOURCE},
    )

    if not isinstance(data, list):
        raise RuntimeError("Payload locations inatteso: attesa lista")

    print(f"Locations trovate: {len(data)}")
    for i, loc in enumerate(data[:20], start=1):
        code = loc.get("locationCode")
        name = loc.get("locationName")
        city = loc.get("locationCity")
        print(f"  {i:2d}) {code} - {name} ({city})")
    return data


def test_quotations(payload: Dict[str, Any]) -> Dict[str, Any]:
    hrule(f"STEP 3 - QUOTATIONS (source={SOURCE})")
    print("Payload quotations inviato alla wrapper:")
    jprint(payload)

    data = request_post(
        "/api/v1/touroperator/quotations",
        payload,
        params={"source": SOURCE},
    )

    qd = data.get("data") or {}
    vehicles = get_vehicles_from_quote(data)

    print(f"PickUp:  {qd.get('PickUpLocation')}")
    print(f"Return:  {qd.get('ReturnLocation')}")
    print(f"Periodo: {qd.get('PickUpDateTime')} -> {qd.get('ReturnDateTime')}")
    print(f"Veicoli trovati: {qd.get('total')}")

    best = choose_best_available_vehicle(vehicles)
    if best:
        best_vs, est, pre = best
        print(f"Miglior offerta: est/pre = {est} / {pre}")
        print(f"VehicleCode: {get_vehicle_code(best_vs)}")
        print(f"VehicleName: {get_vehicle_name(best_vs)}")
    else:
        print("Nessuna miglior offerta calcolabile")

    print("\nPrime 5 offerte:")
    for idx, vs in enumerate(vehicles[:5], start=1):
        tc = get_vehicle_total_charge(vs)
        print(
            f"  [{idx}] Status={vs.get('Status')} "
            f"VehicleCode={get_vehicle_code(vs)} "
            f"Name={get_vehicle_name(vs)} "
            f"TotalCharge={tc.get('EstimatedTotalAmount')}/{tc.get('RateTotalAmount')} "
            f"Optionals={len(vs.get('optionals') or [])}"
        )

    return data


def test_reservation_compose(payload: Dict[str, Any]) -> Dict[str, Any]:
    hrule(f"STEP 4 - RESERVATION COMPOSE (source={SOURCE})")
    print("Payload compose inviato alla wrapper:")
    jprint(payload)

    data = request_post(
        "/api/v1/touroperator/reservations/compose",
        payload,
        params={"source": SOURCE},
    )

    print("\nRisposta compose:")
    jprint(data)

    print("\nSummary compose:")
    print("booking_id:", data.get("booking_id"))
    print("reservation_id_internal:", data.get("reservation_id_internal"))
    print("customer_id:", data.get("customer_id"))
    print("channel:", data.get("channel"))
    print("used_customer_as_driver1:", data.get("used_customer_as_driver1"))

    return data


def test_reservation_details_by_internal_id(reservation_id: str) -> Dict[str, Any]:
    hrule(f"STEP 5 - RESERVATION DETAILS BY INTERNAL ID ({reservation_id})")
    data = request_get(
        f"/api/v1/touroperator/reservations/{reservation_id}",
        params={"source": SOURCE},
    )

    print("Risposta reservation details (internal id):")
    jprint(data)

    booking_detail = data.get("booking_detail") or {}
    print("\nSummary reservation details (internal id):")
    print("reservation_id_internal:", data.get("reservation_id_internal"))
    print("booking_id:", data.get("booking_id"))
    print("customer_id:", data.get("customer_id"))
    print("booking_detail.id:", booking_detail.get("id"))
    print("booking_detail.db_id:", booking_detail.get("db_id"))
    print("booking_detail.status:", booking_detail.get("status"))
    print("booking_detail.vehicle_code:", booking_detail.get("vehicle_code"))
    print("booking_detail.customer_first_name:", booking_detail.get("customer_first_name"))
    print("booking_detail.customer_last_name:", booking_detail.get("customer_last_name"))

    return data


def test_reservation_details_by_code(
    *,
    reservation_code: str,
    customer_email: str,
    reservation_date: str,
) -> Dict[str, Any]:
    hrule("STEP 6 - RESERVATION DETAILS BY CODE + EMAIL + DATE")

    print("Input nuovo endpoint by-code:")
    print("reservationCode :", reservation_code)
    print("customerEmail   :", customer_email)
    print("reservationDate :", reservation_date)

    data = request_get(
        "/api/v1/touroperator/reservations/details/by-code",
        params={
            "reservationCode": reservation_code,
            "customerEmail": customer_email,
            "reservationDate": reservation_date,
            "source": SOURCE,
        },
    )

    print("Risposta reservation details (by-code):")
    jprint(data)

    booking_detail = data.get("booking_detail") or {}
    print("\nSummary reservation details (by-code):")
    print("reservation_id_internal:", data.get("reservation_id_internal"))
    print("booking_id:", data.get("booking_id"))
    print("customer_id:", data.get("customer_id"))
    print("booking_detail.id:", booking_detail.get("id"))
    print("booking_detail.db_id:", booking_detail.get("db_id"))
    print("booking_detail.status:", booking_detail.get("status"))
    print("booking_detail.vehicle_code:", booking_detail.get("vehicle_code"))
    print("customer_first_name:", data.get("customer_first_name"))
    print("customer_last_name:", data.get("customer_last_name"))
    print("driver1:", data.get("driver1"))
    print("driver2:", data.get("driver2"))
    print("driver3:", data.get("driver3"))

    return data


def print_wrapper_capability_notes() -> None:
    hrule("NOTE CAPACITÀ WRAPPER")
    print(
        "Questa demo wrapper replica il flusso unificato disponibile oggi tramite API wrapper:\n"
        "- health\n"
        "- locations\n"
        "- quotations\n"
        "- vehicles list / detail\n"
        "- create booking + booking detail + customer update + driver handling via /reservations/compose\n"
        "- lettura dettagli reservation via /reservations/{reservation_id}\n"
        "- lettura dettagli reservation via /reservations/details/by-code\n\n"
        "Endpoint diretti NON esposti dalla wrapper corrente, quindi non testati qui:\n"
        "- payments\n"
        "- booking status separato\n"
        "- cancel booking\n"
        "- payment link\n"
        "- privacy policy\n"
    )


# =====================================================================================
# MAIN FLOW
# =====================================================================================

def main() -> None:
    collected: Dict[str, Any] = {}

    try:
        # 1) HEALTH
        collected["health"] = test_health()

        # 2) LOCATIONS
        locations = test_locations()
        collected["locations"] = locations

        location_codes = {
            str(x.get("locationCode")).upper()
            for x in locations
            if isinstance(x, dict) and x.get("locationCode") is not None
        }

        if PICKUP_LOCATION.upper() not in location_codes or DROPOFF_LOCATION.upper() not in location_codes:
            hrule("ATTENZIONE LOCATION")
            print(
                f"Nel flusso stai usando PICKUP={PICKUP_LOCATION}, DROPOFF={DROPOFF_LOCATION}, "
                "ma almeno uno dei due non risulta nella lista locations ritornata dalla wrapper."
            )
            print("Codici presenti:", sorted(location_codes)[:100])

        # 3) QUOTATIONS
        raw_start_dt, raw_end_dt = build_start_end_demo_like()
        quotation_payload = build_quotation_payload(raw_start_dt, raw_end_dt)
        collected["quotation_request"] = quotation_payload

        quotation_response = test_quotations(quotation_payload)
        collected["quotation_response"] = quotation_response

        vehicles = get_vehicles_from_quote(quotation_response)
        if not vehicles:
            raise RuntimeError("Nessun veicolo disponibile dalla quotazione wrapper")

        best = choose_best_available_vehicle(vehicles)
        if not best:
            raise RuntimeError("Impossibile selezionare un veicolo dalla quotazione wrapper")

        best_vs, best_est, best_pre = best
        collected["selected_vehicle"] = best_vs
        collected["selected_vehicle_summary"] = {
            "vehicle_code": get_vehicle_code(best_vs),
            "vehicle_name": get_vehicle_name(best_vs),
            "estimated_total_amount": best_est,
            "rate_total_amount": best_pre,
        }

        # FIX:
        # usa le date della quotation ma SENZA conversione timezone,
        # così compose usa lo stesso wall-clock della quotation
        booking_start_dt, booking_end_dt = extract_quote_canonical_booking_datetimes(
            quotation_response,
            raw_start_dt,
            raw_end_dt,
        )

        hrule("STEP 3B - DATE CANONICHE PER BOOKING")
        print("Date input quotazione:", iso_no_tz_seconds(raw_start_dt), "->", iso_no_tz_seconds(raw_end_dt))
        print("Date booking finali  :", iso_no_tz_seconds(booking_start_dt), "->", iso_no_tz_seconds(booking_end_dt))

        # 4) RESERVATION COMPOSE
        compose_payload = build_compose_payload(
            selected_vehicle=best_vs,
            booking_start_dt=booking_start_dt,
            booking_end_dt=booking_end_dt,
        )
        collected["compose_request"] = compose_payload

        compose_response = test_reservation_compose(compose_payload)
        collected["compose_response"] = compose_response

        reservation_id_internal = compose_response.get("reservation_id_internal")
        if reservation_id_internal is None:
            raise RuntimeError("reservation_id_internal assente nella risposta compose")

        # 5) RESERVATION DETAILS BY INTERNAL ID
        reservation_details_internal: Optional[Dict[str, Any]] = None
        if TEST_INTERNAL_DETAILS_ENDPOINT:
            reservation_details_internal = test_reservation_details_by_internal_id(str(reservation_id_internal))
            collected["reservation_details_by_internal_id"] = reservation_details_internal

        # 6) PREPARAZIONE INPUT PER NUOVO ENDPOINT BY-CODE
        hrule("STEP 5B - DERIVAZIONE INPUT PER ENDPOINT BY-CODE")

        reservation_code = extract_reservation_code_for_lookup(
            compose_payload=compose_payload,
            compose_response=compose_response,
            reservation_details_internal=reservation_details_internal,
        )
        customer_email = extract_customer_email_for_lookup(
            compose_payload=compose_payload,
            compose_response=compose_response,
            reservation_details_internal=reservation_details_internal,
        )
        reservation_date = extract_reservation_date_for_lookup(
            compose_payload=compose_payload,
            compose_response=compose_response,
            reservation_details_internal=reservation_details_internal,
        )

        lookup_inputs = {
            "reservationCode": reservation_code,
            "customerEmail": customer_email,
            "reservationDate": reservation_date,
            "source": SOURCE,
        }
        collected["reservation_by_code_lookup_inputs"] = lookup_inputs

        print("Input derivati:")
        jprint(lookup_inputs)

        # 7) RESERVATION DETAILS BY CODE + EMAIL + DATE
        if TEST_BY_CODE_DETAILS_ENDPOINT:
            reservation_details_by_code = test_reservation_details_by_code(
                reservation_code=reservation_code,
                customer_email=customer_email,
                reservation_date=reservation_date,
            )
            collected["reservation_details_by_code"] = reservation_details_by_code

        # NOTE
        print_wrapper_capability_notes()

        if SAVE_OUTPUT_JSON:
            with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(collected, f, indent=2, ensure_ascii=False, default=str)
            print(f"\n[INFO] Output salvato in {OUTPUT_JSON_PATH}")

        hrule("FINE ✅")
        print("Demo wrapper end-to-end completata con successo.")

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