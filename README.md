# MyRent REST SDK (Python)

> **Ambiente di riferimento:** `https://sul.myrent.it/MyRentWeb/api/v1/touroperator`  
> **Versione SDK:** 1.0.0 – aprile 2025  
> **Compatibilità:** Python ≥ 3.9

SDK minimale ma completo per interfacciarsi con l’**API REST MyRent** (Dogma Systems) e automatizzare:

| Funzione | Endpoint | Metodo |
|----------|----------|--------|
| **Login / Token** | `/authentication` | `POST` |
| **Lista sedi** | `/locations` | `GET` |
| **Preventivi (quotations)** | `/quotations` | `POST` |
| **Prenotazioni (bookings)** | `/bookings` | `POST` |

L’intero flusso -- dall’autenticazione alla prenotazione -- è condensato in **un’unica classe** (`MyRentClient`) per semplificare integrazione e manutenzione.

---

## 1. Installazione

```bash
# cloniamo o copiamo il file myrent_client.py nel progetto
pip install requests
````

*Non sono richieste altre dipendenze.*

---

## 2. Quick start

```python
from myrent_client import MyRentClient
import datetime as dt

USER_ID       = "partner_rentalpremium_sul"
PASSWORD      = "R3nt4l_Pr3m1um"
COMPANY_CODE  = "sul"
CHANNEL_CODE  = "WEB001"

client = MyRentClient()
client.authenticate(USER_ID, PASSWORD, COMPANY_CODE)    # => tokenValue

# locations
locs = client.get_locations()
first_code = locs[0]["locationCode"]

# quotations (2 giorni a partire da domani)
start = (dt.datetime.utcnow() + dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
end   = (dt.datetime.utcnow() + dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")

quotes = client.get_quotations(
    start_date=start,
    end_date=end,
    pickup_location=first_code,
    dropoff_location=first_code,
    age=30,
    channel=CHANNEL_CODE,
    show_pics=False
)

# booking minimale
vehicle_code = quotes["data"]["Vehicles"][0]["Vehicle"]["Code"]
booking = client.create_booking(
    start_date=start,
    end_date=end,
    pickup_location=first_code,
    dropoff_location=first_code,
    customer={"Name": "Mario", "Surname": "Rossi"},
    vehicle_code=vehicle_code,
    channel=CHANNEL_CODE
)

print("Booking ID →", booking.get("id"))
```

---

## 3. API dettagliata

### 3.1 `MyRentClient.authenticate(user_id, password, company_code) → str`

| Parametro      | Tipo  | Descrizione                                                      |
| -------------- | ----- | ---------------------------------------------------------------- |
| `user_id`      | `str` | Credenziale fornita da Dogma (*es.* `partner_rentalpremium_sul`) |
| `password`     | `str` | Password associata                                               |
| `company_code` | `str` | Tenant aziendale (*es.* `sul`)                                   |

Effettua il login e salva internamente il `tokenValue` presente in `result.tokenValue`.
L’SDK propaga il token nei successivi header `tokenValue:<token>`.

---

### 3.2 `get_locations() → List[dict]`

Restituisce l’elenco completo delle sedi con:

* `locationCode`, `locationName`, indirizzo, lat/long
* orari (`openings`, `closing`, `festivity`)
* flag aeroporto/stazione ecc.

---

### 3.3 `get_quotations(...) → dict`

| Parametro                              | Tipo            | Note                          |
| -------------------------------------- | --------------- | ----------------------------- |
| `start_date`, `end_date`               | `str`(ISO-8601) | `YYYY-MM-DDTHH:MM:SS`         |
| `pickup_location` / `dropoff_location` | `str`           | Codice sede                   |
| `age`                                  | `int`           | Età conducente                |
| `channel`                              | `str`           | Tariffario (es. `WEB001`)     |
| `show_pics`                            | `bool`          | default `False` (consigliato) |

La risposta (`data.Vehicles[]`) include tariffe, extra, parametri veicolo, disponibilità.

---

### 3.4 `create_booking(...) → dict`

Payload **minimo** richiesto:

| Campo JSON                          | Descrizione                    |
| ----------------------------------- | ------------------------------ |
| `startDate`, `endDate`              | Date/ora ISO-8601              |
| `pickupLocation`, `dropOffLocation` | Codici sede                    |
| `Customer`                          | Oggetto `{Name, Surname, ...}` |
| `VehicleCode`                       | Codice SIPP/gruppo scelto      |
| `channel`                           | Listino (es. `WEB001`)         |

Aggiungere facoltativamente `optionals`, `VehicleRequest`, `Fee`, ecc. seguendo lo schema Swagger.

---

## 4. Gestione errori

* Metodi internamente eseguono `response.raise_for_status()` **→ eccezione `HTTPError` su codice 4xx/5xx**.
* Se il login restituisce `status: false`, viene generato `RuntimeError` con la descrizione di MyRent.

---

## 5. Sicurezza credenziali

Le credenziali presenti negli esempi provengono dalla mail di test Dogma Systems.
**In produzione** spostarle in *environment variables*, secret-manager o CI secrets:

```bash
export MYRENT_USER=partner_rentalpremium_sul
export MYRENT_PASS=R3nt4l_Pr3m1um
export MYRENT_COMPANY=sul
```

---

## 6. Struttura del repository

```
myrent-sdk/
├── myrent_client.py   # modulo SDK
└── README.md          # questa guida
```

*Il design “single-file” facilita l’inclusione in script legacy o funzioni Lambda.
Per progetti più grandi è possibile suddividere il client in package.*

---

## 7. Roadmap (v2)

* endpoint **/bookings/{id}/cancel** & status
* caricamento documenti conducente
* supporto SOAP (wrapper opzionale)
* type-hints Pydantic + coverage tests

---

## 8. Licenza

Questo SDK di esempio è rilasciato con **MIT License**.
Il marchio “MyRent” è di proprietà di **Dogma Systems Srl**; l’uso dell’API è soggetto agli accordi commerciali stipulati con il fornitore.

---

> *Ultimo aggiornamento: 9 aprile 2025*

```
```
