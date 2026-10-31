"""Manual smoke for deposit collection-account snapshot + Transacciones origen."""
import asyncio
import os
import sys

import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
API = sys.argv[1].rstrip("/") + "/api"
ADMIN = {"Cookie": "session_token=test_session_admin_X"}
NORMAL = {"Cookie": "session_token=test_session_normal_X"}
PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


async def seed():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    await db.payment_accounts.delete_many({"id": {"$in": ["pa_test_eur_a", "pa_test_eur_b"]}})
    await db.payment_accounts.insert_many([
        {"id": "pa_test_eur_a", "currency_code": "EUR", "label": "Revolut RB Europe",
         "account_details": "IBAN LT12 3456 7890 1234 5678\nTitular: RB Europe",
         "min_amount": 10, "max_amount": 200, "is_active": True,
         "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"},
        {"id": "pa_test_eur_b", "currency_code": "EUR", "label": "BBVA Empresa",
         "account_details": "ES00 1111 2222 3333", "min_amount": 200.01, "max_amount": None,
         "is_active": True, "created_at": "2026-01-01T00:00:00+00:00",
         "updated_at": "2026-01-01T00:00:00+00:00"},
    ])
    cur = await db.currencies.find_one({"code": "EUR"}, {"_id": 0, "code": 1, "delivery_methods": 1, "is_active": 1, "type": 1, "payment_account": 1})
    print("EUR currency:", cur)
    await db.deposits.delete_many({"id": "dep_legacy_test01"})
    await db.deposits.insert_one({
        "id": "dep_legacy_test01", "user_id": "user_test_normal01", "user_email": "regular@example.com",
        "user_name": "Regular User", "user_role": "normal", "currency": "EUR", "amount": 50.0,
        "method": "transfer", "cash_mode": None, "account_holder": "dayeiry", "status": "confirmed",
        "created_at": "2026-10-29T02:17:30+00:00", "reviewed_at": "2026-10-29T02:17:30+00:00",
        "updated_at": "2026-10-29T02:17:30+00:00"})


asyncio.run(seed())

r = requests.get(f"{API}/deposits/config", headers=NORMAL)
print("config EUR:", [c for c in r.json()["currencies"] if c["code"] == "EUR"])
r = requests.get(f"{API}/payment-accounts/resolve", params={"currency": "EUR", "amount": 50}, headers=NORMAL)
print("resolve:", (r.json().get("account") or {}).get("label"), r.json().get("has_tiers"))
r = requests.post(f"{API}/deposits", json={"currency": "EUR", "amount": 50, "method": "transfer",
                                           "account_holder": "dayeiry", "proof_image": PNG}, headers=NORMAL)
print("create:", r.status_code, {k: r.json().get(k) for k in ("id", "payment_account_id", "payment_account_label", "payment_account_details")} if r.status_code == 200 else r.text)
dep = r.json()["id"]
r = requests.post(f"{API}/deposits", json={"currency": "EUR", "amount": 5, "method": "transfer",
                                           "account_holder": "dayeiry", "proof_image": PNG}, headers=NORMAL)
print("below-min:", r.status_code, r.json().get("detail"))
r = requests.post(f"{API}/admin/deposits/{dep}/confirm", json={}, headers=ADMIN)
print("confirm:", r.status_code)
r = requests.get(f"{API}/admin/deposits/payment-account-options", params={"currency": "EUR"}, headers=ADMIN)
print("options:", [o["label"] for o in r.json()["items"]])
r = requests.put(f"{API}/admin/deposits/dep_legacy_test01/payment-account", json={"payment_account_id": "pa_test_eur_a"}, headers=ADMIN)
print("assign legacy:", r.status_code, r.json().get("payment_account_label"))
r = requests.put(f"{API}/admin/deposits/dep_legacy_test01/payment-account", json={"payment_account_id": "nope"}, headers=ADMIN)
print("assign bad:", r.status_code)
r = requests.get(f"{API}/admin/transactions", params={"ref_type": "deposit", "currency": "EUR"}, headers=ADMIN)
items = r.json()["items"]
print("tx deposits EUR:", r.headers.get("X-Total-Count"), [(i["ref_id"], i["payment_account_label"], i["credited_to"], i["generates_margin"]) for i in items if i["ref_id"] in (dep, "dep_legacy_test01")])
r = requests.get(f"{API}/admin/transactions", params={"ref_type": "order,order_payout"}, headers=ADMIN)
print("tx orders only ref_types:", set(i["ref_type"] for i in r.json()["items"]))
r = requests.get(f"{API}/admin/transactions/export.csv", params={"ref_type": "deposit", "currency": "EUR"}, headers=ADMIN)
print("csv head:", r.text.splitlines()[0])
print("csv row:", [ln for ln in r.text.splitlines() if dep in ln][0][:220])
r = requests.get(f"{API}/admin/transactions/export.pdf", params={"ref_type": "deposit"}, headers=ADMIN)
print("pdf:", r.status_code, r.headers.get("content-type"), len(r.content))
r = requests.get(f"{API}/deposits/mine", headers=NORMAL)
print("mine:", [(d["id"], d.get("payment_account_label")) for d in r.json()["items"] if d["id"] == dep])
print("DEPOSIT_ID", dep)
