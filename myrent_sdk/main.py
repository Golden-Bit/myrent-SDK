# myrent_sdk.py
# SDK MyRent (Authentication + Locations + Quotations + Payments + Bookings)
# Fix inclusi:
# - Formato date con secondi "YYYY-MM-DDTHH:MM:SS"
# - Normalizzazione channel (niente spazi) + fallback a company_code
# - Gestione agreementCoupon come STRING/opzionale (omesso se non stringa o vuota)
# - Messaggistica d’errore più chiara per Code 366 ("Not accepting connections")
# - URL-encoding dei bookingId (spesso contiene spazi: "HQ 46 XXX")
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import time
import json
import logging
import re
from urllib.parse import quote

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
    # New: Payments + Bookings
    "PaymentsRequest",
    "PaymentsResponse",
    "BookingOptional",
    "BookingCompanyInfo",
    "BookingCustomer",
    "BookingFee",
    "BookingVehicleRequest",
    "BookingRequest",
    "Booking",
    "BookingResponse",
    "BookingStatus",
    "CancelResult",
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
    return channel.replace(" ", "")


def _maybe_strip(s: Any) -> Optional[str]:
    if s is None:
        return None
    if isinstance(s, str):
        ss = s.strip()
        return ss if ss else None
    return str(s)


def _encode_path_segment(value: str) -> str:
    """
    BookingId spesso contiene spazi (es. 'HQ 46 XXX') -> va percent-encodato.
    """
    return quote((value or "").strip(), safe="")


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
            "discountValueWithoutVat": self.discount_value_without_vat,
            "macroDescription": self.macro_description,
            "showBookingDiscount": self.show_booking_discount,
            "isYoungDriverAge": self.is_young_driver_age,
            "isSeniorDriverAge": self.is_senior_driver_age,
        }

        # agreementCoupon: gestiscilo a parte (solo string non vuota)
        if isinstance(self.agreement_coupon, str) and self.agreement_coupon.strip():
            payload["agreementCoupon"] = self.agreement_coupon.strip()

        for k, v in opt_map.items():
            if v is not None:
                payload[k] = v

        # Compatibilità con swagger “sporchi”
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
    quotation: List[QuotationItem] = field(default_factory=list)
    total_charge: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_dict(d: Dict[str, Any]) -> "QuotationData":
        # ✅ FORMATO "FLAT" (quello che hai nel raw): data = { total, PickUp..., Vehicles:[...] }
        if isinstance(d, dict) and "Vehicles" in d:
            item = QuotationItem.from_api_dict(d)
            # Nota: spesso TotalCharge NON è a livello root in questo formato (è per-veicolo).
            # Se c'è a root lo prendiamo, altrimenti lo lasciamo vuoto.
            total_charge = d.get("TotalCharge") or {}
            return QuotationData(quotation=[item], total_charge=total_charge)

        # ✅ FORMATO "CLASSICO": data = { quotation:[...], TotalCharge:{...} }
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
        # Formati possibili osservati:
        # 1) { "data": {...} }
        # 2) { "status": true, "message": "...", "data": {...} }
        # 3) { "data": [ {...}, {...} ] }  (lista “diretta”)
        data_obj = payload.get("data") or payload.get("Data") or {}
        if isinstance(data_obj, list):
            # Lista diretta -> la mappo come "quotation"
            items = [QuotationItem.from_api_dict(x) for x in data_obj if isinstance(x, dict)]
            qdata = QuotationData(quotation=items, total_charge={})
        elif isinstance(data_obj, dict):
            qdata = QuotationData.from_api_dict(data_obj)
        else:
            qdata = QuotationData()
        return QuotationResponse(data=qdata, raw=payload)

    def to_dict(self) -> Dict[str, Any]:
        return {"data": self.data.to_dict(), "raw": self.raw}


# =====================================================================================
# SCHEMI (Payments)
# =====================================================================================

@dataclass
class PaymentsRequest:
    """Body per POST /api/v1/touroperator/payments"""
    language: str = "it"

    def to_payload(self) -> Dict[str, Any]:
        return {"language": self.language}


@dataclass(frozen=True)
class PaymentsResponse:
    """
    Risposta tipicamente “libera” (wireTransfer, paypal, Nexi, stripe, ...).
    La manteniamo raw ma con un wrapper coerente.
    """
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_payload(payload: Any) -> "PaymentsResponse":
        if isinstance(payload, dict):
            return PaymentsResponse(raw=payload)
        return PaymentsResponse(raw={"raw": payload})


