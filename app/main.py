from __future__ import annotations
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Union, Dict, Any
from datetime import datetime
import json, os, math, hashlib, base64
from fastapi.middleware.cors import CORSMiddleware

API_TITLE = "Myrent Booking Mock API (Quotations/Locations/Vehicles)"
API_VERSION = "1.0.0"
API_KEY = os.getenv("MYRENT_API_KEY", "MYRENT-DEMO-KEY")

app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=(
        "Simulazione FastAPI degli endpoint Myrent necessari a quotazioni e dettagli vettura.\n"
        f"Autenticazione: header `X-API-Key: {API_KEY}`"
    ),
    root_path="/myrent-wrapper-api"
)

# ---- CORS (aperto) ----------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    allow_credentials=False,
    max_age=86400,
)

# ---- Data -------------------------------------------------------------------
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "vehicles.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    VEH_DATA = json.load(f)

CURRENCY = VEH_DATA.get("currency", "EUR")
VAT_PCT = VEH_DATA.get("vat_percentage", 22)

# ---- Auth dependency ---------------------------------------------------------
def require_api_key(x_api_key: Optional[str] = Header(None), tokenValue: Optional[str] = Header(None)):
    key = x_api_key or tokenValue
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True

# ---- Schemi Pydantic ---------------------------------------------------------

class VehMakeModel(BaseModel):
    """
    Rappresenta un accoppiamento (make/model) visualizzato nel catalogo o nel risultato di una quotazione.

    Esempio oggetto:
    {
      "Name": "Fiat 500 or similar"
    }
    """
    Name: str = Field(
        ...,
        description=(
            "Nome visualizzato del modello o del gruppo esemplificativo. "
            "Esempio: 'Fiat 500 or similar'. Default: campo OBBLIGATORIO (nessun default)."
        ),
        # In pydantic v2 è possibile anche usare json_schema_extra per esempi più ricchi
    )


class BookingVehicle(BaseModel):
    """
    Contenitore dei dettagli veicolo usati nelle risposte di quotazione (VehicleStatus.Vehicle).
    Include codici, branding, macrogruppo/tipo e specifiche tecniche essenziali.

    Esempio oggetto (ridotto):
    {
      "Code": "CDMR",
      "CodeContext": "ACRISS",
      "nationalCode": "D",
      "VehMakeModel": [{"Name": "Volkswagen Golf or similar"}],
      "model": "Volkswagen Golf or similar",
      "brand": null,
      "version": null,
      "VendorCarMacroGroup": "COMPACT",
      "VendorCarType": "HATCHBACK",
      "seats": 5,
      "doors": 5,
      "transmission": "M",
      "fuel": "PETROL",
      "aircon": true,
      "imageUrl": "https://example.org/golf.jpg",
      "dailyRate": 46.0,
      "km": 0,
      "color": null,
      "plate_no": null,
      "chasis_no": null,
      "locations": ["FCO","MXP","FLR"],
      "plates": ["AB123CD"]
    }
    """

    id: Optional[Union[int, str]] = Field(
        None,
        description="ID univoco del gruppo/veicolo (dal file vehicles.json). Esempi: 1, 'K-001'. Default: None."
    )


    # Codici
    Code: str = Field(
        ...,
        description=(
            "Codice internazionale del gruppo (stile ACRISS). "
            "Esempio: 'CDMR', 'IFAR', 'MBMR'. Default: OBBLIGATORIO."
        ),
    )
    CodeContext: Optional[str] = Field(
        "ACRISS",
        description=(
            "Contesto del codice (es. 'ACRISS'). "
            "Esempio: 'ACRISS'. Default: 'ACRISS'."
        ),
    )
    national_code: Optional[str] = Field(
        None,
        alias="nationalCode",
        description=(
            "Codice nazionale utilizzato internamente. "
            "Esempio: 'D', 'A'. Default: None."
        ),
    )

    # Nome/branding
    veh_make_models: List[VehMakeModel] = Field(
        default_factory=list,
        alias="VehMakeModel",
        description=(
            "Lista di elementi make/model da mostrare nel front-end. "
            "Esempio: [{'Name':'Fiat 500 or similar'}]. Default: []."
        ),
    )
    model: Optional[str] = Field(
        None,
        description=(
            "Modello (testo libero, spesso uguale al display name). "
            "Esempio: 'Volkswagen Golf or similar'. Default: None."
        ),
    )
    brand: Optional[str] = Field(
        None,
        description="Marca del veicolo (se disponibile). Esempio: 'Volkswagen'. Default: None.",
    )
    version: Optional[str] = Field(
        None,
        description="Versione/allestimento (se disponibile). Esempio: '1.6 TDI'. Default: None.",
    )

    # Macro / tipo
    VendorCarMacroGroup: Optional[str] = Field(
        None,
        description=(
            "Macrogruppo commerciale del veicolo. "
            "Esempi: 'COMPACT', 'SUV', 'ECONOMY', 'MINI', 'LUXURY', 'WAGON', 'VAN'. "
            "Default: None."
        ),
    )
    VendorCarType: Optional[str] = Field(
        None,
        description=(
            "Tipo di veicolo. Esempi: 'HATCHBACK', 'SEDAN', 'SUV', 'WAGON', 'MINIVAN', 'VAN'. "
            "Default: None."
        ),
    )

    # Specifiche veicolo
    seats: Optional[int] = Field(
        None,
        description="Numero posti. Esempio: 5. Default: None.",
    )
    doors: Optional[int] = Field(
        None,
        description="Numero porte. Esempio: 5. Default: None.",
    )
    transmission: Optional[str] = Field(
        None,
        description=(
            "Cambio: 'M' (Manuale) o 'A' (Automatico). Esempi: 'M', 'A'. Default: None."
        ),
    )
    fuel: Optional[str] = Field(
        None,
        description=(
            "Alimentazione: 'PETROL', 'DIESEL', 'ELECTRIC', ... "
            "Esempio: 'DIESEL'. Default: None."
        ),
    )
    aircon: Optional[bool] = Field(
        None,
        description="Climatizzatore presente. Esempio: true/false. Default: None.",
    )
    image_url: Optional[str] = Field(
        None,
        alias="imageUrl",
        description=(
            "URL immagine rappresentativa. "
            "Esempio: 'https://upload.wikimedia.org/...jpg'. Default: None."
        ),
    )
    daily_rate: Optional[float] = Field(
        None,
        alias="dailyRate",
        description="Tariffa giornaliera base (valuta = CURRENCY). Esempio: 46.0. Default: None.",
    )

    # Altro
    km: Optional[int] = Field(
        None,
        description="Chilometraggio iniziale (se rilevante). Esempio: 0. Default: None.",
    )
    color: Optional[str] = Field(
        None,
        description="Colore (se disponibile). Esempio: 'Blue'. Default: None.",
    )
    plate_no: Optional[str] = Field(
        None,
        description="Targa assegnata (se nota). Esempio: 'GF962VG'. Default: None.",
    )
    chasis_no: Optional[str] = Field(
        None,
        description="Numero di telaio (se noto). Esempio: 'WVWZZZ1KZ6W000001'. Default: None.",
    )
    locations: List[str] = Field(
        default_factory=list,
        description=(
            "Codici location in cui il gruppo è disponibile. "
            "Esempio: ['FCO','MXP','FLR']. Default: []."
        ),
    )
    plates: List[str] = Field(
        default_factory=list,
        description="Eventuali targhe disponibili per il gruppo. Esempio: ['AB123CD']. Default: [].",
    )

    # Pydantic v2
    model_config = ConfigDict(
        populate_by_name=True
    )


