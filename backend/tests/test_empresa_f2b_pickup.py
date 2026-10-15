"""F2-B — Venta del marketplace con recogida en tienda (origen en ESTANTERÍA).

Una compra con recogida en tienda de un producto de Empresa descuenta la
tienda elegida: el TOTAL (stock) por la vía del canje y la ESTANTERÍA
(by_store[sid] + distributed) por la capa de ubicación. Como ambas caen por el
mismo importe, el ALMACÉN CENTRAL (stock − distributed) NO cambia: la venta
consume exactamente esa tienda. El reverso (rechazo/cancelación/recuperación)
devuelve la MISMA tienda exactamente una vez.

Estas pruebas ejercen la capa de servicio (reserve_pickup / restore_pickup /
burn_or_undo_pickup) y la COMPOSICIÓN que usan /vip/redeem, el rechazo admin y
el healer (capa de stock + capa de ubicación juntas).
"""
import uuid

import pytest

from db_client import db
from services.inventory import (apply_stock_idempotent, burn_or_undo_stock)
from services import company_inventory as ci

pytestmark = pytest.mark.asyncio

COMPANY = "user_test_empresa_f2b"


async def _mk(stock, distributed, by_store):
    pid = f"TEST_F2B_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 2.0,
        "cost_usd": 0.0, "stock": float(stock), "distributed": float(distributed),
        "by_store": {k: float(v) for k, v in by_store.items()},
        "is_active": True, "owner_id": COMPANY, "company_id": COMPANY,
        "approval_status": "approved"})
    return pid


async def _clean(pid):
    await db.products.delete_one({"id": pid})
    await db.stock_ops.delete_many({"product_id": pid})
    await db.company_inventory_moves.delete_many({"company_id": COMPANY})
    await db.company_inventory_ops.delete_many({"company_id": COMPANY})


async def _row(pid):
    rows = await ci.build_inventory_rows(COMPANY)
    return next(r for r in rows if r["product_id"] == pid)


def _central_guard_shelf(store_id, qty):
    # Mismo guard que añade /vip/redeem a la reserva de stock para pickup.
    return {"$expr": {"$gte": [{"$ifNull": [f"$by_store.{store_id}", 0]}, qty]}}


# --- COMPOSICIÓN: lo que hacen realmente redeem / reject / healer -----------

async def _sale(pid, store, qty, rid):
    """Reserva de venta con recogida en tienda = capa stock + capa ubicación."""
    st = await apply_stock_idempotent(pid, -qty, f"redeem-stock:{rid}",
                                      extra_filter=_central_guard_shelf(store, qty))
    assert st == "applied"
    lc = await ci.reserve_pickup(COMPANY, pid, store, qty, f"redeem-loc:{rid}")
    assert lc == "applied"


async def _reject(pid, store, qty, rid, cycle=1):
    """Rechazo = restitución de stock + restitución de ubicación (idempotente)."""
    await apply_stock_idempotent(pid, qty, f"reject-stock:{rid}:c{cycle}",
                                 require_available=False)
    await ci.restore_pickup(COMPANY, pid, store, qty, f"reject-loc:{rid}:c{cycle}")


async def _heal(pid, store, qty, rid):
    """Healer de un canje a medio crear = decisión terminal en ambas capas."""
    await burn_or_undo_stock(pid, qty, f"redeem-stock:{rid}")
    await ci.burn_or_undo_pickup(COMPANY, pid, store, qty, f"redeem-loc:{rid}")


# ---------------------------------------------------------------------------

async def test_sale_consumes_the_chosen_store_not_central():
    # total 20, central 12, A 8
    pid = await _mk(20, 8, {"A": 8})
    try:
        rid = uuid.uuid4().hex
        await _sale(pid, "A", 3, rid)
        doc = await db.products.find_one({"id": pid})
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        # total y estantería bajan 3; central intacto; distributed baja 3.
        assert doc["stock"] == 17
        assert by.get("A") == 5
        assert r["distributed"] == 5
        assert r["central"] == 12
        # invariante distributed == suma(by_store)
        assert r["distributed"] == sum(s["qty"] for s in r["stores"])
    finally:
        await _clean(pid)


