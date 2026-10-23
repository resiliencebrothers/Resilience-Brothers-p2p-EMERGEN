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


async def test_N01_reserve_is_restored_after_reactivation_cycle():
    """N01 — entregar→rechazar→reactivar→entregar deja reserva neta 10 (una
    salida por cada ciclo de entrega válido) y el canje activo con reserva."""
    from routes.admin import _reactivation_final_update
    prev = await _set_pct(1.0)
    rid = await _mk_own(1000.0)
    try:
        # c0: entrega → reserva 10 (salida)
        await _reserve_own_inventory_sale(await db.redemptions.find_one({"id": rid}, {"_id": 0}))
        # rechazo: ciclo 1 + reverso 10 (entrada)
        await db.redemptions.update_one({"id": rid}, {"$set": {"rejection_cycle": 1}})
        await _reverse_own_reserve_if_any(await db.redemptions.find_one({"id": rid}, {"_id": 0}))
        r1 = await db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert r1.get("reserve_reversed_at")  # revertido

        # reactivación: el update final debe LIMPIAR las marcas de reserva
        update, _ = _reactivation_final_update(r1, "delivered", {"user_id": "qa"})
        await db.redemptions.update_one({"id": rid}, update)
        r2 = await db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert not r2.get("reserve_at") and not r2.get("reserve_reversed_at")
        assert any("reserve_at" in c for c in (r2.get("settlement_cycles") or []))

        # nueva entrega del ciclo reactivado → nueva reserva 10 (activa)
        await _reserve_own_inventory_sale(r2)
        r3 = await db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert r3.get("reserve_at") and not r3.get("reserve_reversed_at")
        assert round(r3["reserve_amount"], 6) == 10.0

        outs = await db.company_fund_adjustments.count_documents(
            {"ref_id": rid, "adjustment_type": "outflow"})
        ins = await db.company_fund_adjustments.count_documents(
            {"ref_id": rid, "adjustment_type": "inflow"})
        assert outs == 2 and ins == 1  # c0 out, c1 reverse in, c1 out → neto 10
    finally:
        await _cleanup([rid])
        await _set_pct(prev)


async def test_N02_reversal_failure_propagates_and_is_idempotent_on_retry(monkeypatch):
    """N02 — si el asiento del reverso falla, la función PROPAGA (no se marca
    revertido) para poder reintentar; un reintento concilia sin duplicar."""
    import services.company_funds_common as cfc
    prev = await _set_pct(1.0)
    rid = await _mk_own(1000.0)
    try:
        await _reserve_own_inventory_sale(await db.redemptions.find_one({"id": rid}, {"_id": 0}))
        await db.redemptions.update_one({"id": rid}, {"$set": {"rejection_cycle": 1}})
        orig = cfc.record_auto_fund_adjustment
        calls = {"n": 0}

        async def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("fallo transitorio del asiento")
            return await orig(*a, **k)

        monkeypatch.setattr(cfc, "record_auto_fund_adjustment", flaky)
        with pytest.raises(Exception):
            await _reverse_own_reserve_if_any(await db.redemptions.find_one({"id": rid}, {"_id": 0}))
        mid = await db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert not mid.get("reserve_reversed_at")  # NO marcado como revertido
        assert await db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"own-reserve-reverse:{rid}:c1"}) == 0  # no hubo asiento

        # reintento → éxito, un solo asiento de reverso
        await _reverse_own_reserve_if_any(await db.redemptions.find_one({"id": rid}, {"_id": 0}))
        done = await db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert done.get("reserve_reversed_at")
        assert await db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"own-reserve-reverse:{rid}:c1"}) == 1
    finally:
        await _cleanup([rid])
        await _set_pct(prev)


async def test_R03_reserve_uses_frozen_pct_not_delivery_config():
    """R03 — la reserva usa el % CONGELADO al comprar (snapshot), no la config
    global al entregar; un canje heredado sin snapshot usa el fallback."""
    prev = await _set_pct(5.0)  # config al ENTREGAR = 5%
    with_snap = f"{PREFIX}{uuid.uuid4().hex[:8]}"
    legacy = f"{PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        await db.redemptions.insert_many([
            {"id": with_snap, "status": "delivered", "total_usd": 1000.0,
             "quantity": 1, "product_name": "snap", "vendor_owner_id": "",
             "company_id": "", "rejection_cycle": 0, "reserve_pct_snapshot": 1.0},
            {"id": legacy, "status": "delivered", "total_usd": 1000.0,
             "quantity": 1, "product_name": "legacy", "vendor_owner_id": "",
             "company_id": "", "rejection_cycle": 0},
        ])
        await _reserve_own_inventory_sale(await db.redemptions.find_one({"id": with_snap}, {"_id": 0}))
        await _reserve_own_inventory_sale(await db.redemptions.find_one({"id": legacy}, {"_id": 0}))
        a = await db.redemptions.find_one({"id": with_snap}, {"_id": 0})
        b = await db.redemptions.find_one({"id": legacy}, {"_id": 0})
        assert round(a["reserve_amount"], 6) == 10.0  # 1% congelado, NO 50
        assert round(b["reserve_amount"], 6) == 50.0  # fallback a 5%
    finally:
        await _cleanup([with_snap, legacy])
        await _set_pct(prev)
