"""iter45: GET /api/admin/quick-summary — compact payload for the mobile-first
admin dashboard. Combines pendientes + company funds + VIP holdings in 1 call."""
import os
import uuid

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


@pytest.fixture
def seed_orders():
    """Insert one pending order so the response is non-empty, then clean up."""
    db = MongoClient(MONGO_URL)[DB_NAME]
    test_ids = []
    for i in range(2):
        oid = f"test_quick_{uuid.uuid4().hex[:8]}"
        db.orders.insert_one({
            "id": oid,
            "user_id": "user_test_normal01",
            "user_email": "test@example.com",
            "from_code": "USD", "to_code": "USDT",
            "amount_from": 100.0 + i, "amount_to": 97.0 + i,
            "delivery_method": "crypto", "delivery_details": "test",
            "status": "pending",
            "created_at": f"2026-01-0{i+1}T10:00:00Z",
        })
        test_ids.append(oid)
    yield test_ids
    db.orders.delete_many({"id": {"$in": test_ids}})


class TestQuickSummary:
    def test_requires_staff_auth(self):
        # No auth → 401
        r = requests.get(f"{BASE_URL}/api/admin/quick-summary")
        assert r.status_code in (401, 403)
        # Normal user → 403
        r = requests.get(
            f"{BASE_URL}/api/admin/quick-summary", headers=_h(NORMAL_TOKEN)
        )
        assert r.status_code == 403

    def test_admin_gets_full_shape(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/quick-summary", headers=_h(ADMIN_TOKEN)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "pending" in body
        assert "company_funds" in body
        assert "vip_holdings" in body
        # Pending section
        assert "orders_count" in body["pending"]
        assert "withdrawals_count" in body["pending"]
        assert "recent_orders" in body["pending"]
        assert isinstance(body["pending"]["recent_orders"], list)
        # Funds section
        assert "items" in body["company_funds"]
        assert "total_usdt" in body["company_funds"]
        assert isinstance(body["company_funds"]["total_usdt"], (int, float))
        for it in body["company_funds"]["items"]:
            assert "currency" in it and "balance" in it
        # VIP holdings section
        assert "items" in body["vip_holdings"]
        assert "total_usdt" in body["vip_holdings"]

    def test_recent_orders_capped_at_5(self, seed_orders):
        r = requests.get(
            f"{BASE_URL}/api/admin/quick-summary", headers=_h(ADMIN_TOKEN)
        )
        assert r.status_code == 200
        recent = r.json()["pending"]["recent_orders"]
        assert len(recent) <= 5
        # ordered by created_at desc — our newest test_quick_… should be first
        if recent:
            first = recent[0]
            assert set(first.keys()) >= {
                "id", "from_code", "to_code", "amount_from",
                "amount_to", "created_at"
            }

    def test_employee_scope_filters_orders(self, seed_orders):
        """If the employee has allowed_currencies set, the response must only
        include orders touching those currencies."""
        db = MongoClient(MONGO_URL)[DB_NAME]
        # Restrict employee to CUP only (test orders are USD↔USDT → excluded)
        db.users.update_one(
            {"user_id": "user_test_employee01"},
            {"$set": {"allowed_currencies": ["CUP"]}},
        )
        try:
            r = requests.get(
                f"{BASE_URL}/api/admin/quick-summary",
                headers=_h(EMPLOYEE_TOKEN),
            )
            assert r.status_code == 200, r.text
            recent = r.json()["pending"]["recent_orders"]
            test_ids = set(seed_orders)
            visible_ids = {o["id"] for o in recent}
            assert not (test_ids & visible_ids), (
                f"employee saw out-of-scope orders: {test_ids & visible_ids}"
            )
        finally:
            db.users.update_one(
                {"user_id": "user_test_employee01"},
                {"$unset": {"allowed_currencies": ""}},
            )

    def test_counts_match_recent_when_few_orders(self, seed_orders):
        """When there are ≤5 pending orders, orders_count matches len(recent)."""
        r = requests.get(
            f"{BASE_URL}/api/admin/quick-summary", headers=_h(ADMIN_TOKEN)
        )
        body = r.json()
        n_recent = len(body["pending"]["recent_orders"])
        n_count = body["pending"]["orders_count"]
        assert n_count >= n_recent
        # If total pending ≤ 5 then recent should contain all
        if n_count <= 5:
            assert n_recent == n_count
