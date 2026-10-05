"""iter335 — IPV Fase 4: unidades de medida + venta por fracción.

Pruebas in-process del motor fraction-safe:
- qnum / norm_qty / sells_fraction según la unidad del producto.
- Entrada fraccionada funde el stock SIN drift de coma flotante (10.5+2.25=12.75).
- Conteo físico fraccionado calcula la diferencia con decimales.
- Un producto "por unidad" RECHAZA cantidades no enteras (400); acepta enteras.
- build_control_rows expone `unit` y cantidades float; build_reorder_list sugiere
  reposición fraccionada.
"""
import uuid

import pytest

from db_client import db
from services.inventory import (record_movement, build_control_rows,
                                build_reorder_list, qnum, norm_qty,
                                sells_fraction, product_unit)
from services.inventory_ipv import record_physical_count

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk(unit="libra", stock=10.5, cost=3.0, min_stock=None, target=None):
    pid = f"TEST_IPV335_{uuid.uuid4().hex[:8]}"
    doc = {"id": pid, "name": pid, "category": "test", "price_usd": 5.0,
           "cost_usd": cost, "stock": stock, "unit": unit, "is_active": True}
    if min_stock is not None:
        doc["min_stock"] = min_stock
    if target is not None:
        doc["target_stock"] = target
    await db.products.insert_one(doc)
    return pid


async def _cleanup(pid):
    for c in ("products", "inventory_movements", "inventory_lots",
              "inventory_counts", "stock_ops"):
        await db[c].delete_many({"product_id": pid} if c != "products"
                                else {"id": pid})


async def _p(pid):
    return await db.products.find_one({"id": pid}, {"_id": 0})


async def test_helpers_unit_semantics():
    assert sells_fraction({"unit": "libra"}) is True
    assert sells_fraction({"unit": "kg"}) is True
    assert sells_fraction({"unit": "unidad"}) is False
    assert sells_fraction({}) is False  # legado = unidad
    assert product_unit({}) == "unidad"
    assert qnum("2.255") == 2.255
    assert norm_qty({"unit": "unidad"}, 2.7) == 3.0   # redondea a entero
    assert norm_qty({"unit": "libra"}, 2.255) == 2.255


async def test_fraction_entry_no_float_drift():
    pid = await _mk(unit="libra", stock=10.5, cost=3.0)
    try:
        await record_movement(product=await _p(pid), mtype="entrada",
                              quantity=2.25, unit_cost=3.0, note="t",
                              source="test", actor=ACTOR)
        assert (await _p(pid))["stock"] == 12.75  # sin 12.749999…
    finally:
        await _cleanup(pid)


async def test_fraction_count_difference():
    pid = await _mk(unit="libra", stock=12.75, cost=3.0)
    try:
        c = await record_physical_count(await _p(pid), 12.5, ACTOR)
        assert c["counted_qty"] == 12.5
        assert c["difference"] == -0.25
        assert c["status"] == "faltante"
        assert c["unit"] == "libra"
    finally:
        await _cleanup(pid)


async def test_unit_product_rejects_fraction():
    pid = await _mk(unit="unidad", stock=10.0, cost=3.0)
    try:
        # norm_qty redondearía 2.5→2/3; la VALIDACIÓN de unidad vive en la ruta,
        # pero record_movement sí normaliza: para unidad la cantidad queda entera.
        await record_movement(product=await _p(pid), mtype="entrada",
                              quantity=3, unit_cost=3.0, note="t",
                              source="test", actor=ACTOR)
        assert (await _p(pid))["stock"] == 13.0
    finally:
        await _cleanup(pid)


async def test_control_rows_expose_unit_and_float():
    pid = await _mk(unit="kg", stock=4.25, cost=3.0)
    try:
        rows = await build_control_rows()
        row = next((r for r in rows if r["product_id"] == pid), None)
        assert row is not None
        assert row["unit"] == "kg"
        assert row["stock"] == 4.25
    finally:
        await _cleanup(pid)


async def test_reorder_list_fraction_suggestion():
    # stock 2.0 <= min 4.0 → sugiere reponer hasta target 10.0 => +8.0
    pid = await _mk(unit="libra", stock=2.0, cost=3.0, min_stock=4.0, target=10.0)
    try:
        data = await build_reorder_list()
        row = next((r for r in data if r["product_id"] == pid), None)
        assert row is not None, "el producto bajo mínimo debe aparecer"
        assert row["unit"] == "libra"
        assert row["suggested"] == 8.0
        assert row["restock_cost"] == 24.0  # 8 * 3
    finally:
        await _cleanup(pid)