class VehicleParameter(BaseModel):
    """
    Parametro tecnico/descrittivo del veicolo mostrabile a UI (nome, descrizione, posizione, URL file opzionale).

    Esempio oggetto:
    {
      "name :": "Bagagliaio",
      "description :": "185 L",
      "position :": 4,
      "fileUrl :": ""
    }
    """
    name: str = Field(
        ...,
        alias="name :",
        description="Nome del parametro. Esempio: 'Bagagliaio'. Default: OBBLIGATORIO."
    )
    description: str = Field(
        ...,
        alias="description :",
        description="Valore/descrizione del parametro. Esempio: '185 L'. Default: OBBLIGATORIO."
    )
    position: int = Field(
        ...,
        alias="position :",
        description="Ordine di visualizzazione (intero). Esempio: 4. Default: OBBLIGATORIO."
    )
    fileUrl: str = Field(
        "",
        alias="fileUrl :",
        description="URL file correlato (opzionale). Esempio: ''. Default: stringa vuota."
    )

    model_config = ConfigDict(populate_by_name=True)


class GroupPic(BaseModel):
    """
    Pic del gruppo veicolo, utile quando `showPics=true` (ID e URL immagine).

    Esempio oggetto:
    {
      "id": 123,
      "url": "https://example.org/pic.jpg"
    }
    """
    id: int = Field(
        ...,
        description="Identificativo interno dell'immagine di gruppo. Esempio: 123. Default: OBBLIGATORIO."
    )
    url: Optional[str] = Field(
        None,
        description="URL immagine di gruppo. Esempio: 'https://example.org/pic.jpg'. Default: None."
    )


class VehicleStatus(BaseModel):
    """
    Stato di offerta/availability per un determinato gruppo/veicolo in output alle quotazioni.

    Esempio oggetto (ridotto):
    {
      "Status": "Available",
      "Reference": {
        "calculated": { "days": 3, "base_daily": 46.0, "pre_vat": 138.0, "vat_pct": 22, "total": 168.36 }
      },
      "Vehicle": { ...BookingVehicle... },
      "vehicleParameter": [ ...VehicleParameter... ],
      "vehicleExtraImage": [],
      "groupPic": { "id": 321, "url": "https://example.org/pic.jpg" }
    }
    """
    Status: str = Field(
        ...,
        description=(
            "Stato di disponibilità del gruppo. Esempi: 'Available', 'Unavailable'. "
            "Default: OBBLIGATORIO."
        ),
    )
    Reference: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Riferimenti/calcoli interni. Quando presente può includere 'calculated' con: "
            "{days:int, base_daily:float, pre_vat:float, vat_pct:int, total:float}. Default: None."
        ),
    )
    Vehicle: BookingVehicle = Field(
        ...,
        description="Dettagli veicolo/gruppo in offerta (vedi BookingVehicle). Default: OBBLIGATORIO.",
    )
    vehicleParameter: Optional[List[VehicleParameter]] = Field(
        None,
        description=(
            "Parametri veicolo opzionali (mostrati se richiesti). "
            "Esempio: [{'name :':'Bagagliaio',...}]. Default: None."
        ),
    )
    vehicleExtraImage: Optional[List[str]] = Field(
        None,
        description="Lista di URL immagini extra (se richieste). Esempio: []. Default: None."
    )
    groupPic: Optional[GroupPic] = Field(
        None,
        description="Immagine di gruppo (se showPics=true). Default: None."
    )