# =====================================================================================
# SCHEMI (Bookings)
# =====================================================================================

@dataclass
class BookingOptional:
    """
    Rappresenta un optional nel body di create booking.
    Nello spec: 'optionals' è descritto come lista con EquipType, Quantity, Selected, Prepaid.
    In pratica alcune istanze tollerano anche dict generici.
    """
    equip_type: Optional[str] = None
    quantity: Optional[int] = None
    selected: Optional[bool] = None
    prepaid: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.equip_type is not None:
            d["EquipType"] = self.equip_type
        if self.quantity is not None:
            d["Quantity"] = int(self.quantity)
        if self.selected is not None:
            d["Selected"] = bool(self.selected)
        if self.prepaid is not None:
            d["Prepaid"] = bool(self.prepaid)
        return d


@dataclass
class BookingCompanyInfo:
    company_phone_number: Optional[str] = None
    company_email: Optional[str] = None
    company_e_invoicing_code: Optional[str] = None
    company_e_invoicing_email: Optional[str] = None
    company_birth_date: Optional[Union[str, datetime]] = None
    company_birth_city: Optional[str] = None
    company_birth_prov: Optional[str] = None
    company_birth_country: Optional[str] = None
    company_street: Optional[str] = None
    company_street_number: Optional[str] = None
    company_city_name: Optional[str] = None
    company_postal_code: Optional[str] = None
    company_state_prov: Optional[str] = None
    company_country: Optional[str] = None
    company_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        # NB: alcuni campi in spec hanno naming “CompanyX”
        mapping = {
            "CompanyPhoneNumber": self.company_phone_number,
            "CompanyEmail": self.company_email,
            "CompanyEInvoicingCode": self.company_e_invoicing_code,
            "CompanyEInvoicingEmail": self.company_e_invoicing_email,
            "CompanyBirthCity": self.company_birth_city,
            "CompanyBirthProv": self.company_birth_prov,
            "CompanyBirthCountry": self.company_birth_country,
            "CompanyStreet": self.company_street,
            "CompanyStreetNumber": self.company_street_number,
            "CompanyCityName": self.company_city_name,
            "CompanyPostalCode": self.company_postal_code,
            "CompanyStateProv": self.company_state_prov,
            "CompanyCountry": self.company_country,
            "CompanyName": self.company_name,
        }
        for k, v in mapping.items():
            vv = _maybe_strip(v)
            if vv is not None:
                d[k] = vv

        if self.company_birth_date is not None:
            # In spec appare ISO con Z, ma accettiamo anche "YYYY-MM-DDTHH:MM:SS"
            if isinstance(self.company_birth_date, datetime):
                d["CompanyBirthDate"] = self.company_birth_date.replace(microsecond=0).isoformat()
            else:
                d["CompanyBirthDate"] = str(self.company_birth_date).strip()

        return d


