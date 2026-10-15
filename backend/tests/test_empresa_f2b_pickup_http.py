"""F2-B (end-to-end HTTP) — venta con recogida en tienda de un producto de
Empresa: el canje descuenta la tienda elegida y el rechazo la restaura.

Valida el cableado real de /vip/redeem + /admin/redemptions/{id}/status +
/stores?product_id=… (picker con existencias por tienda)."""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
COMPANY = "user_test_empresa_f2b_http"
MARK = "F2BHTTP"


def _h(tok):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _mkstore(name, by_qty=None, active=True):
    db = _db()
    sid = str(uuid.uuid4())
    db.stores.insert_one({
        "id": sid, "company_id": COMPANY, "name": f"{MARK} {name}",
        "address": "Calle 23 #100, Vedado", "municipality": "Plaza",
        "province": "La Habana", "active": active,
        "created_at": "2026-01-01T00:00:00+00:00"})
    return sid


def _mkproduct(stock, distributed, by_store, price=10.0):
    db = _db()
    pid = str(uuid.uuid4())
    db.products.insert_one({
        "id": pid, "name": f"{MARK} Arroz {pid[:6]}", "description": "",
        "image_url": "", "price_usd": price, "cost_usd": 0.0,
        "stock": float(stock), "distributed": float(distributed),
        "by_store": {k: float(v) for k, v in by_store.items()},
        "category": "general", "is_active": True,
        "owner_id": COMPANY, "owner_name": f"{MARK} Empresa",
        "company_id": COMPANY, "approval_status": "approved",
        "available_store_ids": [],
        "created_at": "2026-01-01T00:00:00+00:00"})
    return pid


def _give_usdt(amount=1000.0, user_id="user_test_vip01"):
    _db().users.update_one({"user_id": user_id},
                           {"$set": {"vip_balances.USDT": amount}})


def _redeem(pid, store_id, qty=1):
    return requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                         json={"product_id": pid, "quantity": qty,
                               "fulfillment": "store_pickup", "store_id": store_id},
                         timeout=20)


def _prod(pid):
    return _db().products.find_one({"id": pid}, {"_id": 0})


class TestPickupFromStore:
    def teardown_method(self, _):
        db = _db()
        pids = [p["id"] for p in db.products.find({"company_id": COMPANY})]
        rids = [r["id"] for r in db.redemptions.find({"product_id": {"$in": pids}})]
        db.redemptions.delete_many({"id": {"$in": rids}})
        db.products.delete_many({"company_id": COMPANY})
        db.stores.delete_many({"company_id": COMPANY})
        db.company_inventory_moves.delete_many({"company_id": COMPANY})
        db.company_inventory_ops.delete_many({"company_id": COMPANY})
        db.notifications.delete_many({"data.redemption_id": {"$in": rids}})

    def test_picker_only_lists_stores_with_stock(self):
        s_with = _mkstore("Con stock", active=True)
        s_without = _mkstore("Sin stock", active=True)
        pid = _mkproduct(20, 8, {s_with: 8})  # s_without no está en by_store
        rows = requests.get(f"{API}/stores", params={"product_id": pid},
                            headers=_h(VIP_TOKEN)).json()
        ids = {s["id"]: s for s in rows}
        assert s_with in ids and s_without not in ids
        assert ids[s_with]["available_qty"] == 8

    def test_sale_consumes_store_and_reject_restores(self):
        store = _mkstore("Central")
        pid = _mkproduct(20, 8, {store: 8})  # central = 12
        _give_usdt()
        r = _redeem(pid, store, qty=3)
        assert r.status_code == 200, r.text
        red = r.json()
        assert red["fulfillment"] == "store_pickup" and red["store_id"] == store
        p = _prod(pid)
        assert p["stock"] == 17
        assert round(p["by_store"][store], 3) == 5
        assert round(p["distributed"], 3) == 5
        assert round(p["stock"] - p["distributed"], 3) == 12  # central intacto

        # rechazo admin → restaura EXACTAMENTE la misma tienda
        rj = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "rejected"})
        assert rj.status_code == 200, rj.text
        p = _prod(pid)
        assert p["stock"] == 20
        assert round(p["by_store"][store], 3) == 8
        assert round(p["distributed"], 3) == 8

    def test_reject_is_idempotent_on_repeat(self):
        store = _mkstore("Repite")
        pid = _mkproduct(20, 10, {store: 10})
        _give_usdt()
        red = _redeem(pid, store, qty=4).json()
        for _ in range(2):  # repetir el PUT rejected no duplica la restitución
            requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "rejected"})
        p = _prod(pid)
        assert p["stock"] == 20 and round(p["by_store"][store], 3) == 10

    def test_sale_blocked_when_store_lacks_stock(self):
        store = _mkstore("Poco")
        pid = _mkproduct(20, 2, {store: 2})  # sólo 2 en la tienda
        _give_usdt()
        r = _redeem(pid, store, qty=5)
        assert r.status_code == 400
        assert "tienda" in r.json()["detail"].lower()
        p = _prod(pid)
        assert p["stock"] == 20 and round(p["by_store"][store], 3) == 2