class Charge(BaseModel):
    """
    Componente di costo per optional/servizi aggiuntivi.

    Esempio oggetto:
    {
      "Amount": 24.0,
      "CurrencyCode": "EUR",
      "Description": "CHILD SEAT",
      "IncludedInEstTotalInd": true,
      "IncludedInRate": false,
      "TaxInclusive": false
    }
    """
    Amount: float = Field(
        ...,
        description="Importo del charge (per intero periodo o per calcolo definito a monte). Esempio: 24.0. Default: OBBLIGATORIO."
    )
    CurrencyCode: str = Field(
        default_factory=lambda: CURRENCY,  # mantenere il bind alla costante
        description="Valuta (derivata dal catalogo). Esempio: 'EUR'. Default: CURRENCY globale."
    )
    Description: str = Field(
        ...,
        description="Descrizione voce di addebito. Esempio: 'CHILD SEAT'. Default: OBBLIGATORIO."
    )
    IncludedInEstTotalInd: bool = Field(
        True,
        description="True se incluso nel totale stimato. Esempio: true. Default: true."
    )
    IncludedInRate: bool = Field(
        False,
        description="True se incluso nella 'rate' base. Esempio: false. Default: false."
    )
    TaxInclusive: bool = Field(
        False,
        description="True se importo è già IVA inclusa. Esempio: false. Default: false."
    )


class Equipment(BaseModel):
    """
    Dati dell'equipment/optional associato al Charge.

    Esempio oggetto:
    {
      "Description": "Seggiolino bimbo",
      "EquipType": "BABY",
      "Quantity": 1,
      "isMultipliable": true,
      "optionalImage": null
    }
    """
    Description: str = Field(
        ...,
        description="Descrizione mostrabile a UI. Esempio: 'Seggiolino bimbo'. Default: OBBLIGATORIO."
    )
    EquipType: str = Field(
        ...,
        description="Codice tipo di optional. Esempio: 'BABY', 'ADDITIONAL'. Default: OBBLIGATORIO."
    )
    Quantity: int = Field(
        1,
        description="Quantità predefinita. Esempio: 1. Default: 1."
    )
    isMultipliable: bool = Field(
        True,
        description="Se l'optional è moltiplicabile. Esempio: true. Default: true."
    )
    optionalImage: Optional[str] = Field(
        None,
        description="URL immagine opzionale dell'equipment. Esempio: null or 'https://...'. Default: None."
    )


class OptionalItem(BaseModel):
    # NIENTE maiuscole come nome attributo Python: evitiamo la collisione col tipo
    charge: Charge = Field(
        ...,
        alias="Charge",
        description="Voce di addebito associata all'optional."
    )
    equipment: Equipment = Field(
        ...,
        alias="Equipment",
        description="Dettaglio dell'optional selezionabile."
    )

    # per accettare input sia per alias sia per nome e per esportare con alias
    model_config = ConfigDict(populate_by_name=True)

class TotalCharge(BaseModel):
    """
    Riepilogo economico sintetico della miglior offerta corrente restituita da /quotations.

    Esempio oggetto:
    {
      "EstimatedTotalAmount": 168.36,
      "RateTotalAmount": 138.0
    }
    """
    EstimatedTotalAmount: float = Field(
        ...,
        description=(
            "Totale stimato IVA inclusa (miglior prezzo sul risultato). "
            "Esempio: 168.36. Default: OBBLIGATORIO."
        ),
    )
    RateTotalAmount: float = Field(
        ...,
        description=(
            "Totale pre-IVA corrispondente al miglior prezzo. "
            "Esempio: 138.0. Default: OBBLIGATORIO."
        ),
    )


