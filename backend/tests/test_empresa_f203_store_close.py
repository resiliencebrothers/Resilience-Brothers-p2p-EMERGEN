"""F2-03 — Borrar una tienda no debe corromper `distributed` ni dejar un
cierre parcial.

Invariante central: toda operación de inventario (incluido el cierre de tienda)
conserva `distributed == suma(by_store)` y nunca deja `distributed` negativo.

- La liberación de una tienda es ATÓMICA por producto: resta el valor VIGENTE
  de `by_store[sid]` (no una lectura obsoleta), por lo que una devolución
  concurrente no puede dejar `distributed` en negativo ni habilitar una
  sobre-distribución posterior (el bug reportado: 10 − (−4) = 14).
- Es IDEMPOTENTE y REANUDABLE: reejecutar tras un fallo parcial no duplica el
  efecto ni los movimientos.
- El protocolo de borrado (HTTP) marca la tienda "closing" antes de liberar y
  solo elimina la identidad al final; una tienda en cierre rechaza (409) nuevos
  movimientos.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

from db_client import db
from services import company_inventory as ci
from tests.conftest import BASE_URL

API = f"{BASE_URL}/api"
COMPANY = "user_test_empresa_f203"
EMP_TOKEN = "test_session_empresa_f203_X"


# ------------------------- helpers (nivel servicio) -------------------------

async def _mk(stock=0, distributed=0, by_store=None):
    pid = f"TEST_F203_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 1.0,
        "cost_usd": 0.0, "stock": float(stock), "distributed": float(distributed),
        "by_store": {k: float(v) for k, v in (by_store or {}).items()},
        "is_active": True, "owner_id": COMPANY, "company_id": COMPANY,
        "approval_status": "approved"})
    return pid


async def _clean():
    await db.products.delete_many({"company_id": COMPANY})
    await db.company_inventory_moves.delete_many({"company_id": COMPANY})
    await db.company_inventory_ops.delete_many({"company_id": COMPANY})


async def _doc(pid):
    return await db.products.find_one({"id": pid})


def _invariant_ok(doc) -> bool:
    by = doc.get("by_store") or {}
    dist = round(float(doc.get("distributed") or 0), 3)
    bysum = round(sum(float(v) for v in by.values()), 3)
    return dist == bysum and dist >= 0 and all(float(v) >= 0 for v in by.values())


async def _release_moves(pid):
    return await db.company_inventory_moves.count_documents(
        {"company_id": COMPANY, "product_id": pid, "type": "release"})


# ------------------------- carrera reproducida -------------------------

@pytest.mark.asyncio
async def test_release_vs_concurrent_return_keeps_invariant():
    """Escenario del reporte: total 10, tienda A 10, distributed 10. Una
    devolución de 4 corre a la par del cierre de la tienda. El resultado NUNCA
    puede dejar `distributed` negativo ni permitir luego distribuir 14."""
    await _clean()
    pid = await _mk(stock=10, distributed=10, by_store={"A": 10})
    try:
        await asyncio.gather(
            ci.return_to_central(COMPANY, pid, "A", 4,
                                 op_key=f"ret-{uuid.uuid4().hex}"),
            ci.release_store(COMPANY, "A"),
        )
        doc = await _doc(pid)
        assert _invariant_ok(doc), doc
        # A quedó liberada por el cierre; stock total intacto.
        assert (doc.get("by_store") or {}).get("A", 0) == 0
        assert doc["stock"] == 10
        assert doc.get("distributed", 0) >= 0
        # Regresión del bug: central no quedó inflado → distribuir 14 se rechaza.
        central = round(doc["stock"] - float(doc.get("distributed") or 0), 3)
        assert central == 10
        st = await ci.distribute(COMPANY, pid, "B", 14,
                                 op_key=f"dist-{uuid.uuid4().hex}")
        assert st == "insufficient"
    finally:
        await _clean()


@pytest.mark.asyncio
async def test_release_vs_concurrent_distribute_keeps_invariant():
    """Mientras se cierra A, una distribución a B en paralelo: el invariante se
    mantiene pase lo que pase (A liberada, B consistente, sin negativos)."""
    await _clean()
    pid = await _mk(stock=100, distributed=40, by_store={"A": 40})
    try:
        await asyncio.gather(
            ci.distribute(COMPANY, pid, "B", 30, op_key=f"d-{uuid.uuid4().hex}"),
            ci.release_store(COMPANY, "A"),
        )
        doc = await _doc(pid)
        assert _invariant_ok(doc), doc
        assert (doc.get("by_store") or {}).get("A", 0) == 0  # A liberada
        assert (doc.get("by_store") or {}).get("B") == 30     # B aplicó
        assert doc["stock"] == 100
    finally:
        await _clean()


# ------------------------- idempotente y reanudable -------------------------

@pytest.mark.asyncio
async def test_release_is_idempotent_and_logs_once():
    """Reejecutar el cierre de A (reintento) no duplica el efecto ni el
    movimiento; B no se toca."""
    await _clean()
    pid = await _mk(stock=100, distributed=70, by_store={"A": 30, "B": 40})
    try:
        await ci.release_store(COMPANY, "A")
        await ci.release_store(COMPANY, "A")  # retry
        doc = await _doc(pid)
        assert _invariant_ok(doc), doc
        assert "A" not in (doc.get("by_store") or {})
        assert (doc.get("by_store") or {}).get("B") == 40
        assert doc["distributed"] == 40          # 70 − 30, NO 70 − 60
        assert await _release_moves(pid) == 1     # un solo traslado registrado
    finally:
        await _clean()


@pytest.mark.asyncio
async def test_release_multi_product_partial_then_resume():
    """Varios productos distribuidos a la MISMA tienda: un cierre que corre dos
    veces (simulando fallo a mitad + reintento) termina consistente y sin doble
    conteo en ninguno."""
    await _clean()
    p1 = await _mk(stock=50, distributed=20, by_store={"A": 20})
    p2 = await _mk(stock=80, distributed=35, by_store={"A": 15, "B": 20})
    try:
        await ci.release_store(COMPANY, "A")
        await ci.release_store(COMPANY, "A")  # reanuda (idempotente)
        d1, d2 = await _doc(p1), await _doc(p2)
        assert _invariant_ok(d1) and _invariant_ok(d2)
        assert "A" not in (d1.get("by_store") or {}) and d1["distributed"] == 0
        assert "A" not in (d2.get("by_store") or {})
        assert (d2.get("by_store") or {}).get("B") == 20 and d2["distributed"] == 20
        assert await _release_moves(p1) == 1 and await _release_moves(p2) == 1
    finally:
        await _clean()


@pytest.mark.asyncio
async def test_release_never_negative_under_many_concurrent_returns():
    """Cierre contra múltiples devoluciones simultáneas de la misma tienda:
    jamás queda `distributed` negativo ni se rompe el invariante."""
    await _clean()
    pid = await _mk(stock=100, distributed=50, by_store={"A": 50})
    try:
        await asyncio.gather(
            ci.return_to_central(COMPANY, pid, "A", 10, op_key=f"r1-{uuid.uuid4().hex}"),
            ci.return_to_central(COMPANY, pid, "A", 10, op_key=f"r2-{uuid.uuid4().hex}"),
            ci.return_to_central(COMPANY, pid, "A", 10, op_key=f"r3-{uuid.uuid4().hex}"),
            ci.release_store(COMPANY, "A"),
        )
        doc = await _doc(pid)
        assert _invariant_ok(doc), doc
        assert doc.get("distributed", 0) >= 0
        assert (doc.get("by_store") or {}).get("A", 0) == 0
    finally:
        await _clean()


# ------------------------- protocolo de borrado (HTTP) -------------------------

def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {EMP_TOKEN}", "Content-Type": "application/json"}


def _seed_http():
    d = _db()
    d.users.update_one({"user_id": COMPANY}, {"$set": {
        "user_id": COMPANY, "email": "empresa.f203@example.com",
        "name": "Empresa F203", "role": "empresa", "account_status": "active",
        "email_verified": True, "phone_verified": True, "phone": "+5350000233"}},
        upsert=True)
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    d.user_sessions.update_one({"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": COMPANY, "expires_at": exp}},
        upsert=True)


def _cleanup_http():
    d = _db()
    d.products.delete_many({"company_id": COMPANY})
    d.stores.delete_many({"company_id": COMPANY})
    d.company_inventory_moves.delete_many({"company_id": COMPANY})


def _row(pid):
    r = requests.get(f"{API}/company/inventory", headers=_hdr(), timeout=15)
    assert r.status_code == 200, r.text
    for row in r.json():
        if row["product_id"] == pid:
            return row
    return None


def test_delete_store_recoverable_protocol_http():
    """Borrar una tienda con stock devuelve TODO al central, no deja huérfanos y
    el total vendible no cambia."""
    _seed_http(); _cleanup_http()
    pid = requests.post(f"{API}/company/products", headers=_hdr(), json={
        "name": "Aceite 1L", "price_usd": 2.0, "stock": 0}, timeout=15).json()["id"]
    requests.post(f"{API}/company/inventory/receive", headers=_hdr(),
                  json={"product_id": pid, "qty": 100}, timeout=15)
    sa = requests.post(f"{API}/company/stores", headers=_hdr(), json={
        "name": "Tienda F203", "address": "Dir F203 larga"}, timeout=15).json()["id"]
    requests.post(f"{API}/company/inventory/distribute", headers=_hdr(),
                  json={"product_id": pid, "store_id": sa, "qty": 60}, timeout=15)
    assert _row(pid)["central"] == 40

    r = requests.delete(f"{API}/company/stores/{sa}", headers=_hdr(), timeout=15)
    assert r.status_code == 200, r.text
    row = _row(pid)
    assert row["central"] == 100           # todo volvió al central
    assert row["distributed"] == 0
    assert sa not in {s["store_id"] for s in row["stores"]}  # sin huérfanos
    d = _db()
    assert d.products.find_one({"id": pid})["stock"] == 100  # total intacto
    assert d.stores.find_one({"id": sa}) is None             # identidad eliminada
    _cleanup_http()


def test_closing_store_rejects_new_movements_http():
    """Una tienda marcada 'closing' rechaza distribuir/devolver con 409 (cerrada
    a nuevos movimientos)."""
    _seed_http(); _cleanup_http()
    pid = requests.post(f"{API}/company/products", headers=_hdr(), json={
        "name": "Sal 1kg", "price_usd": 1.0, "stock": 0}, timeout=15).json()["id"]
    requests.post(f"{API}/company/inventory/receive", headers=_hdr(),
                  json={"product_id": pid, "qty": 10}, timeout=15)
    sa = requests.post(f"{API}/company/stores", headers=_hdr(), json={
        "name": "Tienda Cierre", "address": "Dir cierre larga"}, timeout=15).json()["id"]
    _db().stores.update_one({"id": sa}, {"$set": {"status": "closing"}})

    r = requests.post(f"{API}/company/inventory/distribute", headers=_hdr(),
                      json={"product_id": pid, "store_id": sa, "qty": 1}, timeout=15)
    assert r.status_code == 409, r.text
    r = requests.post(f"{API}/company/inventory/return", headers=_hdr(),
                      json={"product_id": pid, "store_id": sa, "qty": 1}, timeout=15)
    assert r.status_code == 409, r.text
    _cleanup_http()
