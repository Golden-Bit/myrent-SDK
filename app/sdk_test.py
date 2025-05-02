"""
Esempio end-to-end:
1. Autentica con le credenziali reali fornite da Dogma Systems
2. Elenca le sedi
3. Effettua preventivo su veicolo categoria CDMR
4. Crea prenotazione con i dati ottenuti
NOTA: questo script effettua vere chiamate HTTP verso l’ambiente di produzione MyRent.
"""

from myrent_rest_sdk import MyRentRestClient
from datetime import datetime, timedelta

# === CREDENZIALI REALI (fornite da Aurora) ===
USERNAME = "..."
PASSWORD = "..."
COMPANY  = "..."          # codice azienda da usare nel body di /authentication

client = MyRentRestClient(USERNAME, PASSWORD, COMPANY)

# 1) Login
token = client.authenticate()
print("Token:", token[:20] + "...")

# 2) Sedi disponibili
locations = client.get_locations()
print("Prime 3 sedi:", locations[:3])

# 3) Preventivo (48 h da domani)
start = (datetime.utcnow() + timedelta(days=1)).replace(microsecond=0)
end   = start + timedelta(days=2)
quotes = client.get_quotations(
    pickup_location=locations[0]["code"],     # uso la prima sede
    pickup_date_iso=start.isoformat() + "Z",
    dropoff_date_iso=end.isoformat() + "Z",
    sipp_code="CDMR",
)
print("Quotations:", quotes[:1])

# 4) Creo prenotazione (sample minimale)
booking_payload = {
    "pickup_location": locations[0]["code"],
    "dropoff_location": locations[0]["code"],
    "pickup_date": start.isoformat() + "Z",
    "dropoff_date": end.isoformat() + "Z",
    "vehicle": {"sipp": "CDMR"},
    "driver": {
        "first_name": "Mario",
        "last_name": "Rossi",
        "age": 35,
        "license": "X1234567"
    },
    "payment": {
        "type": "credit_card",
        "card_number": "4111111111111111",
        "expiry": "12/25",
        "cvv": "123"
    }
}

#confirmation = client.create_booking(booking_payload)
print("Prenotazione confermata:", confirmation)