class QuotationData(BaseModel):
    """
    Payload 'data' della risposta di /api/v1/touroperator/quotations.

    Esempio oggetto (ridotto):
    {
      "total": 5,
      "PickUpLocation": "FCO",
      "ReturnLocation": "MXP",
      "PickUpDateTime": "2025-10-12T10:00:00Z",
      "ReturnDateTime": "2025-10-15T12:00:00Z",
      "Vehicles": [ ...VehicleStatus... ],
      "optionals": [ ...OptionalItem... ],
      "TotalCharge": { "EstimatedTotalAmount": 168.36, "RateTotalAmount": 138.0 }
    }
    """
    total: int = Field(
        ...,
        description="Numero totale di veicoli/gruppi trovati dopo i filtri. Esempio: 5. Default: OBBLIGATORIO."
    )
    PickUpLocation: str = Field(
        ...,
        description="Codice location di ritiro. Esempio: 'FCO'. Default: OBBLIGATORIO."
    )
    ReturnLocation: str = Field(
        ...,
        description="Codice location di riconsegna. Esempio: 'MXP'. Default: OBBLIGATORIO."
    )
    PickUpDateTime: str = Field(
        ...,
        description="Data/ora ritiro in ISO 8601 con suffisso Z. Esempio: '2025-10-12T10:00:00Z'. Default: OBBLIGATORIO."
    )
    ReturnDateTime: str = Field(
        ...,
        description="Data/ora riconsegna in ISO 8601 con suffisso Z. Esempio: '2025-10-15T12:00:00Z'. Default: OBBLIGATORIO."
    )
    Vehicles: List[VehicleStatus] = Field(
        ...,
        description="Lista degli elementi VehicleStatus risultanti dal calcolo. Esempio: [...]. Default: OBBLIGATORIO."
    )
    optionals: Optional[List[OptionalItem]] = Field(
        default_factory=list,
        description="Lista optional disponibili per il periodo; può essere vuota. Default: []."
    )
    total_charge: TotalCharge = Field(
        ...,
        alias="TotalCharge",
        description=(
            "Riepilogo economico (miglior prezzo). "
            "Alias JSON: 'TotalCharge'. Default: OBBLIGATORIO."
        ),
    )

    model_config = ConfigDict(populate_by_name=True)


class QuotationResponse(BaseModel):
    """
    Wrapper di risposta di /api/v1/touroperator/quotations.

    Esempio oggetto:
    {
      "data": { ...QuotationData... }
    }
    """
    data: QuotationData = Field(
        ...,
        description="Contenitore dati della quotazione. Default: OBBLIGATORIO."
    )


class QuotationRequest(BaseModel):
    """
    Struttura della richiesta per /api/v1/touroperator/quotations.

    Esempio oggetto:
    {
      "dropOffLocation": "MXP",
      "endDate": "2025-10-15T12:00:00Z",
      "pickupLocation": "FCO",
      "startDate": "2025-10-12T10:00:00Z",
      "age": 30,
      "channel": "WEB_DEMO",
      "showPics": true,
      "showOptionalImage": true,
      "showVehicleParameter": false,
      "showVehicleExtraImage": false,
      "agreementCoupon": null,
      "discountValueWithoutVat": null,
      "macroDescription": "SUV",
      "showBookingDiscount": false,
      "isYoungDriverAge": null,
      "isSeniorDriverAge": null
    }
    """
    dropOffLocation: str = Field(
        ...,
        description="Codice location di riconsegna. Esempio: 'MXP'. Default: OBBLIGATORIO."
    )
    endDate: str = Field(
        ...,
        description=(
            "Fine noleggio in ISO 8601 (consigliato suffisso 'Z' per UTC). "
            "Esempio: '2025-10-15T12:00:00Z'. Default: OBBLIGATORIO."
        )
    )
    pickupLocation: str = Field(
        ...,
        description="Codice location di ritiro. Esempio: 'FCO'. Default: OBBLIGATORIO."
    )
    startDate: str = Field(
        ...,
        description=(
            "Inizio noleggio in ISO 8601 (consigliato suffisso 'Z' per UTC). "
            "Esempio: '2025-10-12T10:00:00Z'. Default: OBBLIGATORIO."
        )
    )
    age: Optional[Union[int, str]] = Field(
        None,
        description=(
            "Età del guidatore (int o string numerica). Esempi: 30, '30'. "
            "Usata per surcharge giovani/senior. Default: None."
        )
    )
    channel: Optional[str] = Field(
        None,
        description=(
            "Canale di vendita (influenza scontistica). Esempio: 'WEB_DEMO'. Default: None."
        )
    )
    showPics: Optional[bool] = Field(
        False,
        description="Se true, include 'groupPic' nei risultati. Esempio: true/false. Default: false."
    )
    showOptionalImage: Optional[bool] = Field(
        False,
        description="Se true, include immagini per optional (se disponibili). Default: false."
    )
    showVehicleParameter: Optional[bool] = Field(
        False,
        description="Se true, include 'vehicleParameter' con scheda tecnica. Default: false."
    )
    showVehicleExtraImage: Optional[bool] = Field(
        False,
        description="Se true, include 'vehicleExtraImage' (lista URL). Default: false."
    )
    agreementCoupon: Optional[str] = Field(
        None,
        description="Codice convenzione/coupon per sconto. Esempio: 'PROMO5'. Default: None."
    )
    discountValueWithoutVat: Optional[Union[str, float]] = Field(
        None,
        description=(
            "Sconto assoluto senza IVA (valore numerico o stringa numerica). "
            "Esempi: 10.0, '10'. Default: None."
        )
    )
    macroDescription: Optional[str] = Field(
        None,
        description=(
            "Filtro macrogruppo richiesto (es. 'SUV', 'COMPACT', 'ECONOMY', ...). "
            "Default: None."
        )
    )
    showBookingDiscount: Optional[bool] = Field(
        False,
        description="Flag per evidenziare scontistica lato booking. Default: false."
    )
    isYoungDriverAge: Optional[bool] = Field(
        None,
        description=(
            "Forza applicazione sovrapprezzo 'young driver' quando true. "
            "Se None, dedotto da 'age' (<25). Default: None."
        )
    )
    isSeniorDriverAge: Optional[bool] = Field(
        None,
        description=(
            "Forza applicazione sovrapprezzo 'senior driver' quando true. "
            "Se None, dedotto da 'age' (>=70). Default: None."
        )
    )

    @field_validator("startDate", "endDate")
    @classmethod
    def validate_iso(cls, v: str):
        """
        Valida che il campo sia in formato ISO 8601. Accetta stringhe con o senza 'Z'.
        Esempi validi: '2025-10-12T10:00:00Z', '2025-10-12T10:00:00'.
        """
        try:
            datetime.fromisoformat(v.replace("Z", ""))
        except Exception:
            raise ValueError(f"Invalid ISO datetime: {v}")
        return v

