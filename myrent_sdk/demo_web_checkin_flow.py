from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from myrent_sdk.web_checkin import (
    APIError,
    AuthenticationError,
    CustomerUpdateRequest,
    DriverCreateRequest,
    MyRentWebCheckInClient,
    PaymentLinkRequest,
    ReservationLookupRequest,
    ReservationPrivacyPolicyRequest,
)

# =====================================================================================
# CONFIG
# =====================================================================================

BASE_URL = "https://sul.myrent.it/MyRentWeb"
USER_ID = "bookingservice"
PASSWORD = "123booking"
COMPANY_CODE = "sul"

# Se hai gia un token valido puoi incollarlo qui.
TOKEN_VALUE: Optional[str] = None

# ---- input prenotazione ----
# Opzione A: hai gia reservationId o contractId
KNOWN_RESERVATION_ID: Optional[str] = None
KNOWN_CONTRACT_ID: Optional[str] = None

# Opzione B: devi risolvere la prenotazione via endpoint /api/v2/data/reservation
RESERVATION_NUMBER = "6207"
RESERVATION_PREFIX = "SUL"
RESERVATION_DATE = "2026-03-22"  # yyyy-MM-dd
CONFIRMATION_CODE: Optional[str] = None

# ---- customer ----
FETCH_CUSTOMER = True
CUSTOMER_UPDATE_JSON_PATH: Optional[str] = r"input\customer_update.json"

# ---- guidatori ----
SET_CUSTOMER_AS_DRIVER1 = True
NEW_DRIVER1_JSON_PATH: Optional[str] = r"input\driver1.json"
NEW_DRIVER2_JSON_PATH: Optional[str] = r"input\driver2.json"
NEW_DRIVER3_JSON_PATH: Optional[str] = r"input\driver3.json"

# ---- privacy ----
SET_PRIVACY = False
PRIVACY1 = True
PRIVACY2 = True

# ---- pagamento ----
GENERATE_PAYMENT_LINK = True
PAYMENT_AMOUNT = "70"
PAYMENT_MODE = "Nexi"
IS_CHARGE_OR_DEP = "C"  # C=charge, D=deposit
MYRENT_URL_FOR_PAYMENT = "https://sul.myrent.it/MyRentWeb"
IS_EXTERNAL_BOOK = "N"
DEVICE_ID: Optional[str] = "1"

# ---- output ----
SAVE_OUTPUT_JSON = True
OUTPUT_JSON_PATH = "demo_web_checkin_output.json"


# =====================================================================================
# Helper
# =====================================================================================