@dataclass
class BookingCustomer:
    """
    Customer nel body booking. Lo spec ha duplicazioni (Name/Surname e firstName/lastName).
    Qui esponiamo una forma “pulita” ma serializziamo *tutti* i campi quando valorizzati.
    """
    # alias principali
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    # campi aggiuntivi spec
    client_id: Optional[str] = None
    ragione_sociale: Optional[str] = None
    codice: Optional[str] = None
    street: Optional[str] = None
    num: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    ph_num1: Optional[str] = None
    ph_num2: Optional[str] = None
    mobile_number: Optional[str] = None
    email: Optional[str] = None
    vat_number: Optional[str] = None
    birth_place: Optional[str] = None
    birth_date: Optional[Union[str, datetime]] = None
    birth_province: Optional[str] = None
    birth_nation: Optional[str] = None
    gender: Optional[bool] = None  # true=Male, false=Female (spec)
    tax_code: Optional[str] = None
    document: Optional[str] = None
    document_number: Optional[str] = None
    licence_type: Optional[str] = None
    issue_by: Optional[str] = None
    release_date: Optional[Union[str, datetime]] = None
    expiry_date: Optional[Union[str, datetime]] = None
    e_invoice_email: Optional[str] = None
    e_invoice_code: Optional[str] = None
    is_physical_person: Optional[Union[str, bool]] = None  # spesso "true"/"false"
    is_individual_company: Optional[Union[str, bool]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}

        # Spec: supporta sia Name/Surname sia firstName/lastName
        fn = _maybe_strip(self.first_name)
        ln = _maybe_strip(self.last_name)
        if fn is not None:
            d["Name"] = fn
            d["firstName"] = fn
        if ln is not None:
            d["Surname"] = ln
            d["lastName"] = ln

        mapping = {
            "clientId": self.client_id,
            "ragioneSociale": self.ragione_sociale,
            "codice": self.codice,
            "street": self.street,
            "num": self.num,
            "city": self.city,
            "zip": self.zip,
            "country": self.country,
            "state": self.state,
            "phNum1": self.ph_num1,
            "phNum2": self.ph_num2,
            "mobileNumber": self.mobile_number,
            "email": self.email,
            "vatNumber": self.vat_number,
            "birthPlace": self.birth_place,
            "birthProvince": self.birth_province,
            "birthNation": self.birth_nation,
            "taxCode": self.tax_code,
            "document": self.document,
            "documentNumber": self.document_number,
            "licenceType": self.licence_type,
            "issueBy": self.issue_by,
            "eInvoiceEmail": self.e_invoice_email,
            "eInvoiceCode": self.e_invoice_code,
        }
        for k, v in mapping.items():
            vv = _maybe_strip(v)
            if vv is not None:
                d[k] = vv

        if self.gender is not None:
            d["gender"] = bool(self.gender)

        if self.birth_date is not None:
            d["birthDate"] = _fmt_dt_iso_seconds(self.birth_date) if isinstance(self.birth_date, datetime) else str(self.birth_date).strip()

        if self.release_date is not None:
            d["releaseDate"] = _fmt_dt_iso_seconds(self.release_date) if isinstance(self.release_date, datetime) else str(self.release_date).strip()

        if self.expiry_date is not None:
            d["expiryDate"] = _fmt_dt_iso_seconds(self.expiry_date) if isinstance(self.expiry_date, datetime) else str(self.expiry_date).strip()

        # Flag string/bool (“true”/“false” spesso)
        if self.is_physical_person is not None:
            if isinstance(self.is_physical_person, bool):
                d["isPhysicalPerson"] = str(self.is_physical_person).lower()
            else:
                d["isPhysicalPerson"] = str(self.is_physical_person).strip()
        if self.is_individual_company is not None:
            if isinstance(self.is_individual_company, bool):
                d["isIndividualCompany"] = str(self.is_individual_company).lower()
            else:
                d["isIndividualCompany"] = str(self.is_individual_company).strip()

        return d


