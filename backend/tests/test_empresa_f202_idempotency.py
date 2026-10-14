"""F2-02 — reintentos idempotentes por clave estable de operación.

Un reintento HTTP de la MISMA operación lógica (misma clave) NO debe duplicar
el efecto, ni siquiera tras rotar el tope de `inv_ops` (evidencia duradera en
`company_inventory_ops`). Dos operaciones DISTINTAS con misma clave y payload
diferente se rechazan; con claves distintas ambas se aplican.
"""
import asyncio
import uuid

import pytest

from db_client import db
from services import company_inventory as ci

pytestmark = pytest.mark.asyncio

COMPANY = "user_test_empresa_f202"


async def _mk(stock=0, distributed=0, by_store=None):
    pid = f"TEST_F202_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 1.0,
        "cost_usd": 0.0, "stock": float(stock), "distributed": float(distributed),
        "by_store": {k: float(v) for k, v in (by_store or {}).items()},
        "is_active": True, "owner_id": COMPANY, "company_id": COMPANY,
        "approval_status": "approved"})
    return pid


async def _clean(pid):
    await db.products.delete_one({"id": pid})
    await db.company_inventory_moves.delete_many({"company_id": COMPANY})
    await db.company_inventory_ops.delete_many({"company_id": COMPANY})


async def _stock(pid):
    return (await db.products.find_one({"id": pid}))["stock"]


async def _moves(pid, mtype):
    return await db.company_inventory_moves.count_documents(
        {"company_id": COMPANY, "product_id": pid, "type": mtype})


async def test_receive_same_key_applies_once():
    pid = await _mk()
    try:
        k = f"op-{uuid.uuid4().hex}"
        r1 = await ci.receive_central(COMPANY, pid, 100, op_key=k)
        r2 = await ci.receive_central(COMPANY, pid, 100, op_key=k)
        assert r1 == "applied" and r2 == "applied"
        assert await _stock(pid) == 100          # un solo incremento
        assert await _moves(pid, "receive") == 1  # un solo movimiento
    finally:
        await _clean(pid)


async def test_receive_different_keys_apply_twice():
    pid = await _mk()
    try:
        await ci.receive_central(COMPANY, pid, 100, op_key=f"op-{uuid.uuid4().hex}")
        await ci.receive_central(COMPANY, pid, 100, op_key=f"op-{uuid.uuid4().hex}")
        assert await _stock(pid) == 200  # dos operaciones distintas
    finally:
        await _clean(pid)


async def test_distribute_same_key_applies_once():
    pid = await _mk(stock=100)
    try:
        k = f"op-{uuid.uuid4().hex}"
        await ci.distribute(COMPANY, pid, "A", 30, op_key=k)
        await ci.distribute(COMPANY, pid, "A", 30, op_key=k)
        row = next(r for r in await ci.build_inventory_rows(COMPANY) if r["product_id"] == pid)
        by = {s["store_id"]: s["qty"] for s in row["stores"]}
        assert by["A"] == 30 and row["central"] == 70  # NO 60
        assert await _moves(pid, "distribute") == 1
    finally:
        await _clean(pid)


async def test_return_same_key_applies_once():
    pid = await _mk(stock=100, distributed=40, by_store={"A": 40})
    try:
        k = f"op-{uuid.uuid4().hex}"
        await ci.return_to_central(COMPANY, pid, "A", 10, op_key=k)
        await ci.return_to_central(COMPANY, pid, "A", 10, op_key=k)
        row = next(r for r in await ci.build_inventory_rows(COMPANY) if r["product_id"] == pid)
        by = {s["store_id"]: s["qty"] for s in row["stores"]}
        assert by["A"] == 30 and row["central"] == 70  # devuelto 10, no 20
    finally:
        await _clean(pid)


async def test_same_key_different_payload_conflicts():
    pid = await _mk()
    try:
        k = f"op-{uuid.uuid4().hex}"
        assert await ci.receive_central(COMPANY, pid, 100, op_key=k) == "applied"
        # misma clave, cantidad distinta → conflicto, sin efecto
        assert await ci.receive_central(COMPANY, pid, 50, op_key=k) == "conflict"
        assert await _stock(pid) == 100
    finally:
        await _clean(pid)


async def test_durable_after_inv_ops_rotation():
    """Aunque el id salga del tope de inv_ops, el registro duradero impide
    reaplicar la MISMA operación."""
    pid = await _mk()
    try:
        k = f"op-{uuid.uuid4().hex}"
        await ci.receive_central(COMPANY, pid, 100, op_key=k)
        # simula rotación/evicción del guard embebido
        await db.products.update_one({"id": pid}, {"$set": {"inv_ops": []}})
        r2 = await ci.receive_central(COMPANY, pid, 100, op_key=k)
        assert r2 == "applied"
        assert await _stock(pid) == 100  # NO se reaplica
        assert await _moves(pid, "receive") == 1
    finally:
        await _clean(pid)


async def test_concurrent_same_key_applies_once():
    pid = await _mk()
    try:
        k = f"op-{uuid.uuid4().hex}"
        results = await asyncio.gather(
            ci.receive_central(COMPANY, pid, 100, op_key=k),
            ci.receive_central(COMPANY, pid, 100, op_key=k),
            ci.receive_central(COMPANY, pid, 100, op_key=k),
        )
        assert all(r == "applied" for r in results)
        assert await _stock(pid) == 100          # un único incremento
        assert await _moves(pid, "receive") == 1  # un único movimiento
    finally:
        await _clean(pid)
