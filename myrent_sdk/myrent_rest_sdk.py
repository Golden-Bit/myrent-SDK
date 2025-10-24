# myrent_client.py
import requests
from typing import Dict, Any, List


class MyRentClient:
    """
    SDK minimale per l’API REST MyRent (ambiente sul.myrent.it).
    Copre:
      • POST /authentication
      • GET  /locations
      • POST /quotations
      • POST /bookings
    Tutte le richieste dopo il login includono l’header:   tokenValue: <token>
    """

    BASE_URL = "https://sul.myrent.it/MyRentWeb/api/v1/touroperator"

    def __init__(self) -> None:
        self.token: str | None = None

    # ------------------------------------------------------------------ #
    # AUTHENTICATION                                                     #
    # ------------------------------------------------------------------ #
    def authenticate(self, user_id: str, password: str, company_code: str) -> str:
        """
        Effettua il login e salva il token per le successive chiamate.

        Args:
            user_id:     credenziale utente fornita da Dogma Systems
            password:    password
            company_code (tenant): es. "sul"

        Returns:
            tokenValue restituito dall’API
        """
        url = f"{self.BASE_URL}/authentication"
        payload = {
            "UserId": user_id,
            "Password": password,
            "companyCode": company_code,
        }
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("status", False):
            raise RuntimeError(f"Login fallito: {data.get('message')}")

        self.token = data["result"]["tokenValue"]
        return self.token

    # header helper
    def _hdr(self) -> Dict[str, str]:
        if not self.token:
            raise RuntimeError("Chiamare authenticate() prima di usare le API.")
        return {"tokenValue": self.token}

    # ------------------------------------------------------------------ #
    # LOCATIONS                                                          #
    # ------------------------------------------------------------------ #
    def get_locations(self) -> List[Dict[str, Any]]:
        """
        Ritorna la lista completa delle sedi con orari / coordinate.
        """
        url = f"{self.BASE_URL}/locations"
        r = requests.get(url, headers=self._hdr(), timeout=15)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------ #
    # QUOTATIONS                                                         #
    # ------------------------------------------------------------------ #
    def get_quotations(
        self,
        start_date: str,
        end_date: str,
        pickup_location: str,
        dropoff_location: str,
        age: int,
        channel: str,
        show_pics: bool = False,
    ) -> Dict[str, Any]:
        """
        Richiede il preventivo minimo (payload ufficiale).

        Date in ISO-8601, es. "2025-10-01T10:00:00"
        """
        url = f"{self.BASE_URL}/quotations"
        payload = {
            "startDate": start_date,
            "endDate": end_date,
            "pickupLocation": pickup_location,
            "dropOffLocation": dropoff_location,
            "age": age,
            "channel": channel,
            "showPics": show_pics,
        }
        r = requests.post(url, json=payload, headers=self._hdr(), timeout=30)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------ #
    # BOOKINGS                                                           #
    # ------------------------------------------------------------------ #
    def create_booking(
        self,
        start_date: str,
        end_date: str,
        pickup_location: str,
        dropoff_location: str,
        customer: Dict[str, Any],
        vehicle_code: str,
        channel: str,
    ) -> Dict[str, Any]:
        """
        Crea la prenotazione con i campi minimi obbligatori.
        """
        url = f"{self.BASE_URL}/bookings"
        payload = {
            "startDate": start_date,
            "endDate": end_date,
            "pickupLocation": pickup_location,
            "dropOffLocation": dropoff_location,
            "Customer": customer,
            "VehicleCode": vehicle_code,
            "channel": channel,
        }
        r = requests.post(url, json=payload, headers=self._hdr(), timeout=30)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------- #
# ESEMPIO D’USO                                                          #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    USER_ID = "partner_rentalpremium_sul"
    PASSWORD = "R3nt4l_Pr3m1um"
    COMPANY_CODE = "sul"          # tenant
    CHANNEL = "WEB001"            # listino da usare

    client = MyRentClient()

    # 1. Login
    token = client.authenticate(USER_ID, PASSWORD, COMPANY_CODE)
    print("TOKEN:", token)

    # 2. Locations
    locs = client.get_locations()
    first_loc = locs[0]["locationCode"]
    print("Prima location:", first_loc)

    # 3. Quotations → preventivo di 2 giorni a partire da domani
    import datetime as dt
    start = (dt.datetime.utcnow() + dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    end   = (dt.datetime.utcnow() + dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")

    quotes = client.get_quotations(
        start_date=start,
        end_date=end,
        pickup_location=first_loc,
        dropoff_location=first_loc,
        age=30,
        channel=CHANNEL,
        show_pics=False,
    )
    print("Preventivo:", quotes)

    """# 4. Booking minimo (usa il primo codice veicolo disponibile se presente)
    vehicles = quotes["data"]["Vehicles"]
    vehicle_code = vehicles[0]["Vehicle"]["Code"] if vehicles else "A"  # fallback

    booking_resp = client.create_booking(
        start_date=start,
        end_date=end,
        pickup_location=first_loc,
        dropoff_location=first_loc,
        customer={"Name": "Mario", "Surname": "Rossi"},
        vehicle_code=vehicle_code,
        channel=CHANNEL,
    )
    print("Prenotazione:", booking_resp)"""