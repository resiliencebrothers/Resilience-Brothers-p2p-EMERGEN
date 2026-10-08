"""iter352 — RV-01 (ALTA, residual): el RECUPERADOR GENERAL ya no aplica
ajustes de conteo físico sin protección de versión.

Fallo residual reproducido: `credit_recovery.heal_initializing_ops` incluía en
su bloque `needs_stock` los movimientos `source='conteo'` y aplicaba su efecto
DIRECTAMENTE, sin reclamar la versión del conteo ni comprobar su invalidación.
Si el recuperador general ya había leído el movimiento pendiente en memoria y,
entretanto, un RECUENTO (version++) o un BORRADO invalidaba y eliminaba ese
ajuste, el recuperador reanudaba y aplicaba su copia antigua → efecto de stock
FANTASMA (stock cambiaba sin un conteo vigente que lo respaldara). La protección
de _recover_one_count no intervenía porque esta vía era otra.

Fix (iter352): se EXCLUYE `source='conteo'` del recuperador general. Toda la
recuperación de ajustes de conteo queda DELEGADA al recuperador IPV protegido
(recover_pending_count_adjustments → _recover_one_count), que RECLAMA la versión
atómicamente antes de tocar el stock (único ejecutor, sin ventana en memoria).

Escenario del auditor (pasos 1-7), con COMPUERTA para reproducir la ventana:
  stock 10 · conteo 8 (diff -2) interrumpido en pending_apply · venta 9 (→1) ·
  entrada 2 (→3) · el recuperador general tiene el ajuste en memoria · un
  recuento/borrado lo invalida · el recuperador reanuda. Esperado: stock 3.
"""
import uuid
from datetime import timedelta

import pytest

import services.inventory as inv
from db_client import db
from auth_utils import now_utc, iso
from services.inventory import record_movement
from services.inventory_ipv import (record_physical_count, clear_physical_count,
                                     recover_pending_count_adjustments)
from services.credit_recovery import heal_initializing_ops

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}
OLD_TS = iso(now_utc() - timedelta(seconds=600))


async def _mk_product(stock=10.0, cost=200.0):
    pid = f"TEST_IPV352_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 500.0,
        "cost_usd": cost, "stock": float(stock), "unit": "unidad",
        "is_active": True, "owner_id": ""})
    return pid


def _prod(pid, stock):
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


async def _applied_adjustments(pid):
    return await db.inventory_movements.count_documents(
        {"product_id": pid, "type": {"$in": ["ajuste_pos", "ajuste_neg"]},
         "stock_applied": True})


async def _mk_interrupted_count(pid, old=True):
    """Conteo 8 sobre stock 10 (diff -2) dejado en pending_apply con su
    movimiento de ajuste REGISTRADO pero SIN aplicar (interrupción)."""
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
        "actor_email": ACTOR["email"],
        "created_at": OLD_TS if old else iso(now_utc()),
        "dedupe_key": f"count-adjust:{c['id']}:v{version}",
        "needs_stock": True, "stock_applied": False})
    await db.inventory_counts.update_one(
        {"id": c["id"]},
        {"$set": {"auth_state": "pending_apply", "adjustment_document": "DOC-352",
                  "adjustment_movement_id": mov_id, "claimed_by": ACTOR["user_id"]}})
    return c["id"], mov_id


def _gate_apply(op_target, before_apply):
    """Envoltura de apply_stock_idempotent que, la PRIMERA vez que se aplica el
    op objetivo, ejecuta `before_apply` (la invalidación concurrente) ANTES de
    aplicar — reproduce que el recuperador tenía el ajuste en memoria cuando la
    invalidación ganó. Si el fix excluye el op, esta compuerta NUNCA se dispara."""
    real = inv.apply_stock_idempotent
    state = {"fired": False}

    async def gated(*args, **kwargs):
        op_id = args[2] if len(args) > 2 else kwargs.get("op_id")
        if op_id == op_target and not state["fired"]:
            state["fired"] = True
            await before_apply()
        return await real(*args, **kwargs)

    return real, gated, state


# --------------------------------------------------------------------------
# VENTANA EN MEMORIA — RECUENTO gana mientras el recuperador general itera
# --------------------------------------------------------------------------
async def test_general_recoverer_recount_window_no_phantom_effect():
    pid = await _mk_product(10.0)
    try:
        count_id, mov_id = await _mk_interrupted_count(pid)
        await record_movement(product=_prod(pid, 10.0), mtype="venta",
                              quantity=9, note="venta", source="manual", actor=ACTOR)
        assert await _stock(pid) == 1.0
        await record_movement(product=await db.products.find_one({"id": pid}, {"_id": 0}),
                              mtype="entrada", quantity=2, unit_cost=200.0,
                              note="entrada", source="manual", actor=ACTOR)
        assert await _stock(pid) == 3.0

        async def _recount():
            # Recuento de 2 sobre stock 3: sube a versión 2 e invalida el huérfano.
            await record_physical_count(_prod(pid, 3.0), 2, ACTOR)

        real, gated, state = _gate_apply(f"invmov:{mov_id}", _recount)
        inv.apply_stock_idempotent = gated
        try:
            await heal_initializing_ops(max_age_seconds=0)
        finally:
            inv.apply_stock_idempotent = real

        # El recuperador general NO debe haber aplicado el ajuste -2.
        assert state["fired"] is False, \
            "el recuperador general NO debe aplicar ajustes de conteo"
        assert await _stock(pid) == 3.0, "sin efecto fantasma: stock intacto en 3"
        assert await _applied_adjustments(pid) == 0
    finally:
        await _cleanup(pid)


