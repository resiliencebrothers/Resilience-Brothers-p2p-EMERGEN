"""SUN-08-R1-REC — LA RECONCILIACIÓN PUEDE OMITIR PENDIENTES.

Dos límites del mismo mecanismo:
• Caso A — el barrido hacía `find(...).to_list(500)` sobre TODAS las ventas
  abortadas (incluidas las que no tienen nada que reparar) en orden estable: un
  ingreso pendiente detrás de 500 registros sin trabajo nunca se alcanzaba y
  repetir la tarea recorría siempre los mismos 500.
• Caso B — el scheduler llamaba con `since=ahora−24h`; una obligación pendiente
  más vieja que la ventana (recuperador caído durante el intervalo) quedaba
  excluida por antigüedad.

Fix (SUN-08-R1-REC): el barrido es una COLA DE OBLIGACIONES:
- La selección (agregación con $lookup por `dedupe_key`) devuelve SOLO ítems con
  trabajo real (inflow presente + outflow ausente), así que el límite de 500
  aplica a obligaciones reales y repetir las agota.
- Sin exclusión por antigüedad: el scheduler no pasa ventana temporal.
- Idempotente y sin salida fantasma (solo compensa si el inflow EXISTE).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from db_client import db
from services.inventory import (reconcile_aborted_cobro_funds,
                                reconcile_reversed_cobro_effects,
                                record_movement)

STOCK = 50.0


async def _mk(stock=STOCK, price=100.0):
    pid = f"TEST_REC_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": price,
        "cost_usd": 60.0, "stock": stock, "unit": "unidad", "is_active": True})
    return pid


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return round(float((p or {}).get("stock") or 0), 3)


async def _insert_aborted_sale(pid, total=100.0, with_inflow=False,
                               with_outflow=False, voided_at=None):
    mid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.inventory_movements.insert_one({
        "id": mid, "product_id": pid, "product_name": "T368", "type": "venta",
        "source": "manual", "quantity": 1, "total": total,
        "cobro_aborted": True, "voided": True, "voided_at": voided_at or now,
        "created_at": now, "cobro_id": f"c-{mid}"})
    if with_inflow:
        await db.company_fund_adjustments.insert_one({
            "id": str(uuid.uuid4()), "adjustment_type": "inflow", "amount": total,
            "currency": "CUP", "ref_id": mid,
            "dedupe_key": f"invmov-fund:{mid}", "created_at": now})
    if with_outflow:
        await db.company_fund_adjustments.insert_one({
            "id": str(uuid.uuid4()), "adjustment_type": "outflow", "amount": total,
            "currency": "CUP", "ref_id": mid,
            "dedupe_key": f"cobro-rev-fund:{mid}", "created_at": now})
    return mid


async def _net_for_mid(mid):
    rows = await db.company_fund_adjustments.find(
        {"ref_id": mid}, {"_id": 0, "adjustment_type": 1, "amount": 1}
    ).to_list(100)
    net = 0.0
    for r in rows:
        a = float(r["amount"])
        net += a if r["adjustment_type"] == "inflow" else -a
    return round(net, 2)


async def _has_outflow(mid):
    return bool(await db.company_fund_adjustments.find_one(
        {"dedupe_key": f"cobro-rev-fund:{mid}"}, {"_id": 1}))


async def _cleanup(mids, pids=(), cids=()):
    if mids:
        await db.company_fund_adjustments.delete_many({"ref_id": {"$in": mids}})
        await db.inventory_movements.delete_many({"id": {"$in": mids}})
    for pid in pids:
        movs = await db.inventory_movements.find(
            {"product_id": pid}, {"_id": 0, "id": 1}).to_list(5000)
        ids = [m["id"] for m in movs]
        await db.company_fund_adjustments.delete_many({"ref_id": {"$in": ids}})
        await db.inventory_movements.delete_many({"product_id": pid})
        await db.products.delete_many({"id": pid})
    if cids:
        await db.pos_cobros.delete_many({"id": {"$in": list(cids)}})


# ═══ Caso A — un pendiente DETRÁS de 500+ registros sin trabajo se recupera ══
@pytest.mark.asyncio
async def test_pending_behind_500_noop_is_recovered():
    pid = await _mk()
    now = datetime.now(timezone.utc).isoformat()
    noop = [str(uuid.uuid4()) for _ in range(501)]
    # 501 ventas abortadas SIN ingreso (nada que reparar), en orden estable.
    await db.inventory_movements.insert_many([{
        "id": m, "product_id": pid, "product_name": "T368", "type": "venta",
        "source": "manual", "quantity": 1, "total": 100.0, "cobro_aborted": True,
        "voided": True, "voided_at": now, "created_at": now, "cobro_id": f"c-{m}"}
        for m in noop])
    # La obligación real queda al final (detrás de los 501 sin trabajo).
    pending = await _insert_aborted_sale(pid, total=100.0, with_inflow=True)
    try:
        assert await _net_for_mid(pending) == 100.0
        fixed = await reconcile_aborted_cobro_funds()
        assert fixed >= 1
        assert await _has_outflow(pending) is True
        assert await _net_for_mid(pending) == 0.0
        # Ningún registro sin ingreso recibió salida fantasma.
        for m in noop[:15] + noop[-15:]:
            assert await _has_outflow(m) is False
    finally:
        await _cleanup(noop + [pending], pids=(pid,))


# ═══ Caso B — obligación más VIEJA que la ventana (recuperador caído) ════════
@pytest.mark.asyncio
async def test_pending_older_than_window_is_recovered():
    pid = await _mk()
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    mid = await _insert_aborted_sale(pid, total=100.0, with_inflow=True,
                                     voided_at=old)
    try:
        assert await _net_for_mid(mid) == 100.0
        # Control: con la ventana de 24h (como el viejo scheduler) NO lo ve.
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        assert await reconcile_aborted_cobro_funds(since) == 0
        assert await _net_for_mid(mid) == 100.0
        # El barrido real (sin ventana) SÍ lo recupera.
        fixed = await reconcile_aborted_cobro_funds()
        assert fixed >= 1
        assert await _net_for_mid(mid) == 0.0
    finally:
        await _cleanup([mid], pids=(pid,))


# ═══ Idempotencia + ausencia de salida sin ingreso ══════════════════════════
@pytest.mark.asyncio
async def test_idempotent_and_no_phantom_outflow():
    pid = await _mk()
    pending = await _insert_aborted_sale(pid, total=100.0, with_inflow=True)
    noinflow = await _insert_aborted_sale(pid, total=100.0, with_inflow=False)
    try:
        await reconcile_aborted_cobro_funds()
        assert await _net_for_mid(pending) == 0.0
        # Repetir no duplica el outflow ni cambia el neto.
        await reconcile_aborted_cobro_funds()
        assert await _net_for_mid(pending) == 0.0
        outs = await db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"cobro-rev-fund:{pending}"})
        assert outs == 1
        # Sin ingreso → jamás una salida fantasma.
        assert await _has_outflow(noinflow) is False
        assert await _net_for_mid(noinflow) == 0.0
    finally:
        await _cleanup([pending, noinflow], pids=(pid,))


# ═══ El reconciliador de cobros reversados también garantiza progreso ════════
@pytest.mark.asyncio
async def test_reversed_reconciler_progress_past_noop():
    pid = await _mk()
    now = datetime.now(timezone.utc).isoformat()
    # 501 cobros 'reversed' SIN ventas activas (nada que reparar).
    noop_cids = [str(uuid.uuid4()) for _ in range(501)]
    await db.pos_cobros.insert_many([{
        "id": c, "state": "reversed", "owner": "x", "mov_ids": [],
        "updated_at": now, "created_at": now} for c in noop_cids])
    # 1 cobro 'reversed' CON venta activa (obligación), al final.
    cid = str(uuid.uuid4())
    await db.pos_cobros.insert_one({
        "id": cid, "state": "reversed", "owner": "x", "mov_ids": [],
        "updated_at": now, "created_at": now})
    prod = await db.products.find_one({"id": pid}, {"_id": 0})
    await record_movement(product=prod, mtype="venta", quantity=1,
                          source="manual", cobro_id=cid)
    try:
        assert await _stock(pid) == STOCK - 1
        fixed = await reconcile_reversed_cobro_effects()
        assert fixed >= 1
        assert await _stock(pid) == STOCK
        v = await db.inventory_movements.find_one(
            {"cobro_id": cid, "type": "venta"}, {"_id": 0})
        assert v["voided"] is True and v["cobro_aborted"] is True
    finally:
        await _cleanup([], pids=(pid,), cids=noop_cids + [cid])
