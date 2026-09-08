"""iter238 — Código corto de recogida (pickup_code).

Cubre:
- El canje pickup genera un código de 6 chars del alfabeto sin ambiguos;
  los canjes a domicilio no llevan código.
- La notificación "listo para recoger" incluye el código formateado.
- GET /api/admin/pickups/verify: acepta el código en minúsculas/con guión,
  devuelve el pedido; código inválido → 404; corto → 400; sin permiso → 403.
- POST /api/admin/pickups/confirm: marca delivered (con nota de auditoría);
  reutilizar el código después → 404.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER238TEST"
ALPHABET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def _h(tok):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _setup(ready=True):
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


class TestPickupCode:
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

    def test_pickup_generates_code_delivery_does_not(self):
        _, pid, red = _setup(ready=False)
        code = red["pickup_code"]
        assert len(code) == 6 and set(code) <= ALPHABET
        red2 = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                             json={"product_id": pid, "quantity": 1,
                                   "delivery_address": "Calle 10 #123, Habana"}).json()
        assert red2["pickup_code"] == ""

    def test_ready_notification_includes_formatted_code(self):
        _, _, red = _setup(ready=True)
        code = red["pickup_code"]
        notif = _db().notifications.find_one(
            {"type": "pickup_ready", "data.redemption_id": red["id"]})
        assert notif is not None
        assert f"{code[:3]}-{code[3:]}" in notif["message"]

    def test_verify_normalizes_and_validates(self):
        _, _, red = _setup()
        code = red["pickup_code"]
        raw = f" {code[:3].lower()}-{code[3:].lower()} "
        r = requests.get(f"{API}/admin/pickups/verify", params={"code": raw},
                         headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        assert r.json()["id"] == red["id"]
        assert r.json()["product_name"] == red["product_name"]
        assert "pickup_code" not in r.json()
        assert requests.get(f"{API}/admin/pickups/verify",
                            params={"code": "ZZZZZZ"},
                            headers=_h(ADMIN_TOKEN)).status_code == 404
        assert requests.get(f"{API}/admin/pickups/verify",
                            params={"code": "AB1"},
                            headers=_h(ADMIN_TOKEN)).status_code == 400
        assert requests.get(f"{API}/admin/pickups/verify",
                            params={"code": code},
                            headers=_h(NORMAL_TOKEN)).status_code == 403

    def test_confirm_delivers_and_code_is_single_use(self):
        _, _, red = _setup()
        code = red["pickup_code"]
        r = requests.post(f"{API}/admin/pickups/confirm",
                          headers=_h(ADMIN_TOKEN),
                          json={"code": f"{code[:3]}-{code[3:]}"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "delivered"
        assert "código" in r.json()["admin_note"]
        # iter239 — el cliente recibe confirmación inmediata de la entrega.
        notif = _db().notifications.find_one(
            {"type": "pickup_delivered", "data.redemption_id": red["id"],
             "recipient_user_id": "user_test_vip01"})
        assert notif is not None
        assert red["product_name"] in notif["message"]
        r2 = requests.post(f"{API}/admin/pickups/confirm",
                           headers=_h(ADMIN_TOKEN), json={"code": code})
        assert r2.status_code == 404
        rows = requests.get(f"{API}/admin/pickups-today",
                            headers=_h(ADMIN_TOKEN)).json()
        assert not [x for x in rows if x["id"] == red["id"]]