def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", ""))

# ---- Locations/Damages (invariati, ma inclusi per completezza) --------------
class WeekOfDay(BaseModel):
    dayOfTheWeek: int
    dayOfTheWeekName: str
    startTime: str
    endTime: str

class Closing(BaseModel):
    dayOfTheWeek: int
    dayOfTheWeekName: str
    startTime: str
    endTime: str

class Location(BaseModel):
    locationCode: str
    locationName: str
    locationAddress: Optional[str] = None
    locationNumber: Optional[str] = None
    locationCity: Optional[str] = None
    locationType: int = 3
    telephoneNumber: Optional[str] = None
    cellNumber: Optional[str] = None
    email: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    isAirport: bool = False
    isRailway: bool = False
    isAlwaysOpentrue: Optional[bool] = None
    isCarSharingEnabled: bool = False
    allowPickUpDropOffOutOfHours: bool = False
    hasKeyBox: bool = False
    morningStartTime: Optional[str] = None
    morningStopTime: Optional[str] = None
    afternoonStartTime: Optional[str] = None
    afternoonStopTime: Optional[str] = None
    locationInfoEN: Optional[str] = None
    locationInfoLocal: Optional[str] = None
    openings: List[WeekOfDay] = Field(default_factory=list)
    closing: Optional[List[Closing]] = None
    festivity: Optional[List[Dict[str, Any]]] = None
    minimumLeadTimeInHour: Optional[int] = None
    country: Optional[str] = "ITALIA"
    zipCode: Optional[str] = None

class Damage(BaseModel):
    description: Optional[str] = "N/A"
    damageType: Optional[str] = None
    damageDictionary: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    percentage_x: Optional[float] = None
    percentage_y: Optional[float] = None

class WireframeImage(BaseModel):
    image: str
    height: int = 353
    width: int = 698

class DamagesResponse(BaseModel):
    data: Dict[str, Any]

# ----------------- Mock locations -----------------
LOCATIONS: List[Location] = [
    Location(
        locationCode="XRJ", locationName="ROMA TERMINI",
        locationAddress="Via Giovanni Giolitti", locationNumber="16",
        locationCity="ROMA", locationType=3, telephoneNumber="+393485330898",
        cellNumber="+393485330898", email="termini@noleggiare.it",
        latitude=41.899382, longitude=12.50252, isAirport=False, isRailway=False,
        openings=[
            WeekOfDay(dayOfTheWeek=i, dayOfTheWeekName=name, startTime=("08:00"), endTime=("20:00" if i<=5 else "18:00" if i==6 else "13:00"))
            for i, name in [(1,"Monday"),(2,"Tuesday"),(3,"Wednesday"),(4,"Thursday"),(5,"Friday"),(6,"Saturday"),(7,"Sunday")]
        ],
        closing=[
            Closing(dayOfTheWeek=6, dayOfTheWeekName="Saturday", startTime="18:01", endTime="23:59"),
            Closing(dayOfTheWeek=7, dayOfTheWeekName="Sunday", startTime="13:01", endTime="23:59"),
        ],
        country="ITALIA", zipCode="00185"
    ),
    Location(
        locationCode="FCO", locationName="ROMA FIUMICINO AIRPORT",
        locationAddress="Via dell'Aeroporto di Fiumicino", locationCity="ROMA", locationType=3,
        telephoneNumber="+39 06 65951", email="fco@noleggiare.it", latitude=41.7999, longitude=12.2462, isAirport=True,
        openings=[
            WeekOfDay(dayOfTheWeek=i, dayOfTheWeekName=name, startTime="08:00", endTime="20:00")
            for i, name in [(1,"Monday"),(2,"Tuesday"),(3,"Wednesday"),(4,"Thursday"),(5,"Friday"),(6,"Saturday"),(7,"Sunday")]
        ],
        country="ITALIA", zipCode="00054"
    ),
    Location(
        locationCode="MXP", locationName="MILANO MALPENSA AIRPORT",
        locationAddress="Terminal 1", locationCity="MILANO", locationType=3, telephoneNumber="+39 02 232323",
        email="mxp@noleggiare.it", latitude=45.6301, longitude=8.7231, isAirport=True,
        openings=[
            WeekOfDay(dayOfTheWeek=i, dayOfTheWeekName=name, startTime="08:00", endTime="20:00")
            for i, name in [(1,"Monday"),(2,"Tuesday"),(3,"Wednesday"),(4,"Thursday"),(5,"Friday"),(6,"Saturday"),(7,"Sunday")]
        ],
        country="ITALIA", zipCode="21010"
    ),
    Location(
        locationCode="FLR", locationName="FIRENZE AIRPORT",
        locationAddress="Via del Termine", locationCity="FIRENZE", locationType=3, telephoneNumber="+39 055 123456",
        email="flr@noleggiare.it", latitude=43.806, longitude=11.205, isAirport=True,
        openings=[
            WeekOfDay(dayOfTheWeek=i, dayOfTheWeekName=name, startTime="08:00", endTime="20:00")
            for i, name in [(1,"Monday"),(2,"Tuesday"),(3,"Wednesday"),(4,"Thursday"),(5,"Friday"),(6,"Saturday"),(7,"Sunday")]
        ],
        country="ITALIA", zipCode="50127"
    ),
    Location(
        locationCode="PMO100", locationName="PALERMO AIRPORT",
        locationAddress="Aeroporto Falcone e Borsellino", locationCity="PALERMO", locationType=3, telephoneNumber="+39 091 702",
        email="pmo@noleggiare.it", latitude=38.175, longitude=13.091, isAirport=True,
        openings=[
            WeekOfDay(dayOfTheWeek=i, dayOfTheWeekName=name, startTime="08:00", endTime="20:00")
            for i, name in [(1,"Monday"),(2,"Tuesday"),(3,"Wednesday"),(4,"Thursday"),(5,"Friday"),(6,"Saturday"),(7,"Sunday")]
        ],
        country="ITALIA", zipCode="90045"
    ),
    Location(
        locationCode="AHO100", locationName="ALGHERO AIRPORT",
        locationAddress="Reg. Nuraghe Biancu", locationCity="ALGHERO", locationType=3, telephoneNumber="+39 079 935282",
        email="aho@noleggiare.it", latitude=40.632, longitude=8.290, isAirport=True,
        openings=[
            WeekOfDay(dayOfTheWeek=i, dayOfTheWeekName=name, startTime="08:00", endTime="20:00")
            for i, name in [(1,"Monday"),(2,"Tuesday"),(3,"Wednesday"),(4,"Thursday"),(5,"Friday"),(6,"Saturday"),(7,"Sunday")]
        ],
        country="ITALIA", zipCode="07041"
    ),
]
# ---- Pricing utilities -------------------------------------------------------
def season_multiplier(dt: datetime) -> float:
    if dt.month in (7, 8): return 1.25
    if dt.month == 12 and dt.day >= 20: return 1.20
    if dt.month == 4: return 1.10
    return 1.0

