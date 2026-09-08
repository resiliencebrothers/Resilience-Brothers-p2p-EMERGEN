"""iter229 — Precios de tienda física (CUP efectivo) ↔ USDT en la web.

Cubre:
- GET /products: producto de la empresa muestra price_usdt según el rol
  (VIP → rate_vip mayorista, anónimo/normal → rate_normal minorista) +
  price_store/store_currency con el equivalente en efectivo.
- Productos de vendedores VIP quedan en USDT sin conversión.
- Canje web: cobra en USDT (saldo baja el monto convertido), guarda snapshot
  (total_store, fx_rate) y el capital entra al fondo en USDT.
- Rechazo → reverso del fondo en USDT.
- Entrada de mercancía (compra) → SALE del fondo en la moneda de la tienda.
- Alta de producto con stock inicial → también sale del fondo (compra).
- Venta manual en tienda física → ENTRA al fondo en la moneda de la tienda.
- Sin tasa configurada → canje 400 y price_usdt None.
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER229TEST"
CUR = "CUPX229"
RATE_VIP = 400.0
RATE_NORMAL = 380.0


def _h(tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _create_product(**overrides):
    payload = {
        "name": f"{MARK}_Prod_{int(time.time() * 1000)}",
        "price_usd": 800.0, "cost_usd": 500.0, "stock": 10,
        "category": "iter229test", "is_active": True,
    }
    payload.update(overrides)
    r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


class TestStoreFx:
    @classmethod
    def setup_class(cls):
        db = _db()
        cls._prev_code = (db.settings.find_one({"id": "global"}) or {}).get(
            "store_currency_code")
        db.currencies.update_one(
            {"code": CUR},
            {"$setOnInsert": {"id": f"cur_{MARK}", "code": CUR,
                              "name": "CUP Efectivo Test229", "type": "fiat"}},
            upsert=True)
        db.rates.update_one(
            {"from_code": "USDT", "to_code": CUR},
            {"$set": {"rate_normal": RATE_NORMAL, "rate_vip": RATE_VIP},
             "$setOnInsert": {"id": f"rate_{MARK}"}},
            upsert=True)
        db.settings.update_one({"id": "global"},
                               {"$set": {"store_currency_code": CUR}},
                               upsert=True)

    @classmethod
    def teardown_class(cls):
        db = _db()
        db.settings.update_one(
            {"id": "global"},
            {"$set": {"store_currency_code": cls._prev_code}}
            if cls._prev_code else {"$unset": {"store_currency_code": ""}})
        db.rates.delete_many({"to_code": CUR})
        db.currencies.delete_many({"code": CUR})

    def teardown_method(self, _):
        db = _db()
        ids = [p["id"] for p in db.products.find({"name": {"$regex": f"^{MARK}"}})]
        db.products.delete_many({"id": {"$in": ids}})
        movs = [m["id"] for m in db.inventory_movements.find(
            {"product_id": {"$in": ids}})]
        db.inventory_movements.delete_many({"product_id": {"$in": ids}})
        reds = [r["id"] for r in db.redemptions.find(
            {"product_id": {"$in": ids}})]
        db.redemptions.delete_many({"product_id": {"$in": ids}})
        db.company_fund_adjustments.delete_many(
            {"ref_id": {"$in": movs + reds}})
        db.deliveries.delete_many({"source_id": {"$in": reds}})

    # ---------- Display web ----------

    def test_products_price_usdt_by_role(self):
        p = _create_product(price_usd=800.0)
        vip = next(x for x in requests.get(
            f"{API}/products", headers=_h(VIP_TOKEN)).json() if x["id"] == p["id"])
        assert vip["price_usdt"] == 2.0            # 800 / 400 (rate_vip)
        assert vip["price_store"] == 800.0
        assert vip["store_currency"] == CUR
        assert vip["fx_rate"] == RATE_VIP

        anon = next(x for x in requests.get(
            f"{API}/products").json() if x["id"] == p["id"])
        assert anon["price_usdt"] == round(800 / RATE_NORMAL, 2)  # minorista
        assert anon["fx_rate"] == RATE_NORMAL

    def test_admin_products_include_web_equivalent(self):
        p = _create_product(price_usd=1200.0)
        row = next(x for x in requests.get(
            f"{API}/admin/products", headers=_h(ADMIN_TOKEN)).json()
            if x["id"] == p["id"])
        assert row["price_usdt"] == 3.0            # 1200 / 400
        assert row["store_currency"] == CUR

    # ---------- Canje web en USDT ----------

    def test_redeem_charges_usdt_and_fund_inflow_usdt(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {"vip_balances.USDT": 5000.0, "vip_balance_usd": 0.0}})
        p = _create_product(price_usd=800.0, cost_usd=500.0, stock=10)
        r = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                          json={"product_id": p["id"], "quantity": 2,
                                "delivery_address": "Calle iter229 #1"})
        assert r.status_code == 200, r.text
        red = r.json()
        # 1600 CUP / 400 = 4.00 USDT
        assert red["total_usd"] == 4.0
        assert red["total_store"] == 1600.0
        assert red["store_currency"] == CUR
        assert red["fx_rate"] == RATE_VIP
        assert red["cost_usd"] == 2.5              # 1000 / 400
        # saldo bajó exactamente el monto USDT
        u = db.users.find_one({"user_id": "user_test_vip01"})
        assert round(float(u["vip_balances"]["USDT"]), 2) == 4996.0
        # fondo: entrada USDT
        adj = db.company_fund_adjustments.find_one(
            {"ref_id": red["id"], "adjustment_type": "inflow"}, {"_id": 0})
        assert adj and adj["currency"] == "USDT" and adj["amount"] == 4.0
        # libros de la tienda siguen en CUP: movimiento venta con total 1600
        mov = db.inventory_movements.find_one(
            {"ref_id": red["id"], "type": "venta"}, {"_id": 0})
        assert mov["total"] == 1600.0

        # rechazo → reembolso USDT + reverso del fondo en USDT
        rr = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "rejected"})
        assert rr.status_code == 200, rr.text
        u = db.users.find_one({"user_id": "user_test_vip01"})
        assert round(float(u["vip_balances"]["USDT"]), 2) == 5000.0
        out = db.company_fund_adjustments.find_one(
            {"ref_id": red["id"], "adjustment_type": "outflow"}, {"_id": 0})
        assert out and out["currency"] == "USDT" and out["amount"] == 4.0

    # ---------- Fondo CUP efectivo ----------

    def test_initial_stock_purchase_deducts_store_fund(self):
        db = _db()
        p = _create_product(cost_usd=500.0, stock=10)
        mov = db.inventory_movements.find_one(
            {"product_id": p["id"], "type": "entrada"}, {"_id": 0})
        adj = db.company_fund_adjustments.find_one(
            {"ref_id": mov["id"]}, {"_id": 0})
        assert adj is not None
        assert adj["adjustment_type"] == "outflow"
        assert adj["currency"] == CUR
        assert adj["amount"] == 5000.0             # 500 × 10
        assert adj["source_name"] == "Inventario tienda física"

    def test_manual_entrada_deducts_and_manual_venta_adds_store_fund(self):
        db = _db()
        p = _create_product(price_usd=800.0, cost_usd=500.0, stock=0)
        # compra de 4 unidades a 550
        r = requests.post(f"{API}/admin/inventory/movements",
                          headers=_h(ADMIN_TOKEN), json={
                              "product_id": p["id"], "type": "entrada",
                              "quantity": 4, "unit_cost": 550.0})
        assert r.status_code == 200, r.text
        adj = db.company_fund_adjustments.find_one(
            {"ref_id": r.json()["id"]}, {"_id": 0})
        assert adj["adjustment_type"] == "outflow"
        assert adj["currency"] == CUR and adj["amount"] == 2200.0

        # venta en tienda física de 3 al precio del producto (cliente sin app)
        r2 = requests.post(f"{API}/admin/inventory/movements",
                           headers=_h(ADMIN_TOKEN), json={
                               "product_id": p["id"], "type": "venta",
                               "quantity": 3})
        assert r2.status_code == 200, r2.text
        adj2 = db.company_fund_adjustments.find_one(
            {"ref_id": r2.json()["id"]}, {"_id": 0})
        assert adj2["adjustment_type"] == "inflow"
        assert adj2["currency"] == CUR and adj2["amount"] == 2400.0

    def test_marketplace_venta_does_not_double_count_store_fund(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {"vip_balances.USDT": 5000.0, "vip_balance_usd": 0.0}})
        p = _create_product(price_usd=400.0, stock=5)
        r = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                          json={"product_id": p["id"], "quantity": 1,
                                "delivery_address": "Calle iter229 #2"})
        assert r.status_code == 200, r.text
        mov = db.inventory_movements.find_one(
            {"ref_id": r.json()["id"], "type": "venta"}, {"_id": 0})
        # la venta web NO genera entrada al fondo en moneda tienda
        assert db.company_fund_adjustments.find_one(
            {"ref_id": mov["id"]}) is None

    # ---------- Sin tasa configurada ----------

    def test_missing_rate_blocks_redeem_and_hides_web_price(self):
        db = _db()
        db.rates.delete_many({"to_code": CUR})
        try:
            p = _create_product(price_usd=800.0, stock=5)
            row = next(x for x in requests.get(
                f"{API}/products", headers=_h(VIP_TOKEN)).json()
                if x["id"] == p["id"])
            assert row["price_usdt"] is None
            r = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                              json={"product_id": p["id"], "quantity": 1,
                                    "delivery_address": "Calle iter229 #3"})
            assert r.status_code == 400
            assert "tasa" in r.json()["detail"].lower()
        finally:
            db.rates.update_one(
                {"from_code": "USDT", "to_code": CUR},
                {"$set": {"rate_normal": RATE_NORMAL, "rate_vip": RATE_VIP},
                 "$setOnInsert": {"id": f"rate_{MARK}"}},
                upsert=True)

    def test_vendor_product_stays_usdt(self):
        db = _db()
        pid = f"prod_{MARK}_vendor"
        db.products.insert_one({
            "id": pid, "name": f"{MARK}_VendorProd", "price_usd": 25.0,
            "stock": 3, "owner_id": "user_test_vip01",
            "owner_name": "Vip Test", "is_active": True,
            "approval_status": "approved", "created_at": "2026-06-20T00:00:00Z",
        })
        row = next(x for x in requests.get(
            f"{API}/products", headers=_h(VIP_TOKEN)).json() if x["id"] == pid)
        assert row["price_usdt"] == 25.0
        assert row["price_store"] is None
        assert row["store_currency"] is None
