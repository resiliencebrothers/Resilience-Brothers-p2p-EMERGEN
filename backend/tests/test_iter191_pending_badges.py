"""iter191 — Pending-count sidebar badges + transfer withdrawals no longer
require the beneficiary holder name.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, make_vip_totp

API = f"{BASE_URL}/api"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def test_pending_counts_shape_and_math():
    r = requests.get(f"{API}/admin/pending-counts", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("withdrawals", "deposits", "capital_requests", "withdrawals_hub",
              "vip_batches", "orders", "reconciliation"):
        assert k in d and isinstance(d[k], int), k
    assert d["withdrawals_hub"] == d["withdrawals"] + d["deposits"] + d["capital_requests"]


def test_pending_counts_reflect_new_pending_withdrawal():
    db = _db()
    base = requests.get(f"{API}/admin/pending-counts", headers=_hdr(ADMIN_TOKEN)).json()
    wid = f"wd_it191_{uuid.uuid4().hex[:8]}"
    db.withdrawals.insert_one({
        "id": wid, "user_id": "user_test_vip01", "amount_usd": 10,
        "currency": "USD", "method": "transfer", "details": "Banco X 0001",
        "status": "pending", "created_at": "2099-08-01T00:00:00+00:00"})
    try:
        after = requests.get(f"{API}/admin/pending-counts", headers=_hdr(ADMIN_TOKEN)).json()
        assert after["withdrawals"] == base["withdrawals"] + 1
        assert after["withdrawals_hub"] == base["withdrawals_hub"] + 1
    finally:
        db.withdrawals.delete_one({"id": wid})


def test_pending_counts_requires_staff():
    r = requests.get(f"{API}/admin/pending-counts", headers=_hdr(VIP_TOKEN))
    assert r.status_code in (401, 403)


def test_transfer_withdrawal_without_beneficiary_now_succeeds():
    db = _db()
    code = "USDX191"
    db.currencies.update_one(
        {"code": code},
        {"$set": {"code": code, "name": "Test 191", "type": "fiat",
                  "is_active": True, "delivery_methods": None},
         "$setOnInsert": {"id": uuid.uuid4().hex,
                          "created_at": "2026-07-10T00:00:00+00:00"}},
        upsert=True)
    db.users.update_one({"user_id": "user_test_vip01"},
                        {"$set": {f"vip_balances.{code}": 500}})
    try:
        r = requests.post(
            f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN),
            json={
                "amount_usd": 10, "currency": code, "method": "transfer",
                "details": "Banco Popular · cuenta 0102987654321",
                # NO beneficiary_name — must be accepted now (iter191)
                "totp_code": make_vip_totp(),
            })
        assert r.status_code == 200, r.text
    finally:
        db.currencies.delete_one({"code": code})
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$unset": {f"vip_balances.{code}": ""}})
        db.withdrawals.delete_many({"currency": code})