def out_of_hours_fee(loc_code: str, when: datetime) -> float:
    hour = when.hour + when.minute / 60
    return 40.0 if (hour < 8 or hour >= 20) else 0.0

def one_way_fee(pu: str, do: str) -> float:
    return 0.0 if pu == do else 60.0

def young_senior_surcharge(days: int, age: Optional[int], young_flag: Optional[bool], senior_flag: Optional[bool]) -> float:
    young = (young_flag is True) or (age is not None and age < 25)
    senior = (senior_flag is True) or (age is not None and age >= 70)
    fee = 0.0
    if young:  fee += 15.0 * days
    if senior: fee += 10.0 * days
    return fee

def availability_hash_available(group_code: str, pickup: str, start: datetime) -> bool:
    seed = f"{group_code}|{pickup}|{start.date()}"
    n = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return (n % 10) < 8  # 80%

def apply_channel_discount(amount: float, channel: Optional[str], coupon: Optional[str], discount_wo_vat: Optional[Union[str, float]]) -> float:
    disc = 0.0
    if channel and channel.upper().startswith("WEB"): disc += 0.03 * amount
    if coupon: disc += 0.05 * amount
    if discount_wo_vat:
        try: disc += float(discount_wo_vat)
        except: pass
    return max(0.0, min(amount, disc))

