# myrent_sdk.py
# SDK MyRent (Authentication + Locations + Quotations) con SCHEMI tipizzati e fix su:
# - Formato date con secondi "YYYY-MM-DDTHH:MM:SS"
# - Normalizzazione channel (niente spazi) + fallback a company_code
# - Gestione agreementCoupon come STRING/opzionale
# - Messaggistica d’errore più chiara per Code 366 ("Not accepting connections")
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import time
import json
import logging
import re
import requests


__all__ = [
    "MyRentClient",
    "MyRentError",
    "AuthenticationError",
    "APIError",
    "AuthResult",
    "LocationType",
    "OpeningHours",
    "Location",
    "QuotationRequest",
    "QuotationItem",
    "QuotationData",
    "QuotationResponse",
]


# =====================================================================================
# Eccezioni
# =====================================================================================

class MyRentError(Exception):
    """Base exception per MyRent SDK."""


class AuthenticationError(MyRentError):
    """Lanciata quando l'autenticazione fallisce o il token manca/scade."""


class APIError(MyRentError):
    """Lanciata per risposte non-2xx o payload inattesi."""


# =====================================================================================
# Helper di parsing e normalizzazione
# =====================================================================================

_ISO_NO_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
_ISO_WITH_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _coerce_bool(v: Any) -> Optional[bool]:
    """Converte true/false (bool, number, string) in bool. Restituisce None se non interpretabile."""
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


def _coerce_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _coerce_int(v: Any) -> Optional[int]:
    try:
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return int(v) if v is not None else None
    except Exception:
        return None


def _fmt_dt_iso_seconds(dt: Union[str, datetime]) -> str:
    """
    Rende sicuro il formato datetime in stringa **con secondi**:
      - Se è datetime -> 'YYYY-MM-DDTHH:MM:SS'
      - Se è stringa:
          * se è già con i secondi la ritorna com'è
          * se è in forma 'YYYY-MM-DDTHH:MM' aggiunge ':00'
          * altrimenti la ritorna com'è (si assume valida per l'API)
    """
    if isinstance(dt, datetime):
        return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(dt, str):
        s = dt.strip()
        if _ISO_WITH_SECONDS.match(s):
            return s
        if _ISO_NO_SECONDS.match(s):
            return f"{s}:00"
        return s
    raise TypeError("start_date/end_date devono essere str o datetime")


def _sanitize_channel(channel: Optional[str]) -> Optional[str]:
    """
    Normalizza il channel rimuovendo **tutti** gli spazi.
    Esempio: 'RENTAL _PREMIUM_PREPAID' -> 'RENTAL_PREMIUM_PREPAID'
    """
    if channel is None:
        return None
    new_value = channel.replace(" ", "")
    return new_value


# =====================================================================================
# SCHEMI (Authentication + Locations)
# =====================================================================================

