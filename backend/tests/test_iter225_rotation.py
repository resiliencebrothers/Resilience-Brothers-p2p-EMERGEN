"""iter225 — Rotación de inventario (GET /admin/inventory/rotation):
ritmo de venta del período, días para agotarse, rotación del stock y ciclo
de reposición entre entradas.
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, today_havana

API = f"{BASE_URL}/api"
MARK = "ITER225TEST"


def _h(tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _cleanup():
    db = _db()
    ids = [p["id"] for p in db.products.find({"category": "iter225test"}, {"id": 1})]
    db.products.delete_many({"category": "iter225test"})
    if ids:
        db.inventory_movements.delete_many({"product_id": {"$in": ids}})
        db.notifications.delete_many({"data.product_id": {"$in": ids}})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


def _create_product(**overrides):
    payload = {"name": f"{MARK}_{int(time.time()*1000)}", "description": "",
               "image_url": "", "price_usd": 10.0, "cost_usd": 6.0,
               "stock": 20, "category": "iter225test", "is_active": True}
    payload.update(overrides)
    r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _mov(pid, mtype, qty):
    r = requests.post(f"{API}/admin/inventory/movements", headers=_h(ADMIN_TOKEN),
                      json={"product_id": pid, "type": mtype,
                            "quantity": qty, "note": MARK})
    assert r.status_code == 200, r.text


def _rotation(**params):
    r = requests.get(f"{API}/admin/inventory/rotation", params=params,
                     headers=_h(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def test_rotation_math_single_day():
    p = _create_product(stock=20)
    _mov(p["id"], "venta", 5)       # stock 15
    _mov(p["id"], "entrada", 10)    # stock 25 (1ª entrada)
    _mov(p["id"], "entrada", 5)     # stock 30 (2ª entrada → ciclo calculable)
    today = today_havana()
    rows = {x["product_id"]: x for x in _rotation(
        start=today, end=today, product_ids=p["id"])}
    row = rows[p["id"]]
    assert row["sold"] == 5
    assert row["daily_rate"] == 5.0          # 5 vendidas / 1 día
    assert row["stock"] == 30
    assert row["sellout_days"] == 6.0        # 30 / 5 por día
    # rotación = vendidas / (stock + vendidas/2) = 5 / 32.5
    assert row["rotation"] == round(5 / 32.5, 2)
    assert row["days_since_restock"] == 0    # entrada de hoy
    assert row["restock_cycle_days"] is not None  # 2 entradas → ciclo
    # iter226 — se agota en 6 días (≤7) → sugerencia 'pronto'
    assert row["restock_suggestion"] == "pronto"
    assert row["suggested_qty"] == 40        # ceil(5×14 − 30)


def test_restock_now_when_out_of_stock():
    p = _create_product(stock=4)
    _mov(p["id"], "venta", 4)  # agotado con demanda
    today = today_havana()
    rows = {x["product_id"]: x for x in _rotation(
        start=today, end=today, product_ids=p["id"])}
    row = rows[p["id"]]
    assert row["stock"] == 0
    assert row["restock_suggestion"] == "ya"
    assert row["suggested_qty"] == 56        # ceil(4×14 − 0)


def test_urgent_rows_sorted_first():
    slow = _create_product(stock=500)
    urgent = _create_product(stock=2)
    _mov(slow["id"], "venta", 9)   # más vendida pero sobra stock
    _mov(urgent["id"], "venta", 2) # agotada → 'ya'
    today = today_havana()
    rows = _rotation(start=today, end=today,
                     product_ids=f"{slow['id']},{urgent['id']}")
    assert rows[0]["product_id"] == urgent["id"]
    assert rows[0]["restock_suggestion"] == "ya"


def test_rotation_no_sales_fields_null():
    p = _create_product(stock=8)
    today = today_havana()
    rows = {x["product_id"]: x for x in _rotation(
        start=today, end=today, product_ids=p["id"])}
    row = rows[p["id"]]
    assert row["sold"] == 0
    assert row["sellout_days"] is None
    assert row["rotation"] == 0.0
    # iter226 — el alta con stock inicial cuenta como reposición de hoy.
    assert row["days_since_restock"] == 0
    assert row["restock_cycle_days"] is None


def test_rotation_respects_product_filter_and_sorting():
    p1 = _create_product()
    p2 = _create_product()
    _mov(p1["id"], "venta", 3)
    _mov(p2["id"], "venta", 7)
    today = today_havana()
    rows = _rotation(start=today, end=today,
                     product_ids=f"{p1['id']},{p2['id']}")
    assert [r["product_id"] for r in rows] == [p2["id"], p1["id"]]  # más vendida primero


def test_rotation_forbidden_for_clients():
    r = requests.get(f"{API}/admin/inventory/rotation", headers=_h(VIP_TOKEN))
    assert r.status_code == 403
