"""F2-05 — El historial de inventario NO puede perder movimientos en silencio.

- `_log_move` solo traga `DuplicateKeyError` (evidencia única por `op_id`);
  cualquier otro fallo de almacenamiento se PROPAGA → la operación queda
  recuperable (no 'applied' en silencio con historial vacío).
- Un reintento con la MISMA clave recupera: re-registra el movimiento SIN
  reaplicar el stock (guard `inv_ops`) → un único efecto, una única evidencia.
- Cerrar una tienda produce un movimiento 'release' trazable por producto,
  también recuperable si falla la escritura del log.
"""
import uuid

import pytest

from db_client import db
from services import company_inventory as ci

COMPANY = "user_test_empresa_f205"


async def _mk(stock=0, distributed=0, by_store=None):
    pid = f"TEST_F205_{uuid.uuid4().hex[:8]}"
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


async def _moves(pid, mtype=None):
    q = {"company_id": COMPANY, "product_id": pid}
    if mtype:
        q["type"] = mtype
    return await db.company_inventory_moves.count_documents(q)


def _inject_log_failure(monkeypatch, move_type):
    """Hace fallar UNA vez la escritura del log del tipo indicado (fallo de
    almacenamiento, distinto de clave duplicada)."""
    orig = type(db.company_inventory_moves).insert_one
    state = {"armed": True}

    async def wrapper(self, doc, *a, **k):
        if (getattr(self, "name", "") == "company_inventory_moves"
                and state["armed"] and isinstance(doc, dict)
                and doc.get("type") == move_type):
            state["armed"] = False
            raise RuntimeError("inyectado: fallo de almacenamiento del log")
        return await orig(self, doc, *a, **k)

    monkeypatch.setattr(type(db.company_inventory_moves), "insert_one", wrapper)
    return state


@pytest.mark.asyncio
async def test_receive_not_silently_applied_when_log_fails_then_recovers(monkeypatch):
    await _clean()
    pid = await _mk(stock=0)
    key = f"rcv-{uuid.uuid4().hex}"
    try:
        state = _inject_log_failure(monkeypatch, "receive")
        # 1) El fallo de log se PROPAGA (no devuelve applied en silencio).
        with pytest.raises(Exception):
            await ci.receive_central(COMPANY, pid, 25, op_key=key)
        assert state["armed"] is False               # el fallo se disparó
        assert _q((await _doc(pid))["stock"]) == 25   # el stock sí se aplicó
        assert await _moves(pid) == 0                 # pero el log quedó pendiente
        op = await db.company_inventory_ops.find_one(
            {"company_id": COMPANY, "op_key": key})
        assert op and op.get("status") != "done"      # operación recuperable
        # 2) Reintento con la MISMA clave: recupera, re-registra, SIN reaplicar.
        monkeypatch.undo()
        res = await ci.receive_central(COMPANY, pid, 25, op_key=key)
        assert res == "applied"
        assert _q((await _doc(pid))["stock"]) == 25   # un único efecto (no 50)
        assert await _moves(pid, "receive") == 1      # una única evidencia
    finally:
        await _clean()


@pytest.mark.asyncio
async def test_log_swallows_only_verified_duplicate(monkeypatch):
    """Dos llamadas con la MISMA op_key dejan exactamente UN movimiento."""
    await _clean()
    pid = await _mk(stock=0)
    key = f"rcv-{uuid.uuid4().hex}"
    try:
        assert await ci.receive_central(COMPANY, pid, 10, op_key=key) == "applied"
        assert await ci.receive_central(COMPANY, pid, 10, op_key=key) == "applied"
        assert _q((await _doc(pid))["stock"]) == 10
        assert await _moves(pid, "receive") == 1
    finally:
        await _clean()


@pytest.mark.asyncio
async def test_release_logs_a_move_per_product():
    """Cerrar una tienda con 10 devuelve 10 al central y registra el movimiento."""
    await _clean()
    pid = await _mk(stock=10, distributed=10, by_store={"A": 10})
    try:
        await ci.release_store(COMPANY, "A")
        doc = await _doc(pid)
        assert "A" not in (doc.get("by_store") or {})
        central = _q(doc["stock"]) - sum(_q(v) for v in (doc.get("by_store") or {}).values())
        assert round(central, 3) == 10                # vuelve al central
        rel = await db.company_inventory_moves.find_one(
            {"company_id": COMPANY, "product_id": pid, "type": "release"})
        assert rel is not None and _q(rel["qty"]) == 10   # movimiento trazable
        assert rel.get("store_id") == "A"
    finally:
        await _clean()


@pytest.mark.asyncio
async def test_release_recovers_move_after_log_failure(monkeypatch):
    await _clean()
    pid = await _mk(stock=10, distributed=10, by_store={"A": 10})
    try:
        state = _inject_log_failure(monkeypatch, "release")
        # 1) El fallo de log al cerrar se PROPAGA.
        with pytest.raises(Exception):
            await ci.release_store(COMPANY, "A")
        assert state["armed"] is False
        doc = await _doc(pid)
        assert "A" not in (doc.get("by_store") or {})   # el stock ya se movió
        assert await _moves(pid, "release") == 0         # pero sin log aún
        op = await db.company_inventory_ops.find_one(
            {"company_id": COMPANY, "op_key": f"release:A:{pid}"})
        assert op and op.get("status") != "done" and _q(op.get("applied_qty")) == 10
        # 2) Reintento: la recuperación re-registra el movimiento, SIN reaplicar.
        monkeypatch.undo()
        await ci.release_store(COMPANY, "A")
        assert await _moves(pid, "release") == 1
        doc2 = await _doc(pid)
        central = _q(doc2["stock"]) - sum(_q(v) for v in (doc2.get("by_store") or {}).values())
        assert round(central, 3) == 10                   # un único efecto
    finally:
        await _clean()


def _q(v):
    return ci._q(v)
