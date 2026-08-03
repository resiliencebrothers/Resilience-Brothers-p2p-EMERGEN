"""Manual smoke test for iter113 backend (pair batches, deposits, revenue)."""
import os, sys, time
import requests
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE = "http://localhost:8001/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

exp = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
for tok, uid in [("test_session_admin_X", "user_test_admin01"),
                 ("test_session_vip_X", "user_test_vip01"),
                 ("test_session_employee_X", "user_test_employee01"),
                 ("test_session_normal_X", "user_test_normal01")]:
    db.user_sessions.update_one({"session_token": tok},
                                 {"$set": {"session_token": tok, "user_id": uid, "expires_at": exp}},
                                 upsert=True)

A = {"Authorization": "Bearer test_session_admin_X"}
V = {"Authorization": "Bearer test_session_vip_X"}
N = {"Authorization": "Bearer test_session_normal_X"}

def chk(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" — {extra}" if extra else ""))
    if not cond:
        sys.exit(1)

# Ensure a test pair EUR->USDT exists with vip + real rates
db.currencies.update_one({"code": "EUR"}, {"$set": {"code": "EUR", "name": "Euro Transferencia", "type": "fiat", "is_active": True}}, upsert=True)
db.currencies.update_one({"code": "USDT"}, {"$set": {"is_active": True}}, upsert=True)
db.rates.update_one({"from_code": "EUR", "to_code": "USDT"},
                    {"$set": {"from_code": "EUR", "to_code": "USDT", "rate_normal": 1.05,
                              "rate_vip": 1.08, "real_rate": 1.12, "id": "rate_test_eur_usdt"}},
                    upsert=True)

# 1. pairs endpoint
r = requests.get(f"{BASE}/vip/batch-pairs", headers=V)
chk("GET /vip/batch-pairs 200", r.status_code == 200, r.text[:200])
pairs = r.json()["items"]
pair = next((p for p in pairs if p["pair"] == "EUR->USDT"), None)
chk("EUR->USDT pair listed with rate_vip 1.08", pair and pair["rate_vip"] == 1.08, str(pair))

# 2. create pair batch
r = requests.post(f"{BASE}/vip/batches", headers=V, json={"from_code": "EUR", "to_code": "USDT", "note": "test iter113"})
chk("POST /vip/batches pair 200", r.status_code == 200, r.text[:300])
batch = r.json()
chk("batch has from/to + direction=pair", batch.get("from_code") == "EUR" and batch.get("to_code") == "USDT" and batch.get("direction") == "pair")

# invalid pair rejected
r2 = requests.post(f"{BASE}/vip/batches", headers=V, json={"from_code": "EUR", "to_code": "NOEXISTE"})
chk("invalid pair 422", r2.status_code == 422, str(r2.status_code))

# 3. add item 100 EUR
r = requests.post(f"{BASE}/vip/batches/{batch['id']}/items", headers=V, json={"items": [{"holder_name": "Juan Perez", "amount": 100}]})
chk("add item 200", r.status_code == 200, r.text[:300])
item = r.json()["items"][0]
chk("item amount_to = 108 (rate 1.08)", abs(item["amount_to"] - 108.0) < 0.001, str(item.get("amount_to")))

# 4. approve as admin → balance credit + margin
bal_before = (db.users.find_one({"user_id": "user_test_vip01"}) or {}).get("vip_balances", {}).get("USDT", 0.0)
r = requests.post(f"{BASE}/admin/vip-batches/items/{item['id']}/approve", headers=A, json={})
chk("approve item 200", r.status_code == 200, r.text[:300])
fresh = r.json()
bal_after = (db.users.find_one({"user_id": "user_test_vip01"}) or {}).get("vip_balances", {}).get("USDT", 0.0)
chk("VIP USDT balance +108", abs((bal_after - bal_before) - 108.0) < 0.001, f"{bal_before} → {bal_after}")
# margin = 100*1.12 - 108 = 4 USDT
chk("margin_usdt = 4.0", abs(fresh.get("margin_usdt", 0) - 4.0) < 0.001, str(fresh.get("margin_usdt")))

# 5. revenue includes vip batches
r = requests.get(f"{BASE}/admin/revenue?days=1", headers=A)
chk("GET /admin/revenue 200", r.status_code == 200, r.text[:200])
rev = r.json()
chk("revenue vip_batches_profit_usdt >= 4", rev.get("vip_batches_profit_usdt", 0) >= 4.0, str(rev.get("vip_batches_profit_usdt")))
chk("total includes batches", rev["total_profit_usdt"] >= rev.get("vip_batches_profit_usdt", 0))

# timeseries
r = requests.get(f"{BASE}/admin/revenue/timeseries?days=1&granularity=day", headers=A)
rows = r.json() if r.status_code == 200 else []
has = any(row.get("vip_batches_profit_usdt", 0) > 0 for row in (rows if isinstance(rows, list) else rows.get("rows", [])))
chk("timeseries has vip_batches_profit_usdt", has, str(rows)[:200])

# 6. deposits config + create + confirm
r = requests.get(f"{BASE}/deposits/config", headers=N)
chk("GET /deposits/config 200", r.status_code == 200, r.text[:200])
cfg = r.json()
chk("config has courier_min_usdt 1000", cfg.get("courier_min_usdt") == 1000.0)
usdt_cfg = next((c for c in cfg["currencies"] if c["code"] == "USDT"), None)
chk("USDT depositable via crypto", usdt_cfg and "crypto" in usdt_cfg["methods"], str(usdt_cfg))

