"""iter343 — H09: una auditoría de costo NO debe sobrescribir el precio del
histórico.

Bug del auditor (Fase 1): tanto el cambio de PRECIO de venta como la auditoría
del COSTO (WAC) se registraban como movimientos type='precio', y el histórico
(`build_cutoff_report`) interpretaba cualquiera de ellos como cambio de precio.
Resultado: la auditoría «Costo promedio ponderado» (WAC 220) pisaba el precio de
venta (550) y el histórico devolvía price=220.

Reproducción: apertura 8 @ costo 200 y precio 500; entrada de 2 @ costo 300 con
nuevo precio de venta 550. El histórico debe mostrar precio 550 y costo (WAC) 220.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _auth(tok):
    return {"Cookie": f"session_token={tok}"}


def _cleanup(pid):
    db = _db()
    db.products.delete_one({"id": pid})
    db.inventory_movements.delete_many({"product_id": pid})
    db.inventory_lots.delete_many({"product_id": pid})


def _entrada(pid, qty, unit_cost, sale_price=None):
    body = {"product_id": pid, "type": "entrada", "quantity": qty,
            "unit_cost": unit_cost}
    if sale_price is not None:
        body["sale_price"] = sale_price
    r = requests.post(f"{API}/admin/inventory/movements", json=body,
                      headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _report_row(pid):
    r = requests.get(f"{API}/admin/inventory/cutoff-report",
                     headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return next((p for p in r.json()["products"]
                 if p["product_id"] == pid), None)


def test_cost_audit_does_not_overwrite_history_price():
    name = f"TEST_H09_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/admin/products",
                      json={"name": name, "category": "test",
                            "price_usd": 500.0, "cost_usd": 200.0,
                            "stock": 0, "unit": "libra"},
                      headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    try:
        # apertura: 8 @ costo 200 (precio queda en 500, sin cambio)
        _entrada(pid, 8, 200.0)
        # entrada: 2 @ costo 300 con nuevo precio de venta 550
        _entrada(pid, 2, 300.0, sale_price=550.0)

        # se registran DOS movimientos 'precio' bien diferenciados
        db = _db()
        precios = list(db.inventory_movements.find(
            {"product_id": pid, "type": "precio"}, {"_id": 0}))
        kinds = sorted(m.get("change_kind") for m in precios)
        assert kinds == ["cost", "price"], f"kinds separados: {kinds}"

        # el histórico muestra PRECIO 550 y COSTO (WAC) 220
        row = _report_row(pid)
        assert row is not None
        assert abs(float(row["price"]) - 550.0) < 1e-6, f"price={row['price']}"
        assert abs(float(row["wac"]) - 220.0) < 1e-6, f"wac={row['wac']}"
        assert abs(float(row["final_stock"]) - 10.0) < 1e-6
    finally:
        _cleanup(pid)


def test_legacy_cost_audit_detected_by_note():
    """Compatibilidad: movimientos heredados SIN `change_kind` cuya nota empieza
    por «Costo…» también se tratan como auditoría de costo y no pisan el precio."""
    name = f"TEST_H09L_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/admin/products",
                      json={"name": name, "category": "test",
                            "price_usd": 500.0, "cost_usd": 200.0,
                            "stock": 10, "unit": "libra"},
                      headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    db = _db()
    from datetime import datetime, timedelta, timezone
    t0 = datetime.now(timezone.utc).replace(microsecond=0)
    e_at = t0.isoformat()
    p_at = (t0 + timedelta(seconds=1)).isoformat()
    c_at = (t0 + timedelta(seconds=2)).isoformat()
    try:
        # entrada heredada para fijar WAC 200
        db.inventory_movements.insert_one({
            "id": str(uuid.uuid4()), "product_id": pid, "product_name": name,
            "type": "entrada", "quantity": 10, "unit_cost": 200.0,
            "unit_price": 0.0, "total": 2000.0, "created_at": e_at})
        # cambio de precio heredado (sin change_kind): 500 → 550
        db.inventory_movements.insert_one({
            "id": str(uuid.uuid4()), "product_id": pid, "product_name": name,
            "type": "precio", "quantity": 0, "unit_price": 550.0,
            "unit_cost": 0.0, "note": "Precio venta: 500 → 550",
            "created_at": p_at})
        # auditoría de costo heredada (sin change_kind): nota «Costo…»
        db.inventory_movements.insert_one({
            "id": str(uuid.uuid4()), "product_id": pid, "product_name": name,
            "type": "precio", "quantity": 0, "unit_price": 220.0,
            "unit_cost": 0.0, "note": "Costo promedio ponderado: 200 → 220",
            "created_at": c_at})
        row = _report_row(pid)
        assert row is not None
        assert abs(float(row["price"]) - 550.0) < 1e-6, f"price={row['price']}"
    finally:
        _cleanup(pid)
