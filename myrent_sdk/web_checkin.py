from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import json
import logging
import time

import requests


__all__ = [
    "MyRentError",
    "AuthenticationError",
    "APIError",
    "AuthResult",
    "MyRentWebCheckInClient",
    "ReservationLookupRequest",
    "ReservationVoucherSearchRequest",
    "ReservationCustomerLocationSearchRequest",
    "CustomerProfile",
    "CustomerUpdateRequest",
    "DriverCreateRequest",
    "ReservationPrivacyPolicyRequest",
    "PaymentLinkRequest",
    "ReservationRecord",
    "ReservationListResponse",
    "PaymentLinkResponse",
]


# =====================================================================================
# Eccezioni
# =====================================================================================


class MyRentError(Exception):
    """Base exception per MyRent Web Check-In SDK."""


class AuthenticationError(MyRentError):
    """Autenticazione fallita o token assente/scaduto."""


class APIError(MyRentError):
    """Errore HTTP/API o payload inatteso."""


# =====================================================================================
# Helper
# =====================================================================================


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return str(value)


def _coerce_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "t", "1", "yes", "y"}:
            return True
        if s in {"false", "f", "0", "no", "n"}:
            return False
    return None


def _coerce_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return int(v)
    except Exception:
        return None


def _coerce_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _to_form_body(d: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        else:
            out[k] = v
    return out


def _json_dumps_body(d: Dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"), default=str)


# =====================================================================================
# Schemi auth
# =====================================================================================


@dataclass(frozen=True)
class AuthResult:
    user_id: int
    username: str
    token_value: str
    user_role: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_payload(payload: Dict[str, Any]) -> "AuthResult":
        result = payload.get("result") or payload.get("Result") or {}
        token = (
            result.get("tokenValue")
            or result.get("TokenValue")
            or result.get("token")
            or result.get("Token")
        )
        if not token:
            raise AuthenticationError(f"Manca tokenValue nella risposta: {payload}")

        return AuthResult(
            user_id=_coerce_int(result.get("user_id")) or 0,
            username=str(result.get("username", "")),
            token_value=str(token),
            user_role=_stringify(result.get("userRole")),
            raw=payload,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =====================================================================================
# Request DTO
# =====================================================================================


@dataclass
class ReservationLookupRequest:
    reservation_number: str
    reservation_prefix: str
    reservation_date: str
    confirmation_code: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "reservationNumber": str(self.reservation_number),
            "reservationPrefix": str(self.reservation_prefix),
            "reservationDate": str(self.reservation_date),
        }
        if self.confirmation_code:
            payload["confirmationCode"] = str(self.confirmation_code)
        return payload


@dataclass
class ReservationVoucherSearchRequest:
    reservation_voucher: str
    customer_first_name: Optional[str] = None
    customer_last_name: Optional[str] = None
    company_name: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        payload = {"reservationVoucher": str(self.reservation_voucher)}
        if self.customer_first_name is not None:
            payload["customerFirstName"] = str(self.customer_first_name)
        if self.customer_last_name is not None:
            payload["customerLastName"] = str(self.customer_last_name)
        if self.company_name is not None:
            payload["companyName"] = str(self.company_name)
        return payload


@dataclass
class ReservationCustomerLocationSearchRequest:
    res_customer_name: str
    res_customer_surname: str
    res_location_pick_up: str
    res_pick_up_date: str

    def to_payload(self) -> Dict[str, Any]:
        return {
            "resCustomerName": str(self.res_customer_name),
            "resCustomerSurname": str(self.res_customer_surname),
            "resLocationPickUp": str(self.res_location_pick_up),
            "resPickUpDate": str(self.res_pick_up_date),
        }


@dataclass
class CustomerProfile:
    status: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    ragione_sociale: Optional[str] = None
    codice: Optional[str] = None
    street: Optional[str] = None
    num: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    ph_num1: Optional[str] = None
    ph_num2: Optional[str] = None
    mobile_number: Optional[str] = None
    email: Optional[str] = None
    vat_number: Optional[str] = None
    birth_place: Optional[str] = None
    birth_date: Optional[str] = None
    birth_province: Optional[str] = None
    birth_nation: Optional[str] = None
    gender: Optional[bool] = None
    tax_code: Optional[str] = None
    document: Optional[str] = None
    document_number: Optional[str] = None
    licence_type: Optional[str] = None
    issue_by: Optional[str] = None
    document2: Optional[str] = None
    document_number2: Optional[str] = None
    issue_by2: Optional[str] = None
    e_invoice_email: Optional[str] = None
    e_invoice_code: Optional[str] = None
    release_date: Optional[str] = None
    expiry_date: Optional[str] = None
    release_date2: Optional[str] = None
    expiry_date2: Optional[str] = None
    is_physical_person: Optional[bool] = None
    is_individual_company: Optional[bool] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_dict(cls, data: Dict[str, Any]) -> "CustomerProfile":
        return cls(
            status=_stringify(data.get("status")),
            first_name=_stringify(data.get("firstName")),
            middle_name=_stringify(data.get("middleName")),
            last_name=_stringify(data.get("lastName")),
            ragione_sociale=_stringify(data.get("ragioneSociale")),
            codice=_stringify(data.get("codice")),
            street=_stringify(data.get("street")),
            num=_stringify(data.get("num")),
            city=_stringify(data.get("city")),
            zip_code=_stringify(data.get("zip")),
            country=_stringify(data.get("country")),
            state=_stringify(data.get("state")),
            ph_num1=_stringify(data.get("phNum1")),
            ph_num2=_stringify(data.get("phNum2")),
            mobile_number=_stringify(data.get("mobileNumber")),
            email=_stringify(data.get("email")),
            vat_number=_stringify(data.get("vatNumber")),
            birth_place=_stringify(data.get("birthPlace")),
            birth_date=_stringify(data.get("birthDate")),
            birth_province=_stringify(data.get("birthProvince")),
            birth_nation=_stringify(data.get("birthNation")),
            gender=_coerce_bool(data.get("gender")),
            tax_code=_stringify(data.get("taxCode")),
            document=_stringify(data.get("document")),
            document_number=_stringify(data.get("documentNumber")),
            licence_type=_stringify(data.get("licenceType")),
            issue_by=_stringify(data.get("issueBy")),
            document2=_stringify(data.get("document2")),
            document_number2=_stringify(data.get("documentNumber2")),
            issue_by2=_stringify(data.get("issueBy2")),
            e_invoice_email=_stringify(data.get("eInvoiceEmail")),
            e_invoice_code=_stringify(data.get("eInvoiceCode")),
            release_date=_stringify(data.get("releaseDate")),
            expiry_date=_stringify(data.get("expiryDate")),
            release_date2=_stringify(data.get("releaseDate2")),
            expiry_date2=_stringify(data.get("expiryDate2")),
            is_physical_person=_coerce_bool(data.get("isPhysicalPerson")),
            is_individual_company=_coerce_bool(data.get("isIndividualCompany")),
            raw=data,
        )

    def to_payload(self, include_status: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "firstName": self.first_name,
            "middleName": self.middle_name,
            "lastName": self.last_name,
            "ragioneSociale": self.ragione_sociale,
            "codice": self.codice,
            "street": self.street,
            "num": self.num,
            "city": self.city,
            "zip": self.zip_code,
            "country": self.country,
            "state": self.state,
            "phNum1": self.ph_num1,
            "phNum2": self.ph_num2,
            "mobileNumber": self.mobile_number,
            "email": self.email,
            "vatNumber": self.vat_number,
            "birthPlace": self.birth_place,
            "birthDate": self.birth_date,
            "birthProvince": self.birth_province,
            "birthNation": self.birth_nation,
            "gender": self.gender,
            "taxCode": self.tax_code,
            "document": self.document,
            "documentNumber": self.document_number,
            "licenceType": self.licence_type,
            "issueBy": self.issue_by,
            "document2": self.document2,
            "documentNumber2": self.document_number2,
            "issueBy2": self.issue_by2,
            "eInvoiceEmail": self.e_invoice_email,
            "eInvoiceCode": self.e_invoice_code,
            "releaseDate": self.release_date,
            "expiryDate": self.expiry_date,
            "releaseDate2": self.release_date2,
            "expiryDate2": self.expiry_date2,
            "isPhysicalPerson": self.is_physical_person,
            "isIndividualCompany": self.is_individual_company,
        }
        if include_status and self.status is not None:
            payload["status"] = self.status
        return _drop_none(payload)

    def ensure_success(self) -> "CustomerProfile":
        if self.status and self.status.lower() == "error":
            raise APIError(f"Customer operation returned status=error | payload={self.raw}")
        return self


@dataclass
class CustomerUpdateRequest(CustomerProfile):
    pass


@dataclass
class DriverCreateRequest:
    reservation_id: Union[str, int]
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    ragione_sociale: Optional[str] = None
    codice: Optional[Union[str, int]] = None
    street: Optional[str] = None
    num: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    ph_num1: Optional[str] = None
    ph_num2: Optional[str] = None
    mobile_number: Optional[str] = None
    email: Optional[str] = None
    vat_number: Optional[str] = None
    birth_place: Optional[str] = None
    birth_date: Optional[str] = None
    birth_province: Optional[str] = None
    birth_nation: Optional[str] = None
    gender: Optional[bool] = None
    tax_code: Optional[str] = None
    document: Optional[str] = None
    document2: Optional[str] = None
    document_number: Optional[str] = None
    document_number2: Optional[str] = None
    licence_type: Optional[str] = None
    issue_by: Optional[str] = None
    issue_by2: Optional[str] = None
    release_date: Optional[str] = None
    release_date2: Optional[str] = None
    expiry_date: Optional[str] = None
    expiry_date2: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        return _drop_none({
            "reservationId": str(self.reservation_id),
            "firstName": self.first_name,
            "lastName": self.last_name,
            "middleName": self.middle_name,
            "ragioneSociale": self.ragione_sociale,
            "codice": self.codice,
            "street": self.street,
            "num": self.num,
            "city": self.city,
            "zip": self.zip_code,
            "country": self.country,
            "state": self.state,
            "phNum1": self.ph_num1,
            "phNum2": self.ph_num2,
            "mobileNumber": self.mobile_number,
            "email": self.email,
            "vatNumber": self.vat_number,
            "birthPlace": self.birth_place,
            "birthDate": self.birth_date,
            "birthProvince": self.birth_province,
            "birthNation": self.birth_nation,
            "gender": self.gender,
            "taxCode": self.tax_code,
            "document": self.document,
            "document2": self.document2,
            "documentNumber": self.document_number,
            "documentNumber2": self.document_number2,
            "licenceType": self.licence_type,
            "issueBy": self.issue_by,
            "issueBy2": self.issue_by2,
            "releaseDate": self.release_date,
            "releaseDate2": self.release_date2,
            "expiryDate": self.expiry_date,
            "expiryDate2": self.expiry_date2,
        })


@dataclass
class ReservationPrivacyPolicyRequest:
    reservation_id: Union[str, int]
    privacy1: Union[bool, str]
    privacy2: Union[bool, str]

    def to_payload(self) -> Dict[str, Any]:
        p1 = self.privacy1
        p2 = self.privacy2
        if isinstance(p1, bool):
            p1 = "true" if p1 else "false"
        if isinstance(p2, bool):
            p2 = "true" if p2 else "false"
        return {
            "reservationId": str(self.reservation_id),
            "privacy1": str(p1).lower(),
            "privacy2": str(p2).lower(),
        }


@dataclass
class PaymentLinkRequest:
    is_charge_or_dep: str
    myrent_url: str
    amount: Union[int, float, str]
    payment_mode: str
    reservation_id: Optional[Union[str, int]] = None
    contract_id: Optional[Union[str, int]] = None
    device_id: Optional[Union[str, int]] = None
    is_external_book: str = "N"

    def validate(self) -> None:
        mode = str(self.is_charge_or_dep).upper().strip()
        if mode not in {"C", "D"}:
            raise ValueError("is_charge_or_dep must be 'C' or 'D'")
        if not self.reservation_id and not self.contract_id:
            raise ValueError("Pass at least reservation_id or contract_id")
        if not self.payment_mode:
            raise ValueError("payment_mode is required")
        if not self.myrent_url:
            raise ValueError("myrent_url is required")

    def to_payload(self) -> Dict[str, Any]:
        self.validate()
        payload: Dict[str, Any] = {
            "isChargeOrDep": str(self.is_charge_or_dep).upper().strip(),
            "myrentUrl": str(self.myrent_url),
            "contractId": "" if self.contract_id is None else str(self.contract_id),
            "amount": str(self.amount),
            "reservationId": "" if self.reservation_id is None else str(self.reservation_id),
            "paymentMode": str(self.payment_mode),
            "isExternalBook": str(self.is_external_book).upper().strip(),
        }
        if self.device_id is not None:
            payload["deviceId"] = str(self.device_id)
        return payload


# =====================================================================================
# Response DTO
# =====================================================================================


@dataclass(frozen=True)
class ReservationRecord:
    reservation_id: Optional[int] = None
    num_pref_code: Optional[str] = None
    pick_up_date: Optional[str] = None
    pick_up_time: Optional[str] = None
    pick_up_location: Optional[str] = None
    drop_off_date: Optional[str] = None
    drop_off_time: Optional[str] = None
    drop_off_location: Optional[str] = None
    privacy_message1: Optional[bool] = None
    privacy_message2: Optional[bool] = None
    customer: Optional[str] = None
    customer_id: Optional[int] = None
    customer_first_name: Optional[str] = None
    customer_last_name: Optional[str] = None
    customer_middle_name: Optional[str] = None
    is_customer_physical_person: Optional[bool] = None
    is_customer_individual_company: Optional[bool] = None
    driver1: Optional[str] = None
    driver1_id: Optional[int] = None
    driver2: Optional[str] = None
    driver2_id: Optional[int] = None
    driver3: Optional[str] = None
    driver3_id: Optional[int] = None
    voucher: Optional[str] = None
    voucher_days: Optional[int] = None
    voucher_prepaid: Optional[bool] = None
    reservation_source_id: Optional[int] = None
    reservation_source_code: Optional[str] = None
    rez_is_rental: Optional[bool] = None
    rez_is_cancelled: Optional[bool] = None
    rez_is_refused: Optional[bool] = None
    rez_is_no_show: Optional[bool] = None
    rez_is_accepted: Optional[bool] = None
    rez_is_on_request: Optional[bool] = None
    rez_is_confirmed: Optional[bool] = None
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_dict(data: Dict[str, Any]) -> "ReservationRecord":
        return ReservationRecord(
            reservation_id=_coerce_int(data.get("reservationId")),
            num_pref_code=_stringify(data.get("numPrefCode")),
            pick_up_date=_stringify(data.get("pickUpDate")),
            pick_up_time=_stringify(data.get("pickUpTime")),
            pick_up_location=_stringify(data.get("pickUpLocation")),
            drop_off_date=_stringify(data.get("dropOffDate")),
            drop_off_time=_stringify(data.get("dropOffTime")),
            drop_off_location=_stringify(data.get("dropOffLocation")),
            privacy_message1=_coerce_bool(data.get("privacyMessage1")),
            privacy_message2=_coerce_bool(data.get("privacyMessage2")),
            customer=_stringify(data.get("customer")),
            customer_id=_coerce_int(data.get("customerId")),
            customer_first_name=_stringify(data.get("customerFName")),
            customer_last_name=_stringify(data.get("customerLName")),
            customer_middle_name=_stringify(data.get("customerMName")),
            is_customer_physical_person=_coerce_bool(data.get("isCustPhysicalPerson")),
            is_customer_individual_company=_coerce_bool(data.get("isCustIndividualCompany")),
            driver1=_stringify(data.get("driver1")),
            driver1_id=_coerce_int(data.get("driver1Id")),
            driver2=_stringify(data.get("driver2")),
            driver2_id=_coerce_int(data.get("driver2Id")),
            driver3=_stringify(data.get("driver3")),
            driver3_id=_coerce_int(data.get("driver3Id")),
            voucher=_stringify(data.get("voucher")),
            voucher_days=_coerce_int(data.get("voucherDays")),
            voucher_prepaid=_coerce_bool(data.get("voucherPrepaid")),
            reservation_source_id=_coerce_int(data.get("reservationSourceId")),
            reservation_source_code=_stringify(data.get("reservationSourceCode")),
            rez_is_rental=_coerce_bool(data.get("rezIsRental")),
            rez_is_cancelled=_coerce_bool(data.get("rezIsCancelled")),
            rez_is_refused=_coerce_bool(data.get("rezIsRefused")),
            rez_is_no_show=_coerce_bool(data.get("rezIsNoShow")),
            rez_is_accepted=_coerce_bool(data.get("rezIsAccepted")),
            rez_is_on_request=_coerce_bool(data.get("rezIsOnRequest")),
            rez_is_confirmed=_coerce_bool(data.get("rezIsConfirmed")),
            status=_stringify(data.get("status")),
            raw=data,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def ensure_success(self) -> "ReservationRecord":
        if self.status and self.status.lower() == "error":
            raise APIError(f"Reservation operation returned status=error | payload={self.raw}")
        return self


@dataclass(frozen=True)
class ReservationListResponse:
    reservations: List[ReservationRecord] = field(default_factory=list)
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_payload(payload: Any) -> "ReservationListResponse":
        if isinstance(payload, dict):
            items = payload.get("reservationList") or payload.get("data") or []
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list):
                items = []
            reservations = [ReservationRecord.from_api_dict(x) for x in items if isinstance(x, dict)]
            return ReservationListResponse(
                reservations=reservations,
                status=_stringify(payload.get("status")),
                raw=payload,
            )
        return ReservationListResponse(reservations=[], status=None, raw={"raw": payload})

    def ensure_success(self) -> "ReservationListResponse":
        if self.status and self.status.lower() == "error":
            raise APIError(f"Reservation list operation returned status=error | payload={self.raw}")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reservations": [x.to_dict() for x in self.reservations],
            "status": self.status,
            "raw": self.raw,
        }


@dataclass(frozen=True)
class PaymentLinkResponse:
    status: Optional[str] = None
    payment_url: Optional[str] = None
    message: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_payload(payload: Any) -> "PaymentLinkResponse":
        if isinstance(payload, dict):
            return PaymentLinkResponse(
                status=_stringify(payload.get("status")),
                payment_url=_stringify(
                    payload.get("paymentUrl")
                    or payload.get("paymentURL")
                    or payload.get("generateLink")
                    or payload.get("generatedLink")
                    or payload.get("url")
                ),
                message=_stringify(
                    payload.get("msg")
                    or payload.get("message")
                    or payload.get("errorMessage")
                ),
                raw=payload,
            )
        return PaymentLinkResponse(raw={"raw": payload})

    @property
    def is_success(self) -> bool:
        if self.status is None:
            return False
        return self.status.lower() in {"success", "y", "yes", "true"}

    def ensure_success(self) -> "PaymentLinkResponse":
        if not self.is_success:
            msg = self.message or f"Payment link API returned status={self.status!r}"
            raise APIError(msg)
        return self

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =====================================================================================
# Client HTTP standalone
# =====================================================================================


class MyRentWebCheckInClient:
    """
    Client standalone per:
      - AUTH su MyRentWeb: /api/v1/touroperator/authentication
      - WEB CHECK-IN su MyRentWeb: /api/v2/data/...
      - PAYMENT LINK su MyRentWeb: /api/v1/Payment/getPaymentLink

    Allineamento con gli esempi Postman forniti da assistenza:
      - reservation: POST con body raw JSON testuale
      - customer: POST con customerId in query string e body vuoto
      - headers portal: si prova prima con tokenValue + userName + password + companyCode
    """

    AUTH_PATH = "/api/v1/touroperator/authentication"

    RESERVATION_SEARCH_PATH = "/api/v2/data/reservation"
    CUSTOMER_PATH = "/api/v2/data/customer"
    UPDATE_CUSTOMER_PATH = "/api/v2/data/updateCustomer"
    ADV_SEARCH_RES_PATH = "/api/v2/data/advSearchRes"
    ADV_SEARCH_BY_CUSTOMER_LOCATION_PATH = "/api/v2/data/advSearchResByCustomerAndLocation"
    SET_CUSTOMER_AS_DRIVER1_PATH = "/api/v2/data/reservationSetCustomerAsDriver1"
    INSERT_NEW_DRIVER1_PATH = "/api/v2/data/insertNew1Driver"
    INSERT_NEW_DRIVER2_PATH = "/api/v2/data/insertNew2Driver"
    INSERT_NEW_DRIVER3_PATH = "/api/v2/data/insertNew3Driver"
    SET_PRIVACY_POLICY_PATH = "/api/v2/data/setReservationPrivacyPolicy"

    PAYMENT_LINK_PATH = "/api/v1/Payment/getPaymentLink"

    def __init__(
        self,
        base_url: str,
        *,
        user_id: Optional[str] = None,
        password: Optional[str] = None,
        company_code: Optional[str] = None,
        token_value: Optional[str] = None,
        timeout: Union[int, float] = 30,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        user_agent: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        session: Optional[requests.Session] = None,
        portal_auth_mode: str = "combined_then_token_then_basic",
    ) -> None:
        self.base_url = _normalize_base_url(base_url)

        self.user_id = user_id
        self.password = password
        self.company_code = company_code
        self._token_value = token_value

        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.backoff_factor = float(backoff_factor)
        self.user_agent = user_agent or "myrent-web-checkin-sdk/4.1"
        self.portal_auth_mode = portal_auth_mode.strip().lower()

        self.log = logger or logging.getLogger("myrent_web_checkin_sdk")
        if not self.log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.log.addHandler(handler)
            self.log.setLevel(logging.INFO)

        self.session = session or requests.Session()

    # -------------------------------------------------------------------------
    # Low level HTTP
    # -------------------------------------------------------------------------

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self.backoff_factor * (2 ** attempt)
        self.log.debug("retry fra %.2fs", delay)
        time.sleep(delay)

    def _headers(
        self,
        extra: Optional[Dict[str, str]] = None,
        *,
        content_type: Optional[str] = None,
        accept: Optional[str] = "application/json",
    ) -> Dict[str, str]:
        h: Dict[str, str] = {
            "User-Agent": self.user_agent,
        }
        if accept:
            h["Accept"] = accept
        if content_type:
            h["Content-Type"] = content_type
        if extra:
            h.update(extra)
        return h

    def _dispatch_once(
        self,
        *,
        url: str,
        method: str,
        headers: Optional[Dict[str, str]],
        body: Optional[Dict[str, Any]],
        params: Optional[Dict[str, Any]],
        body_mode: str,
    ) -> requests.Response:
        req_headers: Dict[str, str]
        kwargs: Dict[str, Any] = {
            "params": params,
            "timeout": self.timeout,
        }

        if body_mode == "json":
            req_headers = self._headers(headers, content_type="application/json")
            kwargs["json"] = body or {}

        elif body_mode == "form":
            req_headers = self._headers(headers, content_type="application/x-www-form-urlencoded")
            kwargs["data"] = _to_form_body(body or {})

        elif body_mode == "raw_text_json":
            req_headers = self._headers(headers, content_type="text/plain")
            kwargs["data"] = _json_dumps_body(body or {})

        elif body_mode == "raw_app_json":
            req_headers = self._headers(headers, content_type="application/json")
            kwargs["data"] = _json_dumps_body(body or {})

        elif body_mode == "none":
            req_headers = self._headers(headers)

        else:
            raise ValueError(f"Unsupported body_mode: {body_mode}")

        if self.log.isEnabledFor(logging.DEBUG):
            debug_body: Any = body
            if body_mode in {"raw_text_json", "raw_app_json"}:
                debug_body = _json_dumps_body(body or {})
            self.log.debug(
                "REQUEST %s %s body_mode=%s headers=%s body=%s params=%s",
                method.upper(),
                url,
                body_mode,
                req_headers,
                debug_body,
                params,
            )

        return self.session.request(
            method=method.upper(),
            url=url,
            headers=req_headers,
            **kwargs,
        )

    def _request(
        self,
        *,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        body_mode: str = "none",
    ) -> requests.Response:
        url = self.base_url + path
        attempt = 0
        last_exc: Optional[Exception] = None

        while attempt <= self.max_retries:
            try:
                resp = self._dispatch_once(
                    url=url,
                    method=method,
                    headers=headers,
                    body=body,
                    params=params,
                    body_mode=body_mode,
                )

                if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                    self._sleep_backoff(attempt)
                    attempt += 1
                    continue

                return resp

            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                self._sleep_backoff(attempt)
                attempt += 1
                continue

        if last_exc:
            raise APIError(f"Request fallita dopo {self.max_retries + 1} tentativi: {last_exc}") from last_exc
        raise APIError("Request fallita dopo i tentativi massimi.")

    @staticmethod
    def _parse_json(resp: requests.Response) -> Any:
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "application/json" in ct or "json" in ct:
            return resp.json()
        try:
            return resp.json()
        except Exception:
            return resp.text

    @staticmethod
    def _payload_preview(resp: requests.Response) -> str:
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw": resp.text}
        return json.dumps(payload, ensure_ascii=False, default=str)[:1000]

    def _raise_http_error(self, *, method: str, path: str, resp: requests.Response) -> None:
        url = self.base_url + path
        if resp.status_code == 401:
            raise AuthenticationError(
                f"HTTP 401 {method.upper()} {url}: token/credenziali non validi | payload={self._payload_preview(resp)}"
            )
        raise APIError(
            f"HTTP {resp.status_code} {method.upper()} {url}: {self._payload_preview(resp)}"
        )

    # -------------------------------------------------------------------------
    # Auth helpers
    # -------------------------------------------------------------------------

    def _basic_portal_headers(self) -> Dict[str, str]:
        if not (self.user_id and self.password and self.company_code):
            raise AuthenticationError(
                "Per basic portal auth servono user_id, password e company_code."
            )
        return {
            "userName": self.user_id,
            "password": self.password,
            "companyCode": self.company_code,
        }

    def _token_headers(self) -> Dict[str, str]:
        return {"tokenValue": self.ensure_authenticated()}

    def _combined_portal_headers(self) -> Dict[str, str]:
        headers = self._basic_portal_headers()
        headers["tokenValue"] = self.ensure_authenticated()
        return headers

    def _portal_auth_header_sets(self) -> List[Tuple[str, Dict[str, str]]]:
        mode = self.portal_auth_mode

        if mode == "combined_only":
            return [("combined", self._combined_portal_headers())]

        if mode == "token_only":
            return [("token", self._token_headers())]

        if mode == "basic_only":
            return [("basic", self._basic_portal_headers())]

        if mode == "combined_then_token_then_basic":
            return [
                ("combined", self._combined_portal_headers()),
                ("token", self._token_headers()),
                ("basic", self._basic_portal_headers()),
            ]

        if mode == "token_then_basic":
            return [
                ("token", self._token_headers()),
                ("basic", self._basic_portal_headers()),
            ]

        raise ValueError(
            "portal_auth_mode must be one of: "
            "combined_only, token_only, basic_only, "
            "combined_then_token_then_basic, token_then_basic"
        )

    def _portal_request(
        self,
        *,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        preferred_body_modes: Optional[Sequence[str]] = None,
    ) -> requests.Response:
        method_upper = method.upper()

        if method_upper == "GET":
            body_modes = ["none"]
        else:
            body_modes = list(preferred_body_modes) if preferred_body_modes else [
                "raw_text_json",
                "raw_app_json",
                "json",
                "form",
            ]

        header_sets = self._portal_auth_header_sets()

        tried: List[str] = []
        last_resp: Optional[requests.Response] = None

        for body_mode in body_modes:
            for auth_label, headers in header_sets:
                resp = self._request(
                    method=method_upper,
                    path=path,
                    headers=headers,
                    body=body,
                    params=params,
                    body_mode=body_mode,
                )
                last_resp = resp
                tried.append(f"{auth_label}/{body_mode}:{resp.status_code}")

                if 200 <= resp.status_code < 300:
                    return resp

        if last_resp is None:
            raise APIError("Portal request fallita senza risposta.")

        url = self.base_url + path
        attempts_str = ", ".join(tried)

        if last_resp.status_code == 401:
            raise AuthenticationError(
                f"Portal request failed after attempts [{attempts_str}] | "
                f"last=HTTP 401 {method_upper} {url}: {self._payload_preview(last_resp)}"
            )

        raise APIError(
            f"Portal request failed after attempts [{attempts_str}] | "
            f"last=HTTP {last_resp.status_code} {method_upper} {url}: {self._payload_preview(last_resp)}"
        )

    # -------------------------------------------------------------------------
    # Auth pubblica
    # -------------------------------------------------------------------------

    def authenticate(self) -> AuthResult:
        if not (self.user_id and self.password and self.company_code):
            raise AuthenticationError("Servono user_id, password e company_code per authenticate().")

        payload = {
            "UserId": self.user_id,
            "Password": self.password,
            "companyCode": self.company_code,
        }

        resp = self._request(
            method="POST",
            path=self.AUTH_PATH,
            body=payload,
            body_mode="json",
        )
        if not (200 <= resp.status_code < 300):
            self._raise_http_error(method="POST", path=self.AUTH_PATH, resp=resp)

        data = self._parse_json(resp)
        if not isinstance(data, dict):
            raise APIError("Formato inatteso della risposta di authentication.")

        auth = AuthResult.from_api_payload(data)
        self._token_value = auth.token_value
        return auth

    def authenticate_for_web_checkin(self) -> AuthResult:
        return self.authenticate()

    @property
    def token_value(self) -> str:
        if not self._token_value:
            raise AuthenticationError("Token assente. Chiama authenticate() o passa token_value=... al costruttore.")
        return self._token_value

    def ensure_authenticated(self) -> str:
        if self._token_value:
            return self.token_value
        auth = self.authenticate()
        return auth.token_value

    # -------------------------------------------------------------------------
    # Coercion helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _coerce_reservation_response(payload: Any) -> ReservationRecord:
        if not isinstance(payload, dict):
            raise APIError(f"Unexpected reservation payload type: {type(payload)!r} | payload={payload!r}")
        return ReservationRecord.from_api_dict(payload)

    @staticmethod
    def _coerce_customer_response(payload: Any) -> CustomerProfile:
        if not isinstance(payload, dict):
            raise APIError(f"Unexpected customer payload type: {type(payload)!r} | payload={payload!r}")
        return CustomerProfile.from_api_dict(payload)

    # -------------------------------------------------------------------------
    # API methods
    # -------------------------------------------------------------------------

    def search_reservation(self, request: Union[ReservationLookupRequest, Dict[str, Any]]) -> ReservationRecord:
        payload = request.to_payload() if isinstance(request, ReservationLookupRequest) else dict(request)
        resp = self._portal_request(
            method="POST",
            path=self.RESERVATION_SEARCH_PATH,
            body=payload,
            preferred_body_modes=("raw_text_json", "raw_app_json", "json", "form"),
        )
        return self._coerce_reservation_response(self._parse_json(resp))

    def get_customer(self, customer_id: Union[str, int]) -> CustomerProfile:
        resp = self._portal_request(
            method="POST",
            path=self.CUSTOMER_PATH,
            params={"customerId": str(customer_id)},
            body=None,
            preferred_body_modes=("none",),
        )
        return self._coerce_customer_response(self._parse_json(resp))

    def update_customer(
        self,
        customer_id: Union[str, int],
        request: Union[CustomerUpdateRequest, CustomerProfile, Dict[str, Any]],
    ) -> CustomerProfile:
        if isinstance(request, CustomerProfile):
            payload = request.to_payload(include_status=True)
        else:
            payload = dict(request)

        resp = self._portal_request(
            method="POST",
            path=self.UPDATE_CUSTOMER_PATH,
            params={"customerId": str(customer_id)},
            body=payload,
            preferred_body_modes=("raw_text_json", "raw_app_json", "json", "form"),
        )
        return self._coerce_customer_response(self._parse_json(resp))

    def search_reservations_by_voucher(
        self,
        request: Union[ReservationVoucherSearchRequest, Dict[str, Any]],
    ) -> ReservationListResponse:
        payload = request.to_payload() if isinstance(request, ReservationVoucherSearchRequest) else dict(request)
        resp = self._portal_request(
            method="POST",
            path=self.ADV_SEARCH_RES_PATH,
            body=payload,
            preferred_body_modes=("raw_text_json", "raw_app_json", "json", "form"),
        )
        return ReservationListResponse.from_api_payload(self._parse_json(resp))

    def search_reservation_by_customer_location(
        self,
        request: Union[ReservationCustomerLocationSearchRequest, Dict[str, Any]],
    ) -> ReservationRecord:
        payload = request.to_payload() if isinstance(request, ReservationCustomerLocationSearchRequest) else dict(request)
        resp = self._portal_request(
            method="POST",
            path=self.ADV_SEARCH_BY_CUSTOMER_LOCATION_PATH,
            body=payload,
            preferred_body_modes=("raw_text_json", "raw_app_json", "json", "form"),
        )
        return self._coerce_reservation_response(self._parse_json(resp))

    def set_customer_as_driver1(self, reservation_id: Union[str, int]) -> ReservationRecord:
        resp = self._portal_request(
            method="POST",
            path=self.SET_CUSTOMER_AS_DRIVER1_PATH,
            body={"reservationId": str(reservation_id)},
            preferred_body_modes=("raw_text_json", "raw_app_json", "json", "form"),
        )
        return self._coerce_reservation_response(self._parse_json(resp))

    def insert_new_driver1(self, request: Union[DriverCreateRequest, Dict[str, Any]]) -> ReservationRecord:
        payload = request.to_payload() if isinstance(request, DriverCreateRequest) else dict(request)
        resp = self._portal_request(
            method="POST",
            path=self.INSERT_NEW_DRIVER1_PATH,
            body=payload,
            preferred_body_modes=("raw_text_json", "raw_app_json", "json", "form"),
        )
        return self._coerce_reservation_response(self._parse_json(resp))

    def insert_new_driver2(self, request: Union[DriverCreateRequest, Dict[str, Any]]) -> ReservationRecord:
        payload = request.to_payload() if isinstance(request, DriverCreateRequest) else dict(request)
        resp = self._portal_request(
            method="POST",
            path=self.INSERT_NEW_DRIVER2_PATH,
            body=payload,
            preferred_body_modes=("raw_text_json", "raw_app_json", "json", "form"),
        )
        return self._coerce_reservation_response(self._parse_json(resp))

    def insert_new_driver3(self, request: Union[DriverCreateRequest, Dict[str, Any]]) -> ReservationRecord:
        payload = request.to_payload() if isinstance(request, DriverCreateRequest) else dict(request)
        resp = self._portal_request(
            method="POST",
            path=self.INSERT_NEW_DRIVER3_PATH,
            body=payload,
            preferred_body_modes=("raw_text_json", "raw_app_json", "json", "form"),
        )
        return self._coerce_reservation_response(self._parse_json(resp))

    def set_reservation_privacy_policy(
        self,
        request: Union[ReservationPrivacyPolicyRequest, Dict[str, Any]],
    ) -> ReservationRecord:
        payload = request.to_payload() if isinstance(request, ReservationPrivacyPolicyRequest) else dict(request)
        resp = self._portal_request(
            method="POST",
            path=self.SET_PRIVACY_POLICY_PATH,
            body=payload,
            preferred_body_modes=("raw_text_json", "raw_app_json", "json", "form"),
        )
        return self._coerce_reservation_response(self._parse_json(resp))

    def get_payment_link(self, request: Union[PaymentLinkRequest, Dict[str, Any]]) -> PaymentLinkResponse:
        payload = request.to_payload() if isinstance(request, PaymentLinkRequest) else dict(request)
        resp = self._portal_request(
            method="POST",
            path=self.PAYMENT_LINK_PATH,
            body=payload,
            preferred_body_modes=("raw_app_json", "json", "raw_text_json", "form"),
        )
        return PaymentLinkResponse.from_api_payload(self._parse_json(resp))