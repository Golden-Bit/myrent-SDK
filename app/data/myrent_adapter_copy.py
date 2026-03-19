from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
import time
"""
myrent_adapter.py

Classe "connettore/adapter" per:
1) Recuperare Locations e Quotations da MyRent tramite **SDK esterno** (myrent_sdk.py)
2) Convertire i payload MyRent nel formato richiesto dalla nostra wrapper API (FastAPI).

Obiettivo:
- Tenere INVARIATI gli schemi di input/output della wrapper API.
- Offrire una conversione robusta (tollerante a campi mancanti o formati leggermente diversi).

Uso tipico (dentro FastAPI):
    adapter = MyRentAdapter.from_env()
    locations = adapter.get_locations()
    quotation_resp_dict = adapter.get_quotations(wrapper_req_dict)  # -> {"data": {...}}
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
    # Il tuo SDK: deve essere importabile dal PYTHONPATH (package o file myrent_sdk.py)
    from myrent_sdk.main import (  # type: ignore
        MyRentClient,
        QuotationRequest as SDKQuotationRequest,
        APIError,
        AuthenticationError,
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
    """
    Converte stringhe ISO (con o senza 'Z', con o senza millisecondi) in datetime.
    """
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
        # fallback minimali
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
    return None


def _fmt_dt_no_tz_seconds(value: Union[str, datetime]) -> str:
    """
    MyRent (in pratica) accetta spesso 'YYYY-MM-DDTHH:MM:SS' (senza Z).
    Rende sicuro quel formato partendo da:
    - datetime
    - stringa ISO con/senza Z e con/senza ms
    """
    if isinstance(value, datetime):
        return value.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, str):
        dt = _parse_dt_any(value)
        if dt is None:
            # se non parsabile, restituisci la stringa "così com'è" (ultima spiaggia)
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
    - converte Locations e Quotations nel formato wrapper.

    Nota: la wrapper API continuerà ad autenticarsi con la sua API KEY.
    Questo adapter gestisce invece l'autenticazione "verso MyRent".
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

        # istanza SDK
        self.client = MyRentClient(  # type: ignore[misc]
            base_url=base_url,
            user_id=user_id,
            password=password,
            company_code=company_code,
            timeout=float(timeout),
            logger=self.log,
        )

        # ------------------- Vehicles cache (in-memory, thread-safe) -------------------
        # TTL configurabile via env, default 300s (5 minuti)
        ttl_env = os.getenv("MYRENT_VEHICLES_CACHE_TTL_SEC", "300")
        try:
            self._vehicles_cache_ttl_sec = max(0, int(ttl_env))
        except Exception:
            self._vehicles_cache_ttl_sec = 300

        self._vehicles_cache_lock = Lock()
        # cache structure:
        #   key -> {"ts": float(monotonic), "data": List[Dict[str, Any]]}
        self._vehicles_cache: Dict[str, Dict[str, Any]] = {}

    # ----------------------------- Factory da ENV -----------------------------
    @classmethod
    def from_env(
        cls,
        *,
        timeout: Union[int, float] = 30,
        vat_pct_default: int = 22,
        logger: Optional[logging.Logger] = None,
    ) -> "MyRentAdapter":
        """
        Crea l'adapter leggendo la configurazione da env vars.

        Richieste:
          - MYRENT_BASE_URL
          - MYRENT_USER_ID
          - MYRENT_PASSWORD
          - MYRENT_COMPANY_CODE

        Opzionali:
          - MYRENT_TIMEOUT
          - MYRENT_VAT_PCT
        """
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
        """
        Garantisce di avere token valido lato SDK.
        Se manca, chiama authenticate().
        """
        try:
            _ = self.client.token_value  # type: ignore[attr-defined]
            return
        except Exception:
            pass

        self.log.info("MyRentAdapter: token assente, eseguo authenticate() ...")
        self.client.authenticate()  # type: ignore[attr-defined]

    # ----------------------------- Public API: Locations -----------------------------
    def get_locations(self) -> List[Dict[str, Any]]:
        """
        Ritorna Locations convertite nel formato wrapper.
        """
        self._ensure_authenticated()
        try:
            locs = self.client.get_locations()  # type: ignore[attr-defined]
        except AuthenticationError:
            # retry una volta
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
        """
        wrapper_req: dict con chiavi come la request del nostro endpoint /quotations.

        Ritorna:
          {"data": { ...QuotationData... }}  (formato wrapper)
        """
        self._ensure_authenticated()

        sdk_req = self._build_sdk_quotation_request(wrapper_req)

        try:
            resp = self.client.get_quotations(sdk_req)  # type: ignore[attr-defined]
            raw = getattr(resp, "raw", None)
            if not isinstance(raw, dict):
                # fallback: se lo SDK non espone .raw, usa direttamente l'oggetto
                raw = self._obj_to_dict(resp)
        except AuthenticationError:
            # retry una volta
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
        """
        Mappa la QuotationRequest della wrapper nei campi della QuotationRequest del SDK.

        NOTE IMPORTANTI:
        - Date: il SDK gestisce i secondi ma NON sempre la 'Z'; qui normalizziamo a 'YYYY-MM-DDTHH:MM:SS'
        - channel: il SDK normalizza rimuovendo spazi
        """
        pickup = str(wrapper_req.get("pickupLocation") or "")
        dropoff = str(wrapper_req.get("dropOffLocation") or "")
        if not pickup or not dropoff:
            raise MyRentAdapterError("pickupLocation/dropOffLocation mancanti per MYRENT datasource")

        start_raw = wrapper_req.get("startDate")
        end_raw = wrapper_req.get("endDate")
        start_norm = _fmt_dt_no_tz_seconds(str(start_raw)) if start_raw is not None else ""
        end_norm = _fmt_dt_no_tz_seconds(str(end_raw)) if end_raw is not None else ""

        age_int = _coerce_int(wrapper_req.get("age")) or 0

        # normalizziamo discount in stringa se presente (MyRent spesso lo vuole string)
        disc = wrapper_req.get("discountValueWithoutVat")
        disc_norm = None
        if disc is not None:
            disc_norm = str(disc)

        # agreementCoupon: nel wrapper è stringa/None
        coupon = wrapper_req.get("agreementCoupon")
        coupon_norm = str(coupon).strip() if isinstance(coupon, str) and coupon.strip() else None

        # booleans
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
        """
        Converte payload grezzo MyRent -> QuotationData wrapper.
        """
        data_node = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data_node, dict):
            # alcuni ambienti usano "Data"
            data_node = payload.get("Data") if isinstance(payload, dict) else None
        if not isinstance(data_node, dict):
            data_node = {}

        pickup_loc = data_node.get("PickUpLocation") or wrapper_req.get("pickupLocation") or ""
        dropoff_loc = data_node.get("ReturnLocation") or wrapper_req.get("dropOffLocation") or ""
        pickup_dt = data_node.get("PickUpDateTime") or wrapper_req.get("startDate") or ""
        return_dt = data_node.get("ReturnDateTime") or wrapper_req.get("endDate") or ""

        # giorni: calcolo dal wrapper_req (preferibile) oppure dal payload
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

        out: Dict[str, Any] = {
            "total": len(vehicles_out),
            "PickUpLocation": str(pickup_loc),
            "ReturnLocation": str(dropoff_loc),
            "PickUpDateTime": str(pickup_dt),
            "ReturnDateTime": str(return_dt),
            "Vehicles": vehicles_out,
        }
        return out

    # ----------------------------- Internals: conversions -----------------------------
    def _normalize_transmission(self, v: Any) -> Optional[str]:
        """
        Normalizza il campo trasmissione in una stringa compatibile col wrapper:
        - "M" per manuale
        - "A" per automatico

        MyRent può restituire:
          - stringhe ("M", "A", "MANUALE", "AUTOMATICO", ...)
          - dict (es. {"id": 2, "description": "MANUALE"})
          - int (es. 1/2) in alcuni ambienti
        """
        if v is None:
            return None

        # già stringa
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            su = s.upper()
            if su in {"M", "MAN", "MANUALE", "MANUAL"}:
                return "M"
            if su in {"A", "AUT", "AUTO", "AUTOMATICO", "AUTOMATIC"}:
                return "A"
            # euristica
            if "MAN" in su:
                return "M"
            if "AUT" in su or "AUTO" in su:
                return "A"
            # fallback: accetta la stringa così com'è (meglio di un dict)
            return s

        # dict tipo {"id": 2, "description": "MANUALE"}
        if isinstance(v, dict):
            desc = v.get("description") or v.get("Description") or v.get("name") or v.get("Name")
            code = v.get("code") or v.get("Code")
            vid = v.get("id") or v.get("ID")

            # prova description
            if isinstance(desc, str) and desc.strip():
                return self._normalize_transmission(desc)

            # prova code
            if isinstance(code, str) and code.strip():
                return self._normalize_transmission(code)

            # prova id numerico
            vid_int = _coerce_int(vid)
            if vid_int is not None:
                # euristica comune: 1=manuale, 2=automatico (se diverso, la description sopra avrebbe già funzionato)
                if vid_int == 1:
                    return "M"
                if vid_int == 2:
                    return "A"
                return str(vid_int)

            return None

        # numeri
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vi = _coerce_int(v)
            if vi == 1:
                return "M"
            if vi == 2:
                return "A"
            return str(v)

        # fallback robusto: evita di ritornare dict/oggetti
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

        # groupPic (MyRent la mette spesso dentro Vehicle)
        if isinstance(veh_raw.get("groupPic"), dict):
            group_pic_raw = veh_raw.get("groupPic")
        elif isinstance(vs.get("groupPic"), dict):
            group_pic_raw = vs.get("groupPic")
        else:
            group_pic_raw = {}

        code = veh_raw.get("Code") or group_pic_raw.get("internationalCode") or ""
        code_context = veh_raw.get("CodeContext") or "ACRISS"

        # VehMakeModel: MyRent -> dict, wrapper -> lista
        make_model_name = self._extract_make_model_name(veh_raw) or str(code)

        national_code = (
            veh_raw.get("nationalCode")
            or group_pic_raw.get("nationalCode")
            or veh_raw.get("VendorCarType")
            or None
        )

        # id: preferisci groupPic.id (se presente), fallback a Code
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

        # ✅ FIX: normalizzazione transmission (evita dict -> errore Pydantic)
        transmission_norm = self._normalize_transmission(
            veh_raw.get("transmission") or veh_raw.get("Transmission")
        )

        locations = _unique([pickup_loc, dropoff_loc])

        # TotalCharge: normalizza in (pre_vat, total_vat_incl)
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

        # vehicleParameter: prendi da Vehicle.vehicleParameter o VehicleStatus.vehicleParameter
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

        # groupPic wrapper: solo se showPics=true
        group_pic_out = None
        if _coerce_bool(wrapper_req.get("showPics")):
            gid = _coerce_int(group_pic_raw.get("id"))
            if gid is not None:
                group_pic_out = {"id": int(gid), "url": None}

        # vehicleExtraImage wrapper
        vehicle_extra_image = [] if _coerce_bool(wrapper_req.get("showVehicleExtraImage")) else None

        # optionals: MyRent li mette in vs.optionals
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

        # BookingVehicle wrapper (schema nostro)
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
            "transmission": transmission_norm,  # ✅ FIX QUI
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

        vehicle_status_out: Dict[str, Any] = {
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
        return vehicle_status_out

    def _normalize_total_charge(self, tc_raw: Dict[str, Any]) -> Tuple[float, float]:
        """
        MyRent può restituire:
          - RateTotalAmount
          - EstimatedTotalAmount (talvolta 0)
          - TaxableAmount (spesso pre-IVA)
        Noi vogliamo:
          - pre_vat
          - total (iva inclusa)
        """
        est = _coerce_float(tc_raw.get("EstimatedTotalAmount"))
        rate = _coerce_float(tc_raw.get("RateTotalAmount"))
        taxable = _coerce_float(tc_raw.get("TaxableAmount"))

        vat_mult = 1.0 + (self.vat_pct / 100.0 if self.vat_pct else 0.0)

        # Caso comune osservato:
        # TaxableAmount = pre-IVA, RateTotalAmount = totale IVA incl, EstimatedTotalAmount = 0
        if taxable is not None and rate is not None and rate > 0 and taxable > 0 and rate >= taxable:
            pre_vat = taxable
            total = est if (est is not None and est > 0) else rate
            return float(pre_vat), float(total)

        # Se EstimatedTotalAmount è valorizzato e TaxableAmount esiste
        if taxable is not None and est is not None and est > 0:
            return float(taxable), float(est)

        # Se est e rate sono entrambi presenti e positivi, prova a capire chi è totale
        if est is not None and rate is not None and est > 0 and rate > 0:
            if est >= rate:
                total = est
                pre_vat = rate
            else:
                total = rate
                pre_vat = est
            return float(pre_vat), float(total)

        # Fallback: se c'è rate, assumilo come totale IVA incl e derivane pre-IVA
        if rate is not None and rate > 0:
            total = rate
            pre_vat = round(total / vat_mult, 2) if vat_mult else total
            return float(pre_vat), float(total)

        # Fallback: se c'è est, assumilo come totale IVA incl e derivane pre-IVA
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

        # fallback su groupWebDescription
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
        # dataclass SDK: to_dict()
        if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
            try:
                d = obj.to_dict()
                if isinstance(d, dict):
                    return d
            except Exception:
                pass
        # dataclass generico
        try:
            return asdict(obj)
        except Exception:
            pass
        # fallback
        try:
            return dict(getattr(obj, "__dict__", {}) or {})
        except Exception:
            return {}

    def _vehicles_cache_key(self, *, location: str, age: int, channel: Optional[str]) -> str:
        """
        Chiave cache. Include location + age + channel.
        (Se vuoi cache separata per macroDescription ecc, aggiungi qui i campi.)
        """
        loc = (location or "").strip().upper()
        ch = (channel or "").strip().upper()
        return f"{loc}|age={int(age)}|channel={ch}"

    def _vehicles_cache_get(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """
        Ritorna data se presente e non scaduta.
        """
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
                # entry corrotta -> elimina
                self._vehicles_cache.pop(key, None)
                return None

            if (now - float(ts)) > float(self._vehicles_cache_ttl_sec):
                # expired
                self._vehicles_cache.pop(key, None)
                return None

            # ritorna direttamente la lista (è ok; se vuoi immutabilità, fai copy)
            return data

    def _vehicles_cache_set(self, key: str, data: List[Dict[str, Any]]) -> None:
        """
        Salva data in cache.
        """
        if self._vehicles_cache_ttl_sec <= 0:
            return

        now = time.monotonic()
        with self._vehicles_cache_lock:
            self._vehicles_cache[key] = {"ts": now, "data": data}

    def _vehicles_cache_prune(self) -> None:
        """
        Pulizia best-effort: rimuove entry scadute.
        La puoi chiamare occasionalmente (es. prima di set) per evitare crescita memoria.
        """
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
        """
        - Cache in memoria (TTL) per evitare 8 quotazioni ad ogni refresh.
        - Se cache miss: 8 quotazioni (oggi+5 e oggi+10 × 2/4/6/8 giorni), merge & dedupe.
        - Output: lista di dict compatibili con VehicleGroupRaw (schema /vehicles invariato).
        """
        self._ensure_authenticated()

        loc = (location or "").strip().upper()
        if not loc:
            raise MyRentAdapterError("location vuota per list_vehicles_by_location(source=MYRENT)")

        # ------------------- CACHE GET -------------------
        cache_key = self._vehicles_cache_key(location=loc, age=int(age), channel=channel)
        cached = self._vehicles_cache_get(cache_key)
        if cached is not None:
            return cached

        # (best-effort) pulizia entry scadute per limitare crescita memoria
        self._vehicles_cache_prune()

        # ------------------- 8 PROBE QUOTATIONS -------------------
        start_offsets_days = [5, 10]
        durations_days = [2, 4, 6, 8]

        # orario stabile 10:00 UTC (evita outliers notturni)
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
                    q = self.get_quotations(wrapper_req)  # -> {"data": {...}}
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

                        # merge non distruttivo: riempi campi mancanti
                        for k in [
                            "national_code", "display_name", "vendor_macro", "vehicle_type",
                            "seats", "doors", "transmission", "fuel", "aircon", "image_url"
                        ]:
                            if existing.get(k) in (None, "", 0) and item.get(k) not in (None, "", 0):
                                existing[k] = item[k]

                        # daily_rate: tieni il MIN (prezzo "da")
                        ex_dr = _coerce_float(existing.get("daily_rate"))
                        it_dr = _coerce_float(item.get("daily_rate"))
                        if ex_dr is None:
                            existing["daily_rate"] = it_dr
                        elif it_dr is not None:
                            existing["daily_rate"] = min(ex_dr, it_dr)

                        # locations: unione (qui di fatto loc, ma robusto)
                        ex_locs = existing.get("locations") or []
                        it_locs = item.get("locations") or []
                        existing["locations"] = _unique(list(ex_locs) + list(it_locs))

        out = list(merged.values())

        # Se tutte fallite -> errore (FastAPI risponde 502)
        if not out and errors:
            raise MyRentAdapterError("Tutte le probe quotations sono fallite: " + " | ".join(errors[:5]))

        # ordinamento stabile (UX + paginazione consistente)
        out.sort(key=lambda x: (str(x.get("vendor_macro") or ""), str(x.get("international_code") or "")))

        # ------------------- CACHE SET -------------------
        # Salva anche lista vuota (se vuoi evitare hammering su location senza risultati)
        self._vehicles_cache_set(cache_key, out)

        return out
