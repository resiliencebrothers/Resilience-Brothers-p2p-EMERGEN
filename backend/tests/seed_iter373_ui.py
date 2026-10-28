# iter373 — seed TEST_ products for UI testing municipal delivery (300 USDT and 1200 USDT)
import os
from pymongo import MongoClient

env = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l)
db = MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]
for pid, name, price in [("TEST_ui373_cheap", "TEST_UI373 Cheap", 300.0),
                         ("TEST_ui373_big", "TEST_UI373 Big", 1200.0)]:
    db.products.update_one({"id": pid}, {"$set": {
        "id": pid, "name": name, "description": "t", "image_url": "",
        "price_usd": price, "price_usdt": price, "cost_usd": 10.0, "stock": 20.0,
        "category": "test", "is_active": True, "unit": "unidad", "owner_id": None,
        "owner_name": "", "approval_status": "approved",
        "created_at": "2030-01-01T00:00:00+00:00"}}, upsert=True)
print("ok")