# --------------------------------------------------------------------------
# VENTANA EN MEMORIA — BORRADO gana mientras el recuperador general itera
# --------------------------------------------------------------------------
async def test_general_recoverer_delete_window_no_phantom_effect():
    pid = await _mk_product(10.0)
    try:
        count_id, mov_id = await _mk_interrupted_count(pid)
        await record_movement(product=_prod(pid, 10.0), mtype="venta",
                              quantity=9, note="venta", source="manual", actor=ACTOR)
        await record_movement(product=await db.products.find_one({"id": pid}, {"_id": 0}),
                              mtype="entrada", quantity=2, unit_cost=200.0,
                              note="entrada", source="manual", actor=ACTOR)
        assert await _stock(pid) == 3.0

        async def _delete():
            await clear_physical_count(pid)

        real, gated, state = _gate_apply(f"invmov:{mov_id}", _delete)
        inv.apply_stock_idempotent = gated
        try:
            await heal_initializing_ops(max_age_seconds=0)
        finally:
            inv.apply_stock_idempotent = real

        assert state["fired"] is False
        assert await _stock(pid) == 3.0, "sin efecto fantasma: stock intacto en 3"
        assert await _applied_adjustments(pid) == 0
    finally:
        await _cleanup(pid)


# --------------------------------------------------------------------------
# GARANTÍA directa — el recuperador general IGNORA ajustes de conteo
# --------------------------------------------------------------------------
async def test_general_recoverer_never_applies_conteo_adjustment():
    pid = await _mk_product(10.0)
    try:
        _, mov_id = await _mk_interrupted_count(pid)  # pending_apply, movimiento OLD presente
        healed = await heal_initializing_ops(max_age_seconds=0)
        assert isinstance(healed, int)
        assert await _stock(pid) == 10.0, "el general no toca el stock del conteo"
        mov = await db.inventory_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov.get("stock_applied") is not True, \
            "el movimiento de conteo sigue sin aplicar por el general"
    finally:
        await _cleanup(pid)


# --------------------------------------------------------------------------
# CONTROL — el recuperador IPV protegido SIGUE completando un conteo legítimo
# --------------------------------------------------------------------------
async def test_protected_ipv_recoverer_still_completes_legit_count():
    pid = await _mk_product(10.0)
    try:
        count_id, _ = await _mk_interrupted_count(pid)  # sin ventas: stock sigue 10
        healed = await recover_pending_count_adjustments(stale_seconds=0)
        assert healed >= 1
        assert await _stock(pid) == 8.0, "el recuperador protegido aplica el ajuste -2"
        cur = await db.inventory_counts.find_one({"id": count_id}, {"_id": 0})
        assert cur.get("authorized") is True and cur.get("status") == "ajustado"
        # Efecto único: segundo ciclo no duplica.
        await recover_pending_count_adjustments(stale_seconds=0)
        assert await _stock(pid) == 8.0
        assert await _applied_adjustments(pid) == 1
    finally:
        await _cleanup(pid)


# --------------------------------------------------------------------------
# CONTROL — el recuperador general SIGUE recuperando movimientos NO-conteo
# --------------------------------------------------------------------------
async def test_general_recoverer_still_recovers_manual_movement():
    pid = await _mk_product(10.0)
    try:
        mid = str(uuid.uuid4())
        await db.inventory_movements.insert_one({
            "id": mid, "product_id": pid, "product_name": pid, "type": "venta",
            "quantity": 3.0, "unit": "unidad", "unit_price": 500.0,
            "unit_cost": 200.0, "total": 1500.0, "cost_of_sale": 0.0,
            "profit": 0.0, "note": "venta interrumpida", "source": "manual",
            "ref_id": "", "actor_id": ACTOR["user_id"],
            "actor_email": ACTOR["email"], "created_at": OLD_TS,
            "needs_stock": True, "stock_applied": False})
        await heal_initializing_ops(max_age_seconds=0)
        assert await _stock(pid) == 7.0, "el general sigue aplicando ventas manuales"
        mov = await db.inventory_movements.find_one({"id": mid}, {"_id": 0})
        assert mov.get("stock_applied") is True
    finally:
        await _cleanup(pid)
