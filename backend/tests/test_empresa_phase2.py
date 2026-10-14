"""Empresa Fase 2 (EMP-02) — inventario por ubicación + distribución central→tienda.

Verifica el modelo no disruptivo (central = stock − distributed):
- receive incrementa el stock total (almacén central).
- distribute mueve central→tienda de forma atómica; sobre-distribuir → 409.
- return devuelve tienda→central; devolver de más → 409.
- borrar una tienda devuelve su mercancía al central.
- el log de movimientos registra cada operación.
"""
import os
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL

API = f"{BASE_URL}/api"
EMP_ID = "user_test_empresa02"
EMP_TOKEN = "test_session_empresa02_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {EMP_TOKEN}", "Content-Type": "application/json"}


def _seed():
    db = _db()
    db.users.update_one({"user_id": EMP_ID}, {"$set": {
        "user_id": EMP_ID, "email": "empresa2.test@example.com",
        "name": "Empresa Inv Test", "role": "empresa", "account_status": "active",
        "email_verified": True, "phone_verified": True, "phone": "+5350000222"}},
        upsert=True)
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    db.user_sessions.update_one({"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_ID, "expires_at": exp}},
        upsert=True)


def _cleanup():
    db = _db()
    db.products.delete_many({"company_id": EMP_ID})
    db.stores.delete_many({"company_id": EMP_ID})
    db.company_inventory_moves.delete_many({"company_id": EMP_ID})


def _row(pid):
    r = requests.get(f"{API}/company/inventory", headers=_hdr(), timeout=15)
    assert r.status_code == 200, r.text
    for row in r.json():
        if row["product_id"] == pid:
            return row
    return None


def test_full_inventory_distribution_cycle():
    _seed(); _cleanup()
    # producto (stock inicial 0) + dos tiendas vía la API de la Empresa
    r = requests.post(f"{API}/company/products", headers=_hdr(), json={
        "name": "Arroz 1kg", "price_usd": 1.2, "stock": 0}, timeout=15)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    sa = requests.post(f"{API}/company/stores", headers=_hdr(), json={
        "name": "Tienda A", "address": "Dir A larga"}, timeout=15).json()["id"]
    sb = requests.post(f"{API}/company/stores", headers=_hdr(), json={
        "name": "Tienda B", "address": "Dir B larga"}, timeout=15).json()["id"]

    # recibir 100 en el central
    r = requests.post(f"{API}/company/inventory/receive", headers=_hdr(),
                      json={"product_id": pid, "qty": 100}, timeout=15)
    assert r.status_code == 200, r.text
    row = _row(pid)
    assert row["total"] == 100 and row["central"] == 100 and row["distributed"] == 0

    # distribuir 30 a A y 40 a B
    assert requests.post(f"{API}/company/inventory/distribute", headers=_hdr(),
                         json={"product_id": pid, "store_id": sa, "qty": 30}, timeout=15).status_code == 200
    assert requests.post(f"{API}/company/inventory/distribute", headers=_hdr(),
                         json={"product_id": pid, "store_id": sb, "qty": 40}, timeout=15).status_code == 200
    row = _row(pid)
    assert row["central"] == 30 and row["distributed"] == 70
    by = {s["store_id"]: s["qty"] for s in row["stores"]}
    assert by.get(sa) == 30 and by.get(sb) == 40

    # sobre-distribuir (central solo 30) → 409
    r = requests.post(f"{API}/company/inventory/distribute", headers=_hdr(),
                      json={"product_id": pid, "store_id": sa, "qty": 80}, timeout=15)
    assert r.status_code == 409, r.text
    assert _row(pid)["central"] == 30  # sin cambios

    # el stock total (vendible en marketplace) NO cambia al distribuir
    db = _db()
    assert db.products.find_one({"id": pid})["stock"] == 100

    # devolver 10 de A → central 40
    assert requests.post(f"{API}/company/inventory/return", headers=_hdr(),
                         json={"product_id": pid, "store_id": sa, "qty": 10}, timeout=15).status_code == 200
    assert _row(pid)["central"] == 40

    # devolver de más de A (tiene 20) → 409
    r = requests.post(f"{API}/company/inventory/return", headers=_hdr(),
                      json={"product_id": pid, "store_id": sa, "qty": 999}, timeout=15)
    assert r.status_code == 409, r.text

    # borrar tienda B (tiene 40) → vuelven al central (40+40=80)
    assert requests.delete(f"{API}/company/stores/{sb}", headers=_hdr(), timeout=15).status_code == 200
    row = _row(pid)
    assert row["central"] == 80
    assert sb not in {s["store_id"] for s in row["stores"]}

    # log de movimientos
    moves = requests.get(f"{API}/company/inventory/moves", headers=_hdr(), timeout=15).json()
    types = [m["type"] for m in moves]
    assert "receive" in types and "distribute" in types and "return" in types
    _cleanup()


def test_distribute_requires_owned_store_and_product():
    _seed(); _cleanup()
    pid = requests.post(f"{API}/company/products", headers=_hdr(), json={
        "name": "Frijol", "price_usd": 1.0, "stock": 0}, timeout=15).json()["id"]
    requests.post(f"{API}/company/inventory/receive", headers=_hdr(),
                  json={"product_id": pid, "qty": 10}, timeout=15)
    # tienda que no existe → 404
    r = requests.post(f"{API}/company/inventory/distribute", headers=_hdr(),
                      json={"product_id": pid, "store_id": "no-existe", "qty": 1}, timeout=15)
    assert r.status_code == 404, r.text
    # producto ajeno → 404
    r = requests.post(f"{API}/company/inventory/receive", headers=_hdr(),
                      json={"product_id": "prod-ajeno", "qty": 5}, timeout=15)
    assert r.status_code == 404, r.text
    _cleanup()
