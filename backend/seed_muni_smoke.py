import asyncio, os, datetime
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


async def main():
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    now = datetime.datetime.now(datetime.timezone.utc)
    exp = (now + datetime.timedelta(days=7)).isoformat()
    sessions = [
        ("user_test_admin01", "muni_smoke_admin"),
        ("user_test_vip01", "muni_smoke_vip"),
    ]
    for uid, tok in sessions:
        await db.user_sessions.update_one(
            {"session_token": tok},
            {"$set": {"user_id": uid, "session_token": tok,
                      "expires_at": exp, "created_at": now.isoformat()}},
            upsert=True)
    # Ensure VIP has USDT balance for redemption
    vip = await db.users.find_one({"user_id": "user_test_vip01"})
    bal = (vip or {}).get("balances", {})
    print("VIP balances before:", bal)
    await db.users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"balances.USDT": 5000.0, "is_courier": True}})
    vip2 = await db.users.find_one({"user_id": "user_test_vip01"})
    print("VIP balances after:", vip2.get("balances"))
    # Confirm municipality rates seeded
    cnt = await db.courier_municipality_rates.count_documents({})
    provs = await db.courier_municipality_rates.distinct("province")
    print("muni rates count:", cnt, "provinces:", provs)
    print("sessions seeded OK, exp:", exp)


asyncio.run(main())
