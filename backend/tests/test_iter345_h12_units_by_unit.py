"""iter345 — IPV H12 (MEDIA): los totales de cantidades NO pueden mezclar
unidades (u/lb/kg). El histórico, el acta de cierre y la valoración por lotes
deben conservar la unidad por fila y agregar el total físico POR UNIDAD (o
retirarlo). El valor monetario sí se suma en una moneda común.

Escenario del auditor — tres productos de la empresa con unidades distintas en
el mismo inventario:
- A: unidad, 10 uds @ 5 CUP → stock 10
- B: libra, 4.5 lb @ 8 CUP → stock 4.5
- C: kg, 2.0 kg @ 100 CUP → stock 2.0

Antes: units = 16.5 (mezcla sin sentido 10 u + 4.5 lb + 2 kg).
Ahora: units_by_unit = {unidad: 10, libra: 4.5, kg: 2.0} y cada fila lleva unit.
"""
import uuid

import pytest

from db_client import db
from services.inventory_ipv import save_close_review
from services.inventory_history import build_cutoff_report
from services.inventory_lots import build_valuation

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}
D = "2025-05-10"
D_AT = "2025-05-10T12:00:00+00:00"


async def _entrada(pid, qty, unit_cost, unit):
    await db.inventory_movements.insert_one({
        "id": str(uuid.uuid4()), "product_id": pid, "product_name": pid,
        "type": "entrada", "quantity": float(qty), "unit": unit,
        "unit_price": 0.0, "unit_cost": float(unit_cost),
        "total": float(qty) * float(unit_cost), "cost_of_sale": 0.0,
        "profit": 0.0, "note": "", "source": "manual", "ref_id": "",
        "actor_id": "", "actor_email": "", "created_at": D_AT})


async def _product(pid, unit, stock, cost):
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": cost * 2,
        "cost_usd": float(cost), "stock": float(stock), "unit": unit,
        "is_active": True, "owner_id": ""})


async def _cleanup(pids):
    for pid in pids:
        await db.products.delete_many({"id": pid})
        await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_closes.delete_many({"close_date": D})
    await db.inventory_close_snapshots.delete_many({"close_date": D})


async def test_h12_units_by_unit_everywhere():
    sfx = uuid.uuid4().hex[:8]
    pa = f"TEST_H12_A_{sfx}"   # unidad
    pb = f"TEST_H12_B_{sfx}"   # libra
    pc = f"TEST_H12_C_{sfx}"   # kg
    await _product(pa, "unidad", 10, 5.0)
    await _product(pb, "libra", 4.5, 8.0)
    await _product(pc, "kg", 2.0, 100.0)
    try:
        await _entrada(pa, 10, 5.0, "unidad")
        await _entrada(pb, 4.5, 8.0, "libra")
        await _entrada(pc, 2.0, 100.0, "kg")

        # ── 1) Corte histórico ──────────────────────────────────────────
        rep = await build_cutoff_report(D)
        rows = {r["product_id"]: r for r in rep["products"]}
        assert rows[pa]["unit"] == "unidad"
        assert rows[pb]["unit"] == "libra"
        assert rows[pc]["unit"] == "kg"

        tot = rep["totals"]
        assert "units" not in tot, "el total físico mezclado ya no debe existir"
        ubu = tot["units_by_unit"]
        assert ubu == {"unidad": 10.0, "libra": 4.5, "kg": 2.0}, ubu

        # ── 2) Acta de cierre (snapshot congelado) ──────────────────────
        await save_close_review(D, "Resp", "Rev", "F-345", "", ACTOR)
        snap = await db.inventory_close_snapshots.find_one(
            {"close_date": D}, {"_id": 0}, sort=[("version", -1)])
        assert snap is not None
        srows = {r["product_id"]: r for r in snap["products"]}
        assert srows[pa]["unit"] == "unidad"
        assert srows[pb]["unit"] == "libra"
        assert srows[pc]["unit"] == "kg"
        stot = snap["totals"]
        assert "units" not in stot
        assert stot["units_by_unit"] == {"unidad": 10.0, "libra": 4.5, "kg": 2.0}

        # ── 3) Valoración por lotes (stock vivo) ────────────────────────
        val = await build_valuation(window_days=30)
        vrows = {p["product_id"]: p for p in val["products"]}
        assert vrows[pa]["unit"] == "unidad"
        assert vrows[pb]["unit"] == "libra"
        assert vrows[pc]["unit"] == "kg"
        vtot = val["totals"]
        assert "units" not in vtot
        vubu = vtot["units_by_unit"]
        # Otros productos de la empresa pueden sumar a cada unidad; validamos
        # que nuestros aportes queden reflejados por unidad (no mezclados).
        assert vubu.get("libra", 0) >= 4.5
        assert vubu.get("kg", 0) >= 2.0
        assert vubu.get("unidad", 0) >= 10.0
    finally:
        await _cleanup([pa, pb, pc])
