"""iter195 — 'Fondo Resilience' cash box + auto account attribution.

- Manual adjustment method=cash without account_id → auto-tagged to the
  lazily-created 'Fondo Resilience' cash box for that currency.
- Client withdrawal method=cash marked paid → auto paid_from cash box.
- Client withdrawal method=transfer with exactly ONE active account for the
  currency → auto paid_from that account.
- Two accounts → no auto (stays unassigned).
- Company withdrawal with one account → auto.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, with_totp_admin, make_admin_totp

API = f"{BASE_URL}/api"
CASH = "TCA195"    # cash-box currency
SINGLE = "TCB195"  # one transfer account
MULTI = "TCC195"   # two accounts
ALL = [CASH, SINGLE, MULTI]
S = {}

PROOF = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def setup_module():
    db = _db()
    for code in ALL:
        db.currencies.update_one(
            {"code": code},
            {"$set": {"code": code, "name": f"Test {code}", "type": "fiat",
                      "is_active": True},
             "$setOnInsert": {"id": uuid.uuid4().hex,
                              "created_at": "2026-07-10T00:00:00+00:00"}},
            upsert=True)


def teardown_module():
    db = _db()
    db.currencies.delete_many({"code": {"$in": ALL}})
    db.fund_accounts.delete_many({"currency": {"$in": ALL}})
    db.fund_account_transfers.delete_many({"currency": {"$in": ALL}})
    db.company_fund_adjustments.delete_many({"currency": {"$in": ALL}})
    db.company_withdrawals.delete_many({"currency": {"$in": ALL}})
    db.withdrawals.delete_many({"currency": {"$in": ALL}})


def _adjust(currency, amount, method="transfer", account_id=None):
    body = with_totp_admin({
        "adjustment_type": "inflow", "currency": currency, "amount": amount,
        "method": method, "source_name": "Test 195",
        "source_account": "" if method == "cash" else "acct-195",
        "account_id": account_id,
    })
    return requests.post(f"{API}/admin/company-funds/adjustments",
                         headers=_hdr(), json=body)


def _breakdown(currency):
    r = requests.get(f"{API}/admin/company-funds/accounts/{currency}", headers=_hdr())
    assert r.status_code == 200, r.text
    return r.json()


def _seed_withdrawal(currency, method, amount=50):
    wid = f"wd195_{uuid.uuid4().hex[:8]}"
    _db().withdrawals.insert_one({
        "id": wid, "user_id": "user_test_vip01",
        "user_email": "vip.test@resilience.com", "user_name": "VIP Test",
        "amount_usd": amount, "currency": currency, "method": method,
        # iter205 — el guard de mensajería exige fee cobrada para cash-courier;
        # este test valida la auto-atribución de caja, no la mensajería.
        "cash_delivery_mode": "office_pickup",
        "details": "test", "beneficiary_name": "Test 195",
        "status": "pending", "admin_note": "",
        "created_at": "2026-08-09T00:00:00+00:00",
    })
    return wid


def _mark_paid(wid, extra=None):
    body = {"status": "paid", "totp_code": make_admin_totp(),
            "admin_note": "t195", **(extra or {})}
    return requests.put(f"{API}/admin/withdrawals/{wid}/status",
                        headers=_hdr(), json=body)


def test_cash_adjustment_auto_creates_cash_box():
    r = _adjust(CASH, 1000, method="cash")
    assert r.status_code == 200, r.text
    assert r.json()["account_label"] == "Fondo Resilience"
    box = _db().fund_accounts.find_one({"currency": CASH, "name": "Fondo Resilience"})
    assert box and box["method"] == "cash" and box["is_active"]
    S["box"] = box["id"]
    data = _breakdown(CASH)
    row = next(a for a in data["accounts"] if a["id"] == S["box"])
    assert row["balance"] == 1000
    assert data["unassigned"] == 0


def test_cash_withdrawal_paid_auto_from_cash_box():
    wid = _seed_withdrawal(CASH, "cash", amount=100)
    r = _mark_paid(wid)
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["paid_from_account_id"] == S["box"]
    assert w["paid_from_account_label"] == "Fondo Resilience"
    data = _breakdown(CASH)
    row = next(a for a in data["accounts"] if a["id"] == S["box"])
    assert row["balance"] == 900


def test_transfer_withdrawal_single_account_auto():
    r = requests.post(f"{API}/admin/company-funds/accounts", headers=_hdr(),
                      json={"name": "Banco CUPT Test", "currency": SINGLE,
                            "method": "bank"})
    assert r.status_code == 200, r.text
    S["single"] = r.json()["id"]
    assert _adjust(SINGLE, 500, account_id=S["single"]).status_code == 200
    wid = _seed_withdrawal(SINGLE, "transfer", amount=80)
    r = _mark_paid(wid, {"payout_proof_image": PROOF})
    assert r.status_code == 200, r.text
    assert r.json()["paid_from_account_id"] == S["single"]
    data = _breakdown(SINGLE)
    row = next(a for a in data["accounts"] if a["id"] == S["single"])
    assert row["balance"] == 420


def test_transfer_withdrawal_two_accounts_stays_unassigned():
    for name in ("Cuenta A 195", "Cuenta B 195"):
        r = requests.post(f"{API}/admin/company-funds/accounts", headers=_hdr(),
                          json={"name": name, "currency": MULTI, "method": "bank"})
        assert r.status_code == 200, r.text
    assert _adjust(MULTI, 300).status_code == 200  # unassigned inflow
    wid = _seed_withdrawal(MULTI, "transfer", amount=60)
    r = _mark_paid(wid, {"payout_proof_image": PROOF})
    assert r.status_code == 200, r.text
    assert not r.json().get("paid_from_account_id")
    data = _breakdown(MULTI)
    assert data["unassigned"] == 240  # 300 - 60, both accounts untouched
    assert all(a["balance"] == 0 for a in data["accounts"])


def test_explicit_account_still_wins_over_auto():
    wid = _seed_withdrawal(CASH, "cash", amount=10)
    # explicitly pick the cash box (same result) but via explicit path
    r = _mark_paid(wid, {"paid_from_account_id": S["box"]})
    assert r.status_code == 200, r.text
    assert r.json()["paid_from_account_id"] == S["box"]


def test_company_withdrawal_single_account_auto():
    body = with_totp_admin({"amount": 50, "currency": SINGLE,
                            "beneficiary": "Proveedor 195"})
    r = requests.post(f"{API}/admin/company-withdrawals", headers=_hdr(), json=body)
    assert r.status_code == 200, r.text
    cwid = r.json()["id"]
    r = requests.put(f"{API}/admin/company-withdrawals/{cwid}/status",
                     headers=_hdr(),
                     json={"status": "paid", "totp_code": make_admin_totp()})
    assert r.status_code == 200, r.text
    assert r.json()["paid_from_account_id"] == S["single"]
    data = _breakdown(SINGLE)
    row = next(a for a in data["accounts"] if a["id"] == S["single"])
    assert row["balance"] == 370  # 420 - 50