# ---- Builder: qui copiamo TUTTI i campi del veicolo -------------------------
def build_vehicle_status(item: dict, days: int, start: datetime, end: datetime,
                         pickup: str, dropoff: str, req: QuotationRequest) -> VehicleStatus:
    base_daily = item["daily_rate"] * season_multiplier(start)
    base = base_daily * days
    base += one_way_fee(pickup, dropoff)
    base += out_of_hours_fee(pickup, start)

    age_int = None
    if isinstance(req.age, int):
        age_int = req.age
    elif isinstance(req.age, str) and req.age.isdigit():
        age_int = int(req.age)

    base += young_senior_surcharge(days, age_int, req.isYoungDriverAge, req.isSeniorDriverAge)

    discount = apply_channel_discount(base, req.channel, req.agreementCoupon, req.discountValueWithoutVat)
    pre_vat = max(0.0, base - discount)
    total = pre_vat * (1 + VAT_PCT / 100.0)

    available = availability_hash_available(item["international_code"], pickup, start)
    status = "Available" if available else "Unavailable"

    veh = BookingVehicle(
        id=item.get("id"),

        # codici
        Code=item["international_code"],
        national_code=item.get("national_code"),

        # nomi
        veh_make_models=[VehMakeModel(Name=item["display_name"])],
        model=item.get("display_name"),
        brand=None,

        # macro/tipo
        VendorCarMacroGroup=item.get("vendor_macro"),
        VendorCarType=item.get("vehicle_type"),

        # specifiche
        seats=item.get("seats"),
        doors=item.get("doors"),
        transmission=item.get("transmission"),
        fuel=item.get("fuel"),
        aircon=item.get("aircon"),
        image_url=item.get("image_url"),
        daily_rate=item.get("daily_rate"),

        # altro
        km=0,
        color=item.get("color"),
        plate_no=None,
        chasis_no=None,
        locations=item.get("locations", []) or [],
        plates=item.get("plates", []) or [],
    )

    vparams = None
    if req.showVehicleParameter and item.get("vehicle_parameters"):
        vparams = [
            VehicleParameter(**{
                "name :": p.get("name"),
                "description :": p.get("description"),
                "position :": p.get("position"),
                "fileUrl :": ""
            })
            for p in item.get("vehicle_parameters", [])
        ]

    gpic = GroupPic(id=hash(item["international_code"]) % 1000, url=item.get("image_url")) if req.showPics else None

    vehicle_status = VehicleStatus(
        Status=status,
        Reference={"ID": 0, "ID_Context": 0, "Type": 0},  # placeholder
        Vehicle=veh,
        vehicleParameter=vparams,
        vehicleExtraImage=[] if req.showVehicleExtraImage else None,
        groupPic=gpic
    )

    vehicle_status.Reference = {
        "calculated": {
            "days": days,
            "base_daily": round(base_daily, 2),
            "pre_vat": round(pre_vat, 2),
            "vat_pct": VAT_PCT,
            "total": round(total, 2)
        }
    }
    return vehicle_status

# ---- Endpoints ---------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "version": API_VERSION}

# NB: qui puoi incollare la lista LOCATIONS identica al tuo file (omessa per brevità)
@app.get("/api/v1/touroperator/locations", response_model=List[Location], tags=["locations"])
def list_locations(auth: bool = Depends(require_api_key)):
    # restituisci eventuale lista LOCATIONS definita come nel tuo file originale
    return LOCATIONS  # <-- Sostituisci con la tua lista LOCATIONS reale

@app.post("/api/v1/touroperator/quotations", response_model=QuotationResponse, tags=["quotations"])
def quotations(req: QuotationRequest, auth: bool = Depends(require_api_key)):
    start = parse_dt(req.startDate)
    end = parse_dt(req.endDate)
    if end <= start:
        raise HTTPException(400, "endDate must be after startDate")

    dur_hours = (end - start).total_seconds() / 3600.0
    days = max(1, math.ceil(dur_hours / 24.0))

    # filtra per location e macro opzionale
    items: List[dict] = []
    for g in VEH_DATA["groups"]:
        if req.pickupLocation not in g.get("locations", []):
            continue
        if req.macroDescription and req.macroDescription.strip():
            if g.get("vendor_macro", "").lower() != req.macroDescription.strip().lower():
                continue
        items.append(g)

    vehicles_out: List[VehicleStatus] = [
        build_vehicle_status(item, days, start, end, req.pickupLocation, req.dropOffLocation, req)
        for item in items
    ]

    # TotalCharge = min totale tra i veicoli disponibili (se non c'è, 0)
    min_total = None
    min_pre_vat = None
    for vs in vehicles_out:
        calc = (vs.Reference or {}).get("calculated", {})
        tot = calc.get("total")
        pre = calc.get("pre_vat")
        if tot is not None and (min_total is None or tot < min_total):
            min_total = tot
            min_pre_vat = pre
    if min_total is None:
        min_total = 0.0
        min_pre_vat = 0.0

    # optionals d'esempio (sempre presenti così il frontend li vede)
    optionals = [
        OptionalItem(
            Charge=Charge(Amount=8.0 * days, Description="CHILD SEAT", TaxInclusive=False),
            Equipment=Equipment(Description="Seggiolino bimbo", EquipType="BABY", Quantity=1, isMultipliable=True)
        ),
        OptionalItem(
            Charge=Charge(Amount=12.0 * days, Description="ADDITIONAL DRIVER", TaxInclusive=False),
            Equipment=Equipment(Description="Guidatore aggiuntivo", EquipType="ADDITIONAL", Quantity=1, isMultipliable=False)
        ),
    ]

    data = QuotationData(
        total=len(vehicles_out),
        PickUpLocation=req.pickupLocation,
        ReturnLocation=req.dropOffLocation,
        PickUpDateTime=start.isoformat() + "Z",
        ReturnDateTime=end.isoformat() + "Z",
        Vehicles=vehicles_out,
        optionals=optionals,
        total_charge=TotalCharge(
            EstimatedTotalAmount=round(min_total, 2),
            RateTotalAmount=round(min_pre_vat, 2)
        )
    )
    return QuotationResponse(data=data)

# Damages mock (invariato)
PLACEHOLDER_WIREFRAME_B64 = base64.b64encode(b"placeholder").decode()

@app.get("/api/v1/touroperator/damages/{plate_or_vin}", response_model=DamagesResponse, tags=["vehicles"])
def get_damages(plate_or_vin: str, auth: bool = Depends(require_api_key)):
    damages_list: List[Damage] = []
    for g in VEH_DATA["groups"]:
        dmap = g.get("damages", {})
        if plate_or_vin in dmap:
            damages_list = [Damage(**d) for d in dmap[plate_or_vin]]
            break
    payload = {
        "damages": [d.model_dump() for d in damages_list],
        "wireframeImage": WireframeImage(image=PLACEHOLDER_WIREFRAME_B64, height=353, width=698).model_dump()
    }
    return DamagesResponse(data=payload)
