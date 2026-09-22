"""Seed / cleanup helpers for iter289 Fase A frontend testing."""
import os, sys, asyncio
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

def now_iso():
    return datetime.now(timezone.utc).isoformat()

async def db():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return c[os.environ["DB_NAME"]]

def make_delivery(suffix, pin, status="arrived", courier="user_test_vip01",
                  user="user_test_vip01"):
    did = f"ta289_{suffix}"
    ref = f"ta289_ref_{suffix}"
    return {
        "id": did,
        "ref_id": ref,
        "kind": "redemption",
        "user_id": user,
        "client_name": f"Cliente Test {suffix}",
        "address": "Calle Falsa 123, La Habana, +53 5555 1234",
        "province": "La Habana",
        "amount_label": "50 USDT",
        "km": 3.2,
        "fee_usdt": 5.0,
        "courier_share_usdt": 4.0,
        "platform_share_usdt": 1.0,
        "share_pct_snapshot": 80,
        "status": status,
        "courier_id": courier,
        "courier_name": "VIP Test",
        "assigned_to_courier_id": None,
        "delivery_pin": pin,
        "pin_verified": False,
        "delivery_latitude": None,
        "delivery_longitude": None,
        "payout_credited": False,
        "timeline": [
            {"status": "accepted", "at": now_iso()},
            {"status": "on_the_way", "at": now_iso()},
            {"status": "arrived", "at": now_iso()},
        ],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "active_key": f"redemption:{ref}",
    }

async def cleanup():
    d = await db()
    r1 = await d.deliveries.delete_many({"id": {"$regex": "^ta289_"}})
    r2 = await d.deliveries.delete_many({"ref_id": {"$regex": "^ta289_"}})
    r3 = await d.courier_cash_events.delete_many({"note": {"$regex": "^ta289_"}})
    print(f"CLEANUP deliveries: {r1.deleted_count + r2.deleted_count}, cash events: {r3.deleted_count}")

async def seed():
    d = await db()
    await cleanup()
    docs = [
        make_delivery("pin_ok", "4477"),
        make_delivery("pin_exc", "8811"),
        make_delivery("inc", "9911", status="on_the_way"),
    ]
    await d.deliveries.insert_many(docs)
    print(f"SEEDED {len(docs)} deliveries: ta289_pin_ok, ta289_pin_exc, ta289_inc")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "seed"
    asyncio.run(cleanup() if cmd == "cleanup" else seed())
