import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

os.environ.setdefault("PYTHONPATH", "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from db_client import db  # noqa: E402
from routes.service_bookings import process_due_bookings  # noqa: E402

VIP = "user_test_vip01"
EMP = "user_test_empresa_e2e"
SID = "TEST_BK_efdfc4f0"


async def bal(uid, code="USDT"):
    u = await db.users.find_one({"user_id": uid})
    return float((u.get("vip_balances") or {}).get(code, 0))


def mk(status, amount, *, deadline_past=False, end_past=False):
    now = datetime.now(timezone.utc)
    bid = str(uuid.uuid4())
    start = now + timedelta(days=3)
    end = (now - timedelta(hours=2)) if end_past else (start + timedelta(hours=1))
    deadline = (now - timedelta(hours=1)) if deadline_past else (now + timedelta(hours=10))
    return {
        "id": bid, "service_id": SID, "service_title": "Corte QA",
        "company_id": EMP, "company_name": "Empresa QA", "customer_id": VIP,
        "customer_name": "VIP", "slot_date": start.date().isoformat(),
        "slot_start": "09:00", "slot_end": "10:00",
        "slot_start_utc": start.isoformat(), "slot_end_utc": end.isoformat(),
        "accept_deadline_utc": deadline.isoformat(), "timezone": "America/Havana",
        "pricing_type": "fixed", "unit_price_usdt": amount, "quantity": 1,
        "amount_usdt": amount, "currency": "USDT", "status": status,
        "note": "", "reject_reason": "", "pay_op_id": f"svcbk:{bid}:pay",
        "refund_op_id": "", "settle_op_id": "",
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "decided_at": "",
    }


async def main():
    await db.service_bookings.delete_many({"service_id": SID, "customer_name": "VIP"})

    # --- Expire test: pending, deadline past, customer already debited ---
    v0 = await bal(VIP)
    b_exp = mk("pending", 30.0, deadline_past=True)
    await db.service_bookings.insert_one(dict(b_exp))
    # simulate the customer was charged at booking
    await db.users.update_one({"user_id": VIP}, {"$inc": {"vip_balances.USDT": -30.0}})
    v_after_charge = await bal(VIP)

    # --- Settle test: accepted, appointment ended ---
    c0 = await bal(EMP)
    b_set = mk("accepted", 40.0, end_past=True)
    await db.service_bookings.insert_one(dict(b_set))

    r1 = await process_due_bookings()
    v1 = await bal(VIP)
    c1 = await bal(EMP)
    exp_doc = await db.service_bookings.find_one({"id": b_exp["id"]}, {"_id": 0})
    set_doc = await db.service_bookings.find_one({"id": b_set["id"]}, {"_id": 0})
    print("cron run1:", r1)
    print("expired status:", exp_doc["status"], "refund_op:", bool(exp_doc["refund_op_id"]))
    print(f"vip refunded: charged={v_after_charge} -> after_cron={v1} (expect {v0})")
    print("settled status:", set_doc["status"], "settle_op:", bool(set_doc["settle_op_id"]))
    print(f"company credited: {c0} -> {c1} (expect {c0 + 40.0})")

    # --- Idempotency: run cron again, balances must NOT change ---
    r2 = await process_due_bookings()
    v2 = await bal(VIP)
    c2 = await bal(EMP)
    print("cron run2 (idempotent):", r2, "vip", v2, "company", c2,
          "OK" if (abs(v2 - v1) < 1e-9 and abs(c2 - c1) < 1e-9) else "FAIL")

    # cleanup
    await db.service_bookings.delete_many({"id": {"$in": [b_exp["id"], b_set["id"]]}})
    await db.users.update_one({"user_id": EMP}, {"$set": {"vip_balances.USDT": c0}})


asyncio.run(main())
