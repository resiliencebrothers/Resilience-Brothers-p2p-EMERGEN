"""F2-01 — las ventas no deben romper el desglose por ubicación.

Modelo: total = central + distribuido; central = stock − distributed.
- Venta por el marketplace (origen CENTRAL): exige atómicamente central ≥ qty
  (mismo extra_filter que usa /vip/redeem), por lo que NUNCA consume unidades
  asignadas a tiendas ni deja el central negativo.
- Despacho con origen en TIENDA (Fase 4): descuenta total + tienda + distributed
  en una sola escritura atómica; su reverso devuelve exactamente una vez.

Escenario de cierre del auditor:
  total 100, central 30, A 40, B 30.
  venta de 5 desde A  → total 95, central 30, A 35, B 30.
  venta central de 31 → rechazo sin efectos.
"""
import uuid

import pytest

from db_client import db
from services.inventory import apply_stock_idempotent
from services import company_inventory as ci

pytestmark = pytest.mark.asyncio

COMPANY = "user_test_empresa_f201"


def _central_guard(qty):
    # Réplica EXACTA del guard que añade el marketplace para productos Empresa.
    return {"$expr": {"$gte": [
        {"$subtract": [{"$ifNull": ["$stock", 0]}, {"$ifNull": ["$distributed", 0]}]},
        qty]}}


async def _mk(stock, distributed, by_store):
    pid = f"TEST_F201_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 2.0,
        "cost_usd": 0.0, "stock": float(stock), "distributed": float(distributed),
        "by_store": {k: float(v) for k, v in by_store.items()},
        "is_active": True, "owner_id": COMPANY, "company_id": COMPANY,
        "approval_status": "approved"})
    # E34-05 — las devoluciones restauran la estantería SOLO si la tienda existe.
    # Sembramos la tienda real de cada clave de by_store para que el reverso del
    # despacho vuelva a su tienda (y no al central).
    for sid in by_store:
        await db.stores.update_one(
            {"id": sid, "company_id": COMPANY},
            {"$setOnInsert": {"id": sid, "company_id": COMPANY,
                              "name": f"Store {sid}", "active": True}},
            upsert=True)
    return pid


async def _clean(pid):
    await db.products.delete_one({"id": pid})
    await db.stock_ops.delete_many({"product_id": pid})
    await db.company_inventory_moves.delete_many({"company_id": COMPANY})
    await db.stores.delete_many({"company_id": COMPANY})


async def _row(pid):
    rows = await ci.build_inventory_rows(COMPANY)
    return next(r for r in rows if r["product_id"] == pid)


async def test_closing_scenario():
    pid = await _mk(100, 70, {"A": 40, "B": 30})
    try:
        r = await _row(pid)
        assert (r["total"], r["central"], r["distributed"]) == (100, 30, 70)

        # venta de 5 DESDE la tienda A
        st = await ci.dispatch_from_store(COMPANY, pid, "A", 5, op_id=f"d:{uuid.uuid4().hex}")
        assert st == "applied"
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert r["total"] == 95 and r["central"] == 30 and r["distributed"] == 65
        assert by["A"] == 35 and by["B"] == 30

        # venta SOLO desde central por 31 (central=30) → rechazo sin efectos
        st = await apply_stock_idempotent(pid, -31, f"s:{uuid.uuid4().hex}",
                                          extra_filter=_central_guard(31))
        assert st == "insufficient"
        doc = await db.products.find_one({"id": pid})
        assert doc["stock"] == 95  # intacto
        r = await _row(pid)
        assert r["central"] == 30
    finally:
        await _clean(pid)


async def test_central_sale_cannot_consume_store_units():
    """Bug original: total 10, A 10, central 0 → una venta central NO procede."""
    pid = await _mk(10, 10, {"A": 10})
    try:
        st = await apply_stock_idempotent(pid, -1, f"s:{uuid.uuid4().hex}",
                                          extra_filter=_central_guard(1))
        assert st == "insufficient"
        assert (await db.products.find_one({"id": pid}))["stock"] == 10
        r = await _row(pid)
        assert r["central"] == 0 and r["over_distributed"] is False
    finally:
        await _clean(pid)


async def test_central_sale_consumes_only_central():
    pid = await _mk(100, 70, {"A": 70})  # central 30
    try:
        st = await apply_stock_idempotent(pid, -20, f"s:{uuid.uuid4().hex}",
                                          extra_filter=_central_guard(20))
        assert st == "applied"
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert r["total"] == 80 and r["central"] == 10 and by["A"] == 70
    finally:
        await _clean(pid)


async def test_dispatch_and_return_are_idempotent():
    pid = await _mk(50, 50, {"A": 50})
    try:
        op = f"delivery:{uuid.uuid4().hex}"
        assert await ci.dispatch_from_store(COMPANY, pid, "A", 5, op_id=op) == "applied"
        # reintento con el MISMO op → éxito sin reaplicar
        assert await ci.dispatch_from_store(COMPANY, pid, "A", 5, op_id=op) == "applied"
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert r["total"] == 45 and by["A"] == 45

        # despacho de más de lo que hay en la tienda → insufficient
        assert await ci.dispatch_from_store(COMPANY, pid, "A", 999, op_id=f"d:{uuid.uuid4().hex}") == "insufficient"

        # reverso idempotente devuelve exactamente una vez
        rop = f"delivery-ret:{uuid.uuid4().hex}"
        assert await ci.return_dispatch(COMPANY, pid, "A", 5, op_id=rop) == "applied"
        assert await ci.return_dispatch(COMPANY, pid, "A", 5, op_id=rop) == "applied"
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert r["total"] == 50 and by["A"] == 50
    finally:
        await _clean(pid)


async def test_invariant_holds_under_interleaving():
    pid = await _mk(100, 0, {})
    try:
        # intercala: distribuir, despachar desde tienda, vender central, devolver
        await ci.distribute(COMPANY, pid, "A", 40)
        await ci.distribute(COMPANY, pid, "B", 30)
        await ci.dispatch_from_store(COMPANY, pid, "A", 10, op_id=f"de:{uuid.uuid4().hex}")
        await apply_stock_idempotent(pid, -20, f"s:{uuid.uuid4().hex}", extra_filter=_central_guard(20))
        await ci.return_to_central(COMPANY, pid, "B", 5)

        doc = await db.products.find_one({"id": pid})
        r = await _row(pid)
        visible = r["central"] + r["distributed"]
        # INVARIANTE: el total (stock) coincide con central_visible + distribuido
        assert abs(doc["stock"] - visible) < 0.001
        assert r["central"] >= 0 and r["over_distributed"] is False
        # valores esperados: total 70, A 30, B 25, distribuido 55, central 15
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert r["total"] == 70 and r["distributed"] == 55 and r["central"] == 15
        assert by["A"] == 30 and by["B"] == 25
    finally:
        await _clean(pid)
