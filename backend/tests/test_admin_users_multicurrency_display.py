"""iter47 — Multi-currency display fixes for legacy VIP balance widgets.

Tests:
  1. GET /api/admin/users enriches each non-staff user doc with a
     server-side `vip_balance_usdt` (USDT-equivalent of legacy USD +
     vip_balances dict, summed via valuation rate).
  2. Staff users (admin/employee) do NOT get the enrichment field.
  3. Users with only legacy `vip_balance_usd` get the field populated.
  4. Users with only the `vip_balances` dict get the field populated.
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture
def planted_users():
    db = MongoClient(MONGO_URL)[DB_NAME]
    ids = []

    def add(**fields):
        uid = f"test_mc_{uuid.uuid4().hex[:8]}"
        ids.append(uid)
        db.users.insert_one({
            "user_id": uid, "email": f"{uid}@x.com", "name": f"MC {uid[:4]}",
            "role": "vip", "phone_verified": True,
            "account_status": "active",
            **fields,
        })
        return uid

    only_legacy = add(vip_balance_usd=500.0)
    only_dict = add(vip_balances={"CUP": 38000.0})
    both = add(vip_balance_usd=100.0, vip_balances={"USDT": 50.0})
    zero = add(vip_balance_usd=0.0)
    employee = add(role="employee", vip_balance_usd=999.0)  # should NOT be enriched

    yield {
        "only_legacy": only_legacy,
        "only_dict": only_dict,
        "both": both,
        "zero": zero,
        "employee": employee,
    }
    db.users.delete_many({"user_id": {"$in": ids}})


class TestAdminUsersMultiCurrencyEnrichment:
    def _find(self, docs, uid):
        return next((d for d in docs if d.get("user_id") == uid), None)

    def test_legacy_usd_user_gets_usdt_field(self, planted_users):
        # 500 USD → 500 / 0.98 ≈ 510.20 USDT (USDT→USD rate is 0.98 in seed)
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers=_h(ADMIN_TOKEN), params={"limit": 1000})
        assert r.status_code == 200
        d = self._find(r.json(), planted_users["only_legacy"])
        assert d is not None
        assert "vip_balance_usdt" in d
        assert 500.0 <= d["vip_balance_usdt"] <= 520.0, (
            f"got {d['vip_balance_usdt']}"
        )

    def test_dict_only_user_gets_usdt_field(self, planted_users):
        # 38000 CUP → 38000 / 380 = 100 USDT (using USDT→CUP=380)
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers=_h(ADMIN_TOKEN), params={"limit": 1000})
        d = self._find(r.json(), planted_users["only_dict"])
        assert d is not None
        # tolerant band: 99.5 - 100.6 (CUP→USDT rate varies in test seed)
        assert 99.0 <= d["vip_balance_usdt"] <= 101.0, (
            f"got {d['vip_balance_usdt']}"
        )

    def test_both_sources_sum_correctly(self, planted_users):
        # 100 USD (≈ 100/0.98 ≈ 102.04 USDT) + 50 USDT = ≈ 152
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers=_h(ADMIN_TOKEN), params={"limit": 1000})
        d = self._find(r.json(), planted_users["both"])
        assert d is not None
        assert 150.0 <= d["vip_balance_usdt"] <= 155.0, (
            f"got {d['vip_balance_usdt']}"
        )

    def test_zero_balance_user_gets_zero_field(self, planted_users):
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers=_h(ADMIN_TOKEN), params={"limit": 1000})
        d = self._find(r.json(), planted_users["zero"])
        assert d is not None
        assert d.get("vip_balance_usdt") == 0.0

    def test_employee_does_not_get_field(self, planted_users):
        """Staff users are NOT enriched — vip_balance_usd for them is a
        legacy artifact that should never be displayed as user-owed balance."""
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers=_h(ADMIN_TOKEN), params={"limit": 1000})
        d = self._find(r.json(), planted_users["employee"])
        assert d is not None
        assert "vip_balance_usdt" not in d, (
            "employee should NOT have vip_balance_usdt enrichment"
        )