@dataclass
class BookingFee:
    currency_code: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[Union[str, int, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.currency_code is not None:
            d["CurrencyCode"] = str(self.currency_code)
        if self.description is not None:
            d["Description"] = str(self.description)
        if self.amount is not None:
            d["Amount"] = str(self.amount)
        return d


@dataclass
class BookingVehicleRequest:
    """
    VehicleRequest nel body booking.
    PaymentType: valori documentati (BONIFICO/PayPal/CREDITCARDDEFERRED/CUSTOMCREDITCARD)
    """
    payment_type: Optional[str] = None
    type: Optional[str] = None
    payment_amount: Optional[float] = None
    payment_transaction_type_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.payment_type is not None:
            d["PaymentType"] = str(self.payment_type)
        if self.type is not None:
            d["type"] = str(self.type)
        if self.payment_amount is not None:
            d["PaymentAmount"] = float(self.payment_amount)
        if self.payment_transaction_type_code is not None:
            d["PaymentTransactionTypeCode"] = str(self.payment_transaction_type_code)
        return d


@dataclass
class BookingRequest:
    """
    Body per POST /api/v1/touroperator/bookings.

    Minimo “realistico”:
      - pickupLocation, dropOffLocation
      - startDate, endDate
      - channel (fallback a company_code nel client)
      - VehicleCode
      - Customer
      - VehicleRequest (almeno PaymentType, se richiesto dall’istanza)

    Nota: lo spec è incoerente su optionals (object/array): qui supportiamo entrambe.
    """
    drop_off_location: str
    pickup_location: str
    start_date: Union[str, datetime]
    end_date: Union[str, datetime]
    vehicle_code: str

    channel: Optional[str] = None

    optionals: Optional[List[Union[BookingOptional, Dict[str, Any]]]] = None
    young_driver_fee: Optional[Union[int, float]] = None
    senior_driver_fee: Optional[Union[int, float]] = None
    senior_driver_fee_desc: Optional[str] = None
    young_driver_fee_desc: Optional[str] = None
    online_user: Optional[int] = None
    insurance_id: Optional[int] = None
    agreement_coupon: Optional[Union[str, bool]] = None
    transaction_status_code: Optional[str] = None
    pay_now_dis: Optional[str] = None
    is_young_driver_age: Optional[bool] = None
    is_senior_driver_age: Optional[bool] = None

    company_info: Optional[BookingCompanyInfo] = None
    customer: Optional[BookingCustomer] = None
    fee: Optional[BookingFee] = None
    vehicle_request: Optional[BookingVehicleRequest] = None

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "dropOffLocation": self.drop_off_location,
            "pickupLocation": self.pickup_location,
            "startDate": _fmt_dt_iso_seconds(self.start_date),
            "endDate": _fmt_dt_iso_seconds(self.end_date),
            "VehicleCode": self.vehicle_code,
        }

        if self.channel is not None:
            payload["channel"] = _sanitize_channel(self.channel)

        # optionals: lista di dict o BookingOptional
        if self.optionals is not None:
            opt_list: List[Dict[str, Any]] = []
            for o in self.optionals:
                if isinstance(o, BookingOptional):
                    od = o.to_dict()
                    if od:
                        opt_list.append(od)
                elif isinstance(o, dict):
                    opt_list.append(o)
            payload["optionals"] = opt_list

        if self.young_driver_fee is not None:
            payload["youngDriverFee"] = float(self.young_driver_fee)
        if self.senior_driver_fee is not None:
            payload["seniorDriverFee"] = float(self.senior_driver_fee)
        if self.senior_driver_fee_desc is not None:
            payload["seniorDriverFeeDesc"] = self.senior_driver_fee_desc
        if self.young_driver_fee_desc is not None:
            payload["youngDriverFeeDesc"] = self.young_driver_fee_desc
        if self.online_user is not None:
            payload["onlineUser"] = int(self.online_user)
        if self.insurance_id is not None:
            payload["insuranceId"] = int(self.insurance_id)
        if self.transaction_status_code is not None:
            payload["TransactionStatusCode"] = str(self.transaction_status_code)
        if self.pay_now_dis is not None:
            payload["PayNowDis"] = str(self.pay_now_dis)
        if self.is_young_driver_age is not None:
            payload["isYoungDriverAge"] = bool(self.is_young_driver_age)
        if self.is_senior_driver_age is not None:
            payload["isSeniorDriverAge"] = bool(self.is_senior_driver_age)

        # agreementCoupon: includi SOLO se stringa non vuota
        if isinstance(self.agreement_coupon, str) and self.agreement_coupon.strip():
            payload["agreementCoupon"] = self.agreement_coupon.strip()

        if self.company_info is not None:
            ci = self.company_info.to_dict()
            if ci:
                payload["CompanyInfo"] = ci

        if self.customer is not None:
            cu = self.customer.to_dict()
            if cu:
                payload["Customer"] = cu

        if self.fee is not None:
            fe = self.fee.to_dict()
            if fe:
                payload["Fee"] = fe

        if self.vehicle_request is not None:
            vr = self.vehicle_request.to_dict()
            if vr:
                payload["VehicleRequest"] = vr

        return payload


@dataclass(frozen=True)
class Booking:
    """
    Booking “libero” lato response: lo spec è molto grande e incoerente.
    Qui estraiamo id e conserviamo raw.
    """
    id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_dict(d: Dict[str, Any]) -> "Booking":
        booking_id = d.get("id") or d.get("Id") or d.get("bookingId") or d.get("BookingId")
        return Booking(id=str(booking_id) if booking_id is not None else None, raw=d)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "raw": self.raw}


