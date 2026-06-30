"""iter48 — POST /api/vip/convert: instant self-conversion between own VIP
balances. No physical delivery, no admin approval — atomically reshuffles
funds within the SAME user."""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, VIP_TOKEN, NORMAL_TOKEN, EMPLOYEE_TOKEN


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture
def vip_with_cup_balance():
    """Plant 50,000 CUP on the test VIP user, then clean up."""
    db = MongoClient(MONGO_URL)[DB_NAME]
    uid = "user_test_vip01"
    db.users.update_one(
        {"user_id": uid},
        {"$set": {"vip_balances.CUP": 50000.0, "vip_balances.USDT": 0.0}},
    )
    yield uid
    # restore to a clean slate
    db.users.update_one(
        {"user_id": uid},
        {"$unset": {"vip_balances.CUP": "", "vip_balances.USDT": ""}},
    )


class TestVipConvert:
    def test_cup_to_usdt_happy_path(self, vip_with_cup_balance):
        # CUP→USDT rate seeded by conftest: rate_normal=0.0027, rate_vip=0.0028
        r = requests.post(
            f"{BASE_URL}/api/vip/convert",
            headers=_h(VIP_TOKEN),
            json={"from_code": "CUP", "to_code": "USDT",
                  "amount_from": 10000.0},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["from_code"] == "CUP"
        assert body["to_code"] == "USDT"
        assert body["amount_from"] == 10000.0
        # 10000 * vip_rate — verify it's a sensible USDT amount
        assert body["amount_to"] > 0
        assert body["rate"] > 0
        # Verify balance was actually swapped in mongo
        db = MongoClient(MONGO_URL)[DB_NAME]
        u = db.users.find_one({"user_id": vip_with_cup_balance}, {"_id": 0})
        assert u["vip_balances"]["CUP"] == 40000.0  # 50000 - 10000
        assert abs(u["vip_balances"]["USDT"] - body["amount_to"]) < 0.001

    def test_insufficient_balance_returns_400(self, vip_with_cup_balance):
        r = requests.post(
            f"{BASE_URL}/api/vip/convert",
            headers=_h(VIP_TOKEN),
            json={"from_code": "CUP", "to_code": "USDT",
                  "amount_from": 99999999.0},
        )
        assert r.status_code == 400
        assert "insuficiente" in r.text.lower()

    def test_same_currency_rejected(self, vip_with_cup_balance):
        r = requests.post(
            f"{BASE_URL}/api/vip/convert",
            headers=_h(VIP_TOKEN),
            json={"from_code": "CUP", "to_code": "CUP",
                  "amount_from": 100.0},
        )
        assert r.status_code == 400
        assert "diferentes" in r.text.lower()

    def test_missing_rate_pair_returns_400(self, vip_with_cup_balance):
        # CUP → BRL has no seeded rate in either direction
        r = requests.post(
            f"{BASE_URL}/api/vip/convert",
            headers=_h(VIP_TOKEN),
            json={"from_code": "CUP", "to_code": "BRL",
                  "amount_from": 100.0},
        )
        assert r.status_code == 400
        assert "tasa" in r.text.lower()

    def test_employee_role_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/vip/convert",
            headers=_h(EMPLOYEE_TOKEN),
            json={"from_code": "CUP", "to_code": "USDT",
                  "amount_from": 100.0},
        )
        assert r.status_code == 403

    def test_unauth_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/vip/convert",
            json={"from_code": "CUP", "to_code": "USDT",
                  "amount_from": 100.0},
        )
        assert r.status_code in (401, 403)

    def test_validation_amount_must_be_positive(self, vip_with_cup_balance):
        r = requests.post(
            f"{BASE_URL}/api/vip/convert",
            headers=_h(VIP_TOKEN),
            json={"from_code": "CUP", "to_code": "USDT", "amount_from": 0},
        )
        assert r.status_code == 422  # Pydantic gt=0 rejection
        r2 = requests.post(
            f"{BASE_URL}/api/vip/convert",
            headers=_h(VIP_TOKEN),
            json={"from_code": "CUP", "to_code": "USDT",
                  "amount_from": -5.0},
        )
        assert r2.status_code == 422

    def test_audit_log_entry_is_written(self, vip_with_cup_balance):
        db = MongoClient(MONGO_URL)[DB_NAME]
        before = db.audit_log.count_documents({"action": "vip.convert"})
        r = requests.post(
            f"{BASE_URL}/api/vip/convert",
            headers=_h(VIP_TOKEN),
            json={"from_code": "CUP", "to_code": "USDT",
                  "amount_from": 500.0},
        )
        assert r.status_code == 200, r.text
        after = db.audit_log.count_documents({"action": "vip.convert"})
        assert after == before + 1
        latest = db.audit_log.find_one(
            {"action": "vip.convert"}, sort=[("created_at", -1)]
        )
        assert latest["actor_id"] == vip_with_cup_balance
        assert latest["details"]["from_code"] == "CUP"
        assert latest["details"]["to_code"] == "USDT"
        assert latest["details"]["amount_from"] == 500.0