@dataclass(frozen=True)
class AuthResult:
    """Schema di output di Authentication (campo `result` nella risposta API)."""
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
        user_id = _coerce_int(result.get("user_id")) or 0
        username = str(result.get("username", ""))
        user_role = result.get("userRole")
        return AuthResult(
            user_id=user_id,
            username=username,
            token_value=str(token),
            user_role=user_role,
            raw=payload,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpeningHours:
    """Schema per una finestra oraria di apertura nel payload Locations."""
    day_of_the_week: Optional[int] = None
    day_of_the_week_name: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    dropoff_start_time: Optional[str] = None
    dropoff_end_time: Optional[str] = None
    is_valid_period: Optional[bool] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None

    @staticmethod
    def from_api_dict(d: Dict[str, Any]) -> "OpeningHours":
        # accetta sia 'dropoffendTime' che 'dropoffEndTime'
        dropoff_end = d.get("dropoffendTime")
        if dropoff_end is None:
            dropoff_end = d.get("dropoffEndTime")
        return OpeningHours(
            day_of_the_week=_coerce_int(d.get("dayOfTheWeek")),
            day_of_the_week_name=d.get("dayOfTheWeekName"),
            start_time=d.get("startTime"),
            end_time=d.get("endTime"),
            dropoff_start_time=d.get("dropoffStartTime"),
            dropoff_end_time=dropoff_end,
            is_valid_period=_coerce_bool(d.get("isValidPeriod")),
            valid_from=d.get("validFrom"),
            valid_to=d.get("validTo"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dayOfTheWeek": self.day_of_the_week,
            "dayOfTheWeekName": self.day_of_the_week_name,
            "startTime": self.start_time,
            "endTime": self.end_time,
            "dropoffStartTime": self.dropoff_start_time,
            "dropoffendTime": self.dropoff_end_time,  # coerente con payload osservato
            "isValidPeriod": self.is_valid_period,
            "validFrom": self.valid_from,
            "validTo": self.valid_to,
        }


@dataclass(frozen=True)
class Location:
    """Schema di output per una Location (campi dal payload reale)."""
    location_code: Optional[str] = None
    location_name: Optional[str] = None
    location_address: Optional[str] = None
    location_number: Optional[str] = None
    province: Optional[str] = None
    location_city: Optional[str] = None
    location_type: Optional[int] = None
    telephone_number: Optional[str] = None
    cell_number: Optional[str] = None
    email: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_airport: Optional[bool] = None
    is_railway: Optional[bool] = None
    is_always_opentrue: Optional[bool] = None  # nome “strano” coerente con payload
    is_car_sharing_enabled: Optional[bool] = None
    allow_pickup_dropoff_out_of_hours: Optional[bool] = None
    has_key_box: Optional[bool] = None
    morning_start_time: Optional[str] = None
    morning_stop_time: Optional[str] = None
    afternoon_start_time: Optional[str] = None
    afternoon_stop_time: Optional[str] = None
    location_info_en: Optional[str] = None
    location_info_local: Optional[str] = None
    openings: List[OpeningHours] = field(default_factory=list)
    closing: List[Any] = field(default_factory=list)
    festivity: List[Any] = field(default_factory=list)
    minimum_lead_time_in_hour: Optional[int] = None
    country: Optional[str] = None
    zip_code: Optional[str] = None
    public_web_description_en: Optional[str] = None
    public_web_description: Optional[str] = None
    is_out_of_hours: Optional[bool] = None
    only_dropoff_out_of_hours: Optional[bool] = None
    dropoff_address: Optional[str] = None

    @staticmethod
    def from_api_dict(d: Dict[str, Any]) -> "Location":
        openings_payload = d.get("openings") or []
        openings = [OpeningHours.from_api_dict(x) for x in openings_payload if isinstance(x, dict)]
        return Location(
            location_code=d.get("locationCode"),
            location_name=d.get("locationName"),
            location_address=d.get("locationAddress"),
            location_number=d.get("locationNumber"),
            province=d.get("province"),
            location_city=d.get("locationCity"),
            location_type=_coerce_int(d.get("locationType")),
            telephone_number=d.get("telephoneNumber"),
            cell_number=d.get("cellNumber"),
            email=d.get("email"),
            latitude=_coerce_float(d.get("latitude")),
            longitude=_coerce_float(d.get("longitude")),
            is_airport=_coerce_bool(d.get("isAirport")),
            is_railway=_coerce_bool(d.get("isRailway")),
            is_always_opentrue=_coerce_bool(d.get("isAlwaysOpentrue")),
            is_car_sharing_enabled=_coerce_bool(d.get("isCarSharingEnabled")),
            allow_pickup_dropoff_out_of_hours=_coerce_bool(d.get("allowPickUpDropOffOutOfHours")),
            has_key_box=_coerce_bool(d.get("hasKeyBox")),
            morning_start_time=d.get("morningStartTime"),
            morning_stop_time=d.get("morningStopTime"),
            afternoon_start_time=d.get("afternoonStartTime"),
            afternoon_stop_time=d.get("afternoonStopTime"),
            location_info_en=d.get("locationInfoEN"),
            location_info_local=d.get("locationInfoLocal"),
            openings=openings,
            closing=list(d.get("closing") or []),
            festivity=list(d.get("festivity") or []),
            minimum_lead_time_in_hour=_coerce_int(d.get("minimumLeadTimeInHour")),
            country=d.get("country"),
            zip_code=d.get("zipCode"),
            public_web_description_en=d.get("publicWebDescriptionEN"),
            public_web_description=d.get("publicWebDescription"),
            is_out_of_hours=_coerce_bool(d.get("isOutOfHours")),
            only_dropoff_out_of_hours=_coerce_bool(d.get("onlyDropOffOutOfHours")),
            dropoff_address=d.get("dropOffAddress"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "locationCode": self.location_code,
            "locationName": self.location_name,
            "locationAddress": self.location_address,
            "locationNumber": self.location_number,
            "province": self.province,
            "locationCity": self.location_city,
            "locationType": self.location_type,
            "telephoneNumber": self.telephone_number,
            "cellNumber": self.cell_number,
            "email": self.email,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "isAirport": self.is_airport,
            "isRailway": self.is_railway,
            "isAlwaysOpentrue": self.is_always_opentrue,
            "isCarSharingEnabled": self.is_car_sharing_enabled,
            "allowPickUpDropOffOutOfHours": self.allow_pickup_dropoff_out_of_hours,
            "hasKeyBox": self.has_key_box,
            "morningStartTime": self.morning_start_time,
            "morningStopTime": self.morning_stop_time,
            "afternoonStartTime": self.afternoon_start_time,
            "afternoonStopTime": self.afternoon_stop_time,
            "locationInfoEN": self.location_info_en,
            "locationInfoLocal": self.location_info_local,
            "openings": [o.to_dict() for o in self.openings],
            "closing": self.closing,
            "festivity": self.festivity,
            "minimumLeadTimeInHour": self.minimum_lead_time_in_hour,
            "country": self.country,
            "zipCode": self.zip_code,
            "publicWebDescriptionEN": self.public_web_description_en,
            "publicWebDescription": self.public_web_description,
            "isOutOfHours": self.is_out_of_hours,
            "onlyDropOffOutOfHours": self.only_dropoff_out_of_hours,
            "dropOffAddress": self.dropoff_address,
        }


class LocationType:
    """Valori ufficiali:
    - BOOKING_PICKUP = 1
    - BOOKING_DROPOFF = 2
    - BOOKING_BOTH   = 3
    """
    BOOKING_PICKUP: int = 1
    BOOKING_DROPOFF: int = 2
    BOOKING_BOTH: int = 3


# =====================================================================================
# SCHEMI (Quotations)
# =====================================================================================

@dataclass
class QuotationRequest:
    """Schema **input** per POST /api/v1/touroperator/quotations.

    Campi minimi:
    - pickupLocation, dropOffLocation: codici location
    - startDate, endDate: stringa o datetime (verranno forzati a 'YYYY-MM-DDTHH:MM:SS')
    - age: età conducente
    - channel: opzionale -> se non fornito, lo SDK userà company_code (normalizzato)

    Campi opzionali (boolean/string) come da Swagger:
    showPics, showOptionalImage, showVehicleParameter, showVehicleExtraImage,
    agreementCoupon (STRING!), discountValueWithoutVat, macroDescription, showBookingDiscount,
    isYoungDriverAge, isSeniorDriverAge
    """
    drop_off_location: str
    end_date: Union[str, datetime]
    pickup_location: str
    start_date: Union[str, datetime]
    age: int
    channel: Optional[str] = None  # verrà normalizzato (spazi rimossi)

    show_pics: Optional[bool] = None
    show_optional_image: Optional[bool] = None
    show_vehicle_parameter: Optional[bool] = None
    show_vehicle_extra_image: Optional[bool] = None
    # agreementCoupon è STRING in MyRent: se vuoto/None, viene omesso
    agreement_coupon: Optional[Union[str, bool]] = None
    discount_value_without_vat: Optional[str] = None
    macro_description: Optional[str] = None
    show_booking_discount: Optional[bool] = None
    is_young_driver_age: Optional[bool] = None
    is_senior_driver_age: Optional[bool] = None

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "dropOffLocation": self.drop_off_location,
            "endDate": _fmt_dt_iso_seconds(self.end_date),
            "pickupLocation": self.pickup_location,
            "startDate": _fmt_dt_iso_seconds(self.start_date),
            "age": int(self.age),
        }

        # channel: se fornito, normalizza rimuovendo spazi
        if self.channel is not None:
            payload["channel"] = _sanitize_channel(self.channel)

        # Opzionali
        opt_map: Dict[str, Any] = {
            "showPics": self.show_pics,
            "showOptionalImage": self.show_optional_image,
            "showVehicleParameter": self.show_vehicle_parameter,
            "showVehicleExtraImage": self.show_vehicle_extra_image,
            # agreementCoupon: includi SOLO se è una stringa non vuota
            # (se l'utente avesse passato True/False, lo ignoriamo come suggerito dal supporto)
            "discountValueWithoutVat": self.discount_value_without_vat,
            "macroDescription": self.macro_description,
            "showBookingDiscount": self.show_booking_discount,
            # Preferiamo la forma corretta 'isYoungDriverAge' ma includiamo anche la variante osservata
            "isYoungDriverAge": self.is_young_driver_age,
            "isSeniorDriverAge": self.is_senior_driver_age,
        }

        # agreementCoupon: gestiscilo a parte
        if isinstance(self.agreement_coupon, str):
            if self.agreement_coupon.strip():
                payload["agreementCoupon"] = self.agreement_coupon.strip()
        # Se è bool o altro, lo omettiamo per aderire al consiglio del supporto

        for k, v in opt_map.items():
            if v is not None:
                payload[k] = v

        # Per compatibilità con alcuni swagger che usano 'isyoungDriverAge'
        if self.is_young_driver_age is not None:
            payload["isyoungDriverAge"] = self.is_young_driver_age  # variante tollerante

        return payload


@dataclass(frozen=True)
class QuotationItem:
    """Schema **output** per un elemento della lista `quotation` nella risposta."""
    total: Optional[int] = None
    pick_up_location: Optional[str] = None
    return_location: Optional[str] = None
    pick_up_date_time: Optional[str] = None
    return_date_time: Optional[str] = None
    vehicles: List[Dict[str, Any]] = field(default_factory=list)
    optionals: List[Dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def from_api_dict(d: Dict[str, Any]) -> "QuotationItem":
        return QuotationItem(
            total=_coerce_int(d.get("total")),
            pick_up_location=d.get("PickUpLocation"),
            return_location=d.get("ReturnLocation"),
            pick_up_date_time=d.get("PickUpDateTime"),
            return_date_time=d.get("ReturnDateTime"),
            vehicles=list(d.get("Vehicles") or []),
            optionals=list(d.get("optionals") or []),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "PickUpLocation": self.pick_up_location,
            "ReturnLocation": self.return_location,
            "PickUpDateTime": self.pick_up_date_time,
            "ReturnDateTime": self.return_date_time,
            "Vehicles": self.vehicles,
            "optionals": self.optionals,
        }


@dataclass(frozen=True)
class QuotationData:
    """Contenuto della proprietà `data` nella risposta."""
    quotation: List[QuotationItem] = field(default_factory=list)
    total_charge: Dict[str, Any] = field(default_factory=dict)  # libero per ora

    @staticmethod
    def from_api_dict(d: Dict[str, Any]) -> "QuotationData":
        q_list = d.get("quotation") or []
        items = [QuotationItem.from_api_dict(x) for x in q_list if isinstance(x, dict)]
        total_charge = d.get("TotalCharge") or {}
        return QuotationData(quotation=items, total_charge=total_charge)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quotation": [q.to_dict() for q in self.quotation],
            "TotalCharge": self.total_charge,
        }


@dataclass(frozen=True)
class QuotationResponse:
    """Schema **output** radice per la risposta di Quotations."""
    data: QuotationData
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_payload(payload: Dict[str, Any]) -> "QuotationResponse":
        # Formati possibili:
        # { "data": {...} }
        # { "status": true, "message": "...", "data": {...} }
        data_obj = payload.get("data") or payload.get("Data") or {}
        qdata = QuotationData.from_api_dict(data_obj if isinstance(data_obj, dict) else {})
        return QuotationResponse(data=qdata, raw=payload)

    def to_dict(self) -> Dict[str, Any]:
        return {"data": self.data.to_dict(), "raw": self.raw}


# =====================================================================================
# Client HTTP
# =====================================================================================

class MyRentClient:
    """MyRent Booking API SDK (Authentication + Locations + Quotations)

    Endpoints:
      - POST /api/v1/touroperator/authentication
      - GET  /api/v1/touroperator/locations           (header: tokenValue)
      - POST /api/v1/touroperator/quotations          (header: tokenValue)

    Parametri:
      base_url      (str)  es. "https://sul.myrent.it/MyRentWeb"
      user_id       (str)  es. "bookingservice"
      password      (str)  es. "123booking"
      company_code  (str)  es. "sul"
      token_value   (str)  opzionale: se già disponibile
      timeout       (sec)  default 30
      max_retries   (int)  default 3 (429/5xx/timeout)
      backoff_factor(float) default 0.5
      user_agent    (str)  opzionale
      logger        (logging.Logger) opzionale
      session       (requests.Session) opzionale
    """

    AUTH_PATH = "/api/v1/touroperator/authentication"
    LOCATIONS_PATH = "/api/v1/touroperator/locations"
    QUOTATIONS_PATH = "/api/v1/touroperator/quotations"

    def __init__(
        self,
        base_url: str,
        user_id: Optional[str] = None,
        password: Optional[str] = None,
        company_code: Optional[str] = None,
        *,
        token_value: Optional[str] = None,
        timeout: Union[int, float] = 30,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        user_agent: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.user_id = user_id
        self.password = password
        self.company_code = company_code
        self._token_value = token_value
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.backoff_factor = float(backoff_factor)
        self.user_agent = user_agent or "myrent-sdk/0.4"
        self.log = logger or logging.getLogger("myrent_sdk")
        if not self.log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.log.addHandler(handler)
            self.log.setLevel(logging.INFO)
        self.session = session or requests.Session()

    # -------------------- HTTP low-level --------------------
    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self.backoff_factor * (2 ** attempt)
        self.log.debug("retry fra %.2fs", delay)
        time.sleep(delay)

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        url = self.base_url + path
        attempt = 0
        last_exc: Optional[Exception] = None
        print(json.dumps(json_body, indent=2))
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

                # 429 o 5xx -> retry con backoff
                if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                    self._sleep_backoff(attempt)
                    attempt += 1
                    continue

                # errori non retryable
                try:
                    payload = resp.json()
                except Exception:
                    payload = {"raw": resp.text}
                raise APIError(
                    f"HTTP {resp.status_code} {method} {url}: {json.dumps(payload)[:800]}"
                )

            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                self._sleep_backoff(attempt)
                attempt += 1
                continue

        if last_exc:
            raise APIError(
                f"Request fallita dopo {self.max_retries+1} tentativi: {last_exc}"
            ) from last_exc
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

    # -------------------- Authentication --------------------
    def authenticate(self) -> AuthResult:
        if not (self.user_id and self.password and self.company_code):
            raise AuthenticationError(
                "Servono user_id, password e company_code per authenticate()."
            )
        payload = dict(UserId=self.user_id, Password=self.password, companyCode=self.company_code)
        resp = self._request("POST", self.AUTH_PATH, json_body=payload)
        data = self._parse_json(resp)
        if not isinstance(data, dict):
            raise APIError("Formato inatteso della risposta di authentication.")
        auth = AuthResult.from_api_payload(data)
        self._token_value = auth.token_value
        return auth

    @property
    def token_value(self) -> str:
        if not self._token_value:
            raise AuthenticationError(
                "Token assente. Chiama authenticate() o passa token_value=... al costruttore."
            )
        return self._token_value

    # -------------------- Locations --------------------
    def get_locations(self) -> List[Location]:
        headers = {"tokenValue": self.token_value}
        resp = self._request("GET", self.LOCATIONS_PATH, headers=headers)
        payload = self._parse_json(resp)
        if isinstance(payload, dict) and isinstance(payload.get("result"), list):
            raw_list = payload["result"]
        elif isinstance(payload, list):
            raw_list = payload
        else:
            self.log.warning("Formato payload locations inatteso; forzo in lista.")
            raw_list = [payload]
        return [Location.from_api_dict(x) for x in raw_list if isinstance(x, dict)]

    def get_locations_by_type(self, location_type: int) -> List[Location]:
        return [loc for loc in self.get_locations() if loc.location_type == location_type]

    def find_location_by_code(self, code: str) -> Optional[Location]:
        code = (code or "").strip().upper()
        for loc in self.get_locations():
            if (loc.location_code or "").upper() == code:
                return loc
        return None

    # -------------------- Quotations --------------------
    def get_quotations(self, request: QuotationRequest) -> QuotationResponse:
        """
        Esegue una quotazione.

        Header: tokenValue
        Body:   vedi QuotationRequest.to_payload()
        Output: QuotationResponse (data.quotation, data.TotalCharge)

        Fix inclusi:
          - startDate/endDate forzati con secondi
          - normalizzazione channel (rimozione spazi)
          - omissione agreementCoupon se non stringa
          - messaggio esplicativo per error code 366
        """
        headers = {"tokenValue": self.token_value}

        payload = request.to_payload()

        # Se channel non è stato passato, usa company_code come channel (normalizzato)
        if "channel" not in payload:
            if not self.company_code:
                raise APIError("channel non fornito e company_code non impostato sul client.")
            payload["channel"] = _sanitize_channel(self.company_code)

        # Se il channel contiene ancora spazi (caso anomalo), fail fast
        if " " in payload.get("channel", ""):
            raise APIError(f"Il channel contiene spazi non validi: '{payload['channel']}'")

        resp = self._request("POST", self.QUOTATIONS_PATH, headers=headers, json_body=payload)
        print(json.dumps(resp.json(), indent=2))

        # prova subito a leggere JSON
        try:
            raw = resp.json()
        except Exception:
            raw = {"raw": resp.text}

        # Mappatura errori applicativi nota
        if isinstance(raw, dict):
            status = str(raw.get("status", "")).lower()
            err_node = (((raw.get("data") or {}).get("errors") or {}).get("Error") or {})
            short_text = err_node.get("ShortText")
            code = _coerce_int(err_node.get("Code"))

            if status == "error" or short_text:
                # In particolare, gestiamo il Code 366 con un messaggio utile
                if code == 366:
                    # Spesso causato da channel non abilitato per Booking o stringa channel non valida
                    tips = (
                        "Possibili cause: channel non abilitato ('Abilita per Booking' non spuntato) "
                        "oppure valore di 'channel' non valido (p.es. spazi non permessi). "
                        "Verificare in MyRent la convenzione e riprovare."
                    )
                    raise APIError(
                        f"Quotations error (code=366): {short_text}. {tips} | payload={json.dumps(raw)[:500]}"
                    )
                # default
                raise APIError(f"Quotations error (code={code}): {short_text} | payload={json.dumps(raw)[:500]}")

        # altrimenti prosegui con il parser "tollerante"
        data = self._parse_json(resp)
        if not isinstance(data, dict):
            raise APIError("Formato inatteso della risposta di quotations.")
        return QuotationResponse.from_api_payload(data)
