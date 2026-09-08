"""iter230 — Cierre diario de la tienda física.

Cubre:
- GET /admin/inventory/daily-close agrega ventas físicas, compras (alta +
  entradas manuales) y ganancia en la moneda de la tienda, con caja neta.
- Ventas web aparecen aparte (USDT desde el canje) y se excluyen las
  rechazadas.
- Fecha inválida → 400; cliente normal → 403; día sin movimientos → ceros.
"""
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER230TEST"
TODAY = datetime.now(ZoneInfo("America/Havana")).strftime("%Y-%m-%d")


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
        "category": "iter230test", "is_active": True,
    }
    payload.update(overrides)
    r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _close(date=None, tok=ADMIN_TOKEN):
    params = {"date": date} if date else {}
    return requests.get(f"{API}/admin/inventory/daily-close",
                        params=params, headers=_h(tok))


class TestDailyClose:
    def teardown_method(self, _):
        db = _db()
        ids = [p["id"] for p in db.products.find({"name": {"$regex": f"^{MARK}"}})]
        movs = [m["id"] for m in db.inventory_movements.find(
            {"product_id": {"$in": ids}})]
        reds = [r["id"] for r in db.redemptions.find({"product_id": {"$in": ids}})]
        db.products.delete_many({"id": {"$in": ids}})
        db.inventory_movements.delete_many({"product_id": {"$in": ids}})
        db.redemptions.delete_many({"id": {"$in": reds}})
        db.company_fund_adjustments.delete_many({"ref_id": {"$in": movs + reds}})
        db.deliveries.delete_many({"source_id": {"$in": reds}})

    def test_daily_close_aggregates_store_and_web(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {"vip_balances.USDT": 5000.0}})
        p = _create_product()  # alta: compra 10×500 = 5000
        pid = p["id"]
        # venta física 2×800 = 1600, ganancia (800−500)×2 = 600
        r = requests.post(f"{API}/admin/inventory/movements",
                          headers=_h(ADMIN_TOKEN),
                          json={"product_id": pid, "type": "venta", "quantity": 2})
        assert r.status_code == 200, r.text
        # compra manual 4×550 = 2200
        r = requests.post(f"{API}/admin/inventory/movements",
                          headers=_h(ADMIN_TOKEN),
                          json={"product_id": pid, "type": "entrada",
                                "quantity": 4, "unit_cost": 550.0})
        assert r.status_code == 200, r.text
        # venta web 1 (conftest: CUPFX tasa 1:1 → 800 USDT)
        rw = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                           json={"product_id": pid, "quantity": 1,
                                 "delivery_address": "Calle iter230 #1"})
        assert rw.status_code == 200, rw.text

        body = _close(TODAY).json()
        assert body["date"] == TODAY
        row = next(x for x in body["productos"] if x["product_id"] == pid)
        assert row["unidades"] == 2
        assert row["unidades_web"] == 1
        assert row["total"] == 2400.0          # 1600 física + 800 web
        # la entrada a 550 actualiza el costo del producto → web (800−550)=250
        assert row["ganancia"] == 850.0        # 600 física + 250 web
        compra = next(x for x in body["compras_detalle"] if x["product_id"] == pid)
        assert compra["unidades"] == 14        # 10 alta + 4 manual
        assert compra["total"] == 7200.0       # 5000 + 2200
        # los globales incluyen al menos lo de este producto
        assert body["fisica"]["ventas"] >= 1600.0
        assert body["fisica"]["compras"] >= 7200.0
        assert body["fisica"]["ganancia"] >= 600.0
        assert body["web"]["ventas_usdt"] >= 800.0
        assert body["fisica"]["caja_neta"] == round(
            body["fisica"]["ventas"] - body["fisica"]["compras"], 2)

    def test_rejected_web_sale_excluded(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {"vip_balances.USDT": 5000.0}})
        p = _create_product(price_usd=400.0, stock=5)
        rw = requests.post(f"{API}/vip/redeem", headers=_h(VIP_TOKEN),
                           json={"product_id": p["id"], "quantity": 1,
                                 "delivery_address": "Calle iter230 #2"})
        assert rw.status_code == 200, rw.text
        red_id = rw.json()["id"]
        requests.put(f"{API}/admin/redemptions/{red_id}/status",
                     headers=_h(ADMIN_TOKEN), json={"status": "rejected"})
        body = _close(TODAY).json()
        row = next((x for x in body["productos"]
                    if x["product_id"] == p["id"]), None)
        assert row is None or row["unidades_web"] == 0

    def test_empty_day_returns_zeros(self):
        body = _close("2020-01-05").json()
        assert body["fisica"]["ventas"] == 0
        assert body["fisica"]["compras"] == 0
        assert body["web"]["num_ventas"] == 0
        assert body["productos"] == []

    def test_invalid_date_400_and_normal_403(self):
        assert _close("20-01-2026").status_code == 400
        assert _close(TODAY, tok=NORMAL_TOKEN).status_code == 403

    # ---------- iter231: PDF del cierre ----------

    def _close_pdf(self, date=None, tok=ADMIN_TOKEN):
        params = {"date": date} if date else {}
        return requests.get(f"{API}/admin/inventory/daily-close.pdf",
                            params=params, headers=_h(tok))

    def test_close_pdf_valid(self):
        p = _create_product()
        requests.post(f"{API}/admin/inventory/movements",
                      headers=_h(ADMIN_TOKEN),
                      json={"product_id": p["id"], "type": "venta", "quantity": 1})
        r = self._close_pdf(TODAY)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 1500
        assert f"cierre_tienda_{TODAY}" in r.headers["content-disposition"]

    def test_close_pdf_empty_day_still_valid(self):
        r = self._close_pdf("2020-01-05")
        assert r.status_code == 200
        assert r.content[:5] == b"%PDF-"

    def test_close_pdf_guards(self):
        assert self._close_pdf("bad-date").status_code == 400
        assert self._close_pdf(TODAY, tok=NORMAL_TOKEN).status_code == 403
