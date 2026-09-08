"""iter218 — Alerta de Stock Bajo: avisa a los admins (push + email + in-app)
cuando un producto de la EMPRESA cae al umbral configurable o se agota.

Cubre:
1. Venta que deja el stock por encima del umbral → sin alerta.
2. Caída al umbral → 1 notificación in-app 'low_stock' (nivel bajo) por admin.
3. Nueva venta dentro del rango bajo → NO duplica (dedup por nivel).
4. Stock llega a 0 → segunda alerta (nivel agotado).
5. Entrada que repone por encima del umbral limpia el flag → la próxima
   caída vuelve a avisar.
6. El umbral configurado en settings gobierna el estado 'bajo' del control.
7. Productos de vendedores VIP nunca generan alerta de inventario.
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER218TEST"
ADMIN_UID = "user_test_admin01"


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
        "description": "iter218", "image_url": "",
        "price_usd": 6.0, "cost_usd": 4.0, "stock": 10,
        "category": "iter218test", "is_active": True,
    }
    payload.update(overrides)
    r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _venta(pid, qty):
    r = requests.post(f"{API}/admin/inventory/movements", headers=_h(ADMIN_TOKEN),
                      json={"product_id": pid, "type": "venta",
                            "quantity": qty, "note": MARK})
    assert r.status_code == 200, r.text
    return r.json()


def _entrada(pid, qty):
    r = requests.post(f"{API}/admin/inventory/movements", headers=_h(ADMIN_TOKEN),
                      json={"product_id": pid, "type": "entrada",
                            "quantity": qty, "note": MARK})
    assert r.status_code == 200, r.text


def _alerts_for(pid, level=None):
    q = {"type": "low_stock", "recipient_user_id": ADMIN_UID,
         "data.product_id": pid}
    if level:
        q["data.level"] = level
    return list(_db().notifications.find(q, {"_id": 0}))


def _cleanup():
    db = _db()
    ids = [p["id"] for p in db.products.find({"category": "iter218test"}, {"id": 1})]
    db.products.delete_many({"category": "iter218test"})
    if ids:
        db.inventory_movements.delete_many({"product_id": {"$in": ids}})
        db.notifications.delete_many({"data.product_id": {"$in": ids}})


_PREV_THRESHOLD = None


def setup_module(module):
    global _PREV_THRESHOLD
    _cleanup()
    db = _db()
    prev = db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
    _PREV_THRESHOLD = prev.get("low_stock_threshold")
    db.settings.update_one({"id": "global"},
                           {"$set": {"id": "global", "low_stock_threshold": 4}},
                           upsert=True)


def teardown_module(module):
    _cleanup()
    db = _db()
    if _PREV_THRESHOLD is None:
        db.settings.update_one({"id": "global"},
                               {"$unset": {"low_stock_threshold": ""}})
    else:
        db.settings.update_one({"id": "global"},
                               {"$set": {"low_stock_threshold": _PREV_THRESHOLD}})


def test_full_low_stock_alert_cycle():
    p = _create_product(stock=6)
    # 1) 6 → 5 (> umbral 4): sin alerta
    _venta(p["id"], 1)
    assert _alerts_for(p["id"]) == []
    # 2) 5 → 4 (== umbral): alerta 'bajo'
    _venta(p["id"], 1)
    assert len(_alerts_for(p["id"], "bajo")) == 1
    doc = _db().products.find_one({"id": p["id"]}, {"_id": 0})
    assert doc["low_stock_alert_level"] == "bajo"
    # 3) 4 → 3 (sigue bajo): dedup, no duplica
    _venta(p["id"], 1)
    assert len(_alerts_for(p["id"], "bajo")) == 1
    # 4) 3 → 0: alerta 'agotado'
    _venta(p["id"], 3)
    assert len(_alerts_for(p["id"], "agotado")) == 1
    assert len(_alerts_for(p["id"])) == 2
    # 5) entrada repone a 10 (> umbral): limpia flag
    _entrada(p["id"], 10)
    doc = _db().products.find_one({"id": p["id"]}, {"_id": 0})
    assert "low_stock_alert_level" not in doc
    # nueva caída → vuelve a avisar
    _venta(p["id"], 7)  # 10 → 3
    assert len(_alerts_for(p["id"], "bajo")) == 2


def test_alert_message_includes_threshold_and_name():
    p = _create_product(stock=5)
    _venta(p["id"], 2)  # 5 → 3 ≤ 4
    alerts = _alerts_for(p["id"], "bajo")
    assert len(alerts) == 1
    a = alerts[0]
    assert p["name"] in a["message"]
    assert a["data"]["threshold"] == 4
    assert a["data"]["stock"] == 3


def test_control_estado_uses_configured_threshold():
    p = _create_product(stock=4)  # 4 == umbral configurado
    r = requests.get(f"{API}/admin/inventory/control", headers=_h(ADMIN_TOKEN))
    assert r.status_code == 200
    row = next(x for x in r.json() if x["product_id"] == p["id"])
    assert row["estado"] == "bajo"


def test_admin_manual_edit_to_zero_alerts():
    p = _create_product(stock=10)
    body = {k: p[k] for k in ("name", "description", "image_url", "price_usd",
                              "cost_usd", "category", "is_active")}
    body["stock"] = 0
    r = requests.put(f"{API}/admin/products/{p['id']}", headers=_h(ADMIN_TOKEN),
                     json=body)
    assert r.status_code == 200, r.text
    assert len(_alerts_for(p["id"], "agotado")) == 1


def test_vendor_products_never_alert():
    r = requests.post(f"{API}/vip/my-products", headers=_h(VIP_TOKEN),
                      json={"name": f"{MARK}_vendor_{int(time.time()*1000)}",
                            "price_usd": 9.0, "stock": 0,
                            "category": "iter218test"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert _alerts_for(pid) == []


def test_settings_expose_threshold():
    r = requests.get(f"{API}/admin/settings", headers=_h(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["low_stock_threshold"] == 4