def _load_json_file(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"JSON file non trovato: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _pretty(title: str, obj: Any) -> None:
    print(f"\n=== {title} ===")
    if hasattr(obj, "to_dict"):
        data = obj.to_dict()
    elif isinstance(obj, dict):
        data = obj
    else:
        data = getattr(obj, "__dict__", str(obj))
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _coerce_driver_request(path: Optional[str], reservation_id: Optional[str]) -> Optional[DriverCreateRequest]:
    payload = _load_json_file(path)
    if not payload:
        return None

    if reservation_id and "reservationId" not in payload and "reservation_id" not in payload:
        payload["reservation_id"] = reservation_id

    return DriverCreateRequest(
        reservation_id=payload.get("reservation_id") or payload.get("reservationId"),
        first_name=payload["first_name"] if "first_name" in payload else payload["firstName"],
        last_name=payload["last_name"] if "last_name" in payload else payload["lastName"],
        middle_name=payload.get("middle_name") or payload.get("middleName"),
        ragione_sociale=payload.get("ragione_sociale") or payload.get("ragioneSociale"),
        codice=payload.get("codice"),
        street=payload.get("street"),
        num=payload.get("num"),
        city=payload.get("city"),
        zip_code=payload.get("zip_code") or payload.get("zip"),
        country=payload.get("country"),
        state=payload.get("state"),
        ph_num1=payload.get("ph_num1") or payload.get("phNum1"),
        ph_num2=payload.get("ph_num2") or payload.get("phNum2"),
        mobile_number=payload.get("mobile_number") or payload.get("mobileNumber"),
        email=payload.get("email"),
        vat_number=payload.get("vat_number") or payload.get("vatNumber"),
        birth_place=payload.get("birth_place") or payload.get("birthPlace"),
        birth_date=payload.get("birth_date") or payload.get("birthDate"),
        birth_province=payload.get("birth_province") or payload.get("birthProvince"),
        birth_nation=payload.get("birth_nation") or payload.get("birthNation"),
        gender=payload.get("gender"),
        tax_code=payload.get("tax_code") or payload.get("taxCode"),
        document=payload.get("document"),
        document2=payload.get("document2"),
        document_number=payload.get("document_number") or payload.get("documentNumber"),
        document_number2=payload.get("document_number2") or payload.get("documentNumber2"),
        licence_type=payload.get("licence_type") or payload.get("licenceType"),
        issue_by=payload.get("issue_by") or payload.get("issueBy"),
        issue_by2=payload.get("issue_by2") or payload.get("issueBy2"),
        release_date=payload.get("release_date") or payload.get("releaseDate"),
        release_date2=payload.get("release_date2") or payload.get("releaseDate2"),
        expiry_date=payload.get("expiry_date") or payload.get("expiryDate"),
        expiry_date2=payload.get("expiry_date2") or payload.get("expiryDate2"),
    )


# =====================================================================================
# Demo flow
# =====================================================================================


def main() -> None:
    client = MyRentWebCheckInClient(
        base_url=BASE_URL,
        user_id=USER_ID,
        password=PASSWORD,
        company_code=COMPANY_CODE,
        token_value=TOKEN_VALUE,
        portal_auth_mode="token_then_basic",
    )

    collected: Dict[str, Any] = {}

    try:
        if TOKEN_VALUE:
            print("[INFO] Uso token_value preesistente.")
            token = TOKEN_VALUE
        else:
            auth = client.authenticate_for_web_checkin()
            token = auth.token_value
            collected["auth"] = auth.to_dict()
            print(f"[INFO] Token ottenuto dal flow auth: {token[:10]}...")

        reservation = None
        reservation_id = KNOWN_RESERVATION_ID
        customer_id = None

        if not reservation_id and RESERVATION_NUMBER and RESERVATION_PREFIX and RESERVATION_DATE:
            reservation = client.search_reservation(
                ReservationLookupRequest(
                    reservation_number=RESERVATION_NUMBER,
                    reservation_prefix=RESERVATION_PREFIX,
                    reservation_date=RESERVATION_DATE,
                    confirmation_code=CONFIRMATION_CODE,
                )
            ).ensure_success()
            reservation_id = str(reservation.reservation_id) if reservation.reservation_id is not None else None
            customer_id = reservation.customer_id
            collected["reservation_search"] = reservation.to_dict()
            _pretty("reservation_search", reservation)

        elif reservation_id:
            print(f"[INFO] Uso reservationId gia noto: {reservation_id}")

        else:
            print("[WARN] Nessun reservationId noto e nessun input sufficiente per search_reservation().")

        if customer_id is None and reservation is not None:
            customer_id = reservation.customer_id

        if FETCH_CUSTOMER and customer_id is not None:
            customer = client.get_customer(customer_id).ensure_success()
            collected["customer"] = customer.to_payload(include_status=True)
            _pretty("customer", customer)
        elif FETCH_CUSTOMER:
            print("[WARN] Customer fetch saltato: customerId non disponibile.")

        if CUSTOMER_UPDATE_JSON_PATH and customer_id is not None:
            patch = _load_json_file(CUSTOMER_UPDATE_JSON_PATH) or {}
            update_req = (
                CustomerUpdateRequest.from_api_dict(patch)
                if hasattr(CustomerUpdateRequest, "from_api_dict")
                else CustomerUpdateRequest(**patch)
            )
            updated_customer = client.update_customer(customer_id, update_req).ensure_success()
            collected["customer_updated"] = updated_customer.to_payload(include_status=True)
            _pretty("customer_updated", updated_customer)
        elif CUSTOMER_UPDATE_JSON_PATH:
            print("[WARN] Customer update saltato: customerId non disponibile.")

        if SET_CUSTOMER_AS_DRIVER1:
            if not reservation_id:
                raise ValueError("SET_CUSTOMER_AS_DRIVER1=True ma reservation_id non disponibile")
            res = client.set_customer_as_driver1(reservation_id).ensure_success()
            collected["set_customer_as_driver1"] = res.to_dict()
            _pretty("set_customer_as_driver1", res)

        drv1 = _coerce_driver_request(NEW_DRIVER1_JSON_PATH, reservation_id)
        if drv1 is not None:
            res = client.insert_new_driver1(drv1).ensure_success()
            collected["insert_new_driver1"] = res.to_dict()
            _pretty("insert_new_driver1", res)

        drv2 = _coerce_driver_request(NEW_DRIVER2_JSON_PATH, reservation_id)
        if drv2 is not None:
            res = client.insert_new_driver2(drv2).ensure_success()
            collected["insert_new_driver2"] = res.to_dict()
            _pretty("insert_new_driver2", res)

        drv3 = _coerce_driver_request(NEW_DRIVER3_JSON_PATH, reservation_id)
        if drv3 is not None:
            res = client.insert_new_driver3(drv3).ensure_success()
            collected["insert_new_driver3"] = res.to_dict()
            _pretty("insert_new_driver3", res)

        if SET_PRIVACY:
            if not reservation_id:
                raise ValueError("SET_PRIVACY=True ma reservation_id non disponibile")
            privacy_res = client.set_reservation_privacy_policy(
                ReservationPrivacyPolicyRequest(
                    reservation_id=reservation_id,
                    privacy1=PRIVACY1,
                    privacy2=PRIVACY2,
                )
            ).ensure_success()
            collected["privacy"] = privacy_res.to_dict()
            _pretty("privacy", privacy_res)

        if GENERATE_PAYMENT_LINK:
            if not reservation_id and not KNOWN_CONTRACT_ID:
                raise ValueError("Per il payment link serve reservation_id oppure contract_id")

            payment_res = client.get_payment_link(
                PaymentLinkRequest(
                    is_charge_or_dep=IS_CHARGE_OR_DEP,
                    myrent_url=MYRENT_URL_FOR_PAYMENT,
                    contract_id=KNOWN_CONTRACT_ID,
                    amount=PAYMENT_AMOUNT,
                    reservation_id=reservation_id,
                    device_id=DEVICE_ID,
                    payment_mode=PAYMENT_MODE,
                    is_external_book=IS_EXTERNAL_BOOK,
                )
            )

            collected["payment_link"] = payment_res.to_dict()
            _pretty("payment_link", payment_res)

            resolved_payment_url = (
                payment_res.payment_url
                or (payment_res.raw.get("generateLink") if isinstance(payment_res.raw, dict) else None)
                or (payment_res.raw.get("paymentUrl") if isinstance(payment_res.raw, dict) else None)
                or (payment_res.raw.get("paymentURL") if isinstance(payment_res.raw, dict) else None)
            )

            if resolved_payment_url and isinstance(payment_res.raw, dict):
                collected["payment_link"]["payment_url"] = resolved_payment_url

            if payment_res.is_success:
                if resolved_payment_url:
                    print(f"\n[OK] paymentUrl: {resolved_payment_url}")
                else:
                    print("\n[WARN] link pagamento generato ma URL non presente nei campi attesi della risposta")
            else:
                print(f"\n[WARN] pagamento non generato: {payment_res.message or payment_res.status}")

        if SAVE_OUTPUT_JSON:
            Path(OUTPUT_JSON_PATH).write_text(
                json.dumps(collected, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"\n[INFO] Output salvato in {OUTPUT_JSON_PATH}")

    except (AuthenticationError, APIError, ValueError, FileNotFoundError, KeyError) as exc:
        print(f"\n[ERROR] {type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()


# =====================================================================================
# Esempio customer update JSON
# =====================================================================================
# {
#   "status": "success",
#   "firstName": "PAOLO",
#   "lastName": "ROSSI",
#   "street": "VIA GARIBALDI",
#   "num": "5",
#   "city": "ROMA",
#   "zip": "00010",
#   "country": "ITALIA",
#   "state": "RM",
#   "phNum1": "3821299900",
#   "email": "test@123.com",
#   "birthDate": "1960-02-17",
#   "taxCode": "GVN000000000001B",
#   "document": "PATENTE",
#   "documentNumber": "DC00000000",
#   "licenceType": "B",
#   "issueBy": "ROMA",
#   "releaseDate": "2015-02-09",
#   "expiryDate": "2024-02-25",
#   "isPhysicalPerson": false,
#   "isIndividualCompany": true
# }
#
# Esempio new driver JSON
# {
#   "firstName": "info",
#   "lastName": "Dogma",
#   "middleName": "DogmaSystemInfoDriver3",
#   "codice": 6,
#   "phNum1": "2",
#   "mobileNumber": "12345",
#   "email": "info@dogmasystems.com",
#   "gender": true,
#   "document2": "test",
#   "documentNumber2": "test1",
#   "issueBy2": "test3"
# }