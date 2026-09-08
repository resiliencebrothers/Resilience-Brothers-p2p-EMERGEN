"""iter226 — Alta de producto: anti-duplicados + reponer existente.

Cubre:
- Crear producto con stock inicial > 0 registra una Entrada (source='alta')
  auditada, sin duplicar el stock (apply_stock=False).
- Crear otro producto con el mismo nombre (aunque cambie mayúsculas/acentos)
  → 409 con mensaje que sugiere registrar una Entrada.
- Reponer existente vía POST /admin/inventory/movements suma stock y las
  estadísticas (entradas) se acumulan en el MISMO producto.
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER226TEST"


def _h(tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _cleanup(name_prefix):
    db = _db()
    ids = [p["id"] for p in db.products.find({"name": {"$regex": f"^{name_prefix}"}})]
    db.products.delete_many({"id": {"$in": ids}})
    db.inventory_movements.delete_many({"product_id": {"$in": ids}})


def test_initial_stock_recorded_as_entrada_without_double_stock():
    name = f"{MARK}_Cafe_{int(time.time() * 1000)}"
    try:
        r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json={
            "name": name, "price_usd": 9.0, "cost_usd": 5.0,
            "stock": 7, "category": "iter226test", "is_active": True,
        })
        assert r.status_code == 200, r.text
        prod = r.json()

        db = _db()
        stored = db.products.find_one({"id": prod["id"]})
        assert stored["stock"] == 7  # apply_stock=False: no doble conteo

        movs = list(db.inventory_movements.find({"product_id": prod["id"]}))
        assert len(movs) == 1
        assert movs[0]["type"] == "entrada"
        assert movs[0]["quantity"] == 7
        assert movs[0]["source"] == "alta"
        assert movs[0]["total"] == 35.0  # costo 5 × 7
    finally:
        _cleanup(name)


def test_zero_stock_creation_records_no_movement():
    name = f"{MARK}_Sal_{int(time.time() * 1000)}"
    try:
        r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json={
            "name": name, "price_usd": 2.0, "stock": 0,
            "category": "iter226test",
        })
        assert r.status_code == 200, r.text
        db = _db()
        assert db.inventory_movements.count_documents(
            {"product_id": r.json()["id"]}) == 0
    finally:
        _cleanup(name)


def test_duplicate_name_rejected_409_even_with_accents_and_case():
    name = f"{MARK}_Azucar_{int(time.time() * 1000)}"
    try:
        r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json={
            "name": name, "price_usd": 4.0, "stock": 3,
            "category": "iter226test",
        })
        assert r.status_code == 200, r.text

        # mismo nombre exacto → 409
        r2 = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json={
            "name": name, "price_usd": 4.5, "stock": 2,
            "category": "iter226test",
        })
        assert r2.status_code == 409, r2.text
        assert "Entrada" in r2.json()["detail"]

        # variante con mayúsculas, acento y espacios extra → 409 igual
        variant = "  " + name.upper().replace("AZUCAR", "AZÚCAR") + "  "
        r3 = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json={
            "name": variant, "price_usd": 4.5, "stock": 2,
            "category": "iter226test",
        })
        assert r3.status_code == 409, r3.text

        # solo debe existir 1 producto con ese nombre
        db = _db()
        assert db.products.count_documents(
            {"name": {"$regex": f"^{MARK}_Azucar"}}) == 1
    finally:
        _cleanup(name)


def test_restock_existing_accumulates_stats_on_same_product():
    name = f"{MARK}_Arroz_{int(time.time() * 1000)}"
    try:
        r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json={
            "name": name, "price_usd": 10.0, "cost_usd": 6.0,
            "stock": 5, "category": "iter226test",
        })
        assert r.status_code == 200, r.text
        pid = r.json()["id"]

        # reposición (flujo 'Reponer existente' del diálogo)
        r2 = requests.post(f"{API}/admin/inventory/movements",
                           headers=_h(ADMIN_TOKEN), json={
                               "product_id": pid, "type": "entrada",
                               "quantity": 8, "unit_cost": 6.5,
                               "note": "reposición iter226",
                           })
        assert r2.status_code == 200, r2.text

        # control: stock acumulado 13 y entradas 5+8=13 en el MISMO producto
        rows = requests.get(f"{API}/admin/inventory/control",
                            headers=_h(ADMIN_TOKEN)).json()
        row = next(x for x in rows if x["product_id"] == pid)
        assert row["stock"] == 13
        assert row["entradas"] == 13
    finally:
        _cleanup(name)