async def test_sale_rejects_when_store_lacks_stock():
    pid = await _mk(20, 2, {"A": 2})  # A sólo tiene 2
    try:
        rid = uuid.uuid4().hex
        st = await apply_stock_idempotent(
            pid, -5, f"redeem-stock:{rid}",
            extra_filter=_central_guard_shelf("A", 5))
        assert st == "insufficient"  # el guard de estantería bloquea la venta
        assert (await db.products.find_one({"id": pid}))["stock"] == 20
    finally:
        await _clean(pid)


async def test_reject_restores_exact_same_store_once():
    pid = await _mk(20, 8, {"A": 8})
    try:
        rid = uuid.uuid4().hex
        await _sale(pid, "A", 3, rid)
        await _reject(pid, "A", 3, rid)
        # reintento idempotente (reejecutar el rechazo no duplica)
        await _reject(pid, "A", 3, rid)
        doc = await db.products.find_one({"id": pid})
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert doc["stock"] == 20
        assert by.get("A") == 8
        assert r["distributed"] == 8
        assert r["central"] == 12
    finally:
        await _clean(pid)


async def test_healer_reverts_crashed_sale_once():
    pid = await _mk(20, 8, {"A": 8})
    try:
        rid = uuid.uuid4().hex
        await _sale(pid, "A", 4, rid)
        # el proceso murió antes de activar → el healer deshace ambas capas
        await _heal(pid, "A", 4, rid)
        await _heal(pid, "A", 4, rid)  # idempotente
        doc = await db.products.find_one({"id": pid})
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert doc["stock"] == 20 and by.get("A") == 8 and r["distributed"] == 8
    finally:
        await _clean(pid)


async def test_reserve_pickup_idempotent():
    pid = await _mk(20, 8, {"A": 8})
    try:
        op = f"redeem-loc:{uuid.uuid4().hex}"
        assert await ci.reserve_pickup(COMPANY, pid, "A", 3, op) == "applied"
        # mismo op → no reaplica
        assert await ci.reserve_pickup(COMPANY, pid, "A", 3, op) == "applied"
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert by.get("A") == 5 and r["distributed"] == 5
    finally:
        await _clean(pid)


async def test_burn_blocks_a_late_reserve():
    """Si el healer QUEMA una reserva que aún no se aplicó, un creador lento
    con el MISMO op jamás la aplica (token de quema en el guard)."""
    pid = await _mk(20, 8, {"A": 8})
    try:
        op = f"redeem-loc:{uuid.uuid4().hex}"
        assert await ci.burn_or_undo_pickup(COMPANY, pid, "A", 3, op) == "burned"
        # el creador atrasado intenta la reserva → NO muta
        assert await ci.reserve_pickup(COMPANY, pid, "A", 3, op) == "burned"
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert by.get("A") == 8 and r["distributed"] == 8  # intacto
    finally:
        await _clean(pid)


async def test_burn_or_undo_undoes_an_applied_reserve_once():
    pid = await _mk(20, 8, {"A": 8})
    try:
        op = f"redeem-loc:{uuid.uuid4().hex}"
        assert await ci.reserve_pickup(COMPANY, pid, "A", 3, op) == "applied"
        assert await ci.burn_or_undo_pickup(COMPANY, pid, "A", 3, op) == "undone"
        # repetir la decisión terminal no vuelve a sumar (exactamente una vez)
        assert await ci.burn_or_undo_pickup(COMPANY, pid, "A", 3, op) == "undone"
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert by.get("A") == 8 and r["distributed"] == 8
    finally:
        await _clean(pid)


async def test_two_sales_same_store_then_reject_one():
    pid = await _mk(30, 20, {"A": 20})
    try:
        rid1, rid2 = uuid.uuid4().hex, uuid.uuid4().hex
        await _sale(pid, "A", 5, rid1)
        await _sale(pid, "A", 4, rid2)
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert by.get("A") == 11 and (await db.products.find_one({"id": pid}))["stock"] == 21
        # rechazo de la primera venta → vuelve 5, la segunda sigue consumida
        await _reject(pid, "A", 5, rid1)
        r = await _row(pid)
        by = {s["store_id"]: s["qty"] for s in r["stores"]}
        assert by.get("A") == 16 and (await db.products.find_one({"id": pid}))["stock"] == 26
        assert r["distributed"] == 16
    finally:
        await _clean(pid)