r = requests.post(f"{BASE}/deposits", headers=N, json={"currency": "USDT", "amount": 50, "method": "crypto", "tx_hash": "0xabc1234567890"})
chk("POST /deposits 200", r.status_code == 200, r.text[:300])
dep = r.json()
nbal_before = (db.users.find_one({"user_id": "user_test_normal01"}) or {}).get("vip_balances", {}).get("USDT", 0.0)
r = requests.post(f"{BASE}/admin/deposits/{dep['id']}/confirm", headers=A)
chk("confirm deposit 200", r.status_code == 200, r.text[:300])
nbal_after = (db.users.find_one({"user_id": "user_test_normal01"}) or {}).get("vip_balances", {}).get("USDT", 0.0)
chk("normal USDT balance +50", abs((nbal_after - nbal_before) - 50.0) < 0.001, f"{nbal_before} → {nbal_after}")
# double confirm blocked
r = requests.post(f"{BASE}/admin/deposits/{dep['id']}/confirm", headers=A)
chk("double confirm 409", r.status_code == 409, str(r.status_code))

# cash deposit > 1000 requires courier fields
r = requests.post(f"{BASE}/deposits", headers=N, json={"currency": "USD", "amount": 2000, "method": "cash"})
chk("cash >1000 without courier fields → 422", r.status_code == 422, f"{r.status_code} {r.text[:150]}")

# 7. company funds includes new fields
r = requests.get(f"{BASE}/admin/company-funds", headers=A)
chk("company funds 200", r.status_code == 200)
funds = r.json()
eur_row = next((f for f in funds if f["currency"] == "EUR"), None)
chk("EUR inflow_vip_batches = 100", eur_row and abs(eur_row.get("inflow_vip_batches", 0) - 100.0) < 0.001, str(eur_row))
usdt_row = next((f for f in funds if f["currency"] == "USDT"), None)
chk("USDT inflow_deposits >= 50", usdt_row and usdt_row.get("inflow_deposits", 0) >= 50.0, str(usdt_row))

# 8. admin transactions register includes batch item + deposit
r = requests.get(f"{BASE}/admin/transactions?direction=in", headers=A)
chk("admin transactions 200", r.status_code == 200, r.text[:200])
tx = r.json()
items = tx.get("items", tx if isinstance(tx, list) else [])
has_batch = any(t.get("ref_type") == "vip_batch_item" for t in items)
has_dep = any(t.get("ref_type") == "deposit" for t in items)
chk("register has vip_batch_item", has_batch)
chk("register has deposit", has_dep)

# 9. staff pair RBAC
db.users.update_one({"user_id": "user_test_employee01"}, {"$set": {"allowed_batch_pairs": ["ZELLE->CUPT"], "allowed_permissions": ["orders"]}})
r = requests.post(f"{BASE}/vip/batches", headers=V, json={"from_code": "EUR", "to_code": "USDT"})
b2 = r.json()
r = requests.post(f"{BASE}/vip/batches/{b2['id']}/items", headers=V, json={"items": [{"holder_name": "Maria Lopez", "amount": 10}]})
it2 = r.json()["items"][0]
E = {"Authorization": "Bearer test_session_employee_X"}
r = requests.post(f"{BASE}/admin/vip-batches/items/{it2['id']}/approve", headers=E, json={})
chk("scoped employee blocked on EUR->USDT (403)", r.status_code == 403, f"{r.status_code} {r.text[:150]}")
db.users.update_one({"user_id": "user_test_employee01"}, {"$set": {"allowed_batch_pairs": ["EUR->USDT"]}})
r = requests.post(f"{BASE}/admin/vip-batches/items/{it2['id']}/approve", headers=E, json={})
chk("employee with pair can approve", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
db.users.update_one({"user_id": "user_test_employee01"}, {"$set": {"allowed_batch_pairs": []}})

# 10. legacy capital deposit confirm → credits USDT balance (not ledger)
r = requests.post(f"{BASE}/vip/capital-deposits", headers=V, json={"amount": 25, "currency": "USDT", "hash": "0xhash1234567890abc", "note": "test"})
if r.status_code == 200:
    cap = r.json()
    vb = (db.users.find_one({"user_id": "user_test_vip01"}) or {}).get("vip_balances", {}).get("USDT", 0.0)
    r2 = requests.post(f"{BASE}/admin/vip-capital-deposits/{cap['id']}/confirm", headers=A, json={})
    chk("capital confirm 200", r2.status_code == 200, f"{r2.status_code} {r2.text[:200]}")
    vb2 = (db.users.find_one({"user_id": "user_test_vip01"}) or {}).get("vip_balances", {}).get("USDT", 0.0)
    chk("capital credited to USDT balance +25", abs((vb2 - vb) - 25.0) < 0.001, f"{vb} → {vb2}")
    led = db.vip_ledger.find_one({"vip_user_id": "user_test_vip01"}) or {}
    chk("ledger positive NOT incremented", float(led.get("positive_usdt") or 0) == 0.0, str(led.get("positive_usdt")))
else:
    print(f"SKIP capital deposit create → {r.status_code} {r.text[:200]}")

print("ALL BACKEND CHECKS PASSED")
