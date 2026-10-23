"""E06 — reserva del 1% sobre ventas de inventario propio Resilience.

Movimiento REAL: al entregar una venta de inventario propio (sin vendedor ni
empresa) se aparta el 1% como SALIDA del fondo operativo hacia la reserva
(idempotente); un rechazo posterior lo devuelve (entrada). No es un ingreso de
venta nuevo (no duplica el asiento de la venta).
"""
import uuid

import pytest

from db_client import db
from routes.admin import _reserve_own_inventory_sale, _reverse_own_reserve_if_any

pytestmark = pytest.mark.asyncio

PREFIX = "TESTE06_"


async def _mk_own(total):
    rid = f"{PREFIX}{uuid.uuid4().hex[:8]}"
    await db.redemptions.insert_one({
        "id": rid, "status": "delivered", "total_usd": float(total),
        "quantity": 1, "product_name": "QA propio", "vendor_owner_id": "",
        "company_id": "", "rejection_cycle": 0})
    return rid


async def _cleanup(ids):
    await db.redemptions.delete_many({"id": {"$in": ids}})
    await db.company_fund_adjustments.delete_many({"ref_id": {"$in": ids}})


async def _set_pct(pct):
    prev = await db.settings.find_one(
        {"id": "global"}, {"_id": 0, "vendor_commission_pct": 1}) or {}
    await db.settings.update_one(
        {"id": "global"}, {"$set": {"vendor_commission_pct": pct}}, upsert=True)
    return prev.get("vendor_commission_pct", 1.0)


async def test_reserve_sets_aside_1pct_as_fund_outflow_idempotent():
    prev = await _set_pct(1.0)
    rid = await _mk_own(1000.0)
    try:
        await _reserve_own_inventory_sale(await db.redemptions.find_one({"id": rid}, {"_id": 0}))
        r = await db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert round(r["reserve_amount"], 6) == 10.0
        assert r.get("reserve_at") and r["reserve_pct"] == 1.0
        adj = await db.company_fund_adjustments.find_one(
            {"dedupe_key": f"own-reserve:{rid}:c0"}, {"_id": 0})
        assert adj and adj["adjustment_type"] == "outflow"  # salida, NO ingreso
        assert round(adj["amount"], 6) == 10.0
        # Idempotente: segunda pasada no crea otra salida.
        await _reserve_own_inventory_sale(await db.redemptions.find_one({"id": rid}, {"_id": 0}))
        n = await db.company_fund_adjustments.count_documents(
            {"ref_id": rid, "adjustment_type": "outflow"})
        assert n == 1
    finally:
        await _cleanup([rid])
        await _set_pct(prev)


async def test_vendor_and_company_products_are_not_reserved():
    prev = await _set_pct(1.0)
    vend = f"{PREFIX}{uuid.uuid4().hex[:8]}"
    comp = f"{PREFIX}{uuid.uuid4().hex[:8]}"
    await db.redemptions.insert_many([
        {"id": vend, "status": "delivered", "total_usd": 100.0, "quantity": 1,
         "product_name": "v", "vendor_owner_id": "someowner", "company_id": ""},
        {"id": comp, "status": "delivered", "total_usd": 100.0, "quantity": 1,
         "product_name": "c", "vendor_owner_id": "", "company_id": "somecompany"},
    ])
    try:
        await _reserve_own_inventory_sale(await db.redemptions.find_one({"id": vend}, {"_id": 0}))
        await _reserve_own_inventory_sale(await db.redemptions.find_one({"id": comp}, {"_id": 0}))
        assert not (await db.redemptions.find_one({"id": vend}, {"_id": 0})).get("reserve_at")
        assert not (await db.redemptions.find_one({"id": comp}, {"_id": 0})).get("reserve_at")
    finally:
        await _cleanup([vend, comp])
        await _set_pct(prev)


async def test_rejection_returns_the_reserve_to_the_fund():
    prev = await _set_pct(1.0)
    rid = await _mk_own(500.0)
    try:
        await _reserve_own_inventory_sale(await db.redemptions.find_one({"id": rid}, {"_id": 0}))
        await db.redemptions.update_one({"id": rid}, {"$set": {"rejection_cycle": 1}})
        await _reverse_own_reserve_if_any(await db.redemptions.find_one({"id": rid}, {"_id": 0}))
        r = await db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert r.get("reserve_reversed_at")
        rev = await db.company_fund_adjustments.find_one(
            {"dedupe_key": f"own-reserve-reverse:{rid}:c1"}, {"_id": 0})
        assert rev and rev["adjustment_type"] == "inflow"  # devuelve al fondo
        assert round(rev["amount"], 6) == 5.0
    finally:
        await _cleanup([rid])
        await _set_pct(prev)
