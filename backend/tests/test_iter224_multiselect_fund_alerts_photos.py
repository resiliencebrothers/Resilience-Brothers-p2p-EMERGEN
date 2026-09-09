"""iter224 — Paquete:
1. Dashboard multi-mercancía (`product_ids` separado por comas).
2. Alerta Caja Baja: mínimo configurable por cuenta interna / caja, con
   notificación in-app a admins, dedup y rearme al recuperarse.
3. Fotos del mercadito aplicadas por migración a productos sin imagen.
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, today_havana

API = f"{BASE_URL}/api"
MARK = "ITER224TEST"
ADMIN_UID = "user_test_admin01"


def _h(tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _cleanup():
    db = _db()
    ids = [p["id"] for p in db.products.find({"category": "iter224test"}, {"id": 1})]
    db.products.delete_many({"category": "iter224test"})
    if ids:
        db.inventory_movements.delete_many({"product_id": {"$in": ids}})
        db.notifications.delete_many({"data.product_id": {"$in": ids}})
    db.fund_accounts.delete_many({"name": {"$regex": f"^{MARK}"}})
    db.notifications.delete_many({"type": "low_fund_balance",
                                  "title": {"$regex": MARK}})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


def _create_product(**overrides):
    payload = {"name": f"{MARK}_{int(time.time()*1000)}", "description": "",
               "image_url": "", "price_usd": 10.0, "cost_usd": 6.0,
               "stock": 20, "category": "iter224test", "is_active": True}
    payload.update(overrides)
    r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _venta(pid, qty):
    r = requests.post(f"{API}/admin/inventory/movements", headers=_h(ADMIN_TOKEN),
                      json={"product_id": pid, "type": "venta",
                            "quantity": qty, "note": MARK})
    assert r.status_code == 200, r.text


class TestMultiProductDashboard:
    def test_selected_subset_only(self):
        p1 = _create_product(price_usd=10.0, cost_usd=6.0)
        p2 = _create_product(price_usd=8.0, cost_usd=4.0)
        p3 = _create_product(price_usd=5.0, cost_usd=2.0)
        _venta(p1["id"], 2)   # ingresos 20
        _venta(p2["id"], 3)   # ingresos 24
        _venta(p3["id"], 4)   # ingresos 20 (excluido)
        today = today_havana()
        r = requests.get(f"{API}/admin/inventory/dashboard",
                         params={"start": today, "end": today,
                                 "product_ids": f"{p1['id']},{p2['id']}"},
                         headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(d["product_ids"]) == {p1["id"], p2["id"]}
        assert d["units_sold"] == 5
        assert d["sales_revenue"] == 44.0
        assert d["units_in_stock"] == (20 - 2) + (20 - 3)
        assert d["vip_commission_earned"] is None

    def test_single_product_id_backcompat(self):
        p = _create_product()
        _venta(p["id"], 1)
        today = today_havana()
        r = requests.get(f"{API}/admin/inventory/dashboard",
                         params={"start": today, "end": today,
                                 "product_id": p["id"]},
                         headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.json()["product_id"] == p["id"]
        assert r.json()["units_sold"] == 1


class TestLowFundBalanceAlert:
    def _alerts(self, account_id):
        return list(_db().notifications.find(
            {"type": "low_fund_balance", "recipient_user_id": ADMIN_UID,
             "data.account_id": account_id}, {"_id": 0}))

    def test_full_alert_cycle(self):
        import uuid as _uuid
        db = _db()
        acc_id = f"facc_test_{_uuid.uuid4().hex[:8]}"
        db.fund_accounts.insert_one({
            "id": acc_id, "name": f"{MARK} Caja Test", "currency": "USD",
            "method": "cash", "is_active": True, "note": "",
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        try:
            # 1) configurar mínimo 100 (saldo actual 0 → alerta inmediata)
            r = requests.put(
                f"{API}/admin/company-funds/accounts/{acc_id}/min-balance",
                headers=_h(ADMIN_TOKEN), json={"min_balance": 100})
            assert r.status_code == 200, r.text
            assert r.json()["min_balance_alert"] == 100.0
            assert r.json()["low_balance_alerted_at"]
            assert len(self._alerts(acc_id)) == 1
            # 2) re-configurar mismo mínimo → flag se limpia y re-alerta (1 nueva)
            r = requests.put(
                f"{API}/admin/company-funds/accounts/{acc_id}/min-balance",
                headers=_h(ADMIN_TOKEN), json={"min_balance": 100})
            assert r.status_code == 200
            assert len(self._alerts(acc_id)) == 2
            # 3) desactivar (null) → sin min, sin flag
            r = requests.put(
                f"{API}/admin/company-funds/accounts/{acc_id}/min-balance",
                headers=_h(ADMIN_TOKEN), json={"min_balance": None})
            assert r.status_code == 200
            assert r.json()["min_balance_alert"] is None
            doc = db.fund_accounts.find_one({"id": acc_id}, {"_id": 0})
            assert "min_balance_alert" not in doc
            assert "low_balance_alerted_at" not in doc
            # 4) el breakdown expone el campo
            r = requests.get(f"{API}/admin/company-funds/accounts/USD",
                             headers=_h(ADMIN_TOKEN))
            assert r.status_code == 200
            row = next(a for a in r.json()["accounts"] if a["id"] == acc_id)
            assert "min_balance_alert" in row
        finally:
            db.fund_accounts.delete_many({"id": acc_id})

    def test_scan_dedup_and_rearm(self):
        import asyncio
        import sys
        import uuid as _uuid
        sys.path.insert(0, "/app/backend")
        db = _db()
        acc_id = f"facc_test_{_uuid.uuid4().hex[:8]}"
        db.fund_accounts.insert_one({
            "id": acc_id, "name": f"{MARK} Caja Scan", "currency": "USD",
            "method": "cash", "is_active": True, "note": "",
            "min_balance_alert": 50.0,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        try:
            from services.fund_alerts import check_low_fund_balances
            loop = asyncio.new_event_loop()
            n1 = loop.run_until_complete(check_low_fund_balances())
            assert n1 >= 1
            assert len(self._alerts(acc_id)) == 1
            # segundo scan sin cambios → dedup, no duplica
            loop.run_until_complete(check_low_fund_balances())
            assert len(self._alerts(acc_id)) == 1
        finally:
            db.fund_accounts.delete_many({"id": acc_id})

    def test_only_admin_can_configure(self):
        r = requests.put(
            f"{API}/admin/company-funds/accounts/cualquiera/min-balance",
            headers=_h(VIP_TOKEN), json={"min_balance": 10})
        assert r.status_code == 403

    def test_unknown_account_404(self):
        r = requests.put(
            f"{API}/admin/company-funds/accounts/no-existe/min-balance",
            headers=_h(ADMIN_TOKEN), json={"min_balance": 10})
        assert r.status_code == 404


class TestExcelPhotos:
    def test_photos_applied_to_seeded_products(self):
        db = _db()
        marker = db.settings.find_one({"id": "global"}, {"_id": 0})
        assert marker.get("excel_inventory_photos_at")
        sin_foto = db.products.count_documents(
            {"category": "mercadito",
             "$or": [{"image_url": {"$in": [None, ""]}},
                     {"image_url": {"$exists": False}}]})
        assert sin_foto == 0
        maicena = db.products.find_one({"name": "Maicena"}, {"_id": 0})
        assert maicena["image_url"].startswith("https://")
        # la URL responde
        assert requests.head(maicena["image_url"], timeout=10).status_code == 200
