"""iter52 — Balance ledger endpoints.

Tests:
  - GET /api/vip/balance-ledger      (self-service for the calling user)
  - GET /api/admin/users/{uid}/balance-ledger (admin/staff drill-down)
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _iso(dt=None):
    return (dt or datetime.now(timezone.utc)).isoformat()


@pytest.fixture
def user_with_ledger():
    """Plant a normal user with 3 credited accumulate orders + 1 NON-credited
    (no `accumulated_at`) which the endpoint must IGNORE."""
    db = MongoClient(MONGO_URL)[DB_NAME]
    uid = f"test_ldgr_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": uid, "email": f"{uid}@x.com", "name": "Ledger Test",
        "role": "normal", "phone_verified": True, "account_status": "active",
    })
    base_order = {
        "user_id": uid, "user_email": f"{uid}@x.com", "user_name": "x",
        "user_role": "normal", "from_code": "USD", "delivery_method": "accumulate",
        "delivery_details": "n/a", "sender_name": "x", "proof_image": "",
    }
    orders = []
    # 2 CUPT credited
    for amt in [400000.0, 600000.0]:
        oid = f"test_ldgr_order_{uuid.uuid4().hex[:8]}"
        orders.append(oid)
        db.orders.insert_one({
            **base_order, "id": oid, "to_code": "CUPT",
            "amount_from": 100.0, "amount_to": amt,
            "rate_applied": amt / 100, "commission_percent": 0,
            "status": "completed",
            "accumulated_at": _iso(), "created_at": _iso(),
        })
    # 1 USDT credited
    oid_usdt = f"test_ldgr_order_{uuid.uuid4().hex[:8]}"
    orders.append(oid_usdt)
    db.orders.insert_one({
        **base_order, "id": oid_usdt, "to_code": "USDT",
        "amount_from": 100.0, "amount_to": 100.0,
        "rate_applied": 1.0, "commission_percent": 0,
        "status": "approved",
        "accumulated_at": _iso(), "created_at": _iso(),
    })
    # 1 CUPT NOT credited (no accumulated_at) — MUST be excluded
    oid_uncredited = f"test_ldgr_order_{uuid.uuid4().hex[:8]}"
    orders.append(oid_uncredited)
    db.orders.insert_one({
        **base_order, "id": oid_uncredited, "to_code": "CUPT",
        "amount_from": 999.0, "amount_to": 999999.0,
        "rate_applied": 1.0, "commission_percent": 0,
        "status": "completed",
        # no accumulated_at — pre-iter51 ghost order
        "created_at": _iso(),
    })
    # 1 non-accumulate order — also excluded
    oid_transfer = f"test_ldgr_order_{uuid.uuid4().hex[:8]}"
    orders.append(oid_transfer)
    db.orders.insert_one({
        **base_order, "id": oid_transfer, "to_code": "CUP",
        "delivery_method": "transfer",
        "amount_from": 100.0, "amount_to": 50000.0,
        "rate_applied": 500.0, "commission_percent": 0,
        "status": "completed", "accumulated_at": _iso(),
        "created_at": _iso(),
    })
    yield {"uid": uid, "orders": orders, "expected_total_orders": 3}
    db.users.delete_one({"user_id": uid})
    db.orders.delete_many({"id": {"$in": orders}})


class TestVipBalanceLedger:
    def test_self_endpoint_returns_grouped_by_currency(self, user_with_ledger):
        # Patch the NORMAL test user with synthetic orders by overriding user_id
        # we'll instead query as ADMIN_TOKEN since admin endpoint accepts any user_id.
        pass  # see admin variant

    def test_admin_endpoint_groups_by_currency(self, user_with_ledger):
        uid = user_with_ledger["uid"]
        r = requests.get(
            f"{BASE_URL}/api/admin/users/{uid}/balance-ledger",
            headers=_h(ADMIN_TOKEN),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "by_currency" in body
        assert body["total_orders"] == user_with_ledger["expected_total_orders"]
        # CUPT bucket has 2 orders summing to 1,000,000
        assert "CUPT" in body["by_currency"]
        cupt = body["by_currency"]["CUPT"]
        assert cupt["total"] == 1000000.0
        assert len(cupt["orders"]) == 2
        # USDT bucket has 1 order
        assert "USDT" in body["by_currency"]
        usdt = body["by_currency"]["USDT"]
        assert usdt["total"] == 100.0
        assert len(usdt["orders"]) == 1

    def test_admin_endpoint_excludes_uncredited_orders(self, user_with_ledger):
        """The pre-iter51 order without `accumulated_at` MUST NOT appear in
        the ledger — that 999999 CUPT amount would otherwise leak."""
        uid = user_with_ledger["uid"]
        r = requests.get(
            f"{BASE_URL}/api/admin/users/{uid}/balance-ledger",
            headers=_h(ADMIN_TOKEN),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # The 999999 CUPT amount must not be in the CUPT total
        assert body["by_currency"]["CUPT"]["total"] == 1000000.0

    def test_admin_endpoint_excludes_non_accumulate_orders(self, user_with_ledger):
        """A transfer-method order — even if credited via some other path —
        is not part of the accumulate ledger."""
        uid = user_with_ledger["uid"]
        r = requests.get(
            f"{BASE_URL}/api/admin/users/{uid}/balance-ledger",
            headers=_h(ADMIN_TOKEN),
        )
        body = r.json()
        assert "CUP" not in body["by_currency"], (
            "Non-accumulate (transfer) order leaked into ledger"
        )

    def test_admin_endpoint_requires_staff(self, user_with_ledger):
        uid = user_with_ledger["uid"]
        r = requests.get(
            f"{BASE_URL}/api/admin/users/{uid}/balance-ledger",
            headers=_h(NORMAL_TOKEN),
        )
        assert r.status_code in (401, 403)

    def test_self_endpoint_authenticated_returns_own_ledger(self):
        """Direct test for /api/vip/balance-ledger using NORMAL_TOKEN.
        We plant orders specifically owned by `user_test_normal01`."""
        db = MongoClient(MONGO_URL)[DB_NAME]
        uid = "user_test_normal01"
        oids = []
        for amt in [42.0, 58.0]:
            oid = f"test_self_ldgr_{uuid.uuid4().hex[:8]}"
            oids.append(oid)
            db.orders.insert_one({
                "id": oid, "user_id": uid, "user_email": "x@x.com",
                "user_name": "x", "user_role": "normal",
                "from_code": "USD", "to_code": "USDT",
                "amount_from": 100.0, "amount_to": amt,
                "rate_applied": amt / 100, "commission_percent": 0,
                "delivery_method": "accumulate", "delivery_details": "n/a",
                "sender_name": "x", "proof_image": "",
                "status": "completed", "accumulated_at": _iso(),
                "created_at": _iso(),
            })
        try:
            r = requests.get(
                f"{BASE_URL}/api/vip/balance-ledger", headers=_h(NORMAL_TOKEN),
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert "USDT" in body["by_currency"], body
            # Total includes at least our 100 (42 + 58); other tests may have
            # left residue but the floor must hold.
            assert body["by_currency"]["USDT"]["total"] >= 100.0
            visible_ids = {o["id"] for o in body["by_currency"]["USDT"]["orders"]}
            assert set(oids).issubset(visible_ids)
        finally:
            db.orders.delete_many({"id": {"$in": oids}})

    def test_self_endpoint_employee_rejected(self):
        r = requests.get(
            f"{BASE_URL}/api/vip/balance-ledger", headers=_h(EMPLOYEE_TOKEN),
        )
        assert r.status_code == 403

    def test_self_endpoint_unauth_rejected(self):
        r = requests.get(f"{BASE_URL}/api/vip/balance-ledger")
        assert r.status_code in (401, 403)
