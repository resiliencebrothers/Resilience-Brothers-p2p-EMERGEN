"""iter343 — H10: borrar un producto no debe eliminar su saldo histórico.

Bug del auditor (Fase 1): `DELETE /admin/products/{id}` borraba la ficha
físicamente aunque tuviera movimientos; como `build_cutoff_report` solo admite
productos que aún existen o con conteo en la fecha, el corte perdía la fila y el
saldo documentado (p. ej. 12 @ 20 = 240 CUP) desaparecía sin rastro.

Política del equipo (visible y trazable): NO se permite el borrado físico cuando
existen movimientos/conteos; hay que DESACTIVAR el producto (soft delete), que ya
lo contempla el histórico (incluye inactivos).

Criterio: retirar una mercancía con historial no hace desaparecer su saldo; un
producto nuevo sin movimientos sí se puede borrar.
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


def _create(stock, cost=20.0, price=500.0):
    name = f"TEST_H10_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/admin/products",
                      json={"name": name, "category": "test",
                            "price_usd": price, "cost_usd": cost,
                            "stock": stock, "unit": "unidad"},
                      headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _report_row(pid):
    r = requests.get(f"{API}/admin/inventory/cutoff-report",
                     headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return next((p for p in r.json()["products"]
                 if p["product_id"] == pid), None)


def test_delete_blocked_when_product_has_movements():
    # apertura documentada de 12 @ costo 20 (genera movimiento de entrada)
    pid = _create(stock=12, cost=20.0)
    try:
        # el corte muestra el saldo documentado (240 CUP)
        row = _report_row(pid)
        assert row is not None
        assert abs(float(row["final_stock"]) - 12.0) < 1e-6
        assert abs(float(row["value"]) - 240.0) < 1e-6

        # el borrado físico queda BLOQUEADO con regla visible
        r = requests.delete(f"{API}/admin/products/{pid}",
                            headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 409, r.text
        assert "desact" in (r.json().get("detail") or "").lower()

        # la ficha sigue existiendo y el saldo histórico permanece intacto
        assert _db().products.find_one({"id": pid}) is not None
        assert _report_row(pid) is not None

        # al DESACTIVAR, el producto se retira de la operación pero sigue en el
        # histórico (allowed incluye inactivos) → saldo documentado conservado
        tr = requests.post(f"{API}/admin/products/{pid}/toggle-active", json={},
                           headers=_auth(ADMIN_TOKEN))
        assert tr.status_code == 200, tr.text
        assert _db().products.find_one({"id": pid})["is_active"] is False
        row2 = _report_row(pid)
        assert row2 is not None
        assert abs(float(row2["value"]) - 240.0) < 1e-6
    finally:
        _hard_cleanup(pid)


def test_delete_allowed_when_no_movements():
    # producto nuevo sin stock → sin movimientos → se puede borrar
    pid = _create(stock=0)
    try:
        assert _db().inventory_movements.count_documents({"product_id": pid}) == 0
        r = requests.delete(f"{API}/admin/products/{pid}",
                            headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        assert _db().products.find_one({"id": pid}) is None
    finally:
        _hard_cleanup(pid)
