"""iter237 — Aviso "Voy en camino" para recogidas en tienda.

Cubre:
- Cliente marca on-my-way en un canje pickup listo → on_my_way_at + campana
  a los admins (type pickup_on_my_way). Idempotente (409).
- No se puede avisar si el pedido no está listo (400), si el canje es de
  entrega a domicilio (400) o si el canje es de otro usuario (404).
- GET /api/admin/pickups-today: lista recogidas pendientes/aprobadas con
  en-camino primero; excluye entregadas; 403 para clientes normales.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER237TEST"


def _h(tok):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _setup_pickup_redemption(ready=True):
    db = _db()
    store = requests.post(f"{API}/admin/stores", headers=_h(ADMIN_TOKEN),
                          json={"name": f"{MARK} Central",
                                "address": "Calle 23 #456, Vedado"}).json()
    pid = str(uuid.uuid4())
    db.products.insert_one({
        "id": pid, "name": f"{MARK} Arroz {pid[:6]}", "description": "",
        "image_url": "", "price_usd": 10.0, "cost_usd": 5.0, "stock": 50,
        "category": "general", "is_active": True, "owner_id": "",
        "owner_name": "", "approval_status": "approved",
        "available_store_ids": [], "created_at": "2026-01-01T00:00:00+00:00"})
    db.users.update_one({"user_id": "user_test_vip01"},
                        {"$set": {"vip_balances.USD": 1000.0}})
    red = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                        json={"product_id": pid, "quantity": 1,
                              "fulfillment": "store_pickup",
                              "store_id": store["id"]}).json()
    if ready:
        requests.post(f"{API}/admin/redemptions/{red['id']}/pickup-ready",
                      headers=_h(ADMIN_TOKEN))
    return store, pid, red


class TestOnMyWay:
    def teardown_method(self, _):
        db = _db()
        db.stores.delete_many({"name": {"$regex": f"^{MARK}"}})
        pids = [p["id"] for p in db.products.find({"name": {"$regex": f"^{MARK}"}})]
        db.products.delete_many({"id": {"$in": pids}})
        rids = [r["id"] for r in db.redemptions.find({"product_id": {"$in": pids}})]
        db.redemptions.delete_many({"id": {"$in": rids}})
        db.notifications.delete_many({"data.redemption_id": {"$in": rids}})
        db.inventory_movements.delete_many({"ref_id": {"$in": rids}})
        db.company_fund_adjustments.delete_many({"ref_id": {"$in": rids}})

    def test_on_my_way_sets_flag_notifies_admins_and_is_idempotent(self):
        store, pid, red = _setup_pickup_redemption()
        r = requests.post(f"{API}/vip/redemptions/{red['id']}/on-my-way",
                          headers=_h(VIP_TOKEN))
        assert r.status_code == 200, r.text
        assert r.json()["on_my_way_at"]
        notif = _db().notifications.find_one(
            {"type": "pickup_on_my_way", "data.redemption_id": red["id"]})
        assert notif is not None
        assert store["name"] in notif["message"]
        r2 = requests.post(f"{API}/vip/redemptions/{red['id']}/on-my-way",
                           headers=_h(VIP_TOKEN))
        assert r2.status_code == 409

    def test_on_my_way_blocked_until_ready(self):
        _, _, red = _setup_pickup_redemption(ready=False)
        r = requests.post(f"{API}/vip/redemptions/{red['id']}/on-my-way",
                          headers=_h(VIP_TOKEN))
        assert r.status_code == 400
        assert "no está listo" in r.json()["detail"]

    def test_on_my_way_rejected_for_delivery_and_foreign_redemptions(self):
        _, pid, red = _setup_pickup_redemption()
        # canje de otro usuario → 404
        r = requests.post(f"{API}/vip/redemptions/{red['id']}/on-my-way",
                          headers=_h(NORMAL_TOKEN))
        assert r.status_code == 404
        # canje a domicilio → 400
        red2 = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                             json={"product_id": pid, "quantity": 1,
                                   "delivery_address": "Calle 10 #123, Habana"}).json()
        r2 = requests.post(f"{API}/vip/redemptions/{red2['id']}/on-my-way",
                           headers=_h(VIP_TOKEN))
        assert r2.status_code == 400

    def test_pickups_today_list_and_permissions(self):
        _, _, red = _setup_pickup_redemption()
        requests.post(f"{API}/vip/redemptions/{red['id']}/on-my-way",
                      headers=_h(VIP_TOKEN))
        rows = requests.get(f"{API}/admin/pickups-today",
                            headers=_h(ADMIN_TOKEN)).json()
        mine = [x for x in rows if x["id"] == red["id"]]
        assert mine and mine[0]["on_my_way_at"]
        assert rows[0]["on_my_way_at"]  # en camino primero
        # entregado desaparece de la lista
        requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                     headers=_h(ADMIN_TOKEN), json={"status": "delivered"})
        rows2 = requests.get(f"{API}/admin/pickups-today",
                             headers=_h(ADMIN_TOKEN)).json()
        assert not [x for x in rows2 if x["id"] == red["id"]]
        # cliente normal sin permiso
        r = requests.get(f"{API}/admin/pickups-today", headers=_h(NORMAL_TOKEN))
        assert r.status_code == 403
