"""iter341 — IPV H04 seguimiento: apertura auditada de base legacy sin documentar.

Un producto legacy con existencia real pero sin movimiento de origen quedaba
marcado PARCIAL por el corte (iter339/H04). La apertura auditada documenta esa
base: crea un movimiento 'entrada' (apply_stock=False, no toca el fondo) y su
lote; tras ello el corte lo muestra COMPLETA y el stock queda explicado.
"""
import uuid

import pytest

from db_client import db
from services.inventory import today_havana
from services.inventory_ipv import (register_audited_opening,
                                     register_audited_openings_bulk,
                                     _undocumented_gap)
from services.inventory_history import build_cutoff_report

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk(stock, cost=20.0):
    pid = f"TEST_IPV341_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 40.0,
        "cost_usd": cost, "stock": float(stock), "unit": "unidad",
        "is_active": True, "owner_id": ""})
    return pid


async def _mov(pid, mtype, qty, unit_cost=20.0):
    from auth_utils import now_utc, iso
    await db.inventory_movements.insert_one({
        "id": str(uuid.uuid4()), "product_id": pid, "product_name": pid,
        "type": mtype, "quantity": float(qty), "unit": "unidad",
        "unit_price": 0.0, "unit_cost": float(unit_cost),
        "total": float(qty) * float(unit_cost), "cost_of_sale": 0.0,
        "profit": 0.0, "note": "", "source": "manual", "ref_id": "",
        "actor_id": "", "actor_email": "", "created_at": iso(now_utc())})


async def _cleanup(*pids):
    for pid in pids:
        await db.products.delete_many({"id": pid})
        await db.inventory_movements.delete_many({"product_id": pid})
        await db.inventory_lots.delete_many({"product_id": pid})
        await db.company_fund_adjustments.delete_many({"product_id": pid})


async def _row(pid):
    rep = await build_cutoff_report(today_havana())
    return next((r for r in rep["products"] if r["product_id"] == pid), None)


async def test_opening_documents_legacy_base_and_clears_partial():
    pid = await _mk(stock=10, cost=20.0)
    try:
        # Antes: base sin documentar → parcial.
        before = await _row(pid)
        assert before["coverage"] == "parcial"
        assert before["undocumented_base"] is True

        res = await register_audited_opening(pid, None, "", ACTOR)
        assert res["opening_qty"] == 10.0
        assert res["cost_usd"] == 20.0
        assert res["value_cup"] == 200.0

        # Después: el corte muestra la existencia documentada → completa.
        after = await _row(pid)
        assert after["coverage"] == "completa"
        assert after["undocumented_base"] is False
        assert after["final_stock"] == 10.0
        assert after["wac"] == 20.0
        # El movimiento NO generó salida del fondo de la empresa.
        n = await db.company_fund_adjustments.count_documents({"product_id": pid})
        assert n == 0
        # Se registró el lote.
        lots = await db.inventory_lots.count_documents({"product_id": pid})
        assert lots == 1
    finally:
        await _cleanup(pid)


async def test_opening_idempotent_second_call_rejected():
    pid = await _mk(stock=8, cost=10.0)
    try:
        await register_audited_opening(pid, None, "", ACTOR)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await register_audited_opening(pid, None, "", ACTOR)
        assert e.value.status_code == 400
    finally:
        await _cleanup(pid)


async def test_documented_product_rejected():
    pid = await _mk(stock=10, cost=20.0)
    try:
        await _mov(pid, "entrada", 10, 20.0)  # base ya documentada
        assert await _undocumented_gap(await db.products.find_one(
            {"id": pid}, {"_id": 0})) == 0.0
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await register_audited_opening(pid, None, "", ACTOR)
        assert e.value.status_code == 400
    finally:
        await _cleanup(pid)


async def test_cost_override():
    pid = await _mk(stock=5, cost=20.0)
    try:
        res = await register_audited_opening(pid, 7.5, "costo manual", ACTOR)
        assert res["cost_usd"] == 7.5
        assert res["value_cup"] == 37.5
    finally:
        await _cleanup(pid)


async def test_bulk_registers_only_undocumented():
    a = await _mk(stock=10, cost=20.0)            # legacy sin base
    b = await _mk(stock=10, cost=20.0)            # documentado
    try:
        await _mov(b, "entrada", 10, 20.0)
        res = await register_audited_openings_bulk(ACTOR)
        ids = {i["product_id"] for i in res["items"]}
        assert a in ids
        assert b not in ids
        assert (await _row(a))["coverage"] == "completa"
    finally:
        await _cleanup(a, b)