@dataclass(frozen=True)
class BookingResponse:
    """Wrapper della response di create/get booking."""
    data: List[Booking] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_payload(payload: Any) -> "BookingResponse":
        if not isinstance(payload, dict):
            return BookingResponse(data=[], raw={"raw": payload})

        # Formati possibili:
        # - {"data":[{...},{...}]}
        # - {"result":[{...},{...}]}
        # - {"data":{...}} (raro) -> lo wrappiamo in lista
        node = payload.get("data")
        if node is None:
            node = payload.get("result")
        items: List[Dict[str, Any]] = []
        if isinstance(node, list):
            items = [x for x in node if isinstance(x, dict)]
        elif isinstance(node, dict):
            items = [node]
        elif isinstance(payload, dict) and any(k in payload for k in ("id", "Id", "bookingId")):
            # payload “piatto”
            items = [payload]

        bookings = [Booking.from_api_dict(x) for x in items]
        return BookingResponse(data=bookings, raw=payload)

    def to_dict(self) -> Dict[str, Any]:
        return {"data": [b.to_dict() for b in self.data], "raw": self.raw}


@dataclass(frozen=True)
class BookingStatus:
    id: Optional[str] = None
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_payload(payload: Any) -> "BookingStatus":
        if isinstance(payload, dict):
            return BookingStatus(
                id=_maybe_strip(payload.get("id") or payload.get("Id")),
                status=_maybe_strip(payload.get("status") or payload.get("Status")),
                raw=payload,
            )
        return BookingStatus(raw={"raw": payload})


@dataclass(frozen=True)
class CancelResult:
    id: Optional[str] = None
    cancel_status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_api_payload(payload: Any) -> "CancelResult":
        if isinstance(payload, dict):
            return CancelResult(
                id=_maybe_strip(payload.get("id") or payload.get("Id")),
                cancel_status=_maybe_strip(payload.get("CancelStatus") or payload.get("cancelStatus")),
                raw=payload,
            )
        return CancelResult(raw={"raw": payload})


# =====================================================================================
# Client HTTP
# =====================================================================================