class VehicleParameterRaw(BaseModel):
    name: str
    description: str
    position: int

class DamagePointRaw(BaseModel):
    description: Optional[str] = None
    damageType: Optional[str] = None
    damageDictionary: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    percentage_x: Optional[float] = None
    percentage_y: Optional[float] = None

class VehicleGroupRaw(BaseModel):
    # Campi così come nel JSON originale: NON cambiare i nomi!    # ⬇️ AGGIUNGI
    id: Optional[Union[int, str]] = None
    national_code: Optional[str] = None
    international_code: str
    description: Optional[str] = None
    display_name: Optional[str] = None
    vendor_macro: Optional[str] = None
    vehicle_type: Optional[str] = None
    seats: Optional[int] = None
    doors: Optional[int] = None
    transmission: Optional[str] = None
    fuel: Optional[str] = None
    aircon: Optional[bool] = None
    image_url: Optional[str] = None
    daily_rate: Optional[float] = None
    locations: List[str] = Field(default_factory=list)
    plates: Optional[List[str]] = None
    vehicle_parameters: Optional[List[VehicleParameterRaw]] = None
    damages: Optional[Dict[str, List[DamagePointRaw]]] = None

    # IMPORTANTISSIMO: consente di mantenere eventuali campi extra futuri senza perderli
    model_config = ConfigDict(extra="allow")

class VehiclesPage(BaseModel):
    total: int = Field(..., description="Numero totale risultati dopo i filtri")
    skip: int = Field(..., description="Offset corrente")
    page_size: int = Field(..., description="Dimensione della pagina")
    has_next: bool = Field(..., description="Esistono altri risultati dopo questa pagina?")
    next_skip: Optional[int] = Field(None, description="Offset per la pagina successiva (se presente)")
    prev_skip: Optional[int] = Field(None, description="Offset per la pagina precedente (se presente)")
    items: List[VehicleGroupRaw] = Field(default_factory=list, description="Lista veicoli per la pagina corrente")


@app.get(
    "/api/v1/touroperator/vehicles",
    response_model=VehiclesPage,
    tags=["vehicles"],
    summary="Catalogo veicoli (impaginato)",
    description=(
        "Ritorna il catalogo veicoli dal file 'vehicles.json' con impaginazione.\n"
        "Autenticazione via header `X-API-Key` o `tokenValue`.\n"
        "Filtra opzionalmente per `location` (codice sede, es. FCO). "
        "Se non specificata, restituisce i veicoli per tutte le location."
    ),
)
def list_vehicles(
    location: Optional[str] = Query(
        default=None,
        description="Filtro opzionale per codice location (es. FCO, MXP, FLR, ...)",
        examples=["FCO"]
    ),
    skip: int = Query(
        default=0,
        ge=0,
        description="Offset dei risultati (0-based). Esempio: 0, 25, 50..."
    ),
    page_size: int = Query(
        default=25,
        gt=0,
        le=100,
        description="Dimensione pagina (1-100)."
    ),
    auth: bool = Depends(require_api_key),
):
    # 1) Sorgente dati
    groups: List[dict] = VEH_DATA.get("groups", [])

    # 2) Filtro opzionale per location (case-insensitive)
    if location:
        loc_norm = location.strip().upper()
        groups = [
            g for g in groups
            if loc_norm in [l.upper() for l in (g.get("locations") or [])]
        ]

    # 3) Totale dopo i filtri
    total = len(groups)

    # 4) Impaginazione
    start = skip
    end = skip + page_size
    page_items = groups[start:end]

    # 5) Validazione/serializzazione con modello che preserva i campi originali
    items_model = [VehicleGroupRaw(**item) for item in page_items]

    has_next = end < total
    next_skip = end if has_next else None
    prev_skip = max(0, skip - page_size) if skip > 0 else None

    return VehiclesPage(
        total=total,
        skip=skip,
        page_size=page_size,
        has_next=has_next,
        next_skip=next_skip,
        prev_skip=prev_skip,
        items=items_model,
    )

@app.get(
    "/api/v1/touroperator/vehicles/{vehicle_id}",
    response_model=VehicleGroupRaw,
    tags=["vehicles"],
    summary="Dettaglio veicolo per ID",
    description=(
        "Ritorna un singolo veicolo del catalogo individuato per ID, così come definito nel file 'vehicles.json'.\n"
        "Autenticazione via header `X-API-Key` o `tokenValue`."
    ),
)
def get_vehicle_by_id(
    vehicle_id: str,
    auth: bool = Depends(require_api_key),
):
    groups: List[dict] = VEH_DATA.get("groups", [])
    # confronto robusto: cast a stringa
    found = next((g for g in groups if str(g.get("id")) == str(vehicle_id)), None)
    if not found:
        raise HTTPException(status_code=404, detail=f"Vehicle id '{vehicle_id}' not found")
    return VehicleGroupRaw(**found)

# Esegui: uvicorn main:app --reload --port 8000
