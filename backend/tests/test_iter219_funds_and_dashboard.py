"""iter219 — Paquete del operador:
1. Seed del inventario desde el Excel (30 productos, idempotente).
2. Cada venta del marketplace entra como capital al fondo de la empresa
   (ajuste automático inflow USD) y se revierte si el canje se rechaza.
3. La comisión por ventas de productos VIP también entra al fondo (delivered).
4. Dashboard por mercancía específica (product_id) + KPIs de rentabilidad
   y comisión VIP ganada.
5. Entrada con precio de venta → actualiza el producto + auditoría 'precio'.
6. Los ajustes manuales fueron retirados de la API (422).
7. Foto opcional en el movimiento (base64 → R2).
8. Editar precio/costo de producto deja rastro de quién lo cambió.
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, today_havana

API = f"{BASE_URL}/api"
MARK = "ITER219TEST"

# 1×1 px PNG rojo
PNG_DATA_URL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAA"
                "fFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _h(tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _create_product(**overrides):
    payload = {
        "name": f"{MARK}_Prod_{int(time.time()*1000)}",
        "description": "iter219", "image_url": "",
        "price_usd": 10.0, "cost_usd": 6.0, "stock": 10,
        "category": "iter219test", "is_active": True,
    }
    payload.update(overrides)
    r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _movement(body):
    return requests.post(f"{API}/admin/inventory/movements",
                         headers=_h(ADMIN_TOKEN), json=body)


def _fund_adjustments(ref_id):
    return list(_db().company_fund_adjustments.find(
        {"ref_id": ref_id}, {"_id": 0}))


def _cleanup():
    db = _db()
    ids = [p["id"] for p in db.products.find({"category": "iter219test"}, {"id": 1})]
    db.products.delete_many({"category": "iter219test"})
    if ids:
        db.inventory_movements.delete_many({"product_id": {"$in": ids}})
        db.redemptions.delete_many({"product_id": {"$in": ids}})
        db.notifications.delete_many({"data.product_id": {"$in": ids}})
    db.inventory_movements.delete_many({"product_name": {"$regex": f"^{MARK}"}})
    db.company_fund_adjustments.delete_many(
        {"source": "marketplace_auto", "note": {"$regex": MARK}})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


# ============================================================
# 1) Seed del Excel
# ============================================================

class TestExcelSeed:
    def test_excel_products_seeded(self):
        db = _db()
        marker = db.settings.find_one({"id": "global"}, {"_id": 0})
        assert marker.get("excel_inventory_seeded_at")
        maicena = db.products.find_one({"name": "Maicena"}, {"_id": 0})
        assert maicena is not None
        assert maicena["stock"] == 40
        assert maicena["cost_usd"] == 330.0
        assert maicena["price_usd"] == 390.0
        assert maicena["category"] == "mercadito"
        # iter223 — el operador pidió verlos en el marketplace (migración
        # de activación única los deja publicados).
        assert maicena["is_active"] is True
        assert db.products.count_documents({"category": "mercadito"}) >= 30

    def test_seed_is_idempotent(self):
        db = _db()
        before = db.products.count_documents({"category": "mercadito"})
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from services.inventory_seed import seed_excel_inventory
        # loop propio: asyncio.run() de tests previos deja el loop global en
        # None y get_event_loop() lanzaría RuntimeError según el orden.
        loop = asyncio.new_event_loop()
        try:
            created = loop.run_until_complete(seed_excel_inventory())
        finally:
            loop.close()
        assert created == 0
        assert db.products.count_documents({"category": "mercadito"}) == before

    def test_seeded_products_visible_in_control(self):
        r = requests.get(f"{API}/admin/inventory/control", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        names = {x["name"] for x in r.json()}
        assert "Maicena" in names
        assert "Harina de Trigo 50kg" in names


# ============================================================
# 2+3) Capital al fondo de la empresa
# ============================================================

class TestFundInflows:
    def test_company_sale_enters_fund_and_reverses_on_reject(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {"vip_balances.USDT": 5000.0}})
        p = _create_product(price_usd=10.0, stock=10)
        r = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                          json={"product_id": p["id"], "quantity": 3,
                                "delivery_address": "Calle fondo #1"})
        assert r.status_code == 200, r.text
        red = r.json()
        adjs = _fund_adjustments(red["id"])
        assert len(adjs) == 1
        assert adjs[0]["adjustment_type"] == "inflow"
        assert adjs[0]["amount"] == 30.0
        # iter229 — el cliente paga en USDT desde la web.
        assert adjs[0]["currency"] == "USDT"
        assert adjs[0]["source"] == "marketplace_auto"
        row = db.redemptions.find_one({"id": red["id"]}, {"_id": 0})
        assert row["fund_inflow_at"] and row["fund_inflow_amount"] == 30.0
        # rechazo → salida equivalente del fondo
        r = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "rejected"})
        assert r.status_code == 200, r.text
        adjs = _fund_adjustments(red["id"])
        assert len(adjs) == 2
        out = [a for a in adjs if a["adjustment_type"] == "outflow"]
        assert len(out) == 1 and out[0]["amount"] == 30.0
        # iter256(S05) — reactivar (rejected→pending) re-cobra al cliente y
        # RE-REGISTRA la entrada al fondo; el segundo rechazo la revierte.
        # Cada ciclo queda balanceado (inflow+outflow) sin duplicados.
        r = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "pending"})
        assert r.status_code == 200, r.text
        adjs = _fund_adjustments(red["id"])
        assert len(adjs) == 3
        assert len([a for a in adjs if a["adjustment_type"] == "inflow"]) == 2
        r = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "rejected"})
        assert r.status_code == 200, r.text
        adjs = _fund_adjustments(red["id"])
        assert len(adjs) == 4
        assert len([a for a in adjs if a["adjustment_type"] == "outflow"]) == 2
        # repetir el rechazo (mismo estado) no duplica nada
        requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                     headers=_h(ADMIN_TOKEN), json={"status": "rejected"})
        assert len(_fund_adjustments(red["id"])) == 4

    def test_vendor_commission_enters_fund_on_delivered(self):
        db = _db()
        prev = db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
        prev_rate = prev.get("courier_rate_usdt_per_km")
        prev_pct = prev.get("vendor_commission_pct")
        db.settings.update_one(
            {"id": "global"},
            {"$set": {"courier_rate_usdt_per_km": 0,
                      "vendor_commission_pct": 10.0}}, upsert=True)
        try:
            r = requests.post(f"{API}/vip/my-products", headers=_h(VIP_TOKEN),
                              json={"name": f"{MARK}_Vendor_{int(time.time()*1000)}",
                                    "price_usd": 50.0, "stock": 4,
                                    "category": "iter219test"})
            assert r.status_code == 200, r.text
            pid = r.json()["id"]
            requests.post(f"{API}/admin/vendor-products/{pid}/approve",
                          headers=_h(ADMIN_TOKEN), json={})
            db.users.update_one({"user_id": "user_test_admin01"},
                                {"$set": {"vip_balances.USDT": 1000.0}})
            r = requests.post(f"{API}/vip/redeem", headers=_h(ADMIN_TOKEN),
                              json={"product_id": pid, "quantity": 2,
                                    "delivery_address": "x"})
            assert r.status_code == 200, r.text
            red = r.json()
            # al canjear un producto VIP NO entra nada aún
            assert _fund_adjustments(red["id"]) == []
            r = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                             headers=_h(ADMIN_TOKEN), json={"status": "delivered"})
            assert r.status_code == 200, r.text
            adjs = _fund_adjustments(red["id"])
            assert len(adjs) == 1
            assert adjs[0]["adjustment_type"] == "inflow"
            assert adjs[0]["amount"] == 10.0  # 100 × 10% comisión
            # rechazado después → reverso de la comisión
            r = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                             headers=_h(ADMIN_TOKEN), json={"status": "rejected"})
            assert r.status_code == 200, r.text
            adjs = _fund_adjustments(red["id"])
            out = [a for a in adjs if a["adjustment_type"] == "outflow"]
            assert len(out) == 1 and out[0]["amount"] == 10.0
        finally:
            restore = {}
            if prev_rate is not None:
                restore["courier_rate_usdt_per_km"] = prev_rate
            if prev_pct is not None:
                restore["vendor_commission_pct"] = prev_pct
            ops = {}
            if restore:
                ops["$set"] = restore
            unset = {}
            if prev_rate is None:
                unset["courier_rate_usdt_per_km"] = ""
            if prev_pct is None:
                unset["vendor_commission_pct"] = ""
            if unset:
                ops["$unset"] = unset
            if ops:
                db.settings.update_one({"id": "global"}, ops)


# ============================================================
# 4) Dashboard por mercancía + rentabilidad + comisión VIP
# ============================================================

class TestDashboardPerProduct:
    def test_product_filter_and_profitability(self):
        p1 = _create_product(price_usd=10.0, cost_usd=6.0, stock=20)
        p2 = _create_product(price_usd=8.0, cost_usd=4.0, stock=20)
        assert _movement({"product_id": p1["id"], "type": "venta",
                          "quantity": 5, "note": MARK}).status_code == 200
        assert _movement({"product_id": p2["id"], "type": "venta",
                          "quantity": 2, "note": MARK}).status_code == 200
        today = today_havana()
        r = requests.get(f"{API}/admin/inventory/dashboard",
                         params={"start": today, "end": today,
                                 "product_id": p1["id"]},
                         headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["product_id"] == p1["id"]
        assert d["units_sold"] == 5
        assert d["sales_revenue"] == 50.0
        assert d["cogs"] == 30.0
        assert d["profit"] == 20.0
        assert d["profitability_pct"] == round(20.0 / 30.0 * 100, 2)
        assert d["units_in_stock"] == 15  # solo p1
        assert d["vip_commission_earned"] is None  # no aplica con filtro
        # global incluye comisión VIP (número ≥ 0)
        r = requests.get(f"{API}/admin/inventory/dashboard",
                         params={"start": today, "end": today},
                         headers=_h(ADMIN_TOKEN))
        g = r.json()
        assert g["vip_commission_earned"] is not None
        assert g["units_sold"] >= 7


# ============================================================
# 5+6+7+8) Ficha de costo, ajustes retirados, foto y auditoría
# ============================================================

class TestMovementExtras:
    def test_entrada_with_sale_price_updates_product_and_audits(self):
        p = _create_product(price_usd=10.0, cost_usd=6.0, stock=5)
        r = _movement({"product_id": p["id"], "type": "entrada", "quantity": 3,
                       "unit_cost": 7.0, "sale_price": 12.5, "note": MARK})
        assert r.status_code == 200, r.text
        db = _db()
        doc = db.products.find_one({"id": p["id"]}, {"_id": 0})
        assert doc["price_usd"] == 12.5
        assert doc["cost_usd"] == 7.0
        assert doc["stock"] == 8
        audits = list(db.inventory_movements.find(
            {"product_id": p["id"], "type": "precio"}, {"_id": 0}))
        notes = {a["note"] for a in audits}
        assert any("Precio venta: 10 → 12.5" in n for n in notes)
        assert any("Costo unitario: 6 → 7" in n for n in notes)
        assert all(a["actor_email"] for a in audits)

    def test_movement_with_photo_uploaded(self):
        p = _create_product(stock=5)
        r = _movement({"product_id": p["id"], "type": "entrada", "quantity": 1,
                       "note": MARK, "photo_url": PNG_DATA_URL})
        assert r.status_code == 200, r.text
        assert r.json()["photo_url"].startswith("/api/files/inventory/")

    def test_admin_price_edit_leaves_audit_trail(self):
        p = _create_product(price_usd=10.0, cost_usd=6.0, stock=5)
        body = {"name": p["name"], "description": p["description"],
                "image_url": "", "price_usd": 11.0, "cost_usd": 6.0,
                "stock": 5, "category": "iter219test", "is_active": True}
        r = requests.put(f"{API}/admin/products/{p['id']}",
                         headers=_h(ADMIN_TOKEN), json=body)
        assert r.status_code == 200, r.text
        audit = _db().inventory_movements.find_one(
            {"product_id": p["id"], "type": "precio"}, {"_id": 0})
        assert audit is not None
        assert "Precio venta: 10 → 11" in audit["note"]
        assert audit["actor_email"]
