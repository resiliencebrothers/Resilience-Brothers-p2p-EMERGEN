"""iter51 — accumulate side-effect must fire on FIRST money-settled status
(approved OR completed), and must be idempotent via `accumulated_at`.

Reproduces a production bug reported Feb 28, 2026 where an order taken from
`pending` → `completed` directly (admin clicked "Completar" without first
clicking "Confirmar") was never credited to `vip_balances` because the old
logic only ran on `new_status == "approved"`."""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, make_admin_totp


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture
def fresh_normal_user():
    """Plant a fresh normal user with no balance. Return user_id."""
    db = MongoClient(MONGO_URL)[DB_NAME]
    uid = f"test_acc_user_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": uid, "email": f"{uid}@x.com", "name": "Acc Test",
        "role": "normal", "phone": f"+1444{uuid.uuid4().hex[:7]}",
        "phone_verified": True, "account_status": "active",
        "vip_balance_usd": 0.0, "vip_balances": {},
    })
    yield uid
    db.users.delete_one({"user_id": uid})
    db.orders.delete_many({"user_id": uid})


def _plant_pending_accumulate_order(user_id: str, *, to_code="CUPT", amount_to=1000.0):
    """Insert a pending accumulate order directly. Returns order id."""
    db = MongoClient(MONGO_URL)[DB_NAME]
    oid = f"test_acc_order_{uuid.uuid4().hex[:8]}"
    db.orders.insert_one({
        "id": oid, "user_id": user_id,
        "user_email": "x@x.com", "user_name": "x", "user_role": "normal",
        "from_code": "USD", "to_code": to_code,
        "amount_from": 100.0, "amount_to": amount_to,
        "rate_applied": amount_to / 100.0, "commission_percent": 0.0,
        "delivery_method": "accumulate",
        "delivery_details": "n/a", "sender_name": "x", "proof_image": "",
        "status": "pending", "created_at": "2026-02-28T00:00:00Z",
    })
    return oid


def _admin_update_status(order_id: str, new_status: str):
    """Helper — admin PUT /api/admin/orders/{id}/status."""
    return requests.put(
        f"{BASE_URL}/api/admin/orders/{order_id}/status",
        headers=_h(ADMIN_TOKEN),
        json={"status": new_status, "admin_note": "test",
              "totp_code": make_admin_totp()},
    )


class TestAccumulateOnAnyMoneySettled:
    def _balance(self, user_id, code="CUPT"):
        db = MongoClient(MONGO_URL)[DB_NAME]
        u = db.users.find_one({"user_id": user_id}, {"_id": 0, "vip_balances": 1})
        return float((u.get("vip_balances") or {}).get(code) or 0.0)

    def test_pending_to_completed_directly_credits_balance(self, fresh_normal_user):
        """The reported production bug: admin clicks 'Completar' directly,
        skipping 'approved'. Balance MUST still be credited."""
        oid = _plant_pending_accumulate_order(fresh_normal_user, amount_to=750000.0)
        assert self._balance(fresh_normal_user) == 0.0
        r = _admin_update_status(oid, "completed")
        assert r.status_code == 200, r.text
        assert self._balance(fresh_normal_user) == 750000.0

    def test_pending_to_approved_to_completed_credits_once(self, fresh_normal_user):
        """Normal flow: approve THEN complete. The second transition (approved→
        completed) must NOT double-credit thanks to `accumulated_at` idempotency."""
        oid = _plant_pending_accumulate_order(fresh_normal_user, amount_to=500.0)
        r1 = _admin_update_status(oid, "approved")
        assert r1.status_code == 200, r1.text
        assert self._balance(fresh_normal_user) == 500.0
        r2 = _admin_update_status(oid, "completed")
        assert r2.status_code == 200, r2.text
        # Still 500 — not 1000
        assert self._balance(fresh_normal_user) == 500.0

    def test_two_accumulate_orders_with_mixed_paths_both_credit(self, fresh_normal_user):
        """Regression for the actual user case: two CUPT accumulate orders
        approved through different paths (one direct to completed, one via
        approved) — both must contribute to the balance."""
        o1 = _plant_pending_accumulate_order(fresh_normal_user, amount_to=400000.0)
        o2 = _plant_pending_accumulate_order(fresh_normal_user, amount_to=600000.0)
        # o1: pending → completed directly
        r1 = _admin_update_status(o1, "completed")
        assert r1.status_code == 200, r1.text
        # o2: pending → approved
        r2 = _admin_update_status(o2, "approved")
        assert r2.status_code == 200, r2.text
        assert self._balance(fresh_normal_user) == 1000000.0  # 400k + 600k

    def test_accumulated_at_flag_persists_on_order(self, fresh_normal_user):
        oid = _plant_pending_accumulate_order(fresh_normal_user, amount_to=10.0)
        _admin_update_status(oid, "completed")
        db = MongoClient(MONGO_URL)[DB_NAME]
        o = db.orders.find_one({"id": oid}, {"_id": 0})
        assert "accumulated_at" in o, (
            "Order missing `accumulated_at` after credit — idempotency broken"
        )

    def test_rejected_path_does_not_credit(self, fresh_normal_user):
        oid = _plant_pending_accumulate_order(fresh_normal_user, amount_to=10.0)
        r = _admin_update_status(oid, "rejected")
        assert r.status_code == 200, r.text
        assert self._balance(fresh_normal_user) == 0.0

    def test_calling_accumulate_helper_twice_credits_once(self, fresh_normal_user):
        """Direct unit-style check: two consecutive calls to the helper on the
        same order must credit only once thanks to `accumulated_at` guard."""
        import asyncio
        from services.balances import accumulate_vip_balance
        oid = _plant_pending_accumulate_order(fresh_normal_user, amount_to=42.0)
        db = MongoClient(MONGO_URL)[DB_NAME]
        order = db.orders.find_one({"id": oid}, {"_id": 0})
        # First call credits
        applied_1 = asyncio.get_event_loop().run_until_complete(
            accumulate_vip_balance(order)
        ) if False else None
        # Use a fresh event loop because motor's client binds to a loop
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            applied_1 = loop.run_until_complete(accumulate_vip_balance(order))
            applied_2 = loop.run_until_complete(accumulate_vip_balance(order))
        finally:
            loop.close()
            asyncio.set_event_loop(asyncio.new_event_loop())
        assert applied_1 is True
        assert applied_2 is False
        assert self._balance(fresh_normal_user) == 42.0
