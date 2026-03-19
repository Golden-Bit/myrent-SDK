from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
import time
import json
import re
from pathlib import Path

"""
myrent_adapter.py

Classe "connettore/adapter" per:
1) Recuperare Locations e Quotations da MyRent tramite SDK esterno (myrent_sdk.py)
2) Convertire i payload MyRent nel formato richiesto dalla wrapper API (FastAPI)
3) Gestire compose reservation + persistenza indice reservation su JSON locale
4) Arricchire i reservation details interrogando anche il web-checkin
"""

from dataclasses import asdict
from typing import Any, Dict, List, Optional, Union, Tuple
import os
import math
import logging

# --------------------------------------------------------------------------------------
# Import SDK MyRent (ESTERNO)
# --------------------------------------------------------------------------------------
_IMPORT_ERROR: Optional[Exception] = None
try:
    from myrent_sdk.main import (  # type: ignore
        MyRentClient,
        QuotationRequest as SDKQuotationRequest,
        BookingRequest as SDKBookingRequest,
        BookingCustomer as SDKBookingCustomer,
        BookingVehicleRequest as SDKBookingVehicleRequest,
        APIError,
        AuthenticationError,
    )

    from myrent_sdk.web_checkin import (  # type: ignore
        MyRentWebCheckInClient,
        CustomerUpdateRequest as WCCustomerUpdateRequest,
        DriverCreateRequest as WCDriverCreateRequest,
        ReservationLookupRequest as WCReservationLookupRequest,
        ReservationVoucherSearchRequest as WCReservationVoucherSearchRequest,
        APIError as WCAPIError,
        AuthenticationError as WCAuthenticationError,
    )

except Exception as e:  # pragma: no cover
    _IMPORT_ERROR = e
    MyRentClient = None  # type: ignore
    SDKQuotationRequest = None  # type: ignore
    APIError = Exception  # type: ignore
    AuthenticationError = Exception  # type: ignore


# --------------------------------------------------------------------------------------
# Helpers "safe" (coercion / parsing)
# --------------------------------------------------------------------------------------
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
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            return v
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
        return int(v)
    except Exception:
        return None


def _coerce_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return float(int(v))
        return float(v)
    except Exception:
        return None


def _strip_z(s: str) -> str:
    s = (s or "").strip()
    if s.endswith("Z"):
        return s[:-1]
    return s


def _parse_dt_any(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    s = _strip_z(s)
    try:
        return datetime.fromisoformat(s)
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
    return None



def _fmt_dt_no_tz_seconds(value: Union[str, datetime]) -> str:
    if isinstance(value, datetime):
        return value.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, str):
        dt = _parse_dt_any(value)
        if dt is None:
            return value.strip()
        return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    raise TypeError("Datetime non valido")


