from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Optional

from myrent_sdk.main import (
    MyRentClient,
    LocationType,
    QuotationRequest,
    PaymentsRequest,
    BookingRequest,
    BookingCustomer,
    BookingVehicleRequest,
    APIError,
    AuthenticationError,
)

# =====================================================================================
# CONFIG
# =====================================================================================

BASE_URL = "https://sul.myrent.it/MyRentWeb"
USER_ID = "bookingservice"
PASSWORD = "123booking"
COMPANY_CODE = "sul"

PICKUP_LOCATION = "BRI"
DROPOFF_LOCATION = "BRI"

CHANNEL = "RENTAL_PREMIUM_POA"  # oppure "RENTAL_PREMIUM_PREPAID" se abilitato lato MyRent
DRIVER_AGE = 35

START_DT = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=5)
END_DT = START_DT + timedelta(days=3)

FORCE_PAYMENT_TYPE = None  # es. "BONIFICO"

CREATE_BOOKING = True
CANCEL_BOOKING = True

ROME_TZ = ZoneInfo("Europe/Rome")


# =====================================================================================
# DEBUG CLIENT (non modifica l'SDK: ma ti fa vedere 429/5xx con body)
# =====================================================================================

class DebugMyRentClient(MyRentClient):
    def _request(self, method: str, path: str, *, headers=None, json_body=None, params=None):
        import json as _json
        import requests as _requests

        url = self.base_url + path
        attempt = 0
        last_exc: Optional[Exception] = None
        last_retryable_http: Optional[dict] = None

        while attempt <= self.max_retries:
            try:
                resp = self.session.request(
                    method=method.upper(),
                    url=url,
                    headers=self._headers(headers),
                    json=json_body,
                    params=params,
                    timeout=self.timeout,
                )

                if 200 <= resp.status_code < 300:
                    return resp

                if resp.status_code == 401:
                    try:
                        payload = resp.json()
                    except Exception:
                        payload = {"raw": resp.text}
                    raise AuthenticationError(
                        f"HTTP 401 {method} {url}: token non valido/scaduto | payload={_json.dumps(payload)[:800]}"
                    )

                if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                    try:
                        body = resp.json()
                    except Exception:
                        body = resp.text

                    last_retryable_http = {
                        "status": resp.status_code,
                        "body": body if isinstance(body, (dict, list)) else str(body)[:1500],
                    }

                    print(
                        f"[DEBUG] Retryable HTTP {resp.status_code} on {method.upper()} {url} "
                        f"(attempt {attempt+1}/{self.max_retries+1})"
                    )
                    if isinstance(last_retryable_http["body"], (dict, list)):
                        print("[DEBUG] body:", _json.dumps(last_retryable_http["body"], ensure_ascii=False)[:1200])
                    else:
                        print("[DEBUG] body:", str(last_retryable_http["body"])[:1200])

                    self._sleep_backoff(attempt)
                    attempt += 1
                    continue

                try:
                    payload = resp.json()
                except Exception:
                    payload = {"raw": resp.text}
                raise APIError(f"HTTP {resp.status_code} {method} {url}: {_json.dumps(payload)[:1200]}")

            except (_requests.Timeout, _requests.ConnectionError) as exc:
                last_exc = exc
                self._sleep_backoff(attempt)
                attempt += 1
                continue

        if last_exc:
            raise APIError(f"Request fallita dopo {self.max_retries+1} tentativi: {last_exc}") from last_exc
        if last_retryable_http:
            raise APIError(
                f"Request fallita dopo {self.max_retries+1} tentativi. "
                f"Ultimo HTTP retryable={last_retryable_http['status']} body={last_retryable_http['body']}"
            )
        raise APIError("Request fallita dopo i tentativi massimi.")


# =====================================================================================
# Helper
# =====================================================================================

