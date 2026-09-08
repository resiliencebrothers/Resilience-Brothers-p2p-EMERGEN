"""iter217 — Control de inventario de tienda física + marketplace multivendedor VIP.

Cubre:
A) Inventario (permiso 'products'):
   - Entrada suma stock y registra movimiento con total = costo × cantidad.
   - Venta resta stock y calcula ganancia = (precio − costo) × cantidad.
   - Venta / ajuste− con stock insuficiente → 400.
   - Control en tiempo real: entradas/ventas/estado (ok/agotado).
   - Dashboard del período: unidades, ingresos, COGS, ganancia, compras.
   - Un canje del marketplace genera movimiento 'venta' (source=marketplace)
     sin doble descuento de stock.
   - Productos de vendedores VIP no entran al inventario (400).
B) Marketplace multivendedor:
   - VIP crea producto → 'pending', oculto en GET /products.
   - Admin aprueba → visible con owner_name. Rechaza → VIP ve el motivo y al
     editar vuelve a 'pending'.
   - Cliente normal no puede publicar (403).
   - Al marcar el canje 'delivered' se acredita el neto (menos comisión) al
     saldo del vendedor una sola vez; al rechazar después se revierte.
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER217TEST"


def _h(tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _create_company_product(**overrides):
    payload = {
        "name": f"{MARK}_Prod_{int(time.time()*1000)}",
        "description": "producto de prueba iter217",
        "image_url": "",
        "price_usd": 6.0,
        "cost_usd": 4.0,
        "stock": 10,
        "category": "iter217test",
        "is_active": True,
    }
    payload.update(overrides)
    r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _movement(body, tok=ADMIN_TOKEN):
    return requests.post(f"{API}/admin/inventory/movements", headers=_h(tok), json=body)


def _stock(pid):
    doc = _db().products.find_one({"id": pid}, {"_id": 0})
    return int(doc["stock"])


def _cleanup():
    db = _db()
    prods = list(db.products.find({"category": "iter217test"}, {"id": 1}))
    ids = [p["id"] for p in prods]
    db.products.delete_many({"category": "iter217test"})
    db.products.delete_many({"name": {"$regex": f"^{MARK}"}})
    if ids:
        db.inventory_movements.delete_many({"product_id": {"$in": ids}})
        db.redemptions.delete_many({"product_id": {"$in": ids}})
    db.inventory_movements.delete_many({"product_name": {"$regex": f"^{MARK}"}})
    db.company_fund_adjustments.delete_many(
        {"source": "marketplace_auto", "note": {"$regex": MARK}})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


# ============================================================
# A) Inventario
# ============================================================

class TestInventoryMovements:
    def test_entrada_increases_stock_and_totals(self):
        p = _create_company_product(stock=10)
        r = _movement({"product_id": p["id"], "type": "entrada",
                       "quantity": 5, "unit_cost": 4.0, "note": MARK})
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["type"] == "entrada"
        assert doc["total"] == 20.0          # 5 × 4 (salida de caja por compra)
        assert doc["profit"] == 0.0
        assert _stock(p["id"]) == 15

    def test_venta_decrements_stock_and_computes_profit(self):
        p = _create_company_product(stock=10, price_usd=6.0, cost_usd=4.0)
        r = _movement({"product_id": p["id"], "type": "venta",
                       "quantity": 3, "note": MARK})
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["total"] == 18.0          # 3 × 6
        assert doc["cost_of_sale"] == 12.0   # 3 × 4
        assert doc["profit"] == 6.0
        assert _stock(p["id"]) == 7

    def test_venta_insufficient_stock_rejected(self):
        p = _create_company_product(stock=2)
        r = _movement({"product_id": p["id"], "type": "venta",
                       "quantity": 99, "note": MARK})
        assert r.status_code == 400
        assert "insuficiente" in r.json()["detail"].lower()
        assert _stock(p["id"]) == 2          # stock intacto

    def test_ajuste_types_removed_from_api(self):
        # iter219 — el operador pidió retirar los ajustes manuales.
        p = _create_company_product(stock=1)
        for mtype in ("ajuste_pos", "ajuste_neg"):
            r = _movement({"product_id": p["id"], "type": mtype,
                           "quantity": 1, "note": MARK})
            assert r.status_code == 422
        assert _stock(p["id"]) == 1

    def test_control_rows_reflect_movements_and_status(self):
        p = _create_company_product(stock=10)
        _movement({"product_id": p["id"], "type": "entrada", "quantity": 5, "note": MARK})
        _movement({"product_id": p["id"], "type": "venta", "quantity": 3, "note": MARK})
        p0 = _create_company_product(stock=0)
        r = requests.get(f"{API}/admin/inventory/control", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        rows = {x["product_id"]: x for x in r.json()}
        row = rows[p["id"]]
        # iter226 — el stock inicial (10) queda auditado como Entrada 'alta'.
        assert row["entradas"] == 15
        assert row["ventas"] == 3
        assert row["stock"] == 12
        assert row["estado"] == "ok"
        assert row["inventory_value"] == 12 * 4.0
        assert rows[p0["id"]]["estado"] == "agotado"

    def test_dashboard_kpis(self):
        p = _create_company_product(stock=20, price_usd=10.0, cost_usd=7.0)
        _movement({"product_id": p["id"], "type": "entrada",
                   "quantity": 10, "unit_cost": 7.0, "note": MARK})
        _movement({"product_id": p["id"], "type": "venta", "quantity": 4, "note": MARK})
        today = time.strftime("%Y-%m-%d")
        r = requests.get(f"{API}/admin/inventory/dashboard",
                         params={"start": today, "end": today},
                         headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["units_sold"] >= 4
        assert d["sales_revenue"] >= 40.0
        assert d["cogs"] >= 28.0
        assert d["profit"] >= 12.0
        assert d["purchases_out"] >= 70.0
        assert d["units_in_stock"] >= 0
        assert "margin_pct" in d and "net_cash_flow" in d

    def test_client_cannot_access_inventory(self):
        r = requests.get(f"{API}/admin/inventory/control", headers=_h(VIP_TOKEN))
        assert r.status_code == 403

    def test_marketplace_redeem_records_venta_movement_once(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {"vip_balance_usd": 5000.0}})
        p = _create_company_product(stock=10, price_usd=6.0, cost_usd=4.0)
        r = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                          json={"product_id": p["id"], "quantity": 2,
                                "delivery_address": "Calle iter217 #1"})
        assert r.status_code == 200, r.text
        red = r.json()
        # sin doble descuento: 10 − 2 = 8
        assert _stock(p["id"]) == 8
        mov = db.inventory_movements.find_one(
            {"ref_id": red["id"], "type": "venta"}, {"_id": 0})
        assert mov is not None
        assert mov["source"] == "marketplace"
        assert mov["quantity"] == 2
        assert mov["total"] == 12.0
        assert mov["profit"] == 4.0


# ============================================================
# B) Marketplace multivendedor VIP
# ============================================================

def _vip_create_product(**overrides):
    payload = {
        "name": f"{MARK}_Vendor_{int(time.time()*1000)}",
        "description": "vendo esto",
        "image_url": "",
        "price_usd": 25.0,
        "stock": 3,
        "category": "iter217test",
        "is_active": True,
    }
    payload.update(overrides)
    r = requests.post(f"{API}/vip/my-products", headers=_h(VIP_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _public_product_ids():
    r = requests.get(f"{API}/products")
    assert r.status_code == 200
    return {p["id"]: p for p in r.json()}


class TestVendorProducts:
    def test_vip_create_is_pending_and_hidden(self):
        p = _vip_create_product()
        assert p["approval_status"] == "pending"
        assert p["owner_id"] == "user_test_vip01"
        assert p["cost_usd"] == 0.0
        assert p["id"] not in _public_product_ids()

    def test_admin_approve_publishes_with_owner(self):
        p = _vip_create_product()
        r = requests.post(f"{API}/admin/vendor-products/{p['id']}/approve",
                          headers=_h(ADMIN_TOKEN), json={})
        assert r.status_code == 200, r.text
        pub = _public_product_ids()
        assert p["id"] in pub
        assert pub[p["id"]]["owner_name"]

    def test_reject_then_edit_resubmits(self):
        p = _vip_create_product()
        r = requests.post(f"{API}/admin/vendor-products/{p['id']}/reject",
                          headers=_h(ADMIN_TOKEN),
                          json={"reason": "Foto borrosa"})
        assert r.status_code == 200, r.text
        mine = requests.get(f"{API}/vip/my-products", headers=_h(VIP_TOKEN)).json()
        row = next(x for x in mine if x["id"] == p["id"])
        assert row["approval_status"] == "rejected"
        assert row["rejection_reason"] == "Foto borrosa"
        r = requests.put(f"{API}/vip/my-products/{p['id']}",
                         headers=_h(VIP_TOKEN), json={"price_usd": 22.0})
        assert r.status_code == 200, r.text
        assert r.json()["approval_status"] == "pending"
        assert r.json()["rejection_reason"] == ""
        assert r.json()["price_usd"] == 22.0

    def test_vip_cannot_edit_company_or_foreign_product(self):
        company = _create_company_product()
        r = requests.put(f"{API}/vip/my-products/{company['id']}",
                         headers=_h(VIP_TOKEN), json={"price_usd": 1.0})
        assert r.status_code == 404

    def test_normal_client_cannot_publish(self):
        r = requests.post(f"{API}/vip/my-products", headers=_h(NORMAL_TOKEN),
                          json={"name": f"{MARK}_no", "price_usd": 5.0})
        assert r.status_code == 403

    def test_admin_endpoints_reject_clients(self):
        r = requests.get(f"{API}/admin/vendor-products", headers=_h(VIP_TOKEN))
        assert r.status_code == 403

    def test_commission_endpoint(self):
        r = requests.get(f"{API}/vendor/commission", headers=_h(VIP_TOKEN))
        assert r.status_code == 200
        assert float(r.json()["commission_pct"]) >= 0


class TestVendorCredit:
    """Acreditación al vendedor al confirmar entrega + reverso al rechazar."""

    @classmethod
    def setup_class(cls):
        db = _db()
        prev = db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
        cls._prev_rate = prev.get("courier_rate_usdt_per_km")
        cls._prev_pct = prev.get("vendor_commission_pct")
        # Desactiva mensajería (guard 'delivered' se salta) y fija comisión 10%.
        db.settings.update_one(
            {"id": "global"},
            {"$set": {"id": "global", "courier_rate_usdt_per_km": 0,
                      "vendor_commission_pct": 10.0}},
            upsert=True)

    @classmethod
    def teardown_class(cls):
        db = _db()
        restore = {"courier_rate_usdt_per_km": cls._prev_rate,
                   "vendor_commission_pct": cls._prev_pct}
        unset = {k: "" for k, v in restore.items() if v is None}
        keep = {k: v for k, v in restore.items() if v is not None}
        ops = {}
        if keep:
            ops["$set"] = keep
        if unset:
            ops["$unset"] = unset
        if ops:
            db.settings.update_one({"id": "global"}, ops)

    def _vendor_usd_balance(self):
        u = _db().users.find_one({"user_id": "user_test_vip01"}, {"_id": 0})
        return float((u.get("vip_balances") or {}).get("USD", 0.0))

    def test_full_vendor_sale_cycle(self):
        db = _db()
        # 1) VIP publica y admin aprueba
        p = _vip_create_product(price_usd=40.0, stock=5)
        r = requests.post(f"{API}/admin/vendor-products/{p['id']}/approve",
                          headers=_h(ADMIN_TOKEN), json={})
        assert r.status_code == 200, r.text
        # 2) El comprador (admin actuando como cliente) canjea 2 → 80 USD
        db.users.update_one({"user_id": "user_test_admin01"},
                            {"$set": {"vip_balance_usd": 1000.0}})
        r = requests.post(f"{API}/vip/redeem", headers=_h(ADMIN_TOKEN),
                          json={"product_id": p["id"], "quantity": 2,
                                "delivery_address": "Calle vendor #2"})
        assert r.status_code == 200, r.text
        red = r.json()
        assert red["vendor_owner_id"] == "user_test_vip01"
        # No genera movimiento de inventario (producto de vendedor)
        assert db.inventory_movements.find_one({"ref_id": red["id"]}) is None
        # 3) delivered → crédito neto 80 × 0.9 = 72
        bal0 = self._vendor_usd_balance()
        r = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "delivered"})
        assert r.status_code == 200, r.text
        assert self._vendor_usd_balance() == bal0 + 72.0
        row = db.redemptions.find_one({"id": red["id"]}, {"_id": 0})
        assert row["vendor_credited_at"]
        assert row["vendor_credit_net"] == 72.0
        assert row["vendor_commission_pct"] == 10.0
        # 4) idempotencia: repetir delivered no duplica el crédito
        requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                     headers=_h(ADMIN_TOKEN), json={"status": "pending"})
        r = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "delivered"})
        assert r.status_code == 200, r.text
        assert self._vendor_usd_balance() == bal0 + 72.0
        # 5) rechazado después de acreditado → reverso del crédito
        r = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "rejected"})
        assert r.status_code == 200, r.text
        assert self._vendor_usd_balance() == bal0
        row = db.redemptions.find_one({"id": red["id"]}, {"_id": 0})
        assert row["vendor_credit_reversed_at"]

    def test_vendor_cannot_redeem_own_product(self):
        p = _vip_create_product(price_usd=5.0, stock=2)
        requests.post(f"{API}/admin/vendor-products/{p['id']}/approve",
                      headers=_h(ADMIN_TOKEN), json={})
        _db().users.update_one({"user_id": "user_test_vip01"},
                               {"$set": {"vip_balance_usd": 100.0}})
        r = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                          json={"product_id": p["id"], "quantity": 1,
                                "delivery_address": "x"})
        assert r.status_code == 400
        assert "propio producto" in r.json()["detail"]

    def test_vendor_product_rejected_from_inventory(self):
        p = _vip_create_product()
        r = _movement({"product_id": p["id"], "type": "entrada",
                       "quantity": 1, "note": MARK})
        assert r.status_code == 400
        assert "vendedores" in r.json()["detail"].lower()
