"""iter350c — RV-05 / H12: editar la unidad actual NO debe reinterpretar
cantidades históricas.

Bug del auditor:
- `inventory_history.build_cutoff_report` tomaba la unidad de la FICHA VIVA, así
  que cambiar la unidad del producto hoy hacía que un corte pasado de 10 lb
  pasara a mostrar «10 kg» (sin conversión), aunque el movimiento de apertura
  siguiera en libras.
- `routes/market.update_product` aceptaba el cambio simple de unidad.

Fix (defensa en dos capas):
1) El corte deriva la unidad del PERÍODO de la evidencia histórica (unidad
   congelada en los movimientos / el conteo), no de la ficha viva.
2) `update_product` RECHAZA (409) cambiar la unidad de un producto con
   movimientos o conteos históricos.
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


def _hard_cleanup(pid):
    db = _db()
    db.inventory_movements.delete_many({"product_id": pid})
    db.inventory_lots.delete_many({"product_id": pid})
    db.inventory_counts.delete_many({"product_id": pid})
    db.products.delete_one({"id": pid})


def _create(stock, unit="unidad", cost=20.0, price=500.0):
    name = f"TEST_H12U_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/admin/products",
                      json={"name": name, "category": "test",
                            "price_usd": price, "cost_usd": cost,
                            "stock": stock, "unit": unit},
                      headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()["id"], name


def _update(pid, name, unit, stock=5, cost=20.0, price=500.0):
    return requests.put(f"{API}/admin/products/{pid}",
                        json={"name": name, "category": "test",
                              "price_usd": price, "cost_usd": cost,
                              "stock": stock, "unit": unit},
                        headers=_auth(ADMIN_TOKEN))


def _report_row(pid):
    r = requests.get(f"{API}/admin/inventory/cutoff-report",
                     headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return next((p for p in r.json()["products"]
                 if p["product_id"] == pid), None)


def test_cutoff_preserves_historical_unit():
    """El corte muestra la unidad CONGELADA en el movimiento (libra), aunque la
    ficha viva se altere a kg por otra vía."""
    pid, name = _create(stock=10, unit="libra")
    try:
        # El movimiento de apertura quedó en libras.
        mov = _db().inventory_movements.find_one({"product_id": pid})
        assert mov and mov.get("unit") == "libra"
        # Alteramos la ficha viva a kg saltándonos la ruta (simula desajuste).
        _db().products.update_one({"id": pid}, {"$set": {"unit": "kg"}})

        row = _report_row(pid)
        assert row is not None
        assert abs(float(row["final_stock"]) - 10.0) < 1e-6
        # La unidad del corte proviene de la evidencia histórica, NO de la ficha.
        assert row["unit"] == "libra", f"esperaba libra, got {row['unit']}"
    finally:
        _hard_cleanup(pid)


def test_update_rejects_unit_change_with_movements():
    """Con movimientos, cambiar la unidad se RECHAZA (409) y la ficha no cambia."""
    pid, name = _create(stock=5, unit="libra")
    try:
        assert _db().inventory_movements.count_documents(
            {"product_id": pid}) >= 1
        r = _update(pid, name, unit="kg", stock=5)
        assert r.status_code == 409, r.text
        assert "unidad" in (r.json().get("detail") or "").lower()
        # La ficha conserva la unidad original.
        assert _db().products.find_one({"id": pid})["unit"] == "libra"
    finally:
        _hard_cleanup(pid)


def test_update_rejects_unit_change_with_counts():
    """Con un conteo histórico (sin movimientos), también se RECHAZA."""
    pid, name = _create(stock=0, unit="unidad")
    try:
        assert _db().inventory_movements.count_documents(
            {"product_id": pid}) == 0
        _db().inventory_counts.insert_one({
            "id": str(uuid.uuid4()), "product_id": pid, "product_name": name,
            "count_date": "2026-05-01", "counted_qty": 0.0,
            "theoretical_stock": 0.0, "difference": 0.0, "unit": "unidad"})
        r = _update(pid, name, unit="libra", stock=0)
        assert r.status_code == 409, r.text
        assert _db().products.find_one({"id": pid})["unit"] == "unidad"
    finally:
        _hard_cleanup(pid)


def test_update_allows_unit_change_without_history():
    """Un producto sin historial (stock 0, sin movimientos/conteos) SÍ puede
    cambiar de unidad."""
    pid, name = _create(stock=0, unit="unidad")
    try:
        assert _db().inventory_movements.count_documents(
            {"product_id": pid}) == 0
        r = _update(pid, name, unit="libra", stock=0)
        assert r.status_code == 200, r.text
        assert _db().products.find_one({"id": pid})["unit"] == "libra"
    finally:
        _hard_cleanup(pid)