def _unique(seq: List[Any]) -> List[Any]:
    out: List[Any] = []
    seen = set()
    for x in seq:
        if x is None:
            continue
        k = str(x)
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def _pick(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


# --------------------------------------------------------------------------------------
# Error type
# --------------------------------------------------------------------------------------
class MyRentAdapterError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------
# Adapter / Connector
# --------------------------------------------------------------------------------------
class MyRentAdapter:
    """
    Adapter "importabile" che:
    - usa MyRentClient (SDK esterno)
    - usa MyRentWebCheckInClient (SDK esterno)
    - converte Locations e Quotations nel formato wrapper
    - gestisce compose reservation
    - persiste localmente l'indice reservation_id -> booking/channel/customer + metadati
    """

    def __init__(
        self,
        *,
        base_url: str,
        user_id: str,
        password: str,
        company_code: str,
        timeout: Union[int, float] = 30,
        vat_pct: int = 22,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if _IMPORT_ERROR is not None:  # pragma: no cover
            raise MyRentAdapterError(
                "Impossibile importare 'myrent_sdk'. "
                "Assicurati che il modulo sia installato/visibile nel PYTHONPATH. "
                f"Dettaglio: {_IMPORT_ERROR!r}"
            )

        self.log = logger or logging.getLogger("myrent_adapter")
        self.vat_pct = int(vat_pct)

        # istanza SDK booking
        self.client = MyRentClient(  # type: ignore[misc]
            base_url=base_url,
            user_id=user_id,
            password=password,
            company_code=company_code,
            timeout=float(timeout),
            logger=self.log,
        )

        # ------------------- Vehicles cache (in-memory, thread-safe) -------------------
        ttl_env = os.getenv("MYRENT_VEHICLES_CACHE_TTL_SEC", "300")
        try:
            self._vehicles_cache_ttl_sec = max(0, int(ttl_env))
        except Exception:
            self._vehicles_cache_ttl_sec = 300

        self._vehicles_cache_lock = Lock()
        self._vehicles_cache: Dict[str, Dict[str, Any]] = {}

        # istanza SDK web-checkin
        self.web_checkin_client = MyRentWebCheckInClient(
            base_url=base_url,
            user_id=user_id,
            password=password,
            company_code=company_code,
            timeout=float(timeout),
            logger=self.log,
            portal_auth_mode=os.getenv(
                "MYRENT_WEB_CHECKIN_AUTH_MODE",
                "combined_then_token_then_basic",
            ),
        )

        # ------------------- Reservation index persistito -------------------
        self._reservation_index_lock = Lock()

        default_index_path = Path(__file__).resolve().parent / "data" / "reservation_index.json"
        index_path_env = os.getenv("MYRENT_RESERVATION_INDEX_PATH")

        self._reservation_index_path = (
            Path(index_path_env).expanduser().resolve()
            if index_path_env
            else default_index_path
        )

        self._reservation_index: Dict[str, Dict[str, Any]] = {}
        self._load_reservation_index_from_disk()

    # ----------------------------- Factory da ENV -----------------------------
    @classmethod
    def from_env(
        cls,
        *,
        timeout: Union[int, float] = 30,
        vat_pct_default: int = 22,
        logger: Optional[logging.Logger] = None,
    ) -> "MyRentAdapter":
        base_url = os.getenv("MYRENT_BASE_URL")
        user_id = os.getenv("MYRENT_USER_ID")
        password = os.getenv("MYRENT_PASSWORD")
        company_code = os.getenv("MYRENT_COMPANY_CODE")

        missing = [
            k
            for k, v in {
                "MYRENT_BASE_URL": base_url,
                "MYRENT_USER_ID": user_id,
                "MYRENT_PASSWORD": password,
                "MYRENT_COMPANY_CODE": company_code,
            }.items()
            if not v
        ]

        if missing:
            raise MyRentAdapterError(
                "Configurazione MyRent mancante. Imposta le variabili ambiente: " + ", ".join(missing)
            )

        timeout_env = os.getenv("MYRENT_TIMEOUT")
        eff_timeout = float(timeout_env) if timeout_env else float(timeout)

        vat_env = os.getenv("MYRENT_VAT_PCT")
        eff_vat = int(vat_env) if vat_env and vat_env.isdigit() else int(vat_pct_default)

        return cls(
            base_url=str(base_url),
            user_id=str(user_id),
            password=str(password),
            company_code=str(company_code),
            timeout=eff_timeout,
            vat_pct=eff_vat,
            logger=logger,
        )

    # ----------------------------- Auth verso MyRent -----------------------------
    def _ensure_authenticated(self) -> None:
        try:
            _ = self.client.token_value  # type: ignore[attr-defined]
            return
        except Exception:
            pass

        self.log.info("MyRentAdapter: token assente, eseguo authenticate() ...")
        self.client.authenticate()  # type: ignore[attr-defined]

    def _ensure_web_checkin_authenticated(self) -> None:
        try:
            _ = self.web_checkin_client.token_value
            return
        except Exception:
            pass

        self.log.info("MyRentAdapter: web-checkin token assente, eseguo authenticate() ...")
        self.web_checkin_client.authenticate_for_web_checkin()

    def _normalize_channel(self, channel: Optional[str]) -> str:
        ch = (channel or getattr(self.client, "company_code", None) or "").strip().replace(" ", "")
        if not ch:
            raise MyRentAdapterError("channel mancante e company_code non disponibile")
        return ch

    # ----------------------------- Reservation index persistence -----------------------------
    def _ensure_reservation_index_parent_dir(self) -> None:
        try:
            self._reservation_index_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise MyRentAdapterError(
                f"Impossibile creare directory reservation index: {self._reservation_index_path.parent} ({e})"
            ) from e

    def _load_reservation_index_from_disk(self) -> None:
        self._ensure_reservation_index_parent_dir()

        if not self._reservation_index_path.exists():
            self.log.info("Reservation index assente, inizializzo vuoto: %s", self._reservation_index_path)
            with self._reservation_index_lock:
                self._reservation_index = {}
            return

        try:
            raw = self._reservation_index_path.read_text(encoding="utf-8").strip()
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                data = {}

            normalized: Dict[str, Dict[str, Any]] = {}
            for k, v in data.items():
                if not isinstance(v, dict):
                    continue
                rid = str(k).strip()
                if not rid:
                    continue
                normalized[rid] = v

            with self._reservation_index_lock:
                self._reservation_index = normalized

            self.log.info(
                "Reservation index caricato da %s (%s record)",
                self._reservation_index_path,
                len(normalized),
            )
        except Exception as e:
            self.log.warning(
                "Errore lettura reservation index %s: %s. Uso indice vuoto.",
                self._reservation_index_path,
                e,
            )
            with self._reservation_index_lock:
                self._reservation_index = {}

    def _save_reservation_index_to_disk(self) -> None:
        self._ensure_reservation_index_parent_dir()

        with self._reservation_index_lock:
            snapshot = dict(self._reservation_index)

        tmp_path = self._reservation_index_path.with_suffix(self._reservation_index_path.suffix + ".tmp")

        try:
            tmp_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            tmp_path.replace(self._reservation_index_path)

            self.log.info(
                "Reservation index salvato su %s (%s record)",
                self._reservation_index_path,
                len(snapshot),
            )
        except Exception as e:
            raise MyRentAdapterError(
                f"Impossibile salvare reservation index su disco: {self._reservation_index_path} ({e})"
            ) from e

    def _index_reservation(
        self,
        reservation_id: Union[str, int],
        booking_id: str,
        channel: str,
        customer_id: Optional[Union[str, int]],
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        rid = str(reservation_id).strip()
        if not rid:
            return

        payload: Dict[str, Any] = {
            "booking_id": str(booking_id).strip(),
            "channel": str(channel).strip(),
            "customer_id": None if customer_id is None else str(customer_id).strip(),
        }

        if extra and isinstance(extra, dict):
            payload.update(extra)

        with self._reservation_index_lock:
            self._reservation_index[rid] = payload

        self.log.info(
            "Indexed reservation: reservation_id=%s booking_id=%s channel=%s customer_id=%s",
            rid,
            booking_id,
            channel,
            customer_id,
        )

        self._save_reservation_index_to_disk()

    def _get_indexed_reservation(self, reservation_id: Union[str, int]) -> Optional[Dict[str, Any]]:
        rid = str(reservation_id).strip()

        with self._reservation_index_lock:
            found = self._reservation_index.get(rid)

        if found:
            return found

        self._load_reservation_index_from_disk()

        with self._reservation_index_lock:
            return self._reservation_index.get(rid)

    # ----------------------------- Small helpers -----------------------------
    def _customer_profile_to_dict(self, obj: Any) -> Optional[Dict[str, Any]]:
        if obj is None:
            return None
        payload = obj.to_payload(include_status=True)
        payload["raw"] = getattr(obj, "raw", {})
        return payload

    def _extract_date_only_iso(self, value: Any) -> Optional[str]:
        dt = _parse_dt_any(value)
        if dt is not None:
            return dt.date().isoformat()

        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            if "T" in s:
                return s.split("T", 1)[0]
            if len(s) >= 10:
                return s[:10]
        return None

    def _parse_booking_lookup_fields(
        self,
        booking_id: str,
        booking_detail_dict: Optional[Dict[str, Any]] = None,
        booking_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Optional[str]]:
        booking_str = str(booking_id or "").strip()

        reservation_prefix: Optional[str] = None
        reservation_number: Optional[str] = None
        reservation_voucher: Optional[str] = None

        # esempio atteso: "SUL 6268 TESTDOGMA"
        m = re.match(r"^(?P<prefix>[A-Za-z]+)\s+(?P<number>\d+)(?:\s+(?P<voucher>.+))?$", booking_str)
        if m:
            reservation_prefix = m.group("prefix").strip()
            reservation_number = m.group("number").strip()
            reservation_voucher = (m.group("voucher") or "").strip() or None

        reservation_date = None

        if booking_data:
            reservation_date = self._extract_date_only_iso(
                _pick(booking_data, "start_date", "startDate")
            )

        if not reservation_date and booking_detail_dict:
            reservation_date = self._extract_date_only_iso(
                booking_detail_dict.get("pick_up_date_time")
                or booking_detail_dict.get("pickUpDateTime")
                or booking_detail_dict.get("pick_up_date")
                or booking_detail_dict.get("pickUpDate")
            )

        return {
            "reservation_prefix": reservation_prefix,
            "reservation_number": reservation_number,
            "reservation_date": reservation_date,
            "reservation_voucher": reservation_voucher,
        }

    # ----------------------------- Builder SDK DTO -----------------------------
    def _build_booking_customer(self, data: Dict[str, Any]) -> SDKBookingCustomer:
        return SDKBookingCustomer(
            first_name=_pick(data, "first_name", "firstName", "Name"),
            last_name=_pick(data, "last_name", "lastName", "Surname"),
            client_id=_pick(data, "client_id", "clientId"),
            ragione_sociale=_pick(data, "ragione_sociale", "ragioneSociale"),
            codice=_pick(data, "codice"),
            street=_pick(data, "street"),
            num=_pick(data, "num"),
            city=_pick(data, "city"),
            zip=_pick(data, "zip", "zipCode"),
            country=_pick(data, "country"),
            state=_pick(data, "state"),
            ph_num1=_pick(data, "ph_num1", "phNum1"),
            ph_num2=_pick(data, "ph_num2", "phNum2"),
            mobile_number=_pick(data, "mobile_number", "mobileNumber"),
            email=_pick(data, "email"),
            vat_number=_pick(data, "vat_number", "vatNumber"),
            birth_place=_pick(data, "birth_place", "birthPlace"),
            birth_date=_pick(data, "birth_date", "birthDate"),
            birth_province=_pick(data, "birth_province", "birthProvince"),
            birth_nation=_pick(data, "birth_nation", "birthNation"),
            gender=_coerce_bool(_pick(data, "gender")),
            tax_code=_pick(data, "tax_code", "taxCode"),
            document=_pick(data, "document"),
            document_number=_pick(data, "document_number", "documentNumber"),
            licence_type=_pick(data, "licence_type", "licenceType"),
            issue_by=_pick(data, "issue_by", "issueBy"),
            release_date=_pick(data, "release_date", "releaseDate"),
            expiry_date=_pick(data, "expiry_date", "expiryDate"),
            e_invoice_email=_pick(data, "e_invoice_email", "eInvoiceEmail"),
            e_invoice_code=_pick(data, "e_invoice_code", "eInvoiceCode"),
            is_physical_person=_pick(data, "is_physical_person", "isPhysicalPerson"),
            is_individual_company=_pick(data, "is_individual_company", "isIndividualCompany"),
        )

    def _build_vehicle_request(self, data: Optional[Dict[str, Any]]) -> Optional[SDKBookingVehicleRequest]:
        if not data:
            return None

        return SDKBookingVehicleRequest(
            payment_type=_pick(data, "payment_type", "paymentType", "PaymentType"),
            type=_pick(data, "type"),
            payment_amount=_coerce_float(_pick(data, "payment_amount", "paymentAmount", "PaymentAmount")),
            payment_transaction_type_code=_pick(
                data,
                "payment_transaction_type_code",
                "paymentTransactionTypeCode",
                "PaymentTransactionTypeCode",
            ),
            voucher_number=_pick(data, "voucher_number", "voucherNumber", "VoucherNumber"),
        )

    def _build_customer_update_request(self, data: Dict[str, Any]) -> WCCustomerUpdateRequest:
        return WCCustomerUpdateRequest(
            status=_pick(data, "status"),
            first_name=_pick(data, "first_name", "firstName", "Name"),
            middle_name=_pick(data, "middle_name", "middleName"),
            last_name=_pick(data, "last_name", "lastName", "Surname"),
            ragione_sociale=_pick(data, "ragione_sociale", "ragioneSociale"),
            codice=_pick(data, "codice"),
            street=_pick(data, "street"),
            num=_pick(data, "num"),
            city=_pick(data, "city"),
            zip_code=_pick(data, "zip_code", "zip", "zipCode"),
            country=_pick(data, "country"),
            state=_pick(data, "state"),
            ph_num1=_pick(data, "ph_num1", "phNum1"),
            ph_num2=_pick(data, "ph_num2", "phNum2"),
            mobile_number=_pick(data, "mobile_number", "mobileNumber"),
            email=_pick(data, "email"),
            vat_number=_pick(data, "vat_number", "vatNumber"),
            birth_place=_pick(data, "birth_place", "birthPlace"),
            birth_date=_pick(data, "birth_date", "birthDate"),
            birth_province=_pick(data, "birth_province", "birthProvince"),
            birth_nation=_pick(data, "birth_nation", "birthNation"),
            gender=_coerce_bool(_pick(data, "gender")),
            tax_code=_pick(data, "tax_code", "taxCode"),
            document=_pick(data, "document"),
            document_number=_pick(data, "document_number", "documentNumber"),
            licence_type=_pick(data, "licence_type", "licenceType"),
            issue_by=_pick(data, "issue_by", "issueBy"),
            document2=_pick(data, "document2"),
            document_number2=_pick(data, "document_number2", "documentNumber2"),
            issue_by2=_pick(data, "issue_by2", "issueBy2"),
            e_invoice_email=_pick(data, "e_invoice_email", "eInvoiceEmail"),
            e_invoice_code=_pick(data, "e_invoice_code", "eInvoiceCode"),
            release_date=_pick(data, "release_date", "releaseDate"),
            expiry_date=_pick(data, "expiry_date", "expiryDate"),
            release_date2=_pick(data, "release_date2", "releaseDate2"),
            expiry_date2=_pick(data, "expiry_date2", "expiryDate2"),
            is_physical_person=_coerce_bool(_pick(data, "is_physical_person", "isPhysicalPerson")),
            is_individual_company=_coerce_bool(_pick(data, "is_individual_company", "isIndividualCompany")),
        )

    def _build_driver_request(self, reservation_id: Union[str, int], data: Dict[str, Any]) -> WCDriverCreateRequest:
        return WCDriverCreateRequest(
            reservation_id=reservation_id,
            first_name=_pick(data, "first_name", "firstName", "Name"),
            last_name=_pick(data, "last_name", "lastName", "Surname"),
            middle_name=_pick(data, "middle_name", "middleName"),
            ragione_sociale=_pick(data, "ragione_sociale", "ragioneSociale"),
            codice=_pick(data, "codice"),
            street=_pick(data, "street"),
            num=_pick(data, "num"),
            city=_pick(data, "city"),
            zip_code=_pick(data, "zip_code", "zip", "zipCode"),
            country=_pick(data, "country"),
            state=_pick(data, "state"),
            ph_num1=_pick(data, "ph_num1", "phNum1"),
            ph_num2=_pick(data, "ph_num2", "phNum2"),
            mobile_number=_pick(data, "mobile_number", "mobileNumber"),
            email=_pick(data, "email"),
            vat_number=_pick(data, "vat_number", "vatNumber"),
            birth_place=_pick(data, "birth_place", "birthPlace"),
            birth_date=_pick(data, "birth_date", "birthDate"),
            birth_province=_pick(data, "birth_province", "birthProvince"),
            birth_nation=_pick(data, "birth_nation", "birthNation"),
            gender=_coerce_bool(_pick(data, "gender")),
            tax_code=_pick(data, "tax_code", "taxCode"),
            document=_pick(data, "document"),
            document2=_pick(data, "document2"),
            document_number=_pick(data, "document_number", "documentNumber"),
            document_number2=_pick(data, "document_number2", "documentNumber2"),
            licence_type=_pick(data, "licence_type", "licenceType"),
            issue_by=_pick(data, "issue_by", "issueBy"),
            issue_by2=_pick(data, "issue_by2", "issueBy2"),
            release_date=_pick(data, "release_date", "releaseDate"),
            release_date2=_pick(data, "release_date2", "releaseDate2"),
            expiry_date=_pick(data, "expiry_date", "expiryDate"),
            expiry_date2=_pick(data, "expiry_date2", "expiryDate2"),
        )

    # ----------------------------- Public API: Locations -----------------------------
    def get_locations(self) -> List[Dict[str, Any]]:
        self._ensure_authenticated()
        try:
            locs = self.client.get_locations()  # type: ignore[attr-defined]
        except AuthenticationError:
            self.log.warning("MyRent locations: auth fallita, retry authenticate() ...")
            self.client.authenticate()  # type: ignore[attr-defined]
            locs = self.client.get_locations()  # type: ignore[attr-defined]
        return self.convert_locations(locs)

    def convert_locations(self, locs: List[Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for loc in (locs or []):
            d = self._obj_to_dict(loc)

            openings_in = d.get("openings") or []
            openings_out: List[Dict[str, Any]] = []
            for o in openings_in:
                od = self._obj_to_dict(o)
                w = self._normalize_weekofday(od)
                if w:
                    openings_out.append(w)

            closing_in = d.get("closing") or []
            closing_out: List[Dict[str, Any]] = []
            for c in closing_in:
                cd = self._obj_to_dict(c)
                w = self._normalize_weekofday(cd)
                if w:
                    closing_out.append(w)

            payload: Dict[str, Any] = {
                "locationCode": d.get("locationCode"),
                "locationName": d.get("locationName"),
                "locationAddress": d.get("locationAddress"),
                "locationNumber": d.get("locationNumber"),
                "locationCity": d.get("locationCity"),
                "locationType": _coerce_int(d.get("locationType")) or 3,
                "telephoneNumber": d.get("telephoneNumber"),
                "cellNumber": d.get("cellNumber"),
                "email": d.get("email"),
                "latitude": _coerce_float(d.get("latitude")),
                "longitude": _coerce_float(d.get("longitude")),
                "isAirport": _coerce_bool(d.get("isAirport")),
                "isRailway": _coerce_bool(d.get("isRailway")),
                "isAlwaysOpentrue": _coerce_bool(d.get("isAlwaysOpentrue")),
                "isCarSharingEnabled": _coerce_bool(d.get("isCarSharingEnabled")),
                "allowPickUpDropOffOutOfHours": _coerce_bool(d.get("allowPickUpDropOffOutOfHours")),
                "hasKeyBox": _coerce_bool(d.get("hasKeyBox")),
                "morningStartTime": d.get("morningStartTime"),
                "morningStopTime": d.get("morningStopTime"),
                "afternoonStartTime": d.get("afternoonStartTime"),
                "afternoonStopTime": d.get("afternoonStopTime"),
                "locationInfoEN": d.get("locationInfoEN"),
                "locationInfoLocal": d.get("locationInfoLocal"),
                "openings": openings_out,
                "closing": closing_out if closing_out else None,
                "festivity": d.get("festivity"),
                "minimumLeadTimeInHour": _coerce_int(d.get("minimumLeadTimeInHour")),
                "country": d.get("country") or "ITALIA",
                "zipCode": d.get("zipCode"),
            }
            out.append(payload)
        return out

    # ----------------------------- Public API: Quotations -----------------------------
    def get_quotations(self, wrapper_req: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_authenticated()
        sdk_req = self._build_sdk_quotation_request(wrapper_req)

        try:
            resp = self.client.get_quotations(sdk_req)  # type: ignore[attr-defined]
            raw = getattr(resp, "raw", None)
            if not isinstance(raw, dict):
                raw = self._obj_to_dict(resp)
        except AuthenticationError:
            self.log.warning("MyRent quotations: auth fallita, retry authenticate() ...")
            self.client.authenticate()  # type: ignore[attr-defined]
            resp = self.client.get_quotations(sdk_req)  # type: ignore[attr-defined]
            raw = getattr(resp, "raw", None)
            if not isinstance(raw, dict):
                raw = self._obj_to_dict(resp)
        except APIError as e:
            raise MyRentAdapterError(f"MyRent quotations failed: {e}") from e

        converted_data = self.convert_quotation_payload(raw, wrapper_req)
        return {"data": converted_data}

    def _build_sdk_quotation_request(self, wrapper_req: Dict[str, Any]) -> Any:
        pickup = str(wrapper_req.get("pickupLocation") or "")
        dropoff = str(wrapper_req.get("dropOffLocation") or "")
        if not pickup or not dropoff:
            raise MyRentAdapterError("pickupLocation/dropOffLocation mancanti per MYRENT datasource")

        start_raw = wrapper_req.get("startDate")
        end_raw = wrapper_req.get("endDate")
        start_norm = _fmt_dt_no_tz_seconds(str(start_raw)) if start_raw is not None else ""
        end_norm = _fmt_dt_no_tz_seconds(str(end_raw)) if end_raw is not None else ""

        age_int = _coerce_int(wrapper_req.get("age")) or 0

        disc = wrapper_req.get("discountValueWithoutVat")
        disc_norm = None
        if disc is not None:
            disc_norm = str(disc)

        coupon = wrapper_req.get("agreementCoupon")
        coupon_norm = str(coupon).strip() if isinstance(coupon, str) and coupon.strip() else None

        show_pics = _coerce_bool(wrapper_req.get("showPics"))
        show_opt_img = _coerce_bool(wrapper_req.get("showOptionalImage"))
        show_params = _coerce_bool(wrapper_req.get("showVehicleParameter"))
        show_extra_img = _coerce_bool(wrapper_req.get("showVehicleExtraImage"))
        show_booking_discount = _coerce_bool(wrapper_req.get("showBookingDiscount"))
        is_young = _coerce_bool(wrapper_req.get("isYoungDriverAge"))
        is_senior = _coerce_bool(wrapper_req.get("isSeniorDriverAge"))

        sdk_req = SDKQuotationRequest(  # type: ignore[misc]
            drop_off_location=dropoff,
            end_date=end_norm,
            pickup_location=pickup,
            start_date=start_norm,
            age=int(age_int),
            channel=wrapper_req.get("channel"),
            show_pics=show_pics,
            show_optional_image=show_opt_img,
            show_vehicle_parameter=show_params,
            show_vehicle_extra_image=show_extra_img,
            agreement_coupon=coupon_norm,
            discount_value_without_vat=disc_norm,
            macro_description=wrapper_req.get("macroDescription"),
            show_booking_discount=show_booking_discount,
            is_young_driver_age=is_young,
            is_senior_driver_age=is_senior,
        )
        return sdk_req

    def convert_quotation_payload(self, payload: Dict[str, Any], wrapper_req: Dict[str, Any]) -> Dict[str, Any]:
        data_node = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data_node, dict):
            data_node = payload.get("Data") if isinstance(payload, dict) else None
        if not isinstance(data_node, dict):
            data_node = {}

        pickup_loc = data_node.get("PickUpLocation") or wrapper_req.get("pickupLocation") or ""
        dropoff_loc = data_node.get("ReturnLocation") or wrapper_req.get("dropOffLocation") or ""
        pickup_dt = data_node.get("PickUpDateTime") or wrapper_req.get("startDate") or ""
        return_dt = data_node.get("ReturnDateTime") or wrapper_req.get("endDate") or ""

        start_dt = _parse_dt_any(wrapper_req.get("startDate")) or _parse_dt_any(pickup_dt)
        end_dt = _parse_dt_any(wrapper_req.get("endDate")) or _parse_dt_any(return_dt)
        days = 1
        if start_dt and end_dt and end_dt > start_dt:
            dur_hours = (end_dt - start_dt).total_seconds() / 3600.0
            days = max(1, int(math.ceil(dur_hours / 24.0)))

        vehicles_in = data_node.get("Vehicles") or []
        vehicles_out: List[Dict[str, Any]] = []
        for vs in vehicles_in:
            if not isinstance(vs, dict):
                continue
            vehicles_out.append(self._convert_vehicle_status(vs, wrapper_req, days, pickup_loc, dropoff_loc))

        return {
            "total": len(vehicles_out),
            "PickUpLocation": str(pickup_loc),
            "ReturnLocation": str(dropoff_loc),
            "PickUpDateTime": str(pickup_dt),
            "ReturnDateTime": str(return_dt),
            "Vehicles": vehicles_out,
        }

    def _build_probe_wrapper_req(
        self,
        *,
        location: str,
        start: datetime,
        duration_days: int,
        age: int,
        channel: Optional[str],
    ) -> Dict[str, Any]:
        end = start + timedelta(days=max(1, int(duration_days)))
        loc = str(location).strip().upper()

        return {
            "pickupLocation": loc,
            "dropOffLocation": loc,
            "startDate": _fmt_dt_no_tz_seconds(start),
            "endDate": _fmt_dt_no_tz_seconds(end),
            "age": int(age),
            "channel": channel,
            "showPics": False,
            "showOptionalImage": False,
            "showVehicleParameter": False,
            "showVehicleExtraImage": False,
            "agreementCoupon": None,
            "discountValueWithoutVat": None,
            "macroDescription": None,
            "showBookingDiscount": False,
            "isYoungDriverAge": None,
            "isSeniorDriverAge": None,
        }

    # ----------------------------- Public API: Reservation compose -----------------------------
    def create_reservation_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_authenticated()
        self._ensure_web_checkin_authenticated()

        booking_data = payload.get("booking") or {}
        customer_data = payload.get("customer") or {}
        customer_update_data = payload.get("customerUpdate") or payload.get("customer_update") or {}
        driver1_data = payload.get("driver1")
        driver2_data = payload.get("driver2")
        driver3_data = payload.get("driver3")

        if not booking_data:
            raise MyRentAdapterError("booking mancante")
        if not customer_data:
            raise MyRentAdapterError("customer mancante")

        channel = self._normalize_channel(booking_data.get("channel"))

        booking_req = SDKBookingRequest(
            pickup_location=str(_pick(booking_data, "pickup_location", "pickupLocation")),
            drop_off_location=str(_pick(booking_data, "drop_off_location", "dropOffLocation")),
            start_date=_fmt_dt_no_tz_seconds(str(_pick(booking_data, "start_date", "startDate"))),
            end_date=_fmt_dt_no_tz_seconds(str(_pick(booking_data, "end_date", "endDate"))),
            vehicle_code=str(_pick(booking_data, "vehicle_code", "vehicleCode")),
            channel=channel,
            optionals=booking_data.get("optionals") or [],
            young_driver_fee=_coerce_float(_pick(booking_data, "young_driver_fee", "youngDriverFee")),
            senior_driver_fee=_coerce_float(_pick(booking_data, "senior_driver_fee", "seniorDriverFee")),
            senior_driver_fee_desc=_pick(booking_data, "senior_driver_fee_desc", "seniorDriverFeeDesc"),
            young_driver_fee_desc=_pick(booking_data, "young_driver_fee_desc", "youngDriverFeeDesc"),
            online_user=_coerce_int(_pick(booking_data, "online_user", "onlineUser")),
            insurance_id=_coerce_int(_pick(booking_data, "insurance_id", "insuranceId")),
            agreement_coupon=_pick(booking_data, "agreement_coupon", "agreementCoupon"),
            transaction_status_code=_pick(booking_data, "transaction_status_code", "TransactionStatusCode"),
            pay_now_dis=_pick(booking_data, "pay_now_dis", "PayNowDis"),
            is_young_driver_age=_coerce_bool(_pick(booking_data, "is_young_driver_age", "isYoungDriverAge")),
            is_senior_driver_age=_coerce_bool(_pick(booking_data, "is_senior_driver_age", "isSeniorDriverAge")),
            customer=self._build_booking_customer(customer_data),
            vehicle_request=self._build_vehicle_request(booking_data.get("vehicleRequest") or booking_data.get("vehicle_request")),
        )

        try:
            booking_resp = self.client.create_booking(booking_req)
        except APIError as e:
            raise MyRentAdapterError(f"Create booking fallita: {e}") from e

        if not booking_resp.data or not booking_resp.data[0].id:
            raise MyRentAdapterError("Create booking riuscita senza booking id in risposta")

        booking_row = booking_resp.data[0]
        booking_id = str(booking_row.id)

        try:
            booking_detail_resp = self.client.get_booking(booking_id, channel=channel)
        except APIError as e:
            raise MyRentAdapterError(f"Get booking detail fallita dopo create_booking: {e}") from e

        if not booking_detail_resp.data:
            raise MyRentAdapterError("Get booking detail non ha restituito dati")

        booking_detail = booking_detail_resp.data[0]

        if hasattr(booking_detail, "to_dict") and callable(getattr(booking_detail, "to_dict")):
            booking_detail_dict = booking_detail.to_dict()
        else:
            booking_detail_dict = self._obj_to_dict(booking_detail)

        reservation_id_internal = (
            getattr(booking_detail, "db_id", None)
            or booking_detail_dict.get("db_id")
            or booking_detail_dict.get("dbId")
        )
        customer_id = (
            getattr(booking_detail, "customer_id", None)
            or booking_detail_dict.get("customer_id")
            or booking_detail_dict.get("customerId")
        )

        if not reservation_id_internal:
            raise MyRentAdapterError("Impossibile estrarre dbId / reservation id interno dal booking detail")

        lookup_info = self._parse_booking_lookup_fields(
            booking_id=booking_id,
            booking_detail_dict=booking_detail_dict,
            booking_data=booking_data,
        )

        self._index_reservation(
            reservation_id=reservation_id_internal,
            booking_id=booking_id,
            channel=channel,
            customer_id=customer_id,
            extra=lookup_info,
        )

        customer_before = None
        if customer_id:
            try:
                customer_before_obj = self.web_checkin_client.get_customer(customer_id).ensure_success()
                customer_before = self._customer_profile_to_dict(customer_before_obj)
            except Exception as e:
                self.log.warning("Get customer post-booking fallita: %s", e)

        customer_after = customer_before

        merged_customer_update_data: Dict[str, Any] = {}
        if customer_data:
            merged_customer_update_data.update(customer_data)
        if customer_update_data:
            merged_customer_update_data.update(customer_update_data)

        if merged_customer_update_data and customer_id:
            try:
                update_req = self._build_customer_update_request(merged_customer_update_data)
                updated_customer_obj = self.web_checkin_client.update_customer(customer_id, update_req).ensure_success()
                customer_after = self._customer_profile_to_dict(updated_customer_obj)
            except (WCAPIError, WCAuthenticationError, Exception) as e:
                raise MyRentAdapterError(f"Update customer fallita: {e}") from e

        has_any_driver = any([driver1_data, driver2_data, driver3_data])

        driver1_result = None
        driver2_result = None
        driver3_result = None
        customer_as_driver1_result = None

        if (driver2_data or driver3_data) and not driver1_data:
            raise MyRentAdapterError("driver2/driver3 forniti senza driver1: caso non supportato in modo implicito")

        if not has_any_driver:
            try:
                customer_as_driver1_result = self.web_checkin_client.set_customer_as_driver1(
                    reservation_id_internal
                ).ensure_success().to_dict()
            except (WCAPIError, WCAuthenticationError, Exception) as e:
                raise MyRentAdapterError(f"set_customer_as_driver1 fallita: {e}") from e
        else:
            if driver1_data:
                try:
                    req1 = self._build_driver_request(reservation_id_internal, driver1_data)
                    driver1_result = self.web_checkin_client.insert_new_driver1(req1).ensure_success().to_dict()
                except (WCAPIError, WCAuthenticationError, Exception) as e:
                    raise MyRentAdapterError(f"insert_new_driver1 fallita: {e}") from e

            if driver2_data:
                try:
                    req2 = self._build_driver_request(reservation_id_internal, driver2_data)
                    driver2_result = self.web_checkin_client.insert_new_driver2(req2).ensure_success().to_dict()
                except (WCAPIError, WCAuthenticationError, Exception) as e:
                    raise MyRentAdapterError(f"insert_new_driver2 fallita: {e}") from e

            if driver3_data:
                try:
                    req3 = self._build_driver_request(reservation_id_internal, driver3_data)
                    driver3_result = self.web_checkin_client.insert_new_driver3(req3).ensure_success().to_dict()
                except (WCAPIError, WCAuthenticationError, Exception) as e:
                    raise MyRentAdapterError(f"insert_new_driver3 fallita: {e}") from e

        self._index_reservation(
            reservation_id=reservation_id_internal,
            booking_id=booking_id,
            channel=channel,
            customer_id=customer_id,
            extra={
                **lookup_info,
                "used_customer_as_driver1": customer_as_driver1_result is not None,
                "set_customer_as_driver1_result": customer_as_driver1_result,
                "driver1_result": driver1_result,
                "driver2_result": driver2_result,
                "driver3_result": driver3_result,
                "customer_before_update": customer_before,
                "customer_after_update": customer_after,
            },
        )

        booking_create_dict = (
            booking_resp.to_dict()
            if hasattr(booking_resp, "to_dict") and callable(getattr(booking_resp, "to_dict"))
            else self._obj_to_dict(booking_resp)
        )

        return {
            "booking_id": booking_id,
            "reservation_id_internal": reservation_id_internal,
            "customer_id": customer_id,
            "channel": channel,
            "booking_create": booking_create_dict,
            "booking_detail": booking_detail_dict,
            "customer_before_update": customer_before,
            "customer_after_update": customer_after,
            "used_customer_as_driver1": customer_as_driver1_result is not None,
            "set_customer_as_driver1_result": customer_as_driver1_result,
            "driver1_result": driver1_result,
            "driver2_result": driver2_result,
            "driver3_result": driver3_result,
        }

    def _normalize_email(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        s = str(value).strip().lower()
        return s or None

    def _emails_match(self, a: Optional[str], b: Optional[str]) -> bool:
        return self._normalize_email(a) == self._normalize_email(b)

    def _search_webcheckin_reservation_by_code(
            self,
            *,
            reservation_code: str,
            reservation_date: str,
    ):
        self._ensure_web_checkin_authenticated()

        parsed = self._parse_external_reservation_code(reservation_code)

        attempts = [
            WCReservationLookupRequest(
                reservation_number=str(parsed["reservation_number"]),
                reservation_prefix=str(parsed["reservation_prefix"]),
                reservation_date=str(reservation_date),
                confirmation_code=parsed["confirmation_code"],
            )
        ]

        # fallback: alcuni ambienti potrebbero voler number + confirmation nello stesso campo
        if parsed["confirmation_code"]:
            attempts.append(
                WCReservationLookupRequest(
                    reservation_number=f'{parsed["reservation_number"]} {parsed["confirmation_code"]}',
                    reservation_prefix=str(parsed["reservation_prefix"]),
                    reservation_date=str(reservation_date),
                    confirmation_code=None,
                )
            )

        last_error = None
        for req in attempts:
            try:
                return self.web_checkin_client.search_reservation(req).ensure_success()
            except Exception as e:
                last_error = e

        raise MyRentAdapterError(
            f"Nessuna reservation trovata via web-checkin per code='{reservation_code}' "
            f"e reservation_date='{reservation_date}'. Last error: {last_error}"
        )

    def _parse_external_reservation_code(self, reservation_code: str) -> Dict[str, Optional[str]]:
        raw = re.sub(r"\s+", " ", (reservation_code or "").strip())
        if not raw:
            raise MyRentAdapterError("reservation_code vuoto")

        m = re.match(
            r"^(?P<prefix>[A-Za-z]+)\s+(?P<number>\d+)(?:\s+(?P<confirmation>.+))?$",
            raw
        )
        if not m:
            raise MyRentAdapterError(
                f"Formato reservation_code non valido: '{reservation_code}'. "
                "Atteso ad es. 'SUL 123' oppure 'SUL 123 TESTDOGMA'"
            )

        return {
            "reservation_prefix": m.group("prefix").strip(),
            "reservation_number": m.group("number").strip(),
            "confirmation_code": (m.group("confirmation") or "").strip() or None,
            "raw_code": raw,
        }

    def _build_reservation_full_details(
            self,
            *,
            booking_id: str,
            channel: str,
            customer_id: Optional[Union[str, int]],
            reservation_web_checkin: Optional[Dict[str, Any]] = None,
            persisted_meta: Optional[Dict[str, Any]] = None,
            reservation_id_internal_hint: Optional[Union[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        Costruisce il payload finale dei reservation details partendo da:
        - booking_id
        - channel
        - customer_id opzionale
        - eventuale reservation_web_checkin già risolta a monte
        - eventuali metadati persistiti (driver results, flags, prefix/number/date/voucher)
        - eventuale reservation_id interno già noto
        """
        booking_id = str(booking_id or "").strip()
        if not booking_id:
            raise MyRentAdapterError("booking_id vuoto")

        channel = self._normalize_channel(channel)
        meta: Dict[str, Any] = dict(persisted_meta or {})

        # ------------------------------------------------------------------
        # 1) booking detail
        # ------------------------------------------------------------------
        self._ensure_authenticated()
        try:
            booking_detail_resp = self.client.get_booking(booking_id, channel=channel)
        except AuthenticationError:
            self.log.warning(
                "MyRent reservation details: auth fallita su get_booking, retry authenticate() ..."
            )
            self.client.authenticate()
            booking_detail_resp = self.client.get_booking(booking_id, channel=channel)
        except APIError as e:
            raise MyRentAdapterError(
                f"Get booking detail fallita per booking_id '{booking_id}': {e}"
            ) from e

        if not booking_detail_resp.data:
            raise MyRentAdapterError(
                f"Get booking detail non ha restituito dati per booking_id '{booking_id}'"
            )

        booking_detail = booking_detail_resp.data[0]

        if hasattr(booking_detail, "to_dict") and callable(getattr(booking_detail, "to_dict")):
            booking_detail_dict = booking_detail.to_dict()
        else:
            booking_detail_dict = self._obj_to_dict(booking_detail)

        if not isinstance(booking_detail_dict, dict) or not booking_detail_dict:
            raise MyRentAdapterError(
                f"Impossibile serializzare booking detail per booking_id '{booking_id}'"
            )

        fresh_customer_id = (
                booking_detail_dict.get("customerId")
                or booking_detail_dict.get("customer_id")
                or getattr(booking_detail, "customer_id", None)
                or customer_id
        )

        fresh_reservation_id = (
                booking_detail_dict.get("dbId")
                or booking_detail_dict.get("db_id")
                or getattr(booking_detail, "db_id", None)
                or reservation_id_internal_hint
        )

        # ------------------------------------------------------------------
        # 2) customer detail
        # ------------------------------------------------------------------
        customer_payload = None
        if fresh_customer_id:
            self._ensure_web_checkin_authenticated()
            try:
                customer_obj = self.web_checkin_client.get_customer(fresh_customer_id).ensure_success()
                customer_payload = self._customer_profile_to_dict(customer_obj)
            except WCAuthenticationError:
                self.log.warning(
                    "MyRent reservation details: auth fallita su get_customer, retry authenticate_for_web_checkin() ..."
                )
                self.web_checkin_client.authenticate_for_web_checkin()
                customer_obj = self.web_checkin_client.get_customer(fresh_customer_id).ensure_success()
                customer_payload = self._customer_profile_to_dict(customer_obj)
            except WCAPIError as e:
                raise MyRentAdapterError(
                    f"Get customer fallita per customer_id '{fresh_customer_id}': {e}"
                ) from e
            except Exception as e:
                raise MyRentAdapterError(
                    f"Get customer fallita per customer_id '{fresh_customer_id}': {e}"
                ) from e

        # ------------------------------------------------------------------
        # 3) lookup info utili per search_reservation / indicizzazione
        # ------------------------------------------------------------------
        reservation_prefix = meta.get("reservation_prefix")
        reservation_number = meta.get("reservation_number")
        reservation_date = meta.get("reservation_date")
        reservation_voucher = meta.get("reservation_voucher")

        recomputed_lookup = self._parse_booking_lookup_fields(
            booking_id=booking_id,
            booking_detail_dict=booking_detail_dict,
            booking_data=None,
        )

        reservation_prefix = reservation_prefix or recomputed_lookup.get("reservation_prefix")
        reservation_number = reservation_number or recomputed_lookup.get("reservation_number")
        reservation_date = reservation_date or recomputed_lookup.get("reservation_date")
        reservation_voucher = reservation_voucher or recomputed_lookup.get("reservation_voucher")

        # Se reservation_web_checkin è già stato passato, uso anche quello per arricchire i campi
        if reservation_web_checkin:
            reservation_voucher = reservation_voucher or reservation_web_checkin.get("voucher")
            if not reservation_date:
                reservation_date = self._extract_date_only_iso(
                    reservation_web_checkin.get("pick_up_date")
                    or reservation_web_checkin.get("pickUpDate")
                )

        # ------------------------------------------------------------------
        # 4) reservation live via web-checkin, se non già fornita
        # ------------------------------------------------------------------
        if reservation_web_checkin is None:
            self._ensure_web_checkin_authenticated()

            if reservation_prefix and reservation_number and reservation_date:
                try:
                    res_obj = self.web_checkin_client.search_reservation(
                        WCReservationLookupRequest(
                            reservation_number=str(reservation_number),
                            reservation_prefix=str(reservation_prefix),
                            reservation_date=str(reservation_date),
                        )
                    ).ensure_success()
                    reservation_web_checkin = res_obj.to_dict()
                except Exception as e:
                    self.log.warning(
                        "search_reservation fallita per booking_id=%s prefix=%s number=%s date=%s: %s",
                        booking_id,
                        reservation_prefix,
                        reservation_number,
                        reservation_date,
                        e,
                    )

            if reservation_web_checkin is None and reservation_voucher:
                try:
                    voucher_resp = self.web_checkin_client.search_reservations_by_voucher(
                        WCReservationVoucherSearchRequest(
                            reservation_voucher=str(reservation_voucher),
                        )
                    ).ensure_success()

                    matched = None
                    for item in voucher_resp.reservations:
                        if str(item.reservation_id or "") == str(fresh_reservation_id or ""):
                            matched = item
                            break
                        if str(item.num_pref_code or "").strip() == booking_id:
                            matched = item
                            break

                    if matched is None and voucher_resp.reservations:
                        matched = voucher_resp.reservations[0]

                    if matched is not None:
                        reservation_web_checkin = matched.to_dict()
                except Exception as e:
                    self.log.warning(
                        "search_reservations_by_voucher fallita per booking_id=%s voucher=%s: %s",
                        booking_id,
                        reservation_voucher,
                        e,
                    )

        # ------------------------------------------------------------------
        # 5) riallinea indice locale, se possibile
        # ------------------------------------------------------------------
        if fresh_reservation_id:
            try:
                self._index_reservation(
                    reservation_id=fresh_reservation_id,
                    booking_id=booking_id,
                    channel=channel,
                    customer_id=fresh_customer_id,
                    extra={
                        "reservation_prefix": reservation_prefix,
                        "reservation_number": reservation_number,
                        "reservation_date": reservation_date,
                        "reservation_voucher": reservation_voucher,
                        "used_customer_as_driver1": meta.get("used_customer_as_driver1"),
                        "set_customer_as_driver1_result": meta.get("set_customer_as_driver1_result"),
                        "driver1_result": meta.get("driver1_result"),
                        "driver2_result": meta.get("driver2_result"),
                        "driver3_result": meta.get("driver3_result"),
                        "customer_before_update": meta.get("customer_before_update"),
                        "customer_after_update": meta.get("customer_after_update"),
                    },
                )
            except Exception as e:
                self.log.warning(
                    "Indicizzazione reservation fallita per reservation_id=%s booking_id=%s: %s",
                    fresh_reservation_id,
                    booking_id,
                    e,
                )

        # ------------------------------------------------------------------
        # 6) payload finale
        # ------------------------------------------------------------------
        return {
            "reservation_id_internal": fresh_reservation_id,
            "booking_id": booking_id,
            "channel": channel,
            "customer_id": fresh_customer_id,
            "booking_detail": booking_detail_dict,
            "customer": customer_payload,

            # risultati compose persistiti dalla wrapper
            "used_customer_as_driver1": meta.get("used_customer_as_driver1"),
            "set_customer_as_driver1_result": meta.get("set_customer_as_driver1_result"),
            "driver1_result": meta.get("driver1_result"),
            "driver2_result": meta.get("driver2_result"),
            "driver3_result": meta.get("driver3_result"),

            # dettaglio live da web-checkin
            "reservation_web_checkin": reservation_web_checkin,

            # campi comodi
            "customer_first_name": None if reservation_web_checkin is None else reservation_web_checkin.get(
                "customer_first_name"),
            "customer_last_name": None if reservation_web_checkin is None else reservation_web_checkin.get(
                "customer_last_name"),
            "driver1": None if reservation_web_checkin is None else reservation_web_checkin.get("driver1"),
            "driver1_id": None if reservation_web_checkin is None else reservation_web_checkin.get("driver1_id"),
            "driver2": None if reservation_web_checkin is None else reservation_web_checkin.get("driver2"),
            "driver2_id": None if reservation_web_checkin is None else reservation_web_checkin.get("driver2_id"),
            "driver3": None if reservation_web_checkin is None else reservation_web_checkin.get("driver3"),
            "driver3_id": None if reservation_web_checkin is None else reservation_web_checkin.get("driver3_id"),
        }

    # ----------------------------- Public API: Reservation details -----------------------------
    def get_reservation_full_details(self, reservation_id: Union[str, int]) -> Dict[str, Any]:
        """
        Recupera i dettagli completi di una reservation a partire dal reservation_id interno
        usando l'indice persistito/in-memory, poi delega la costruzione del payload
        finale a _build_reservation_full_details(...).
        """
        rid = str(reservation_id).strip()
        if not rid:
            raise MyRentAdapterError("reservation_id vuoto")

        indexed = self._get_indexed_reservation(rid)
        if not indexed:
            raise MyRentAdapterError(
                f"reservation_id interno '{rid}' non trovato nell'indice persistito/in-memory. "
                "La reservation deve essere stata creata da questa wrapper oppure il file indice non deve essere stato perso."
            )

        booking_id = str(indexed.get("booking_id") or "").strip()
        channel = self._normalize_channel(indexed.get("channel"))
        customer_id = indexed.get("customer_id")

        if not booking_id:
            raise MyRentAdapterError(
                f"Indice corrotto/incompleto per reservation_id '{rid}': booking_id mancante"
            )

        return self._build_reservation_full_details(
            booking_id=booking_id,
            channel=channel,
            customer_id=customer_id,
            reservation_web_checkin=None,
            persisted_meta=indexed,
            reservation_id_internal_hint=rid,
        )

    def _normalize_channel_from_source_code(self, value: Optional[str]) -> Optional[str]:
        """
        Converte un reservation_source_code del web-checkin nel formato channel
        atteso dal booking SDK.

        Esempio:
            "RENTAL PREMIUM POA" -> "RENTAL_PREMIUM_POA"
        """
        if value is None:
            return None

        s = re.sub(r"\s+", " ", str(value).strip())
        if not s:
            return None

        return s.replace(" ", "_")

    def _candidate_channels_for_by_code(
        self,
        *,
        persisted_meta: Optional[Dict[str, Any]],
        reservation_web_checkin: Optional[Dict[str, Any]],
    ) -> List[str]:
        """
        Costruisce la lista dei channel candidati da usare per get_booking(...)
        nel flusso by-code.

        Priorità:
        1) channel persistito nell'indice locale
        2) reservation_source_code del web-checkin convertito in formato channel
        3) company_code del client come fallback finale
        """
        raw_candidates: List[str] = []

        if isinstance(persisted_meta, dict):
            persisted_channel = persisted_meta.get("channel")
            if isinstance(persisted_channel, str) and persisted_channel.strip():
                raw_candidates.append(persisted_channel.strip())

        if isinstance(reservation_web_checkin, dict):
            source_code = reservation_web_checkin.get("reservation_source_code")
            normalized_from_source = self._normalize_channel_from_source_code(source_code)
            if normalized_from_source:
                raw_candidates.append(normalized_from_source)

        company_code = getattr(self.client, "company_code", None)
        if isinstance(company_code, str) and company_code.strip():
            raw_candidates.append(company_code.strip())

        out: List[str] = []
        seen = set()

        for candidate in raw_candidates:
            try:
                normalized = self._normalize_channel(candidate)
            except Exception:
                continue

            key = normalized.upper()
            if key in seen:
                continue

            seen.add(key)
            out.append(normalized)

        return out

    def _booking_detail_is_complete(self, payload: Optional[Dict[str, Any]]) -> bool:
        """
        Verifica che il booking_detail ritornato sia davvero valido e non un payload
        parziale/errore mascherato.
        """
        if not isinstance(payload, dict):
            return False

        booking_detail = payload.get("booking_detail")
        if not isinstance(booking_detail, dict):
            return False

        # caso buono
        if booking_detail.get("id") and booking_detail.get("vehicle_code"):
            return True

        # caso errore mascherato in raw
        raw = booking_detail.get("raw")
        if isinstance(raw, dict) and raw.get("errors"):
            return False

        return False

    def get_reservation_full_details_by_code_and_email(
            self,
            *,
            reservation_code: str,
            customer_email: str,
            reservation_date: str,
    ) -> Dict[str, Any]:
        """
        Recupera i dettagli completi di una reservation partendo da:
        - reservation_code esterno (es. 'SUL 123' oppure 'SUL 123 TESTDOGMA')
        - email del customer
        - reservation_date (reservation date o pick-up date, formato yyyy-MM-dd)

        Flusso:
        1) lookup live via /api/v2/data/reservation
        2) get_customer(customer_id)
        3) verifica email
        4) risoluzione channel corretto
        5) get_booking(numPrefCode, channel) con retry sui channel candidati
        6) costruzione payload finale via _build_reservation_full_details(...)
        """
        if not reservation_code or not str(reservation_code).strip():
            raise MyRentAdapterError("reservation_code vuoto")

        if not customer_email or not str(customer_email).strip():
            raise MyRentAdapterError("customer_email vuota")

        if not reservation_date or not str(reservation_date).strip():
            raise MyRentAdapterError("reservation_date vuota")

        # 1) lookup live via web-checkin
        reservation_rec = self._search_webcheckin_reservation_by_code(
            reservation_code=reservation_code,
            reservation_date=reservation_date,
        )

        reservation_web_checkin = reservation_rec.to_dict()

        booking_id = reservation_rec.num_pref_code
        if not booking_id:
            raise MyRentAdapterError(
                "La reservation trovata non contiene numPrefCode, impossibile richiedere il booking detail"
            )

        customer_id = reservation_rec.customer_id
        if not customer_id:
            raise MyRentAdapterError(
                "La reservation trovata non contiene customerId, impossibile validare la mail"
            )

        # 2) lettura customer e verifica email
        self._ensure_web_checkin_authenticated()
        try:
            customer_obj = self.web_checkin_client.get_customer(customer_id).ensure_success()
        except WCAuthenticationError:
            self.web_checkin_client.authenticate_for_web_checkin()
            customer_obj = self.web_checkin_client.get_customer(customer_id).ensure_success()
        except Exception as e:
            raise MyRentAdapterError(
                f"Get customer fallita durante validazione email per customer_id '{customer_id}': {e}"
            ) from e

        if not self._emails_match(customer_obj.email, customer_email):
            # risposta neutra per evitare enumeration
            raise MyRentAdapterError("Reservation non trovata")

        # 3) prova a recuperare eventuali metadati già persistiti
        persisted_meta: Dict[str, Any] = {}
        if reservation_rec.reservation_id is not None:
            indexed = self._get_indexed_reservation(reservation_rec.reservation_id)
            if isinstance(indexed, dict):
                persisted_meta = dict(indexed)

        # se non c'è nulla nell'indice, almeno salvo lookup base
        if not persisted_meta:
            parsed_code = self._parse_external_reservation_code(reservation_code)
            persisted_meta = {
                "reservation_prefix": parsed_code.get("reservation_prefix"),
                "reservation_number": parsed_code.get("reservation_number"),
                "reservation_date": reservation_date,
                "reservation_voucher": reservation_rec.voucher,
            }

        # 4) costruisci i channel candidati
        candidate_channels = self._candidate_channels_for_by_code(
            persisted_meta=persisted_meta,
            reservation_web_checkin=reservation_web_checkin,
        )

        if not candidate_channels:
            raise MyRentAdapterError(
                f"Impossibile determinare il channel corretto per booking_id '{booking_id}'"
            )

        self.log.info(
            "By-code lookup booking_id=%s, channel candidati=%s",
            booking_id,
            candidate_channels,
        )

        # 5) prova i channel candidati finché non ottieni un booking detail valido
        last_payload: Optional[Dict[str, Any]] = None
        last_error: Optional[Exception] = None

        for channel in candidate_channels:
            try:
                payload = self._build_reservation_full_details(
                    booking_id=str(booking_id),
                    channel=channel,
                    customer_id=customer_id,
                    reservation_web_checkin=reservation_web_checkin,
                    persisted_meta=persisted_meta,
                    reservation_id_internal_hint=reservation_rec.reservation_id,
                )

                if self._booking_detail_is_complete(payload):
                    return payload

                last_payload = payload
                self.log.warning(
                    "By-code lookup: booking detail incompleto per booking_id=%s con channel=%s",
                    booking_id,
                    channel,
                )

            except Exception as e:
                last_error = e
                self.log.warning(
                    "By-code lookup: tentativo fallito per booking_id=%s con channel=%s: %s",
                    booking_id,
                    channel,
                    e,
                )

        # 6) nessun channel ha funzionato: errore esplicito
        if last_payload is not None:
            booking_detail = last_payload.get("booking_detail") if isinstance(last_payload, dict) else {}
            raw = booking_detail.get("raw") if isinstance(booking_detail, dict) else None
            raise MyRentAdapterError(
                f"Booking detail non recuperabile per booking_id '{booking_id}'. "
                f"Canali tentati: {candidate_channels}. "
                f"Ultima risposta raw: {raw}"
            )

        raise MyRentAdapterError(
            f"Booking detail non recuperabile per booking_id '{booking_id}'. "
            f"Canali tentati: {candidate_channels}. "
            f"Ultimo errore: {last_error}"
        )

    # ----------------------------- Internals: conversions -----------------------------
    def _normalize_transmission(self, v: Any) -> Optional[str]:
        if v is None:
            return None

        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            su = s.upper()
            if su in {"M", "MAN", "MANUALE", "MANUAL"}:
                return "M"
            if su in {"A", "AUT", "AUTO", "AUTOMATICO", "AUTOMATIC"}:
                return "A"
            if "MAN" in su:
                return "M"
            if "AUT" in su or "AUTO" in su:
                return "A"
            return s

        if isinstance(v, dict):
            desc = v.get("description") or v.get("Description") or v.get("name") or v.get("Name")
            code = v.get("code") or v.get("Code")
            vid = v.get("id") or v.get("ID")

            if isinstance(desc, str) and desc.strip():
                return self._normalize_transmission(desc)

            if isinstance(code, str) and code.strip():
                return self._normalize_transmission(code)

            vid_int = _coerce_int(vid)
            if vid_int is not None:
                if vid_int == 1:
                    return "M"
                if vid_int == 2:
                    return "A"
                return str(vid_int)

            return None

        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vi = _coerce_int(v)
            if vi == 1:
                return "M"
            if vi == 2:
                return "A"
            return str(v)

        try:
            s = str(v).strip()
            return s or None
        except Exception:
            return None

    def _convert_vehicle_status(
        self,
        vs: Dict[str, Any],
        wrapper_req: Dict[str, Any],
        days: int,
        pickup_loc: str,
        dropoff_loc: str,
    ) -> Dict[str, Any]:
        status = str(vs.get("Status") or "Available")
        ref_raw = vs.get("Reference") if isinstance(vs.get("Reference"), dict) else {}

        veh_raw = vs.get("Vehicle") if isinstance(vs.get("Vehicle"), dict) else {}

        if isinstance(veh_raw.get("groupPic"), dict):
            group_pic_raw = veh_raw.get("groupPic")
        elif isinstance(vs.get("groupPic"), dict):
            group_pic_raw = vs.get("groupPic")
        else:
            group_pic_raw = {}

        code = veh_raw.get("Code") or group_pic_raw.get("internationalCode") or ""
        code_context = veh_raw.get("CodeContext") or "ACRISS"

        make_model_name = self._extract_make_model_name(veh_raw) or str(code)

        national_code = (
            veh_raw.get("nationalCode")
            or group_pic_raw.get("nationalCode")
            or veh_raw.get("VendorCarType")
            or None
        )

        vid = group_pic_raw.get("id")
        if vid is None:
            vid = veh_raw.get("id")
        if vid is None or vid == "":
            vid = str(code) if code else None

        seats = _coerce_int(veh_raw.get("seats"))
        if seats == 0:
            seats = None

        air_condition = veh_raw.get("airCondition")
        if air_condition is None:
            air_condition = veh_raw.get("aircon")
        aircon = _coerce_bool(air_condition)

        fuel = veh_raw.get("fuel") or veh_raw.get("fuelType")

        transmission_norm = self._normalize_transmission(
            veh_raw.get("transmission") or veh_raw.get("Transmission")
        )

        locations = _unique([pickup_loc, dropoff_loc])

        tc_raw = vs.get("TotalCharge") if isinstance(vs.get("TotalCharge"), dict) else {}
        pre_vat, total = self._normalize_total_charge(tc_raw)

        base_daily = round((pre_vat / days), 2) if days > 0 else 0.0

        reference_out: Dict[str, Any] = {
            "calculated": {
                "days": days,
                "base_daily": base_daily,
                "pre_vat": round(pre_vat, 2),
                "vat_pct": self.vat_pct,
                "total": round(total, 2),
            },
            "myrent": ref_raw,
        }

        vparams_out = None
        if _coerce_bool(wrapper_req.get("showVehicleParameter")):
            if isinstance(vs.get("vehicleParameter"), list):
                params_raw = vs.get("vehicleParameter")
            elif isinstance(veh_raw.get("vehicleParameter"), list):
                params_raw = veh_raw.get("vehicleParameter")
            else:
                params_raw = []

            vparams_out = []
            for i, p in enumerate(params_raw or [], start=1):
                if not isinstance(p, dict):
                    continue
                name = p.get("name") or p.get("Name")
                desc = p.get("description") or p.get("Description")
                pos = _coerce_int(p.get("position") or p.get("Position")) or i
                if not name or not desc:
                    continue
                vparams_out.append(
                    {
                        "name :": str(name),
                        "description :": str(desc),
                        "position :": int(pos),
                        "fileUrl :": str(p.get("fileUrl") or ""),
                    }
                )

        group_pic_out = None
        if _coerce_bool(wrapper_req.get("showPics")):
            gid = _coerce_int(group_pic_raw.get("id"))
            if gid is not None:
                group_pic_out = {"id": int(gid), "url": None}

        vehicle_extra_image = [] if _coerce_bool(wrapper_req.get("showVehicleExtraImage")) else None

        optionals_out: List[Dict[str, Any]] = []
        show_opt_img = bool(_coerce_bool(wrapper_req.get("showOptionalImage")))
        opt_list = vs.get("optionals") if isinstance(vs.get("optionals"), list) else []
        for opt in opt_list:
            if not isinstance(opt, dict):
                continue
            ch = opt.get("Charge") if isinstance(opt.get("Charge"), dict) else {}
            eq = opt.get("Equipment") if isinstance(opt.get("Equipment"), dict) else {}

            amount = _coerce_float(ch.get("Amount")) or 0.0
            currency = ch.get("CurrencyCode") or "EUR"
            desc = ch.get("Description") or eq.get("Description") or eq.get("Code") or "OPTIONAL"

            optionals_out.append(
                {
                    "Charge": {
                        "Amount": round(amount, 2),
                        "CurrencyCode": str(currency),
                        "Description": str(desc),
                        "IncludedInEstTotalInd": bool(ch.get("IncludedInEstTotalInd", False)),
                        "IncludedInRate": bool(ch.get("IncludedInRate", False)),
                        "TaxInclusive": bool(ch.get("TaxInclusive", False)),
                    },
                    "Equipment": {
                        "Description": str(eq.get("Description") or desc),
                        "EquipType": str(eq.get("EquipType") or eq.get("Code") or "GEN"),
                        "Quantity": _coerce_int(eq.get("Quantity")) or 0,
                        "isMultipliable": bool(eq.get("isMultipliable", False)),
                        "optionalImage": (eq.get("optionalImage") if show_opt_img else None),
                    },
                }
            )

        vehicle_out: Dict[str, Any] = {
            "id": vid,
            "Code": str(code),
            "CodeContext": str(code_context),
            "nationalCode": national_code,
            "VehMakeModel": [{"Name": make_model_name}] if make_model_name else [],
            "model": make_model_name,
            "brand": None,
            "version": None,
            "VendorCarMacroGroup": veh_raw.get("VendorCarMacroGroup") or veh_raw.get("macroClass"),
            "VendorCarType": veh_raw.get("VendorCarType"),
            "seats": seats,
            "doors": _coerce_int(veh_raw.get("doors")) or None,
            "transmission": transmission_norm,
            "fuel": fuel,
            "aircon": aircon,
            "imageUrl": (veh_raw.get("vehicleGroupPic") or None) or None,
            "dailyRate": None,
            "km": 0,
            "color": None,
            "plate_no": None,
            "chasis_no": None,
            "locations": locations,
            "plates": [],
        }

        return {
            "Status": status,
            "Reference": reference_out,
            "Vehicle": vehicle_out,
            "vehicleParameter": vparams_out,
            "vehicleExtraImage": vehicle_extra_image,
            "groupPic": group_pic_out,
            "optionals": optionals_out,
            "total_charge": {
                "EstimatedTotalAmount": round(total, 2),
                "RateTotalAmount": round(pre_vat, 2),
            },
        }

    def _normalize_total_charge(self, tc_raw: Dict[str, Any]) -> Tuple[float, float]:
        est = _coerce_float(tc_raw.get("EstimatedTotalAmount"))
        rate = _coerce_float(tc_raw.get("RateTotalAmount"))
        taxable = _coerce_float(tc_raw.get("TaxableAmount"))

        vat_mult = 1.0 + (self.vat_pct / 100.0 if self.vat_pct else 0.0)

        if taxable is not None and rate is not None and rate > 0 and taxable > 0 and rate >= taxable:
            pre_vat = taxable
            total = est if (est is not None and est > 0) else rate
            return float(pre_vat), float(total)

        if taxable is not None and est is not None and est > 0:
            return float(taxable), float(est)

        if est is not None and rate is not None and est > 0 and rate > 0:
            if est >= rate:
                total = est
                pre_vat = rate
            else:
                total = rate
                pre_vat = est
            return float(pre_vat), float(total)

        if rate is not None and rate > 0:
            total = rate
            pre_vat = round(total / vat_mult, 2) if vat_mult else total
            return float(pre_vat), float(total)

        if est is not None and est > 0:
            total = est
            pre_vat = round(total / vat_mult, 2) if vat_mult else total
            return float(pre_vat), float(total)

        return 0.0, 0.0

    def _extract_make_model_name(self, veh_raw: Dict[str, Any]) -> Optional[str]:
        vmm = veh_raw.get("VehMakeModel")
        if isinstance(vmm, dict):
            name = vmm.get("Name") or vmm.get("name")
            if name:
                return str(name)

        if isinstance(vmm, list) and vmm:
            first = vmm[0]
            if isinstance(first, dict):
                name = first.get("Name") or first.get("name")
                if name:
                    return str(name)

        gw = veh_raw.get("groupWebDescription")
        if gw:
            return str(gw)

        return None

    def _normalize_weekofday(self, d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        day = _coerce_int(d.get("dayOfTheWeek"))
        name = d.get("dayOfTheWeekName")
        start = d.get("startTime")
        end = d.get("endTime")
        if day is None or not name or not start or not end:
            return None
        return {
            "dayOfTheWeek": int(day),
            "dayOfTheWeekName": str(name),
            "startTime": str(start),
            "endTime": str(end),
        }

    def _obj_to_dict(self, obj: Any) -> Dict[str, Any]:
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj

        if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
            try:
                d = obj.to_dict()
                if isinstance(d, dict):
                    return d
            except Exception:
                pass

        try:
            return asdict(obj)
        except Exception:
            pass

        try:
            return dict(getattr(obj, "__dict__", {}) or {})
        except Exception:
            return {}

    # ----------------------------- Vehicles cache & catalog -----------------------------
    def _vehicles_cache_key(self, *, location: str, age: int, channel: Optional[str]) -> str:
        loc = (location or "").strip().upper()
        ch = (channel or "").strip().upper()
        return f"{loc}|age={int(age)}|channel={ch}"

    def _vehicles_cache_get(self, key: str) -> Optional[List[Dict[str, Any]]]:
        if self._vehicles_cache_ttl_sec <= 0:
            return None

        now = time.monotonic()
        with self._vehicles_cache_lock:
            entry = self._vehicles_cache.get(key)
            if not entry:
                return None

            ts = entry.get("ts")
            data = entry.get("data")
            if not isinstance(ts, (int, float)) or not isinstance(data, list):
                self._vehicles_cache.pop(key, None)
                return None

            if (now - float(ts)) > float(self._vehicles_cache_ttl_sec):
                self._vehicles_cache.pop(key, None)
                return None

            return data

    def _vehicles_cache_set(self, key: str, data: List[Dict[str, Any]]) -> None:
        if self._vehicles_cache_ttl_sec <= 0:
            return

        now = time.monotonic()
        with self._vehicles_cache_lock:
            self._vehicles_cache[key] = {"ts": now, "data": data}

    def _vehicles_cache_prune(self) -> None:
        if self._vehicles_cache_ttl_sec <= 0:
            return

        now = time.monotonic()
        with self._vehicles_cache_lock:
            dead = []
            for k, entry in self._vehicles_cache.items():
                ts = entry.get("ts")
                if not isinstance(ts, (int, float)):
                    dead.append(k)
                    continue
                if (now - float(ts)) > float(self._vehicles_cache_ttl_sec):
                    dead.append(k)
            for k in dead:
                self._vehicles_cache.pop(k, None)

    def _vehicle_status_to_vehicle_group_raw(
        self,
        vs: Dict[str, Any],
        *,
        location: str,
    ) -> Optional[Dict[str, Any]]:
        veh = vs.get("Vehicle") if isinstance(vs.get("Vehicle"), dict) else {}
        ref = vs.get("Reference") if isinstance(vs.get("Reference"), dict) else {}
        calc = ref.get("calculated") if isinstance(ref.get("calculated"), dict) else {}

        vid = veh.get("id")
        international_code = veh.get("Code")
        if not international_code:
            return None

        national_code = veh.get("nationalCode")

        display_name = veh.get("model")
        if not display_name:
            vmm = veh.get("VehMakeModel")
            if isinstance(vmm, list) and vmm and isinstance(vmm[0], dict):
                display_name = vmm[0].get("Name")

        vendor_macro = veh.get("VendorCarMacroGroup")
        vehicle_type = veh.get("VendorCarType")

        seats = veh.get("seats")
        doors = veh.get("doors")
        transmission = veh.get("transmission")
        fuel = veh.get("fuel")
        aircon = veh.get("aircon")

        image_url = None
        gp = vs.get("groupPic") if isinstance(vs.get("groupPic"), dict) else {}
        if gp.get("url"):
            image_url = gp.get("url")
        if not image_url and isinstance(veh.get("imageUrl"), str):
            image_url = veh.get("imageUrl")

        daily_rate = _coerce_float(calc.get("base_daily"))

        return {
            "id": vid,
            "national_code": national_code,
            "international_code": international_code,
            "description": None,
            "display_name": display_name,
            "vendor_macro": vendor_macro,
            "vehicle_type": vehicle_type,
            "seats": _coerce_int(seats),
            "doors": _coerce_int(doors),
            "transmission": transmission,
            "fuel": fuel,
            "aircon": _coerce_bool(aircon),
            "image_url": image_url,
            "daily_rate": daily_rate,
            "locations": [location],
            "plates": None,
            "vehicle_parameters": None,
            "damages": None,
        }

    def list_vehicles_by_location(
        self,
        location: str,
        *,
        age: int = 30,
        channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_authenticated()

        loc = (location or "").strip().upper()
        if not loc:
            raise MyRentAdapterError("location vuota per list_vehicles_by_location(source=MYRENT)")

        cache_key = self._vehicles_cache_key(location=loc, age=int(age), channel=channel)
        cached = self._vehicles_cache_get(cache_key)
        if cached is not None:
            return cached

        self._vehicles_cache_prune()

        start_offsets_days = [5, 10]
        durations_days = [2, 4, 6, 8]

        now = datetime.utcnow()
        base_time = now.replace(hour=10, minute=0, second=0, microsecond=0)

        merged: Dict[str, Dict[str, Any]] = {}
        errors: List[str] = []

        for off in start_offsets_days:
            start_dt = base_time + timedelta(days=off)
            for dur in durations_days:
                wrapper_req = self._build_probe_wrapper_req(
                    location=loc,
                    start=start_dt,
                    duration_days=dur,
                    age=int(age),
                    channel=channel,
                )

                try:
                    q = self.get_quotations(wrapper_req)
                    vehicles = (q.get("data") or {}).get("Vehicles") or []
                except Exception as e:
                    self.log.warning(
                        "Probe quotations failed loc=%s off=%s dur=%s: %s",
                        loc, off, dur, e
                    )
                    errors.append(f"off={off} dur={dur}: {e}")
                    continue

                for vs in vehicles:
                    if not isinstance(vs, dict):
                        continue

                    item = self._vehicle_status_to_vehicle_group_raw(vs, location=loc)
                    if not item:
                        continue

                    key = str(item.get("id") or item.get("international_code") or "")
                    if not key:
                        continue

                    if key not in merged:
                        merged[key] = item
                    else:
                        existing = merged[key]

                        for k in [
                            "national_code", "display_name", "vendor_macro", "vehicle_type",
                            "seats", "doors", "transmission", "fuel", "aircon", "image_url"
                        ]:
                            if existing.get(k) in (None, "", 0) and item.get(k) not in (None, "", 0):
                                existing[k] = item[k]

                        ex_dr = _coerce_float(existing.get("daily_rate"))
                        it_dr = _coerce_float(item.get("daily_rate"))
                        if ex_dr is None:
                            existing["daily_rate"] = it_dr
                        elif it_dr is not None:
                            existing["daily_rate"] = min(ex_dr, it_dr)

                        ex_locs = existing.get("locations") or []
                        it_locs = item.get("locations") or []
                        existing["locations"] = _unique(list(ex_locs) + list(it_locs))

        out = list(merged.values())

        if not out and errors:
            raise MyRentAdapterError("Tutte le probe quotations sono fallite: " + " | ".join(errors[:5]))

        out.sort(key=lambda x: (str(x.get("vendor_macro") or ""), str(x.get("international_code") or "")))
        self._vehicles_cache_set(cache_key, out)

        return out