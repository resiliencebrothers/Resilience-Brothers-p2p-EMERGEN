"""iter350f — Conversión de Unidad: cambiar la unidad de un producto CON
historial sin reinterpretar los datos pasados.

Modelo: salida por conversión (unidad vieja) + entrada de apertura por conversión
(unidad nueva, costo convertido), fechadas en la vigencia. Los cortes anteriores
conservan unidad/cantidad originales; desde la vigencia opera en la unidad nueva;
el valor total se preserva; `source='conversion'` no mueve el fondo de la empresa.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import record_movement, today_havana
from services.inventory_history import build_cutoff_report
from services.inventory_ipv import convert_product_unit

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}
LB2KG = 0.45359237


def _d(days_ago):
    return (datetime.strptime(today_havana(), "%Y-%m-%d")
            - timedelta(days=days_ago)).strftime("%Y-%m-%d")


async def _mk_product_with_history(stock=10.0, cost=2.0, unit="libra",
                                   hist_days_ago=20):
    """Producto con apertura DOCUMENTADA (entrada) fechada en el pasado."""
    pid = f"TEST_CONV_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 10.0,
        "cost_usd": 0.0, "stock": 0.0, "unit": unit, "is_active": True,
        "owner_id": ""})
    prod = await db.products.find_one({"id": pid}, {"_id": 0})
    mov = await record_movement(product=prod, mtype="entrada", quantity=stock,
                                unit_cost=cost, source="alta", actor=ACTOR)
    await db.inventory_movements.update_one(
        {"id": mov["id"]},
        {"$set": {"created_at": f"{_d(hist_days_ago)}T12:00:00+00:00",
                  "applied_at": f"{_d(hist_days_ago)}T12:00:00+00:00"}})
    return pid


async def _cleanup(pid):
    movs = await db.inventory_movements.find(
        {"product_id": pid}, {"_id": 0, "id": 1}).to_list(100)
    ids = [m["id"] for m in movs]
    await db.company_fund_adjustments.delete_many({"ref_id": {"$in": ids}})
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_lots.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})
    await db.stock_ops.delete_many({"product_id": pid})
    await db.unit_conversions.delete_many({"product_id": pid})


async def _row(pid, cutoff):
    rep = await build_cutoff_report(cutoff)
    return next((r for r in rep["products"] if r["product_id"] == pid), None)


async def test_conversion_preserves_value_and_switches_unit():
    pid = await _mk_product_with_history(stock=10.0, cost=2.0, unit="libra")
    try:
        res = await convert_product_unit(pid, "kg", LB2KG, _d(10), "DOC-CONV",
                                         "recalibración", ACTOR)
        assert res["from_unit"] == "libra" and res["to_unit"] == "kg"
        assert res["new_stock"] == 4.536  # round(10*0.45359237,3)
        prod = await db.products.find_one({"id": pid}, {"_id": 0})
        assert prod["unit"] == "kg"
        assert abs(prod["stock"] - 4.536) < 1e-6
        # Valor preservado: 10*2 = 20 ≈ 4.536 * new_cost.
        assert abs(prod["stock"] * prod["cost_usd"] - 20.0) < 0.05
    finally:
        await _cleanup(pid)


async def test_past_cutoff_keeps_old_unit_and_qty():
    pid = await _mk_product_with_history(stock=10.0, cost=2.0, unit="libra")
    try:
        await convert_product_unit(pid, "kg", LB2KG, _d(10), "DOC-CONV", "", ACTOR)
        # ANTES de la vigencia: 10 libras intactas.
        before = await _row(pid, _d(15))
        assert before is not None
        assert before["unit"] == "libra"
        assert abs(before["final_stock"] - 10.0) < 1e-6
        # EN/DESPUÉS de la vigencia: unidad nueva (kg) y existencia convertida.
        after = await _row(pid, _d(10))
        assert after["unit"] == "kg"
        assert abs(after["final_stock"] - 4.536) < 1e-6
        today_row = await _row(pid, today_havana())
        assert today_row["unit"] == "kg"
        assert abs(today_row["final_stock"] - 4.536) < 1e-6
    finally:
        await _cleanup(pid)


async def test_no_undocumented_base_after_conversion():
    pid = await _mk_product_with_history(stock=10.0, cost=2.0, unit="libra")
    try:
        await convert_product_unit(pid, "kg", LB2KG, _d(10), "DOC-CONV", "", ACTOR)
        after = await _row(pid, today_havana())
        assert after["undocumented_base"] is False
        assert after["base_gap"] == 0.0
        assert after["coverage"] == "completa"
        # El corte anterior sigue cuadrando en libras.
        before = await _row(pid, _d(15))
        assert before["undocumented_base"] is False
    finally:
        await _cleanup(pid)


async def test_conversion_does_not_touch_company_funds():
    pid = await _mk_product_with_history(stock=10.0, cost=2.0, unit="libra")
    try:
        res = await convert_product_unit(pid, "kg", LB2KG, _d(5), "DOC-CONV",
                                         "", ACTOR)
        conv_ids = [i for i in (res["out_movement_id"], res["in_movement_id"])
                    if i]
        n = await db.company_fund_adjustments.count_documents(
            {"ref_id": {"$in": conv_ids}})
        assert n == 0, "la conversión no debe mover el fondo de la empresa"
    finally:
        await _cleanup(pid)


async def test_validations():
    pid = await _mk_product_with_history(stock=10.0, cost=2.0, unit="libra")
    try:
        # Sin documento.
        with pytest.raises(HTTPException) as e1:
            await convert_product_unit(pid, "kg", LB2KG, _d(5), "", "", ACTOR)
        assert e1.value.status_code == 400
        # Factor <= 0.
        with pytest.raises(HTTPException) as e2:
            await convert_product_unit(pid, "kg", 0, _d(5), "DOC", "", ACTOR)
        assert e2.value.status_code == 400
        # Misma unidad.
        with pytest.raises(HTTPException) as e3:
            await convert_product_unit(pid, "libra", 1.0, _d(5), "DOC", "", ACTOR)
        assert e3.value.status_code == 400
        # Vigencia futura.
        with pytest.raises(HTTPException) as e4:
            await convert_product_unit(pid, "kg", LB2KG, _d(-5), "DOC", "", ACTOR)
        assert e4.value.status_code == 400
        # Vigencia anterior a la última actividad (hist hace 20 días).
        with pytest.raises(HTTPException) as e5:
            await convert_product_unit(pid, "kg", LB2KG, _d(30), "DOC", "", ACTOR)
        assert e5.value.status_code == 400
        # Ninguna conversión debió persistir.
        assert await db.unit_conversions.count_documents({"product_id": pid}) == 0
    finally:
        await _cleanup(pid)


async def test_manual_factor_unidad_to_libra():
    """Factor manual para una conversión que la tabla no cubre (unidad→libra)."""
    pid = await _mk_product_with_history(stock=4.0, cost=5.0, unit="unidad",
                                         hist_days_ago=8)
    try:
        # 1 unidad = 0.5 lb → 4 u = 2 lb; costo 5/u = 10/lb.
        res = await convert_product_unit(pid, "libra", 0.5, _d(3), "DOC", "",
                                         ACTOR)
        assert res["new_stock"] == 2.0
        prod = await db.products.find_one({"id": pid}, {"_id": 0})
        assert prod["unit"] == "libra"
        assert abs(prod["stock"] - 2.0) < 1e-6
        assert abs(prod["stock"] * prod["cost_usd"] - 20.0) < 0.05
    finally:
        await _cleanup(pid)
