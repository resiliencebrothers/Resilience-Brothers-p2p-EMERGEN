"""iter48 — POST /api/vip/convert: instant self-conversion between own VIP
balances. No physical delivery, no admin approval — atomically reshuffles
funds within the SAME user."""
import os

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

    def test_usdt_to_cup_direct_rate_used(self):
        """iter49 — Reverse direction (USDT→CUP) uses the DIRECT seeded rate."""
        db = MongoClient(MONGO_URL)[DB_NAME]
        uid = "user_test_vip01"
        db.users.update_one(
            {"user_id": uid},
            {"$set": {"vip_balances.USDT": 100.0, "vip_balances.CUP": 0.0}},
        )
        try:
            r = requests.post(
                f"{BASE_URL}/api/vip/convert",
                headers=_h(VIP_TOKEN),
                json={"from_code": "USDT", "to_code": "CUP",
                      "amount_from": 1.0},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            # USDT→CUP rate_vip=395 → 1 USDT = 395 CUP gross.
            # iter55.36i — universal 0.01 USDT fee converted at rate_normal
            # (USDT→CUP=380) = 3.80 CUP. Net = 395 - 3.80 = 391.20 CUP.
            assert body["rate"] == 395.0
            assert body["usdt_fee"] == 0.01
            assert body["amount_to"] == 391.20
        finally:
            db.users.update_one(
                {"user_id": uid},
                {"$unset": {"vip_balances.USDT": "",
                            "vip_balances.CUP": ""}},
            )

    def test_usd_to_cup_via_inverse_rate(self):
        """iter49 — USD→CUP has no direct rate; uses inverse USDT path?
        Actually USDT→USD and USD→CUP both exist; we test the path where
        the user converts between two non-USDT currencies that have direct
        rates. USD→CUP IS direct (rate_normal=380, rate_vip=395)."""
        db = MongoClient(MONGO_URL)[DB_NAME]
        uid = "user_test_vip01"
        db.users.update_one(
            {"user_id": uid},
            {"$set": {"vip_balances.USD": 10.0, "vip_balances.CUP": 0.0}},
        )
        try:
            r = requests.post(
                f"{BASE_URL}/api/vip/convert",
                headers=_h(VIP_TOKEN),
                json={"from_code": "USD", "to_code": "CUP",
                      "amount_from": 10.0},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["rate"] == 395.0  # vip rate for the conversion
            # iter55.36i — fee 0.01 USDT · rate_normal(USDT→CUP)=380 = 3.80 CUP.
            # Net = 3950 - 3.80 = 3946.20 CUP.
            assert body["amount_to"] == 3946.20
        finally:
            db.users.update_one(
                {"user_id": uid},
                {"$unset": {"vip_balances.USD": "",
                            "vip_balances.CUP": ""}},
            )

    def test_normal_role_can_convert_uses_rate_normal(self):
        """iter50 — normal users (non-VIP) are also allowed to convert and
        the backend uses `rate_normal` instead of `rate_vip`."""
        db = MongoClient(MONGO_URL)[DB_NAME]
        uid = "user_test_normal01"
        db.users.update_one(
            {"user_id": uid},
            {"$set": {"vip_balances.USDT": 10.0, "vip_balances.CUP": 0.0}},
        )
        try:
            r = requests.post(
                f"{BASE_URL}/api/vip/convert",
                headers=_h(NORMAL_TOKEN),
                json={"from_code": "USDT", "to_code": "CUP",
                      "amount_from": 1.0},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            # rate_normal=380 (vs rate_vip=395) — normals get the worse rate.
            # iter55.36i — 0.01 USDT fee · rate_normal(USDT→CUP)=380 = 3.80 CUP.
            # Net = 380 - 3.80 = 376.20 CUP.
            assert body["rate"] == 380.0
            assert body["amount_to"] == 376.20
        finally:
            db.users.update_one(
                {"user_id": uid},
                {"$unset": {"vip_balances.USDT": "",
                            "vip_balances.CUP": ""}},
            )
