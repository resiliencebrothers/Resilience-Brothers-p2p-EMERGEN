"""iter350d — RV-01 / H01 (ALTA, residual): protección de versión del conteo
frente al Recuperador Automático.

Fallo residual: el recuperador aplicaba el stock (`record_movement`) ANTES de
reclamar atómicamente la versión. Si entre que el recuperador leía el conteo y
lo aplicaba, un RECUENTO subía la versión o un BORRADO eliminaba el conteo, el
recuperador aplicaba igualmente el ajuste antiguo → el stock cambiaba sin un
conteo vigente que lo respaldara.

Fix:
- `_recover_one_count` RECLAMA atómicamente la misma versión (pending_apply →
  claiming) ANTES de tocar el stock; si no casa (recuento/borrado), aborta sin
  aplicar efecto. Al pasar a 'claiming', recuentos/borrados quedan bloqueados.
- `record_physical_count` / `clear_physical_count` INVALIDAN el movimiento de
  ajuste huérfano (no aplicado) de un conteo pending_apply que se sustituye o
  borra, para que nunca pueda completarse más tarde.

Cubre recuento y borrado, en AMBOS órdenes, y el efecto único de stock.
"""
import uuid

import pytest
from fastapi import HTTPException

from db_client import db
from auth_utils import now_utc, iso
from services.inventory_ipv import (record_physical_count, clear_physical_count,
                                     _recover_one_count)

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk_product(stock=10.0, cost=200.0):
    pid = f"TEST_IPV350D_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 500.0,
        "cost_usd": cost, "stock": float(stock), "unit": "unidad",
        "is_active": True, "owner_id": ""})
    return pid


def _prod(pid, stock=10.0):
    return {"id": pid, "name": pid, "stock": float(stock), "cost_usd": 200.0,
            "unit": "unidad"}


async def _cleanup(pid):
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_lots.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})
    await db.stock_ops.delete_many({"product_id": pid})
    await db.inventory_incidents.delete_many({"product_id": pid})


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return p["stock"]


async def _adj_movs(pid):
    return await db.inventory_movements.count_documents(
        {"product_id": pid, "type": {"$in": ["ajuste_pos", "ajuste_neg"]}})


async def _mk_pending(pid):
    """Crea un conteo 8 sobre stock 10 (diff -2) dejado en pending_apply con su
    movimiento de ajuste REGISTRADO pero SIN aplicar (interrupción). Devuelve el
    snapshot (dict) del conteo tal como lo leería el recuperador."""
    c = await record_physical_count(_prod(pid, 10.0), 8, ACTOR)
    cur = await db.inventory_counts.find_one({"id": c["id"]}, {"_id": 0})
    version = cur["version"]
    mov_id = str(uuid.uuid4())
    await db.inventory_movements.insert_one({
        "id": mov_id, "product_id": pid, "product_name": pid,
        "type": "ajuste_neg", "quantity": 2.0, "unit": "unidad",
        "unit_price": 500.0, "unit_cost": 200.0, "total": 400.0,
        "cost_of_sale": 0.0, "profit": 0.0, "note": "Ajuste interrumpido",
        "source": "conteo", "ref_id": c["id"], "actor_id": ACTOR["user_id"],
        "actor_email": ACTOR["email"], "created_at": iso(now_utc()),
        "dedupe_key": f"count-adjust:{c['id']}:v{version}",
        "needs_stock": True, "stock_applied": False})
    await db.inventory_counts.update_one(
        {"id": c["id"]},
        {"$set": {"auth_state": "pending_apply", "adjustment_document": "DOC-D",
                  "adjustment_movement_id": mov_id,
                  "claimed_by": ACTOR["user_id"]}})
    return await db.inventory_counts.find_one({"id": c["id"]}, {"_id": 0})


async def test_recount_then_recover_aborts_and_invalidates():
    """Recuento ANTES de recuperar: sube la versión e invalida el huérfano; el
    recuperador (con la versión vieja) aborta sin tocar el stock."""
    pid = await _mk_product(10.0)
    try:
        stale = await _mk_pending(pid)
        v0 = stale["version"]
        assert await _adj_movs(pid) == 1

        # RECUENTO: sustituye el conteo pendiente (sube versión, invalida huérfano).
        await record_physical_count(_prod(pid, 10.0), 2, ACTOR)
        assert await _adj_movs(pid) == 0, "el huérfano no aplicado debe invalidarse"

        healed = await _recover_one_count(stale)
        assert healed is False
        assert await _stock(pid) == 10.0  # stock intacto
        cur = await db.inventory_counts.find_one({"id": stale["id"]}, {"_id": 0})
        assert cur["version"] > v0
        assert cur.get("authorized") is not True
        assert await _adj_movs(pid) == 0  # sigue sin efecto de stock
    finally:
        await _cleanup(pid)


async def test_delete_then_recover_aborts_and_invalidates():
    """Borrado ANTES de recuperar: elimina el conteo e invalida el huérfano; el
    recuperador aborta sin tocar el stock."""
    pid = await _mk_product(10.0)
    try:
        stale = await _mk_pending(pid)
        assert await _adj_movs(pid) == 1

        await clear_physical_count(pid)
        assert await _adj_movs(pid) == 0

        healed = await _recover_one_count(stale)
        assert healed is False
        assert await _stock(pid) == 10.0
        assert await db.inventory_counts.find_one({"id": stale["id"]}) is None
    finally:
        await _cleanup(pid)


async def test_recover_then_recount_single_effect():
    """Recuperar ANTES de recontar: el recuperador aplica una sola vez (stock 8,
    conteo autorizado); un recuento posterior se RECHAZA (409)."""
    pid = await _mk_product(10.0)
    try:
        stale = await _mk_pending(pid)
        healed = await _recover_one_count(stale)
        assert healed is True
        assert await _stock(pid) == 8.0
        assert await _adj_movs(pid) == 1

        with pytest.raises(HTTPException) as ei:
            await record_physical_count(_prod(pid, 8.0), 5, ACTOR)
        assert ei.value.status_code == 409
        assert await _stock(pid) == 8.0  # efecto único
        assert await _adj_movs(pid) == 1
    finally:
        await _cleanup(pid)


async def test_recover_then_delete_single_effect():
    """Recuperar ANTES de borrar: tras autorizar, el borrado se RECHAZA (409)."""
    pid = await _mk_product(10.0)
    try:
        stale = await _mk_pending(pid)
        healed = await _recover_one_count(stale)
        assert healed is True and await _stock(pid) == 8.0

        with pytest.raises(HTTPException) as ei:
            await clear_physical_count(pid)
        assert ei.value.status_code == 409
        assert await _stock(pid) == 8.0
        assert await _adj_movs(pid) == 1
    finally:
        await _cleanup(pid)


async def test_double_recover_single_effect():
    """Dos recuperadores sobre el mismo conteo: un ÚNICO efecto de stock."""
    pid = await _mk_product(10.0)
    try:
        stale = await _mk_pending(pid)
        h1 = await _recover_one_count(stale)
        h2 = await _recover_one_count(stale)
        assert h1 is True and h2 is False
        assert await _stock(pid) == 8.0
        assert await _adj_movs(pid) == 1
    finally:
        await _cleanup(pid)