class MyRentClient:
    """MyRent Booking API SDK

    Endpoints:
      - POST /api/v1/touroperator/authentication
      - GET  /api/v1/touroperator/locations              (header: tokenValue)
      - POST /api/v1/touroperator/quotations             (header: tokenValue)
      - POST /api/v1/touroperator/payments               (header: tokenValue)
      - POST /api/v1/touroperator/bookings               (header: tokenValue)
      - GET  /api/v1/touroperator/bookings/{bookingId}   (header: tokenValue + channel)
      - GET  /api/v1/touroperator/bookings/{bookingId}/status
      - GET  /api/v1/touroperator/bookings/{bookingId}/cancel (header: tokenValue + channel)

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

    PAYMENTS_PATH = "/api/v1/touroperator/payments"
    BOOKINGS_PATH = "/api/v1/touroperator/bookings"
    BOOKING_STATUS_SUFFIX = "/status"
    BOOKING_CANCEL_SUFFIX = "/cancel"

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
        self.user_agent = user_agent or "myrent-sdk/0.5"
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

        while attempt <= self.max_retries:
            try:
                if self.log.isEnabledFor(logging.DEBUG) and json_body is not None:
                    self.log.debug("REQUEST %s %s body=%s", method.upper(), url, json.dumps(json_body, indent=2))

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

                # 401 -> token invalid/expired (spesso)
                if resp.status_code == 401:
                    try:
                        payload = resp.json()
                    except Exception:
                        payload = {"raw": resp.text}
                    raise AuthenticationError(
                        f"HTTP 401 {method} {url}: token non valido/scaduto | payload={json.dumps(payload)[:800]}"
                    )

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

    def _require_channel(self, channel: Optional[str]) -> str:
        ch = _sanitize_channel(channel)
        if not ch:
            # fallback a company_code
            ch = _sanitize_channel(self.company_code)
        if not ch:
            raise APIError("channel mancante e company_code non impostato sul client.")
        if " " in ch:
            raise APIError(f"Il channel contiene spazi non validi: '{ch}'")
        return ch

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

        # Formati osservati:
        # - [{"locationCode":...}, ...]
        # - {"result":[...]}
        # - {"data":[...]} (alcune istanze)
        if isinstance(payload, dict) and isinstance(payload.get("result"), list):
            raw_list = payload["result"]
        elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
            raw_list = payload["data"]
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
            payload["channel"] = self._require_channel(None)

        # Se il channel contiene ancora spazi (caso anomalo), fail fast
        if " " in payload.get("channel", ""):
            raise APIError(f"Il channel contiene spazi non validi: '{payload['channel']}'")

        resp = self._request("POST", self.QUOTATIONS_PATH, headers=headers, json_body=payload)

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
                if code == 366:
                    tips = (
                        "Possibili cause: channel non abilitato ('Abilita per Booking' non spuntato) "
                        "oppure valore di 'channel' non valido (p.es. spazi non permessi). "
                        "Verificare in MyRent la convenzione e riprovare."
                    )
                    raise APIError(
                        f"Quotations error (code=366): {short_text}. {tips} | payload={json.dumps(raw)[:500]}"
                    )
                raise APIError(
                    f"Quotations error (code={code}): {short_text} | payload={json.dumps(raw)[:500]}"
                )

        data = self._parse_json(resp)
        if not isinstance(data, dict):
            raise APIError("Formato inatteso della risposta di quotations.")
        return QuotationResponse.from_api_payload(data)

    # =================================================================================
    # NEW ENDPOINTS: payments(), create_booking(), get_booking(), get_booking_status(),
    #                cancel_booking()
    # =================================================================================

    # -------------------- Payments --------------------
    def payments(self, request: Optional[PaymentsRequest] = None) -> PaymentsResponse:
        """
        POST /api/v1/touroperator/payments
        Header: tokenValue
        Body: { "language": "it" | "en" | ... }

        Ritorna PaymentsResponse(raw=...).
        """
        req = request or PaymentsRequest()
        headers = {"tokenValue": self.token_value}
        resp = self._request("POST", self.PAYMENTS_PATH, headers=headers, json_body=req.to_payload())
        payload = self._parse_json(resp)
        return PaymentsResponse.from_api_payload(payload)

    # -------------------- Create Booking --------------------
    def create_booking(self, request: BookingRequest) -> BookingResponse:
        """
        POST /api/v1/touroperator/bookings
        Header: tokenValue
        Body: BookingRequest.to_payload()

        Fix inclusi:
          - startDate/endDate forzati con secondi
          - normalizzazione channel (rimozione spazi) + fallback company_code
          - omissione agreementCoupon se non stringa
          - URL/bookingId non rilevante qui (POST)
        """
        headers = {"tokenValue": self.token_value}
        payload = request.to_payload()

        # channel: se non presente nel request, fallback a company_code
        if "channel" not in payload:
            payload["channel"] = self._require_channel(None)
        else:
            payload["channel"] = self._require_channel(payload.get("channel"))

        resp = self._request("POST", self.BOOKINGS_PATH, headers=headers, json_body=payload)
        data = self._parse_json(resp)
        return BookingResponse.from_api_payload(data)

    # -------------------- Get Booking (Dettaglio) --------------------
    def get_booking(self, booking_id: str, channel: Optional[str]) -> BookingResponse:
        """
        GET /api/v1/touroperator/bookings/{bookingId}
        Header: tokenValue + channel (OBBLIGATORIO nello spec)

        Nota: bookingId spesso contiene spazi -> viene URL-encodato.
        """
        bid = _encode_path_segment(booking_id)
        ch = self._require_channel(channel)
        headers = {"tokenValue": self.token_value, "channel": ch}

        path = f"{self.BOOKINGS_PATH}/{bid}"
        resp = self._request("GET", path, headers=headers)
        payload = self._parse_json(resp)
        return BookingResponse.from_api_payload(payload)

    # -------------------- Get Booking Status --------------------
    def get_booking_status(self, booking_id: str) -> BookingStatus:
        """
        GET /api/v1/touroperator/bookings/{bookingId}/status
        Header: tokenValue
        """
        bid = _encode_path_segment(booking_id)
        headers = {"tokenValue": self.token_value}

        path = f"{self.BOOKINGS_PATH}/{bid}{self.BOOKING_STATUS_SUFFIX}"
        resp = self._request("GET", path, headers=headers)
        payload = self._parse_json(resp)
        return BookingStatus.from_api_payload(payload)

    # -------------------- Cancel Booking --------------------
    def cancel_booking(self, booking_id: str, channel: Optional[str]) -> CancelResult:
        """
        GET /api/v1/touroperator/bookings/{bookingId}/cancel
        Header: tokenValue + channel (OBBLIGATORIO nello spec)
        """
        bid = _encode_path_segment(booking_id)
        ch = self._require_channel(channel)
        headers = {"tokenValue": self.token_value, "channel": ch}

        path = f"{self.BOOKINGS_PATH}/{bid}{self.BOOKING_CANCEL_SUFFIX}"
        resp = self._request("GET", path, headers=headers)
        payload = self._parse_json(resp)
        return CancelResult.from_api_payload(payload)
