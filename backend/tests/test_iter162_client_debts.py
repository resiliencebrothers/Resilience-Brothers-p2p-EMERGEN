"""iter162 — Client debts report regression tests.

Endpoint: GET /api/admin/company-funds/client-debts
  we_owe : custody balances (vip_balances + legacy vip_balance_usd)
  owe_us : vip_ledger.negative_usdt (VIP debt in USDT)
"""
import os
import uuid

import requests
from pymongo import MongoClient

from conftest import (
    BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP, NORMAL_TOKEN as NORMAL,
)

URL = f"{BASE_URL}/api/admin/company-funds/client-debts"

DEBTOR_ID = "user_test_debtor162"
HOLDER_ID = "user_test_holder162"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed():
    db = _db()
    db.users.update_one(
        {"user_id": DEBTOR_ID},
        {"$set": {"user_id": DEBTOR_ID, "name": "Debtor 162",
                  "email": "debtor162@test.com", "role": "vip"},
         "$setOnInsert": {"id": uuid.uuid4().hex}},
        upsert=True,
    )
    db.vip_ledger.update_one(
        {"vip_user_id": DEBTOR_ID},
        {"$set": {"negative_usdt": 777.77, "positive_usdt": 0.0,
                  "updated_at": "2026-06-01T00:00:00+00:00"}},
        upsert=True,
    )
    db.users.update_one(
        {"user_id": HOLDER_ID},
        {"$set": {"user_id": HOLDER_ID, "name": "Holder 162",
                  "email": "holder162@test.com", "role": "vip",
                  "vip_balances": {"USDT": 300.0, "USD": 0.0}}},
        upsert=True,
    )


def _cleanup():
    db = _db()
    db.vip_ledger.delete_many({"vip_user_id": DEBTOR_ID})
    db.users.delete_many({"user_id": {"$in": [DEBTOR_ID, HOLDER_ID]}})


class TestClientDebts:
    def setup_method(self):
        _seed()

    def teardown_method(self):
        _cleanup()

    def test_admin_gets_both_sides_and_net(self):
        r = requests.get(URL, headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["base"] == "USDT"

        debtor = next((x for x in body["owe_us"] if x["user_id"] == DEBTOR_ID), None)
        assert debtor is not None, "seeded debtor missing from owe_us"
        assert debtor["total_usdt"] == 777.77
        assert debtor["balances"][0]["currency"] == "USDT"
        assert debtor["email"] == "debtor162@test.com"

        holder = next((x for x in body["we_owe"] if x["user_id"] == HOLDER_ID), None)
        assert holder is not None, "seeded holder missing from we_owe"
        assert holder["total_usdt"] == 300.0
        # zero-amount currencies (USD: 0.0) must not appear as rows
        assert all(b["currency"] != "USD" for b in holder["balances"])

        assert body["total_owe_us_usdt"] >= 777.77
        assert body["total_we_owe_usdt"] >= 300.0
        assert body["net_usdt"] == round(
            body["total_owe_us_usdt"] - body["total_we_owe_usdt"], 2)

    def test_rows_sorted_desc_by_total(self):
        r = requests.get(URL, headers=_h(ADMIN))
        assert r.status_code == 200
        body = r.json()
        for side in ("we_owe", "owe_us"):
            totals = [x["total_usdt"] for x in body[side]]
            assert totals == sorted(totals, reverse=True)

    def test_vip_and_normal_forbidden(self):
        for tok in (VIP, NORMAL):
            r = requests.get(URL, headers=_h(tok))
            assert r.status_code == 403, r.text

    def test_unauthenticated_401(self):
        r = requests.get(URL)
        assert r.status_code == 401
