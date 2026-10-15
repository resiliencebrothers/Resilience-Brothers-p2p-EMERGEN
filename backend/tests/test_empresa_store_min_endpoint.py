"""Endpoint de umbral por tienda — POST /company/inventory/store-min y que
/company/inventory refleje `min`/`low` por sucursal."""
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL

API = f"{BASE_URL}/api"
EMP_ID = "user_test_empresa_smin"
EMP_TOKEN = "test_session_empresa_smin_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {EMP_TOKEN}", "Content-Type": "application/json"}


def _seed():
    db = _db()
    db.users.update_one({"user_id": EMP_ID}, {"$set": {
        "user_id": EMP_ID, "email": "empresa.smin@example.com", "name": "Empresa Smin",
        "role": "empresa", "account_status": "active", "email_verified": True,
        "phone_verified": True, "phone": "+5350000888"}}, upsert=True)
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    db.user_sessions.update_one({"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_ID, "expires_at": exp}},
        upsert=True)


def _cleanup():
    db = _db()
    db.products.delete_many({"company_id": EMP_ID})
    db.stores.delete_many({"company_id": EMP_ID})
    db.notifications.delete_many({"recipient_user_id": EMP_ID})


class TestStoreMinEndpoint:
    def setup_method(self, _):
        _seed(); _cleanup()

    def teardown_method(self, _):
        _cleanup()

    def test_set_min_reflects_in_inventory_and_alerts(self):
        db = _db()
        sid = str(uuid.uuid4())
        db.stores.insert_one({"id": sid, "company_id": EMP_ID, "name": "Suc Smin",
                              "address": "x", "active": True})
        pid = str(uuid.uuid4())
        db.products.insert_one({
            "id": pid, "name": "Prod Smin", "category": "general", "price_usd": 1.0,
            "cost_usd": 0.0, "stock": 10.0, "distributed": 3.0, "by_store": {sid: 3.0},
            "is_active": True, "owner_id": EMP_ID, "company_id": EMP_ID,
            "approval_status": "approved", "unit": "unidad"})

        r = requests.post(f"{API}/company/inventory/store-min", headers=_hdr(),
                          json={"product_id": pid, "store_id": sid, "min_stock": 4})
        assert r.status_code == 200, r.text
        assert r.json()["min_stock"] == 4

        inv = requests.get(f"{API}/company/inventory", headers=_hdr()).json()
        row = next(x for x in inv if x["product_id"] == pid)
        st = next(s for s in row["stores"] if s["store_id"] == sid)
        assert st["min"] == 4
        assert st["low"] is True   # 3 <= 4

        # al fijar el umbral por encima del stock actual, disparó la alerta
        assert db.notifications.count_documents({
            "recipient_user_id": EMP_ID, "type": "company_store_out_of_stock",
            "data.store_id": sid}) == 1

    def test_rejects_foreign_store(self):
        db = _db()
        pid = str(uuid.uuid4())
        db.products.insert_one({
            "id": pid, "name": "P", "category": "general", "price_usd": 1.0,
            "cost_usd": 0.0, "stock": 5.0, "distributed": 0.0, "by_store": {},
            "is_active": True, "owner_id": EMP_ID, "company_id": EMP_ID,
            "approval_status": "approved", "unit": "unidad"})
        r = requests.post(f"{API}/company/inventory/store-min", headers=_hdr(),
                          json={"product_id": pid, "store_id": "no-such-store", "min_stock": 2})
        assert r.status_code in (403, 404)
