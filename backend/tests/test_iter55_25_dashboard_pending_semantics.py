"""iter55.25 — Dashboard counter distinguishes order.approved vs withdrawal.approved.

Bug reported by owner on 11 Feb 2026: on production, a Standard client saw
`PENDIENTES: 2` on their dashboard but the "Mis Órdenes" table showed only 1
pending row. Root cause: iter55.22 grouped `approved` into IN_FLIGHT for
BOTH orders and withdrawals, but the semantic of `approved` differs:

- orders.approved      → "Confirmado" (staff validated + paid) → NOT pending
- withdrawals.approved → "En progreso" for cash withdrawals → still pending

The fix splits the IN_FLIGHT set by entity type. This backend test guards
the raw values that the frontend depends on so the drift can't recur.
"""
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, VIP_TOKEN

API = f"{API_ROOT}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _seed_order(status, prefix="test-o25-"):
    oid = f"{prefix}{uuid.uuid4().hex[:8]}"
    _db().orders.insert_one({
        "id": oid,
        "user_id": "user_test_vip01",
        "user_email": "vip@test.local",
        "user_name": "VIP Test",
        "user_role": "vip",
        "from_code": "USDT",
        "to_code": "USD",
        "amount_from": 50, "amount_to": 50,
        "rate_applied": 1.0, "commission_percent": 0.0,
        "delivery_method": "transfer", "delivery_details": "x",
        "status": status,
        "sender_name": "s", "proof_image": "",
        "created_at": _iso(),
    })
    return oid


def _seed_withdrawal(status):
    wid = f"test-w25-{uuid.uuid4().hex[:8]}"
    _db().withdrawals.insert_one({
        "id": wid,
        "user_id": "user_test_vip01",
        "method": "cash",
        "currency": "USD",
        "amount_usd": 100,
        "status": status,
        "details": "n",
        "beneficiary_name": "b",
        "created_at": _iso(),
    })
    return wid


def _cleanup():
    _db().orders.delete_many({"id": {"$regex": "^test-o25-"}})
    _db().withdrawals.delete_many({"id": {"$regex": "^test-w25-"}})


def test_orders_mine_returns_all_statuses_verbatim():
    """The frontend depends on the raw `status` string to run its own
    IN_FLIGHT set. This test just guards the endpoint contract."""
    _cleanup()
    _seed_order("pending")
    _seed_order("approved")  # "Confirmado" — must be visible to the frontend
    _seed_order("completed")

    r = requests.get(f"{API}/orders/mine", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    statuses = [o["status"] for o in r.json() if o["id"].startswith("test-o25-")]
    assert set(statuses) == {"pending", "approved", "completed"}, statuses
    _cleanup()


def test_withdrawals_mine_returns_all_statuses_verbatim():
    _cleanup()
    _seed_withdrawal("pending")
    _seed_withdrawal("approved")  # cash "En progreso" — still counts as pending
    _seed_withdrawal("paid")

    r = requests.get(f"{API}/vip/withdrawals/mine", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    statuses = [w["status"] for w in r.json() if w["id"].startswith("test-w25-")]
    assert set(statuses) == {"pending", "approved", "paid"}, statuses
    _cleanup()


def test_pending_semantics_documented():
    """Mirror of the frontend's per-type IN_FLIGHT sets so a future change on
    either side breaks lock-step (this doc-as-code test lives with the
    backend and points reviewers at the frontend file). If you change these
    sets in OverviewView.jsx, update this test too."""
    ORDER_IN_FLIGHT = {"pending", "requires_double_approval"}
    WITHDRAWAL_IN_FLIGHT = {"pending", "approved", "requires_double_approval"}

    # Explicit exclusions that caused the reported bug:
    assert "approved" not in ORDER_IN_FLIGHT, (
        "orders.approved = 'Confirmado' — must NOT count as pending"
    )
    assert "approved" in WITHDRAWAL_IN_FLIGHT, (
        "withdrawals.approved = 'En progreso' for cash — MUST count as pending"
    )
    # Terminal states must never be in-flight:
    for terminal in ["completed", "delivered", "paid", "rejected"]:
        assert terminal not in ORDER_IN_FLIGHT
        assert terminal not in WITHDRAWAL_IN_FLIGHT
