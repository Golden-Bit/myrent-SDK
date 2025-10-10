# Myrent Booking Mock API — README

API di esempio basata su **FastAPI** che simula gli endpoint minimi di un gestionale di noleggio auto (quotazioni, sedi e danni).
Questa guida spiega **cos’è disponibile, come avviarla, come autenticarsi, i contratti di richiesta/risposta, la logica di pricing, gli errori** e come testare rapidamente.

---

## Indice

1. [Prerequisiti](#prerequisiti)
2. [Installazione e avvio](#installazione-e-avvio)
3. [Autenticazione](#autenticazione)
4. [CORS](#cors)
5. [Struttura dati (`data/vehicles.json`)](#struttura-dati-datavehiclesjson)
6. [Endpoint](#endpoint)

   * [GET `/health`](#get-health)
   * [GET `/api/v1/touroperator/locations`](#get-apiv1touroperatorlocations)
   * [POST `/api/v1/touroperator/quotations`](#post-apiv1touroperatorquotations)
   * [GET `/api/v1/touroperator/damages/{plate_or_vin}`](#get-apiv1touroperatordamagesplate_or_vin)
7. [Logica di prezzo e disponibilità](#logica-di-prezzo-e-disponibilità)
8. [Dettagli d’implementazione (Pydantic v2, alias, serializzazione)](#dettagli-dimplementazione-pydantic-v2-alias-serializzazione)
9. [Esempi di test (curl e script)](#esempi-di-test-curl-e-script)
10. [Errori comuni e codici di stato](#errori-comuni-e-codici-di-stato)
11. [Note operative e personalizzazioni](#note-operative-e-personalizzazioni)

---

## Prerequisiti

* **Python 3.10+**
* **pip** e **virtualenv** (consigliato)
* **Uvicorn** per lo sviluppo

---

## Installazione e avvio

```bash
# 1) Clona o copia i file del progetto
cd myrent-SDK/app

# 2) Crea e attiva un virtualenv (opzionale ma consigliato)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 3) Installa dipendenze
pip install fastapi uvicorn pydantic

# 4) Avvia in locale
uvicorn main:app --reload --port 8000
```

Variabili d’ambiente:

* `MYRENT_API_KEY` (opzionale): chiave API. Se non impostata, la chiave di default è **`MYRENT-DEMO-KEY`**.

---

## Autenticazione

Ogni endpoint (tranne `GET /health`) richiede **API Key** tramite **uno** di questi header:

* `X-API-Key: <API_KEY>`
* `tokenValue: <API_KEY>`

Se l’API key è assente o errata, la risposta è `401 Unauthorized`.

---

## CORS

È abilitato **CORS aperto**:

* `allow_origins=["*"]`
* `allow_methods=["*"]`
* `allow_headers=["*"]`
* `allow_credentials=False`
* `max_age=86400`

Questo consente a qualunque front-end di chiamare l’API senza restrizioni di origine.

> Se ti servono **cookie/credenziali** da browser, imposta `allow_credentials=True` e restringi `allow_origins` a domini specifici.

---

## Struttura dati `data/vehicles.json`

Il file contiene i dati di listino e di flotta usati dagli endpoint:

```json
{
  "currency": "EUR",
  "vat_percentage": 22,
  "groups": [
    {
      "national_code": "A",
      "international_code": "MBMR",
      "description": "MINI",
      "display_name": "Fiat 500 or similar",
      "vendor_macro": "MINI",
      "vehicle_type": "HATCHBACK",
      "seats": 4,
      "doors": 3,
      "transmission": "M",
      "fuel": "PETROL",
      "aircon": true,
      "image_url": "https://…",
      "daily_rate": 32.0,
      "locations": ["FCO", "MXP", "…"],
      "plates": ["GF962VG"],
      "vehicle_parameters": [
        {"name": "Lunghezza esterna", "description": "3571 mm", "position": 1}
      ],
      "damages": {
        "GF962VG": [
          {
            "description": "Graffio leggero",
            "damageType": "Scratch",
            "damageDictionary": "Rear bumper scratch",
            "x": 280, "y": 65,
            "percentage_x": 40.1, "percentage_y": 18.4
          }
        ]
      }
    }
  ]
}
```

* `currency` e `vat_percentage` configurano la valuta e l’IVA.
* `groups` elenca le categorie veicolo. Campi importanti:

  * `international_code` (tipo ACRISS, es. `CDMR`, `IFAR`)
  * `display_name` (nome commerciale mostrato al cliente)
  * `vendor_macro` (macro-gruppo, es. `MINI`, `ECONOMY`, `COMPACT`, `SUV`, `LUXURY`)
  * `daily_rate` (tariffa base al giorno)
  * `locations` (codici sede in cui il gruppo è disponibile)
  * `vehicle_parameters` (specifiche tecniche opzionali)
  * `damages` mappato per **targa/VIN** → lista danni

> Nota: puoi aggiungere/variare i gruppi senza toccare il codice, purché rispetti la struttura.

---

## Endpoint

### GET `/health`

* **Scopo**: health check del servizio.
* **Auth**: **NO**.
* **200 OK** — Esempio risposta:

```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

### GET `/api/v1/touroperator/locations`

* **Scopo**: restituisce la lista delle sedi.
* **Auth**: **SÌ** (`X-API-Key` o `tokenValue`).
* **Risposta**: **array** di oggetti `Location` (non wrappato in `{ "data": ... }`).

**Schema `Location` (campi principali)**

* `locationCode` (es. `FCO`, `MXP`, `XRJ`, `PMO100`, `AHO100`, `FLR`)
* `locationName`, `locationCity`, `isAirport`, `latitude`, `longitude`
* `openings`: fasce orarie (in demo 08:00–20:00; domenica 08:00–13:00 a Roma Termini)
* `closing`: eventuali chiusure (es. fuori orario)

**Esempio cURL**

```bash
curl -s http://localhost:8000/api/v1/touroperator/locations \
  -H "X-API-Key: MYRENT-DEMO-KEY"
```

---

### POST `/api/v1/touroperator/quotations`

* **Scopo**: calcola quotazioni per il periodo richiesto filtrando i gruppi disponibili nella sede di ritiro.
* **Auth**: **SÌ**.

**Body `QuotationRequest`**

```json
{
  "dropOffLocation": "MXP",
  "endDate": "2025-07-05T12:00:00Z",
  "pickupLocation": "FCO",
  "startDate": "2025-07-02T10:00:00Z",
  "age": 30,
  "channel": "WEB_PORTAL",
  "showPics": true,
  "showOptionalImage": false,
  "showVehicleParameter": true,
  "showVehicleExtraImage": false,
  "agreementCoupon": null,
  "discountValueWithoutVat": null,
  "macroDescription": "SUV",
  "showBookingDiscount": false,
  "isYoungDriverAge": null,
  "isSeniorDriverAge": null
}
```

**Campi notevoli**

* Date e orari: **ISO 8601** con o senza `Z`. La validazione accetta entrambi.
* `macroDescription`: se valorizzato, filtra per `vendor_macro` (match **case-insensitive**).
* `age`: int **o** stringa numerica (es. `"30"`).
* Flag di presentazione:

  * `showPics`: include `groupPic` con `image_url`
  * `showVehicleParameter`: include `vehicleParameter`
  * `showVehicleExtraImage`: se true, restituisce array `vehicleExtraImage` (in demo vuoto)
  * `showOptionalImage`: **non influenza** l’inclusione in demo (vedi nota sotto)

**Risposta `QuotationResponse`**

```json
{
  "data": {
    "total": 3,
    "PickUpLocation": "FCO",
    "ReturnLocation": "MXP",
    "PickUpDateTime": "2025-07-02T10:00:00Z",
    "ReturnDateTime": "2025-07-05T12:00:00Z",
    "Vehicles": [
      {
        "Status": "Available",
        "Reference": {
          "calculated": {
            "days": 4,
            "base_daily": 80.0,
            "pre_vat": 340.0,
            "vat_pct": 22,
            "total": 414.8
          }
        },
        "Vehicle": {
          "Code": "CFMR",
          "CodeContext": "ACRISS",
          "VehMakeModel": [{"Name": "Nissan Qashqai or similar"}],
          "VendorCarMacroGroup": "SUV",
          "VendorCarType": "SUV",
          "km": 0,
          "model": "Nissan Qashqai or similar"
        },
        "vehicleParameter": [
          {"name :": "Lunghezza esterna", "description :": "4394 mm", "position :": 1, "fileUrl :": ""}
        ],
        "vehicleExtraImage": [],
        "groupPic": {"id": 123, "url": "https://…/qashqai.jpg"}
      }
    ],
    "optionals": [
      {
        "Charge": {"Amount": 32.0, "CurrencyCode": "EUR", "Description": "CHILD SEAT", "IncludedInEstTotalInd": true, "IncludedInRate": false, "TaxInclusive": false},
        "Equipment": {"Description": "Seggiolino bimbo", "EquipType": "BABY", "Quantity": 1, "isMultipliable": true, "optionalImage": null}
      },
      {
        "Charge": {"Amount": 48.0, "CurrencyCode": "EUR", "Description": "ADDITIONAL DRIVER", "IncludedInEstTotalInd": true, "IncludedInRate": false, "TaxInclusive": false},
        "Equipment": {"Description": "Guidatore aggiuntivo", "EquipType": "ADDITIONAL", "Quantity": 1, "isMultipliable": false, "optionalImage": null}
      }
    ],
    "TotalCharge": {
      "EstimatedTotalAmount": 414.8,
      "RateTotalAmount": 340.0
    }
  }
}
```

**Note importanti**

* `Vehicles[*].Status` è basato su una funzione pseudo-random deterministica (80% “Available”).
* `Reference.calculated` espone breakdown del prezzo per trasparenza (giorni calcolati, base giornaliera, pre-IVA, IVA %, totale).
* `TotalCharge` a livello di risposta rappresenta il **minimo totale stimato** tra i veicoli disponibili (o `0` se nessuno).
* **Optionals**: nel codice demo sono **sempre inclusi** (anche se `showOptionalImage=false`) per praticità.

---

### GET `/api/v1/touroperator/damages/{plate_or_vin}`

* **Scopo**: restituisce l’elenco danni associati a una targa/VIN (se presenti nel dataset).
* **Auth**: **SÌ**.
* **Header opzionale**: `Accept-Language` (non usato nella demo).

**Esempio risposta**

```json
{
  "data": {
    "damages": [
      {
        "description": "Graffio leggero",
        "damageType": "Scratch",
        "damageDictionary": "Rear bumper scratch",
        "x": 280,
        "y": 65,
        "percentage_x": 40.1,
        "percentage_y": 18.4
      }
    ],
    "wireframeImage": {
      "image": "cGxhY2Vob2xkZXI=",  // placeholder Base64
      "height": 353,
      "width": 698
    }
  }
}
```

Se non ci sono danni registrati per la targa/VIN, la lista `damages` è vuota. L’immagine “wireframe” è sempre presente (placeholder base64).

---

## Logica di prezzo e disponibilità

**1) Giorni noleggio**
Vengono calcolati come **ceil(ore_totali / 24)**, con minimo 1 giorno.

**2) Moltiplicatore stagionale** (`season_multiplier`):

* Luglio–Agosto: **+25%** (×1.25)
* 20–31 Dicembre: **+20%** (×1.20)
* Aprile: **+10%** (×1.10)
* Altrimenti: ×1.00

**3) Fee fuori orario** (`out_of_hours_fee`)
Se l’orario di **pick-up** è **prima delle 08:00** o **dalle 20:00 in poi** → **+40 EUR** flat.

> Nella demo, le sedi hanno fasce 08:00–20:00 (Roma Termini chiude 18:00 Sabato, 13:00 Domenica—ma la fee è calcolata in modo semplice solo su 8–20).

**4) One-way fee** (`one_way_fee`)
Se `pickupLocation != dropOffLocation` → **+60 EUR**.

**5) Surcharge età** (`young_senior_surcharge`)

* Giovane: `<25 anni` **o** `isYoungDriverAge=true` → **+15 EUR/giorno**.
* Senior: `≥70 anni` **o** `isSeniorDriverAge=true` → **+10 EUR/giorno**.
* Cumulabili.

**6) Sconti** (`apply_channel_discount`) — applicati **pre-IVA**:

* `channel` che inizia con `WEB` → **-3%** del subtotale
* `agreementCoupon` valorizzato → **-5%** del subtotale
* `discountValueWithoutVat` numerico → sottratto **in valore assoluto**
* Il totale sconto è **clippato** tra `0` e `amount`.

**7) Disponibilità** (`availability_hash_available`)
Deterministica 80% con hash `md5("{group_code}|{pickup}|{date}")`.

**Formula riassuntiva**

```
base_daily = daily_rate * season_multiplier
base = (base_daily * days)
      + one_way_fee
      + out_of_hours_fee
      + young/senior_surcharge

pre_vat = max(0, base - discount)
total   = pre_vat * (1 + VAT_PCT/100)
```

---

## Dettagli d’implementazione (Pydantic v2, alias, serializzazione)

* Il progetto usa **Pydantic v2** (`field_validator`, `ConfigDict(populate_by_name=True)`, `model_dump()`).
* Per evitare conflitti tra **nome campo** e **nome tipo**:

  * In `BookingVehicle` il campo Python è `veh_make_models` ma l’alias di serializzazione è **`"VehMakeModel"`**.

    * **Input** e **output** continueranno a usare `"VehMakeModel"`.
  * In `QuotationData` il campo Python è `total_charge` ma l’alias è **`"TotalCharge"`**.
* Questo risolve l’errore Pydantic tipo:
  `TypeError: Unable to evaluate type annotation 'List[VehMakeModel]'`
* Gli alias garantiscono **retrocompatibilità** con payload preesistenti:

  * In ingresso: accetta **sia** `veh_make_models` **sia** `VehMakeModel`.
  * In uscita: viene serializzato come **`VehMakeModel`** (perché l’alias corrisponde allo schema atteso).

---

## Esempi di test (curl e script)

### Curl

```bash
# Health (no auth)
curl -s http://localhost:8000/health | jq

# Locations (auth)
curl -s http://localhost:8000/api/v1/touroperator/locations \
  -H "X-API-Key: MYRENT-DEMO-KEY" | jq

# Quotations (auth)
curl -s http://localhost:8000/api/v1/touroperator/quotations \
  -H "X-API-Key: MYRENT-DEMO-KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "dropOffLocation": "MXP",
        "endDate": "2025-07-05T12:00:00Z",
        "pickupLocation": "FCO",
        "startDate": "2025-07-02T10:00:00Z",
        "age": 30,
        "channel": "WEB_DEMO",
        "showPics": true,
        "showOptionalImage": false,
        "showVehicleParameter": true,
        "showVehicleExtraImage": false,
        "macroDescription": "SUV"
      }' | jq

# Damages (auth)
curl -s http://localhost:8000/api/v1/touroperator/damages/GF962VG \
  -H "X-API-Key: MYRENT-DEMO-KEY" | jq
```

### Script di demo

Nel messaggio precedente trovi `demo_api_fixed.py` con **valori fissi**:

* testa `/health`, `/locations`, diverse chiamate `/quotations` (macro, fuori orario, giovane), e `/damages/GF962VG`.
* Esecuzione:

```bash
pip install requests
python demo_api_fixed.py
```

---

## Errori comuni e codici di stato

* `401 Unauthorized` — API key assente o errata.
* `400 Bad Request` — `endDate <= startDate` nel body di `/quotations`.
* `422 Unprocessable Entity` — payload JSON malformato o campi non conformi allo schema (validazione Pydantic).
* `500 Internal Server Error` — errori inattesi (es. `vehicles.json` non leggibile).

---

## Note operative e personalizzazioni

* **Valuta/IVA**: controllate da `currency` e `vat_percentage` del JSON.
* **Sedi**: sono codificate nel sorgente (`LOCATIONS`), ma puoi spostarle su file se serve.
* **Immagini extra**: `vehicleExtraImage` è presente solo come campo vuoto quando `showVehicleExtraImage=true` (demo).
* **Optionals**: per la demo sono **sempre inclusi**. Per renderli condizionati a `showOptionalImage`, modifica:

  ```python
  optionals = [...] if req.showOptionalImage else []
  ```
* **CORS con credenziali**: se ti servono cookie/Authorization nel browser:

  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["https://tuo-dominio.example"],
      allow_methods=["*"],
      allow_headers=["*"],
      allow_credentials=True,
  )
  ```
* **Avvio in produzione**: usa un ASGI server (es. `gunicorn` + `uvicorn.workers.UvicornWorker`) dietro proxy/reverse-proxy.

---

## Riepilogo

* **4 endpoint**: `health`, `locations`, `quotations`, `damages`.
* **Auth semplice** via header API key.
* **CORS aperto** per uso immediato da frontend.
* **Prezzi trasparenti** con breakdown in `Reference.calculated`.
* **Dataset flessibile** (`vehicles.json`) per aggiungere gruppi, sedi, danni.
* **Compatibile Pydantic v2** con alias per evitare collisioni di nomi.

Se vuoi, posso generare un **README.md** pronto da committare nel repository (con la stessa struttura) o creare uno **Swagger snippet** di esempio aggiuntivo.
