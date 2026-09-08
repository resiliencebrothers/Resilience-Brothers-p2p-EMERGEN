"""iter236 — Recogida en tienda física (Store Pickup).

Cubre:
- CRUD de tiendas (admin) + listado público solo con activas.
- Filtro por producto: `available_store_ids` (vacío = todas).
- Canje con fulfillment=store_pickup: sin costo de mensajería, snapshot de
  la tienda, sin trabajo de mensajería.
- Validaciones: sin store_id → 400, tienda inactiva → 404, producto no
  disponible en esa sucursal → 400, producto de vendedor VIP → 400.
- Marcar "listo para recoger": notifica al cliente, idempotente (409),
  auto-aprueba canjes pendientes.
- Canje pickup se puede marcar 'delivered' sin mensajería (bypass del candado).
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER236TEST"


def _h(tok):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _mkstore(name=None, **overrides):
    body = {"name": name or f"{MARK} Central", "address": "Calle 23 #456, Vedado",
            "municipality": "Plaza", "province": "La Habana",
            "phone": "+53 5555 5555", "hours": "Lun-Sáb 9:00-17:00"}
    body.update(overrides)
    return requests.post(f"{API}/admin/stores", headers=_h(ADMIN_TOKEN), json=body)


def _mkproduct(price=10.0, stock=50, store_ids=None):
    db = _db()
    pid = str(uuid.uuid4())
    db.products.insert_one({
        "id": pid, "name": f"{MARK} Arroz {pid[:6]}", "description": "",
        "image_url": "", "price_usd": price, "cost_usd": 5.0, "stock": stock,
        "category": "general", "is_active": True, "owner_id": "",
        "owner_name": "", "approval_status": "approved",
        "available_store_ids": store_ids or [],
        "created_at": "2026-01-01T00:00:00+00:00"})
    return pid


def _give_balance(user_id="user_test_vip01", amount=1000.0):
    _db().users.update_one({"user_id": user_id},
                           {"$set": {"vip_balances.USD": amount}})


def _redeem(pid, store_id=None, fulfillment="store_pickup", qty=1):
    body = {"product_id": pid, "quantity": qty, "fulfillment": fulfillment}
    if store_id:
        body["store_id"] = store_id
    return requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN), json=body)


class TestStorePickup:
    def teardown_method(self, _):
        db = _db()
        store_ids = [s["id"] for s in db.stores.find({"name": {"$regex": f"^{MARK}"}})]
        db.stores.delete_many({"id": {"$in": store_ids}})
        pids = [p["id"] for p in db.products.find({"name": {"$regex": f"^{MARK}"}})]
        db.products.delete_many({"id": {"$in": pids}})
        rids = [r["id"] for r in db.redemptions.find({"product_id": {"$in": pids}})]
        db.redemptions.delete_many({"id": {"$in": rids}})
        db.notifications.delete_many({"data.redemption_id": {"$in": rids}})
        db.inventory_movements.delete_many({"ref_id": {"$in": rids}})
        db.company_fund_adjustments.delete_many({"ref_id": {"$in": rids}})

    # ------------------------------------------------ CRUD tiendas

    def test_admin_store_crud(self):
        r = _mkstore()
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        assert r.json()["active"] is True
        r2 = requests.put(f"{API}/admin/stores/{sid}", headers=_h(ADMIN_TOKEN),
                          json={"name": f"{MARK} Editada", "address": "Nueva dirección 123",
                                "active": False})
        assert r2.status_code == 200
        assert r2.json()["name"] == f"{MARK} Editada"
        assert r2.json()["active"] is False
        listed = requests.get(f"{API}/admin/stores", headers=_h(ADMIN_TOKEN)).json()
        assert any(s["id"] == sid for s in listed)
        r3 = requests.delete(f"{API}/admin/stores/{sid}", headers=_h(ADMIN_TOKEN))
        assert r3.status_code == 200

    def test_normal_client_cannot_manage_stores(self):
        r = requests.post(f"{API}/admin/stores", headers=_h(NORMAL_TOKEN),
                          json={"name": f"{MARK} Hack", "address": "Dirección x1234"})
        assert r.status_code == 403

    def test_public_list_only_active(self):
        active = _mkstore(f"{MARK} Activa").json()
        inactive = _mkstore(f"{MARK} Inactiva", active=False).json()
        rows = requests.get(f"{API}/stores", headers=_h(NORMAL_TOKEN)).json()
        ids = [s["id"] for s in rows]
        assert active["id"] in ids
        assert inactive["id"] not in ids

    def test_public_list_filters_by_product_availability(self):
        s1 = _mkstore(f"{MARK} S1").json()
        s2 = _mkstore(f"{MARK} S2").json()
        pid_all = _mkproduct()
        pid_only_s1 = _mkproduct(store_ids=[s1["id"]])
        rows_all = requests.get(f"{API}/stores", params={"product_id": pid_all},
                                headers=_h(VIP_TOKEN)).json()
        ids_all = [s["id"] for s in rows_all]
        assert s1["id"] in ids_all and s2["id"] in ids_all
        rows_s1 = requests.get(f"{API}/stores", params={"product_id": pid_only_s1},
                               headers=_h(VIP_TOKEN)).json()
        ids_s1 = [s["id"] for s in rows_s1]
        assert s1["id"] in ids_s1 and s2["id"] not in ids_s1

    # ------------------------------------------------ canje con recogida

    def test_redeem_store_pickup_no_courier_fee(self):
        store = _mkstore().json()
        pid = _mkproduct(price=10.0)
        _give_balance()
        r = _redeem(pid, store["id"])
        assert r.status_code == 200, r.text
        red = r.json()
        assert red["fulfillment"] == "store_pickup"
        assert red["store_id"] == store["id"]
        assert red["store_name"] == store["name"]
        assert red["store_address"] == store["address"]
        assert red["courier_fee_usd"] == 0
        assert red["courier_fee_status"] == "none"
        job = _db().deliveries.find_one({"kind": "redemption", "ref_id": red["id"]})
        assert job is None

    def test_redeem_pickup_requires_store_id(self):
        pid = _mkproduct()
        _give_balance()
        r = _redeem(pid, store_id=None)
        assert r.status_code == 400
        assert "Selecciona la tienda" in r.json()["detail"]

    def test_redeem_pickup_inactive_store_rejected(self):
        store = _mkstore(active=False).json()
        pid = _mkproduct()
        _give_balance()
        r = _redeem(pid, store["id"])
        assert r.status_code == 404

    def test_redeem_pickup_store_not_carrying_product(self):
        s1 = _mkstore(f"{MARK} Con producto").json()
        s2 = _mkstore(f"{MARK} Sin producto").json()
        pid = _mkproduct(store_ids=[s1["id"]])
        _give_balance()
        r = _redeem(pid, s2["id"])
        assert r.status_code == 400
        assert "no está disponible" in r.json()["detail"]

    def test_vendor_product_cannot_pickup(self):
        store = _mkstore().json()
        pid = _mkproduct()
        _db().products.update_one({"id": pid}, {"$set": {"owner_id": "user_test_normal01",
                                                         "owner_name": "Vendedor"}})
        _give_balance()
        r = _redeem(pid, store["id"])
        assert r.status_code == 400
        assert "vendedores VIP" in r.json()["detail"]

    def test_redeem_delivery_still_works(self):
        pid = _mkproduct()
        _give_balance()
        r = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                          json={"product_id": pid, "quantity": 1,
                                "delivery_address": "Calle 10 #123, Habana"})
        assert r.status_code == 200, r.text
        assert r.json()["fulfillment"] == "delivery"
        assert r.json()["store_id"] == ""

    # ------------------------------------------------ listo para recoger

    def test_pickup_ready_notifies_and_is_idempotent(self):
        store = _mkstore().json()
        pid = _mkproduct()
        _give_balance()
        red = _redeem(pid, store["id"]).json()
        r = requests.post(f"{API}/admin/redemptions/{red['id']}/pickup-ready",
                          headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pickup_ready_at"]
        assert body["status"] == "approved"  # pending → auto-approved
        notif = _db().notifications.find_one(
            {"type": "pickup_ready", "data.redemption_id": red["id"]})
        assert notif is not None
        assert store["name"] in notif["message"]
        r2 = requests.post(f"{API}/admin/redemptions/{red['id']}/pickup-ready",
                           headers=_h(ADMIN_TOKEN))
        assert r2.status_code == 409

    def test_pickup_ready_rejected_for_delivery_redemption(self):
        pid = _mkproduct()
        _give_balance()
        red = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                            json={"product_id": pid, "quantity": 1,
                                  "delivery_address": "Calle 10 #123, Habana"}).json()
        r = requests.post(f"{API}/admin/redemptions/{red['id']}/pickup-ready",
                          headers=_h(ADMIN_TOKEN))
        assert r.status_code == 400

    def test_pickup_redemption_can_be_delivered_without_courier(self):
        store = _mkstore().json()
        pid = _mkproduct()
        _give_balance()
        red = _redeem(pid, store["id"]).json()
        r = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "delivered"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "delivered"
