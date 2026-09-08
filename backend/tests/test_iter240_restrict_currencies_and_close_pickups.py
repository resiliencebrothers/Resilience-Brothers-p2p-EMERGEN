"""iter240 — (A) Restringir TODAS las monedas a un staff (centinela __NONE__)
y (B) entregas en tienda dentro del cierre diario.

A:
- El admin puede guardar allowed_currencies=["__NONE__"] vía PUT /admin/users.
- Con el centinela, el empleado no ve ninguna orden (scope) y no puede mover
  fondos en ninguna moneda (403).
B:
- Al confirmar una recogida se guarda delivered_at; el daily-close del día
  incluye la sección `recogidas` (num, unidades, total_usdt, detalle) y el
  PDF se genera OK. Recogidas no entregadas no aparecen.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import (ADMIN_TOKEN, BASE_URL, EMPLOYEE_TOKEN, VIP_TOKEN,
                            make_admin_totp, make_employee_totp)

API = f"{BASE_URL}/api"
MARK = "ITER240TEST"
EMP_ID = "user_test_employee01"


def _h(tok):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


class TestRestrictAllCurrencies:
    def teardown_method(self, _):
        _db().users.update_one({"user_id": EMP_ID},
                               {"$set": {"allowed_currencies": []}})

    def test_admin_can_save_none_sentinel(self):
        r = requests.put(f"{API}/admin/users/{EMP_ID}", headers=_h(ADMIN_TOKEN),
                         json={"allowed_currencies": ["__NONE__"],
                               "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        u = _db().users.find_one({"user_id": EMP_ID}, {"allowed_currencies": 1})
        assert u["allowed_currencies"] == ["__NONE__"]

    def test_sentinel_hides_all_orders_from_employee(self):
        _db().users.update_one({"user_id": EMP_ID},
                               {"$set": {"allowed_currencies": ["__NONE__"]}})
        r = requests.get(f"{API}/admin/orders", headers=_h(EMPLOYEE_TOKEN))
        assert r.status_code == 200
        assert r.json() == []

    def test_sentinel_blocks_fund_adjustments_in_any_currency(self):
        db = _db()
        emp = db.users.find_one({"user_id": EMP_ID}, {"_id": 0})
        prev = {"allowed_currencies": emp.get("allowed_currencies", []),
                "can_manage_company_funds": emp.get("can_manage_company_funds", False)}
        db.users.update_one({"user_id": EMP_ID},
                            {"$set": {"allowed_currencies": ["__NONE__"],
                                      "can_manage_company_funds": True}})
        try:
            r = requests.post(f"{API}/admin/company-funds/adjustments",
                              headers=_h(EMPLOYEE_TOKEN),
                              json={"adjustment_type": "inflow",
                                    "currency": "USD", "amount": 1,
                                    "method": "cash",
                                    "source_name": f"{MARK} bloqueado",
                                    "totp_code": make_employee_totp()})
            assert r.status_code == 403, r.text
            assert "No estás autorizado" in r.json()["detail"]
        finally:
            db.users.update_one({"user_id": EMP_ID}, {"$set": prev})

    def test_empty_list_still_means_unrestricted(self):
        _db().users.update_one({"user_id": EMP_ID},
                               {"$set": {"allowed_currencies": []}})
        r = requests.get(f"{API}/admin/orders", headers=_h(EMPLOYEE_TOKEN))
        assert r.status_code == 200


class TestClosePickups:
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

    def _setup_two_pickups(self):
        db = _db()
        store = requests.post(f"{API}/admin/stores", headers=_h(ADMIN_TOKEN),
                              json={"name": f"{MARK} Central",
                                    "address": "Calle 23 #456, Vedado"}).json()
        pid = str(uuid.uuid4())
        db.products.insert_one({
            "id": pid, "name": f"{MARK} Frijoles {pid[:6]}", "description": "",
            "image_url": "", "price_usd": 12.0, "cost_usd": 6.0, "stock": 50,
            "category": "general", "is_active": True, "owner_id": "",
            "owner_name": "", "approval_status": "approved",
            "available_store_ids": [], "created_at": "2026-01-01T00:00:00+00:00"})
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {"vip_balances.USD": 1000.0}})
        reds = []
        for qty in (2, 1):
            red = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                                json={"product_id": pid, "quantity": qty,
                                      "fulfillment": "store_pickup",
                                      "store_id": store["id"]}).json()
            requests.post(f"{API}/admin/redemptions/{red['id']}/pickup-ready",
                          headers=_h(ADMIN_TOKEN))
            reds.append(red)
        return reds

    def test_delivered_pickup_appears_in_daily_close_and_pdf(self):
        red_done, red_pending = self._setup_two_pickups()
        r = requests.post(f"{API}/admin/pickups/confirm", headers=_h(ADMIN_TOKEN),
                          json={"code": red_done["pickup_code"]})
        assert r.status_code == 200, r.text
        assert r.json()["delivered_at"]

        close = requests.get(f"{API}/admin/inventory/daily-close",
                             headers=_h(ADMIN_TOKEN)).json()
        rec = close["recogidas"]
        ids = [p["id"] for p in rec["detalle"]]
        assert red_done["id"] in ids
        assert red_pending["id"] not in ids  # sin entregar no cuenta
        mine = next(p for p in rec["detalle"] if p["id"] == red_done["id"])
        assert mine["quantity"] == 2
        assert rec["unidades"] >= 2
        assert rec["total_usdt"] >= mine["total_usd"]

        pdf = requests.get(f"{API}/admin/inventory/daily-close.pdf",
                           headers=_h(ADMIN_TOKEN))
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content[:4] == b"%PDF"

    def test_status_update_delivered_sets_delivered_at(self):
        red, _ = self._setup_two_pickups()
        r = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "delivered"})
        assert r.status_code == 200, r.text
        doc = _db().redemptions.find_one({"id": red["id"]}, {"_id": 0})
        assert doc["delivered_at"]
