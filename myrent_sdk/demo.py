# demo.py
from datetime import datetime, timedelta
from myrent_sdk.main import (
    MyRentClient,
    LocationType,
    QuotationRequest,
)

client = MyRentClient(
    base_url="https://sul.myrent.it/MyRentWeb",
    user_id="bookingservice",
    password="123booking",
    company_code="sul",
)

# 1) Autenticazione
auth = client.authenticate()
print("Token:", auth.token_value)

# 2) Locations (stampa conteggio e prime due)
locs = client.get_locations()
print("Totale locations:", len(locs))
for l in locs[:2]:
    print(" -", l.location_code, l.location_name, "type:", l.location_type)

# 3) Quotations
#   NB: start/end possono essere stringhe nel formato accettato da MyRent
#   oppure datetime: lo SDK le formatterà come 'YYYY-MM-DDTHH:MM'
start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=5, hours=0)
end = start + timedelta(days=3)
req = QuotationRequest(
    pickup_location="BRI",
    drop_off_location="BRI",
    start_date=start,
    end_date=end,
    age=35,
    channel="RENTAL_PREMIUM_PREPAID", #D1sc0v3rc4rs_Sul_Ppay,  # <-- omesso: lo SDK userà "sul"
    show_pics=True,
    show_optional_image=True,
    show_vehicle_parameter=True,
    show_vehicle_extra_image=False,
    agreement_coupon=False,
    discount_value_without_vat="0",
    macro_description="web-api",
    show_booking_discount=True,
    is_young_driver_age=False,
    is_senior_driver_age=False,
)

quote = client.get_quotations(req)
print("Quotations trovate:", len(quote.data.quotation))
for q in quote.data.quotation[:1]:  # mostra solo la prima per brevità
    print(
        "Quote item -> total:", q.total,
        "| PU:", q.pick_up_location,
        "| DO:", q.return_location,
        "| from:", q.pick_up_date_time,
        "| to:", q.return_date_time,
    )

# TotalCharge è lasciato libero (dict) per ora
print("TotalCharge:", quote.data.total_charge)
