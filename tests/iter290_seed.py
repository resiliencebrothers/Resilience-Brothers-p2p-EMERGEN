"""Seed / cleanup for iter290 Fase B frontend testing (FE-only).

Sembramos:
 - Cola disponibles: 3 deliveries libres (old 180min, mid 60min, new 5min)
   + 1 reservada al VIP (2 min). Kind variado, provincias mixtas.
 - Banner atención: 1 reservada a otro courier 45min + 1 on_the_way 120min.
 - Sync/retry: 1 delivery kind=withdrawal confirmed con settlement_pending y
   1 withdrawal id=<wid> status=approved cash USD 500.
 - Además una entrega mía 'accepted' para probar GPS + carga activa.
"""
import os
import sys
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient

PREFIX = "tb290_"
VIP_UID = "user_test_vip01"
OTHER = "tb290_other"


def iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


async def db():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return c[os.environ["DB_NAME"]]


def mk_del(did, kind="redemption", ref_id=None, status="available",
           courier_id=None, assigned_to=None, minutes_ago=0, province="La Habana",
           extra=None, user_id="tb290_client"):
    rid = ref_id or f"{PREFIX}ref_{did}"
    at = iso(minutes_ago)
    doc = {
        "id": did,
        "kind": kind,
        "ref_id": rid,
        "active_key": f"{kind}:{rid}",
        "user_id": user_id,
        "user_name": "Cliente TB290",
        "user_email": "client@tb290.test",
        "client_name": "Cliente TB290",
        "address": "Calle Falsa 123, La Habana, +53 5555 1234",
        "province": province,
        "amount_label": "50 USDT",
        "delivery_latitude": None,
        "delivery_longitude": None,
        "km": 5.0,
        "fee_usdt": 10.0,
        "share_pct_snapshot": 80.0,
        "courier_share_usdt": 8.0,
        "platform_share_usdt": 2.0,
        "status": status,
        "courier_id": courier_id,
        "courier_name": "TB290 courier" if courier_id else None,
        "assigned_to_courier_id": assigned_to,
        "delivery_pin": "1234",
        "pin_verified": False,
        "payout_credited": False,
        "payout_credited_at": None,
        "timeline": [],
        "created_at": at,
        "updated_at": at,
    }
    if extra:
        doc.update(extra)
    return doc


async def cleanup():
    d = await db()
    r1 = await d.deliveries.delete_many({"$or": [
        {"id": {"$regex": f"^{PREFIX}"}},
        {"ref_id": {"$regex": f"^{PREFIX}"}}]})
    r2 = await d.withdrawals.delete_many({"id": {"$regex": f"^{PREFIX}"}})
    r3 = await d.deposits.delete_many({"id": {"$regex": f"^{PREFIX}"}})
    r4 = await d.redemptions.delete_many({"id": {"$regex": f"^{PREFIX}"}})
    print(f"CLEANUP deliveries={r1.deleted_count} withdrawals={r2.deleted_count} "
          f"deposits={r3.deleted_count} redemptions={r4.deleted_count}")


async def seed():
    d = await db()
    await cleanup()

    # -- #4 cola: 3 libres con edades escalonadas + 1 reservada para VIP
    old_d = mk_del(f"{PREFIX}old", kind="redemption", minutes_ago=180,
                   province="La Habana")
    mid_d = mk_del(f"{PREFIX}mid", kind="deposit", minutes_ago=60,
                   province="La Habana")
    new_d = mk_del(f"{PREFIX}new", kind="redemption", minutes_ago=5,
                   province="Artemisa")
    res_d = mk_del(f"{PREFIX}reserved", kind="redemption", minutes_ago=2,
                   province="La Habana", assigned_to=VIP_UID)

    # -- #4 banner atención (admin): reservada otro courier 45 min + stalled 120 min
    stale_res = mk_del(f"{PREFIX}stalares", kind="redemption", minutes_ago=45,
                       assigned_to=OTHER)
    stalled = mk_del(f"{PREFIX}stalled", kind="redemption", status="on_the_way",
                     courier_id=OTHER, minutes_ago=120)

    # -- #5 carga activa VIP + GPS: entrega accepted del VIP
    mine_active = mk_del(f"{PREFIX}mineact", kind="redemption",
                         status="accepted", courier_id=VIP_UID, minutes_ago=15)

    # -- #6 retry-sync: withdrawal + delivery
    wid = f"{PREFIX}w_{uuid.uuid4().hex[:6]}"
    await d.withdrawals.insert_one({
        "id": wid,
        "user_id": "tb290_client",
        "user_name": "Cliente TB290",
        "user_email": "client@tb290.test",
        "status": "approved",
        "method": "cash",
        "currency": "USD",
        "amount_usd": 500,
        "amount": 500,
        "details": "TB290 test",
        "created_at": iso(20),
    })
    settle_del = mk_del(
        f"{PREFIX}settle", kind="withdrawal", ref_id=wid, status="confirmed",
        courier_id=OTHER, minutes_ago=30,
        extra={
            "payout_credited": True,
            "payout_credited_at": iso(10),
            "courier_share_paid_usdt": 8.0,
            "courier_share_paid_at": iso(10),
            "settlement_pending": {
                "kind": "withdrawal", "ref_id": wid, "at": iso(10)},
        })

    docs = [old_d, mid_d, new_d, res_d, stale_res, stalled, mine_active,
            settle_del]
    await d.deliveries.insert_many(docs)
    print(f"SEEDED deliveries={len(docs)} wid={wid}")
    print(f"IDS: old={old_d['id']} mid={mid_d['id']} new={new_d['id']} "
          f"reserved={res_d['id']} stalares={stale_res['id']} "
          f"stalled={stalled['id']} mineact={mine_active['id']} "
          f"settle={settle_del['id']}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "seed"
    asyncio.run(cleanup() if cmd == "cleanup" else seed())
