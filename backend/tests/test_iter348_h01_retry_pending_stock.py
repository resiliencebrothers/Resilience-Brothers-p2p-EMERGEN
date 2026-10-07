"""iter348 — RV-01 / H01 (ALTA): el reintento NO puede dar por ajustado un
conteo cuyo stock sigue pendiente.

Reproduce EXACTAMENTE el caso del auditor: el movimiento de ajuste ya quedó
registrado con stock_applied=False (interrupción entre el log y la aplicación)
y auth_state='claiming'. Al reintentar la autorización de la MISMA versión:
- debe existir UN solo ajuste y el stock debe quedar en 8 (efecto completado), o
- la operación debe seguir pendiente (409) hasta alcanzar ese estado.
Nunca debe responder 'ajustado' con stock 10 y stock_applied=False.
"""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from db_client import db
from services.inventory import today_havana
from services.inventory_ipv import (record_physical_count,
                                     authorize_count_adjustment)

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk_product(stock=10.0, cost=200.0):
    pid = f"TEST_IPV348_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 500.0,
        "cost_usd": cost, "stock": stock, "unit": "unidad", "is_active": True})
    return pid


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


async def _inject_interrupted_adjustment(pid, count_id, *, applied_stock):
    """Simula el ajuste registrado pero con el stock SIN aplicar (interrupción
    tras insertar el movimiento, antes de aplicar stock). Si `applied_stock` es
    False el stock del producto NO se toca (sigue como está)."""
    count = await db.inventory_counts.find_one({"id": count_id}, {"_id": 0})
    version = count.get("version")
    mov_id = str(uuid.uuid4())
    await db.inventory_movements.insert_one({
        "id": mov_id, "product_id": pid, "product_name": pid,
        "type": "ajuste_neg", "quantity": 2.0, "unit": "unidad",
        "unit_price": 500.0, "unit_cost": 200.0, "total": 400.0,
        "cost_of_sale": 0.0, "profit": 0.0,
        "note": "Ajuste interrumpido", "photo_url": "", "source": "conteo",
        "ref_id": count_id, "actor_id": ACTOR["user_id"],
        "actor_email": ACTOR["email"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dedupe_key": f"count-adjust:{count_id}:v{version}",
        "needs_stock": True, "stock_applied": bool(applied_stock)})
    await db.inventory_counts.update_one(
        {"id": count_id}, {"$set": {"auth_state": "claiming"}})
    return mov_id


async def test_retry_completes_pending_stock_once():
    """Caso del auditor: stock 10, conteo 8 (diff -2), ajuste YA registrado con
    stock_applied=False. El reintento debe COMPLETAR el efecto: stock 8, un solo
    ajuste, stock_applied=True y conteo 'ajustado'."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await record_physical_count(
            {"id": pid, "name": pid, "stock": 10.0, "cost_usd": 200.0,
             "unit": "unidad"}, 8, ACTOR)
        assert c["difference"] == -2.0
        mov_id = await _inject_interrupted_adjustment(pid, c["id"], applied_stock=False)
        # Precondición del bug: el stock sigue en 10 y el movimiento pendiente.
        assert await _stock(pid) == 10.0

        res = await authorize_count_adjustment(c["id"], "DOC-348", "", ACTOR)

        # Aceptación: un único ajuste y stock 8 (efecto confirmado).
        assert await _stock(pid) == 8.0
        n_adj = await db.inventory_movements.count_documents(
            {"product_id": pid, "type": {"$in": ["ajuste_pos", "ajuste_neg"]}})
        assert n_adj == 1, "el ajuste no debe duplicarse"
        mov = await db.inventory_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["stock_applied"] is True
        assert res["authorized"] is True and res["status"] == "ajustado"
        assert res["adjustment_movement_id"] == mov_id
    finally:
        await _cleanup(pid)


async def test_retry_stays_pending_when_stock_insufficient():
    """Si al reintentar el stock es insuficiente para aplicar el ajuste, la
    autorización NO debe finalizar: debe quedar EN CURSO (409, pending_apply),
    nunca 'ajustado' con el efecto sin aplicar."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await record_physical_count(
            {"id": pid, "name": pid, "stock": 10.0, "cost_usd": 200.0,
             "unit": "unidad"}, 8, ACTOR)  # diff -2 → ajuste_neg de 2
        await _inject_interrupted_adjustment(pid, c["id"], applied_stock=False)
        # El stock baja a 1 (insuficiente para restar 2) antes del reintento.
        await db.products.update_one({"id": pid}, {"$set": {"stock": 1.0}})

        with pytest.raises(HTTPException) as e:
            await authorize_count_adjustment(c["id"], "DOC-348B", "", ACTOR)
        assert e.value.status_code == 409

        cnt = await db.inventory_counts.find_one({"id": c["id"]}, {"_id": 0})
        assert cnt.get("authorized") is not True
        assert cnt.get("status") != "ajustado"
        assert cnt.get("auth_state") == "pending_apply"
        assert await _stock(pid) == 1.0  # no se aplicó nada
        mov = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "ajuste_neg"}, {"_id": 0})
        assert mov["stock_applied"] is False
    finally:
        await _cleanup(pid)


async def test_normal_authorize_unaffected():
    """Camino feliz sin interrupción: sigue funcionando (stock 8, ajustado)."""
    pid = await _mk_product(stock=10.0)
    try:
        c = await record_physical_count(
            {"id": pid, "name": pid, "stock": 10.0, "cost_usd": 200.0,
             "unit": "unidad"}, 8, ACTOR)
        res = await authorize_count_adjustment(c["id"], "DOC-348OK", "", ACTOR)
        assert res["authorized"] is True and res["status"] == "ajustado"
        assert await _stock(pid) == 8.0
    finally:
        await _cleanup(pid)