def _safe_get(d: Any, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _to_dict(obj: Any) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            return {}
    return {}


def _parse_iso_dt(s: str) -> Optional[datetime]:
    """
    Parsea stringhe tipo:
    - 2026-01-07T12:00:00.000Z
    - 2026-01-07T12:00:00Z
    - 2026-01-07T12:00:00+00:00
    """
    if not isinstance(s, str) or not s.strip():
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        # prova a togliere i millisecondi se presente
        if "." in s:
            s2 = s.split(".")[0] + s[s.find("+"):] if "+" in s else s.split(".")[0]
            try:
                return datetime.fromisoformat(s2)
            except Exception:
                return None
        return None


def _extract_quote_canonical_datetimes(quote_obj: Any) -> tuple[Optional[datetime], Optional[datetime]]:
    qd = _to_dict(quote_obj)
    q0 = _safe_get(qd, "data", "quotation", default=[])
    if not (isinstance(q0, list) and q0 and isinstance(q0[0], dict)):
        return None, None
    pu = _parse_iso_dt(q0[0].get("PickUpDateTime", ""))
    ret = _parse_iso_dt(q0[0].get("ReturnDateTime", ""))
    return pu, ret


def _canonical_to_local_naive(dt_utc_aware: datetime) -> datetime:
    """
    Converte datetime aware (UTC) -> ora Europa/Roma (naive) da inviare a MyRent.
    """
    return dt_utc_aware.astimezone(ROME_TZ).replace(tzinfo=None)


def _flatten_quotation_to_vehicle_list(quote_obj: Any) -> list[dict]:
    # via oggetti SDK
    qdata = getattr(quote_obj, "data", None)
    qlist = getattr(qdata, "quotation", None)
    if isinstance(qlist, list) and qlist:
        qi0 = qlist[0]
        vs = getattr(qi0, "vehicles", None)
        if isinstance(vs, list):
            return [v for v in vs if isinstance(v, dict)]

    # fallback via to_dict
    qd = _to_dict(quote_obj)
    quotation = _safe_get(qd, "data", "quotation", default=[])
    if isinstance(quotation, list) and quotation and isinstance(quotation[0], dict):
        vs = quotation[0].get("Vehicles") or []
        if isinstance(vs, list):
            return [v for v in vs if isinstance(v, dict)]
    return []


def _extract_vehicle_code(vehicle: dict) -> Optional[str]:
    vc = _safe_get(vehicle, "Vehicle", "Code")
    if isinstance(vc, str) and vc.strip():
        return vc.strip()
    vc2 = _safe_get(vehicle, "Vehicle", "groupPic", "internationalCode")
    if isinstance(vc2, str) and vc2.strip():
        return vc2.strip()
    return None


def _normalize_optional_dict(o: dict) -> Optional[dict]:
    """
    MyRent booking vuole SOLO questi campi.
    EquipType di solito sta in:
      - o["EquipType"]
      - o["Equipment"]["EquipType"]
    """
    equip_type = o.get("EquipType") or _safe_get(o, "Equipment", "EquipType") or _safe_get(o, "Equipment", "equipType")
    if not equip_type:
        return None

    qty = o.get("Quantity") or _safe_get(o, "Equipment", "Quantity") or 1
    try:
        qty = int(qty)
    except Exception:
        qty = 1
    if qty <= 0:
        qty = 1

    prepaid = o.get("Prepaid")
    if prepaid is None:
        prepaid = False

    # se lo includiamo, deve essere Selected=True
    return {
        "EquipType": str(equip_type),
        "Quantity": qty,
        "Selected": True,
        "Prepaid": bool(prepaid),
    }


def _extract_required_optionals_for_booking(vehicle: dict) -> list[dict]:
    """
    Include:
    - quelli già Selected=True
    - quelli "inclusi in tariffa": Charge.IncludedInRate / IncludedInEstTotalInd
    Restituisce optionals NORMALIZZATI (minimi) -> evita 500.
    """
    opts = vehicle.get("optionals")
    if not isinstance(opts, list):
        return []

    out: list[dict] = []
    for o in opts:
        if not isinstance(o, dict):
            continue
        charge = o.get("Charge") if isinstance(o.get("Charge"), dict) else {}
        must_include = (
            o.get("Selected") is True
            or charge.get("IncludedInRate") is True
            or charge.get("IncludedInEstTotalInd") is True
        )
        if not must_include:
            continue
        nd = _normalize_optional_dict(o)
        if nd:
            out.append(nd)
    return out


def _make_birth_date_iso(start_dt: datetime, driver_age: int) -> str:
    year = start_dt.year - driver_age
    bd = datetime(year, start_dt.month, min(start_dt.day, 28), 0, 0, 0)
    return bd.isoformat(timespec="seconds")


def _choose_payment_type(pay_resp_obj: Any) -> Optional[str]:
    if FORCE_PAYMENT_TYPE:
        return str(FORCE_PAYMENT_TYPE)

    d = _to_dict(pay_resp_obj)
    raw = d.get("raw") or d.get("data") or d
    if not isinstance(raw, dict) or not raw:
        return None

    keys = {k.lower() for k in raw.keys()}
    if "wiretransfer" in keys or "wire_transfer" in keys:
        return "BONIFICO"
    if any("paypal" in k for k in keys):
        return "PayPal"
    if any("nexi" in k for k in keys):
        return "CREDITCARDDEFERRED"
    if any("stripe" in k for k in keys):
        return "CREDITCARDDEFERRED"
    return "BONIFICO"


def _extract_error(booking_resp: Any) -> tuple[Optional[int], Optional[str]]:
    raw = getattr(booking_resp, "raw", None)
    if not isinstance(raw, dict):
        raw = _to_dict(booking_resp)
    err = _safe_get(raw, "data", "errors", "Error")
    if isinstance(err, dict):
        code = err.get("Code")
        txt = err.get("ShortText")
        try:
            code = int(code)
        except Exception:
            pass
        return code if isinstance(code, int) else None, txt if isinstance(txt, str) else None
    return None, None


# =====================================================================================
# FLOW
# =====================================================================================

def main():
    client = DebugMyRentClient(
        base_url=BASE_URL,
        user_id=USER_ID,
        password=PASSWORD,
        company_code=COMPANY_CODE,
        max_retries=1,       # tienilo basso: vedi subito gli errori veri
        backoff_factor=0.3,
        timeout=30,
    )

    auth = client.authenticate()
    print("\n=== 1) AUTHENTICATION ===")
    print("Token:", auth.token_value)

    print("\n=== 2) LOCATIONS ===")
    locs = client.get_locations()
    print("Totale locations:", len(locs))
    for l in locs:
        print(" -", l.location_code, l.location_name, "type:", l.location_type)

    pickups = client.get_locations_by_type(LocationType.BOOKING_PICKUP)
    print("Locations pickup (filter SDK):", len(pickups), "(ok: type=3 è BOTH)")

    print("\n=== 3) QUOTATIONS ===")
    req = QuotationRequest(
        pickup_location=PICKUP_LOCATION,
        drop_off_location=DROPOFF_LOCATION,
        start_date=START_DT,
        end_date=END_DT,
        age=DRIVER_AGE,
        channel=CHANNEL,
        show_pics=True,
        show_optional_image=True,
        show_vehicle_parameter=True,
        show_vehicle_extra_image=False,
        agreement_coupon=None,
        discount_value_without_vat="0",
        show_booking_discount=True,
    )

    quote = client.get_quotations(req)

    #print(quote.to_dict())

    canonical_start, canonical_end = _extract_quote_canonical_datetimes(quote)
    if canonical_start and canonical_end:
        # >>> FIX: UTC aware -> ora locale (naive) per booking
        booking_start_dt = _canonical_to_local_naive(canonical_start)
        booking_end_dt = _canonical_to_local_naive(canonical_end)
        print("Canonical dates from quote (UTC):", canonical_start, "->", canonical_end)
        print("Booking dates (Europe/Rome naive):", booking_start_dt, "->", booking_end_dt)
    else:
        booking_start_dt = START_DT
        booking_end_dt = END_DT
        print("Canonical dates NOT found, fallback:", booking_start_dt, "->", booking_end_dt)

    vehicles = _flatten_quotation_to_vehicle_list(quote)
    print("Numero veicoli estratti:", len(vehicles))
    if not vehicles:
        raise RuntimeError("Nessun veicolo disponibile dalla quotazione.")

    for i, v in enumerate(vehicles[:5], start=1):
        vc = _extract_vehicle_code(v)
        rate_total = (v.get("TotalCharge") or {}).get("RateTotalAmount")
        print(f"  [{i}] Status={v.get('Status')} VehicleCode={vc} RateTotal={rate_total}")

    print("\n=== 4) PAYMENTS ===")
    pay_resp = client.payments(PaymentsRequest(language="it"))
    payment_type = _choose_payment_type(pay_resp)
    if payment_type:
        print("PaymentType scelto:", payment_type)
    else:
        print("Payments vuoti -> POA tipico, non imposto PaymentType")

    print("\n=== 5) CREATE BOOKING ===")
    if not CREATE_BOOKING:
        print("CREATE_BOOKING=False -> skip.")
        return

    birth_date_iso = _make_birth_date_iso(booking_start_dt, DRIVER_AGE)

    booking_id = None
    last_error = None

    for idx, vehicle in enumerate(vehicles, start=1):
        if str(vehicle.get("Status", "")).lower() != "available":
            continue

        vehicle_code = _extract_vehicle_code(vehicle)
        if not vehicle_code:
            continue

        # >>> FIX: optionals MINIMI (no dict enormi)
        optionals = _extract_required_optionals_for_booking(vehicle)

        # VehicleRequest: includilo SOLO se hai un payment_type
        vehicle_request = BookingVehicleRequest(payment_type=payment_type) if payment_type else None

        booking_req = BookingRequest(
            pickup_location=PICKUP_LOCATION,
            drop_off_location=DROPOFF_LOCATION,
            start_date=booking_start_dt,
            end_date=booking_end_dt,
            vehicle_code=vehicle_code,
            channel=CHANNEL,
            optionals=optionals,
            customer=BookingCustomer(
                first_name="Mario",
                last_name="Rossi",
                email="mario.rossi@example.com",
                mobile_number="+393331234567",
                country="IT",
                city="Bari",
                zip="70121",
                street="Via Roma",
                num="1",
                tax_code="RSSMRA80A01H501U",
                birth_date=birth_date_iso,
                birth_place="Bari",
                birth_province="BA",
            ),
            vehicle_request=vehicle_request,
        )

        print(f"\nTentativo booking [{idx}/{len(vehicles)}] VehicleCode={vehicle_code} optionals={len(optionals)} paymentType={payment_type}")

        try:
            booking_resp = client.create_booking(booking_req)
        except APIError as e:
            last_error = ("HTTP/APIError", str(e))
            print("  -> APIError:", e)
            # prova comunque con altra categoria (spesso una passa)
            continue

        code, txt = _extract_error(booking_resp)
        if code:
            last_error = (code, txt)
            print(f"  -> ERRORE MyRent Code={code}: {txt}")
            continue

        if booking_resp.data and booking_resp.data[0].id:
            booking_id = booking_resp.data[0].id
            print("  -> SUCCESS BookingId:", booking_id)
            break

        last_error = ("NO_ID", getattr(booking_resp, "raw", None))
        print("  -> risposta senza errori ma ID mancante, provo prossima categoria...")

    if not booking_id:
        raise RuntimeError(f"Booking non creato. Ultimo errore: {last_error}")

    print("\n=== 6) GET BOOKING (DETAIL) ===")
    booking_detail = client.get_booking(booking_id, channel=CHANNEL)
    print("GetBooking items:", len(booking_detail.data))
    if booking_detail.data:
        print("GetBooking first id:", booking_detail.data[0].id)

    print("\n=== 7) GET BOOKING STATUS ===")
    st = client.get_booking_status(booking_id)
    print("Status id:", st.id)
    print("Status:", st.status)

    print("\n=== 8) CANCEL BOOKING ===")
    if not CANCEL_BOOKING:
        print("CANCEL_BOOKING=False -> skip.")
        return

    cancel = client.cancel_booking(booking_id, channel=CHANNEL)
    print("Cancel id:", cancel.id)
    print("Cancel status:", cancel.cancel_status)

    print("\n=== DEMO COMPLETATA ===")


if __name__ == "__main__":
    main()
