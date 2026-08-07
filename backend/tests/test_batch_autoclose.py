"""Daily VIP batch auto-close (scheduler.run_daily_batch_autoclose).

Coverage:
 1. Open batch WITH items → closed + auto_closed=True + closed_at set.
 2. Open batch WITHOUT items → deleted (no blank history entries).
 3. Already-closed batches are untouched (no auto_closed flag).
 4. Second run is a no-op for the already auto-closed batch.
"""
import pytest

from db_client import db
from scheduler import run_daily_batch_autoclose

pytestmark = pytest.mark.asyncio

NOTE = "autoclose_test"


def _batch(bid: str, status: str = "open") -> dict:
    return {
        "id": bid, "vip_user_id": "user_test_vip01", "status": status,
        "direction": "pair", "from_code": "USDT", "to_code": "CUP",
        "currency": "USDT", "note": NOTE,
        "created_at": "2026-06-01T12:00:00+00:00",
        "closed_at": None, "updated_at": "2026-06-01T12:00:00+00:00",
    }


async def _cleanup():
    await db.vip_batches.delete_many({"note": NOTE})
    await db.vip_batch_items.delete_many({"batch_id": {"$in": ["test_ac_a", "test_ac_b", "test_ac_c"]}})


async def test_daily_autoclose():
    await _cleanup()
    await db.vip_batches.insert_many([
        _batch("test_ac_a"),                     # open + 1 item  → close
        _batch("test_ac_b"),                     # open + 0 items → delete
        _batch("test_ac_c", status="closed"),    # closed         → untouched
    ])
    await db.vip_batch_items.insert_one({
        "id": "test_ac_item", "batch_id": "test_ac_a",
        "vip_user_id": "user_test_vip01", "holder_name": "9212 9598 7274 4356",
        "card_number": "9212 9598 7274 4356", "amount": 10, "status": "pending",
        "created_at": "2026-06-01T13:00:00+00:00",
    })

    res = await run_daily_batch_autoclose(db)
    assert res["closed"] >= 1
    assert res["deleted_empty"] >= 1

    a = await db.vip_batches.find_one({"id": "test_ac_a"}, {"_id": 0})
    assert a["status"] == "closed"
    assert a.get("auto_closed") is True
    assert a.get("closed_at")

    assert await db.vip_batches.find_one({"id": "test_ac_b"}) is None

    c = await db.vip_batches.find_one({"id": "test_ac_c"}, {"_id": 0})
    assert c["status"] == "closed"
    assert not c.get("auto_closed")

    # Second run: already-closed batch A must keep its original closed_at.
    first_closed_at = a["closed_at"]
    await run_daily_batch_autoclose(db)
    a2 = await db.vip_batches.find_one({"id": "test_ac_a"}, {"_id": 0})
    assert a2["closed_at"] == first_closed_at

    await _cleanup()
