"""iter69 — Company funds: split client withdrawals by user role.

Regression report: an admin viewed `/admin/company-funds` after a NORMAL
client withdrew from their accumulated balance. The frontend labeled the
outflow as "Retiros VIP" — misleading, because the collection
`db.withdrawals` stores BOTH VIP and normal-client withdrawals.

Fix: `_compute_company_funds` now returns `outflow_clients_vip` and
`outflow_clients_normal` as separate fields (plus a legacy combined
`outflow_clients` field so old consumers don't break). The frontend
renders the two lines separately.

These tests exercise the aggregation using seeded VIP + normal users and
paid withdrawals against them.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from routes.admin_company_funds import _compute_company_funds


def _make_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.asyncio
async def test_normal_client_withdrawal_lands_in_outflow_clients_normal():
    """Seed one paid withdrawal from a NORMAL user in an isolated currency
    and verify it's counted under `outflow_clients_normal`, NOT under VIP."""
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    # Use a synthetic ISO currency code no other test touches.
    marker_ccy = "CUP69NRM"
    marker_uid = f"orphan_test_{uuid.uuid4().hex[:8]}"
    try:
        await db.users.insert_one({
            "user_id": marker_uid, "role": "normal", "email": "n@t.com",
            "name": "Norma", "created_at": _make_now(),
        })
        await db.withdrawals.insert_one({
            "id": uuid.uuid4().hex, "user_id": marker_uid,
            "currency": marker_ccy, "amount_usd": 69.80,
            "status": "paid", "created_at": _make_now(),
        })
        rows = await _compute_company_funds([marker_ccy])
        assert len(rows) == 1, f"Expected 1 currency row, got {rows}"
        r = rows[0]
        assert r["currency"] == marker_ccy
        assert r["outflow_clients_normal"] == 69.80, (
            f"Normal-user withdrawal must land in outflow_clients_normal, "
            f"got {r['outflow_clients_normal']}. Full row: {r}"
        )
        assert r["outflow_clients_vip"] == 0.0, (
            f"Nothing should be in outflow_clients_vip. "
            f"Row: {r}"
        )
        # Legacy combined field still totals correctly.
        assert r["outflow_clients"] == 69.80
    finally:
        await db.users.delete_one({"user_id": marker_uid})
        await db.withdrawals.delete_many({"user_id": marker_uid})
        client.close()


@pytest.mark.asyncio
async def test_vip_and_normal_withdrawals_split_correctly():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    marker_ccy = "CUP69MIX"
    vip_uid = f"orphan_test_vip_{uuid.uuid4().hex[:8]}"
    normal_uid = f"orphan_test_norm_{uuid.uuid4().hex[:8]}"
    try:
        await db.users.insert_many([
            {"user_id": vip_uid, "role": "vip", "email": "v@t.com",
             "name": "VipUser", "created_at": _make_now()},
            {"user_id": normal_uid, "role": "normal", "email": "n@t.com",
             "name": "NormalUser", "created_at": _make_now()},
        ])
        await db.withdrawals.insert_many([
            {"id": uuid.uuid4().hex, "user_id": vip_uid,
             "currency": marker_ccy, "amount_usd": 500.0,
             "status": "paid", "created_at": _make_now()},
            {"id": uuid.uuid4().hex, "user_id": normal_uid,
             "currency": marker_ccy, "amount_usd": 30.0,
             "status": "paid", "created_at": _make_now()},
            # An unpaid one shouldn't count either bucket.
            {"id": uuid.uuid4().hex, "user_id": normal_uid,
             "currency": marker_ccy, "amount_usd": 999.0,
             "status": "pending", "created_at": _make_now()},
        ])
        rows = await _compute_company_funds([marker_ccy])
        r = rows[0]
        assert r["outflow_clients_vip"] == 500.0
        assert r["outflow_clients_normal"] == 30.0
        assert r["outflow_clients"] == 530.0  # legacy total
    finally:
        await db.users.delete_many({"user_id": {"$in": [vip_uid, normal_uid]}})
        await db.withdrawals.delete_many({"user_id": {"$in": [vip_uid, normal_uid]}})
        client.close()


@pytest.mark.asyncio
async def test_withdrawal_from_unknown_user_falls_into_normal_bucket():
    """Safest accounting default — if the user_id doesn't resolve (deleted
    account, data drift), the withdrawal is treated as a normal-client
    outflow rather than being lost or miscounted as VIP."""
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    marker_ccy = "CUP69GHOST"
    try:
        await db.withdrawals.insert_one({
            "id": uuid.uuid4().hex, "user_id": "ghost_never_existed",
            "currency": marker_ccy, "amount_usd": 42.0,
            "status": "paid", "created_at": _make_now(),
        })
        rows = await _compute_company_funds([marker_ccy])
        r = rows[0]
        assert r["outflow_clients_normal"] == 42.0
        assert r["outflow_clients_vip"] == 0.0
    finally:
        await db.withdrawals.delete_many({"currency": marker_ccy})
        client.close()
