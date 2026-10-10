"""SUN-08-R1 (variante pendiente) — INGRESO TARDÍO tras el aborto.

Bug: el recuperador general selecciona una COPIA del movimiento ANTES del
aborto; luego la solicitud aborta el cobro; al reanudarse, el recuperador llama
`_record_fund_flow(copia_vieja)` y, como comprobaba `cobro_aborted` sobre la
copia en memoria, insertaba el ingreso +100 pese a que el movimiento ya estaba
abortado/anulado. Fondo neto del cobro = +100 en vez de 0. Volver a ejecutar
los recuperadores no lo quitaba.

Fix: (1) `_record_fund_flow` RE-LEE la decisión terminal desde la BD justo antes
de insertar (cierra la ventana común lectura→aborto→inserción); (2) como el
ingreso y el aborto viven en colecciones distintas sin transacción, un
`reconcile_aborted_cobro_funds` DURABLE e IDEMPOTENTE compensa cualquier ingreso
tardío que se cuele (inflow presente + outflow ausente en una venta abortada →
publica el outflow). El neto final es 0 y repetir la recuperación no lo cambia.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from db_client import db
import services.inventory as sinv
from services.inventory import (record_movement, reverse_cobro,
                                reconcile_aborted_cobro_funds)


async def _mk(stock=10.0, price=100.0, cost=60.0, unit="unidad"):
    pid = f"TEST_LI_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": price,
        "cost_usd": cost, "stock": stock, "unit": unit, "is_active": True})
    return pid


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return round(float((p or {}).get("stock") or 0), 3)


async def _fund_net(pid):
    movs = await db.inventory_movements.find(
        {"product_id": pid}, {"_id": 0, "id": 1}).to_list(5000)
    ids = [m["id"] for m in movs]
    rows = await db.company_fund_adjustments.find(
        {"ref_id": {"$in": ids}}, {"_id": 0, "adjustment_type": 1, "amount": 1}
    ).to_list(5000)
    net = 0.0
    for r in rows:
        a = float(r["amount"])
        net += a if r["adjustment_type"] == "inflow" else -a
    return round(net, 2)


async def _cleanup(*pids):
    for pid in pids:
        movs = await db.inventory_movements.find(
            {"product_id": pid}, {"_id": 0, "id": 1, "cobro_id": 1}).to_list(5000)
        mov_ids = [m["id"] for m in movs]
        cobro_ids = [m.get("cobro_id") for m in movs if m.get("cobro_id")]
        await db.company_fund_adjustments.delete_many({"ref_id": {"$in": mov_ids}})
        await db.inventory_movements.delete_many({"product_id": pid})
        for mid in mov_ids:
            await db.stock_ops.delete_many(
                {"op_id": {"$in": [f"invmov:{mid}", f"invmov:{mid}:burn",
                                   f"invmov:{mid}:undo"]}})
        await db.products.delete_many({"id": pid})
        await db.inventory_lots.delete_many({"product_id": pid})
        if cobro_ids:
            await db.pos_cobros.delete_many({"id": {"$in": cobro_ids}})


async def _noop_fund(mov):   # el ingreso NO llega a registrarse
    return


def _since():
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()


# ═══════ Orden exacto: recuperador lee → aborto → inserción tardía ══════════
@pytest.mark.asyncio
async def test_late_inflow_after_abort_is_skipped_by_fresh_recheck(monkeypatch):
    S = 10.0
    pid = await _mk(stock=S, price=100.0, cost=60.0)
    cid = str(uuid.uuid4())
    prod = await db.products.find_one({"id": pid}, {"_id": 0})
    try:
        # Venta aplicada SIN ingreso (fallo absorbido): stock −1, sin inflow.
        monkeypatch.setattr(sinv, "_record_fund_flow", _noop_fund)
        mov = await record_movement(product=prod, mtype="venta", quantity=1,
                                   source="manual", cobro_id=cid)
        monkeypatch.undo()
        assert await _stock(pid) == S - 1
        assert await _fund_net(pid) == 0.0

        # El recuperador general obtiene una COPIA del movimiento ANTES del aborto.
        stale = await db.inventory_movements.find_one({"id": mov["id"]}, {"_id": 0})
        assert "cobro_aborted" not in stale

        # La solicitud aborta el cobro por completo.
        await reverse_cobro(cid)
        assert await _stock(pid) == S
        assert await _fund_net(pid) == 0.0

        # El recuperador REANUDA con su copia vieja → intento de inserción tardía.
        # El re-check de la decisión terminal desde la BD lo OMITE.
        await sinv._record_fund_flow(stale)
        assert await _fund_net(pid) == 0.0

        # Repetir la recuperación no cambia el neto.
        await sinv._record_fund_flow(stale)
        await reverse_cobro(cid)
        assert await _fund_net(pid) == 0.0
        assert await _stock(pid) == S
    finally:
        await _cleanup(pid)


# ═══════ Compensación DURABLE e IDEMPOTENTE del ingreso tardío que se cuela ═
@pytest.mark.asyncio
async def test_reconciler_compensates_leaked_late_inflow_idempotently():
    S = 10.0
    pid = await _mk(stock=S, price=100.0, cost=60.0)
    cid = str(uuid.uuid4())
    prod = await db.products.find_one({"id": pid}, {"_id": 0})
    try:
        mov = await record_movement(product=prod, mtype="venta", quantity=1,
                                   source="manual", cobro_id=cid)   # aplicado + ingreso
        await reverse_cobro(cid)                                    # aborto: neto 0
        assert await _fund_net(pid) == 0.0

        # Modelar la VENTANA RESIDUAL: el ingreso quedó, pero el outflow de
        # reversión no (inflow presente + outflow ausente en venta abortada).
        await db.company_fund_adjustments.delete_many(
            {"dedupe_key": f"cobro-rev-fund:{mov['id']}"})
        assert await _fund_net(pid) == 100.0

        # El reconciliador durable compensa (publica el outflow).
        fixed = await reconcile_aborted_cobro_funds(_since())
        assert fixed >= 1
        assert await _fund_net(pid) == 0.0

        # Idempotente: repetir no duplica ni descuadra.
        await reconcile_aborted_cobro_funds(_since())
        assert await _fund_net(pid) == 0.0
    finally:
        await _cleanup(pid)


# ═══════ Sin ingreso → el reconciliador NO crea salida fantasma ════════════
@pytest.mark.asyncio
async def test_reconciler_no_phantom_outflow_without_inflow(monkeypatch):
    S = 10.0
    pid = await _mk(stock=S, price=100.0, cost=60.0)
    cid = str(uuid.uuid4())
    prod = await db.products.find_one({"id": pid}, {"_id": 0})
    try:
        monkeypatch.setattr(sinv, "_record_fund_flow", _noop_fund)
        mov = await record_movement(product=prod, mtype="venta", quantity=1,
                                   source="manual", cobro_id=cid)   # sin ingreso
        monkeypatch.undo()
        await reverse_cobro(cid)                                    # aborto
        assert await _fund_net(pid) == 0.0

        await reconcile_aborted_cobro_funds(_since())
        # Nunca hubo ingreso → NO se publica ningún outflow (sin fantasma).
        assert await _fund_net(pid) == 0.0
        out = await db.company_fund_adjustments.find_one(
            {"dedupe_key": f"cobro-rev-fund:{mov['id']}"}, {"_id": 1})
        assert out is None
    finally:
        await _cleanup(pid)
