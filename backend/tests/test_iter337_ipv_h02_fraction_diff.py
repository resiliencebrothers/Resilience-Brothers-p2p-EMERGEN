"""iter337 — IPV H02: la diferencia fraccionaria NO debe truncarse a entero.

Reproduce el caso exacto de la auditoría: producto de 10 lb, costo 20 CUP/lb,
conteo físico 9,25 lb. La diferencia −0,75 lb (−15 CUP) debe coincidir en:
- conteo (ya correcto antes del fix),
- histórico / corte (build_cutoff_report) y su CSV,
- incidencia de 'diferencia' (que NO puede auto-resolverse como si cuadrara).

Antes del fix ambos consumidores usaban int(difference) → −0,75 se volvía 0,
el valor caía a 0 y la incidencia se cerraba sola. Estas pruebas blindan eso.
"""
import uuid

import pytest

from db_client import db
from services.inventory import today_havana
from services.inventory_ipv import record_physical_count
from services.inventory_history import build_cutoff_report
from services.inventory_incidents import on_count_recorded

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk(unit="libra", stock=10.0, cost=20.0):
    pid = f"TEST_IPV337_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 40.0,
        "cost_usd": cost, "stock": stock, "unit": unit, "is_active": True})
    return pid


async def _cleanup(pid):
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_lots.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})
    await db.inventory_incidents.delete_many({"product_id": pid})
    await db.stock_ops.delete_many({"product_id": pid})


async def _incident(pid):
    return await db.inventory_incidents.find_one(
        {"product_id": pid, "type": "diferencia"}, {"_id": 0})


# ───────────────────── conteo (línea base, debe ya estar bien) ─────────────
async def test_count_stores_fractional_difference():
    pid = await _mk(stock=10.0, cost=20.0)
    try:
        c = await record_physical_count(await db.products.find_one(
            {"id": pid}, {"_id": 0}), 9.25, ACTOR)
        assert c["difference"] == -0.75
        assert c["difference_value"] == -15.0
        assert c["unit"] == "libra"
        assert c["status"] == "faltante"
    finally:
        await _cleanup(pid)


# ───────────────────────── histórico / corte ─────────────────────────
async def test_cutoff_report_keeps_fractional_difference():
    pid = await _mk(stock=10.0, cost=20.0)
    try:
        await record_physical_count(await db.products.find_one(
            {"id": pid}, {"_id": 0}), 9.25, ACTOR)
        report = await build_cutoff_report(today_havana())
        row = next((r for r in report["products"]
                    if r["product_id"] == pid), None)
        assert row is not None, "el producto con conteo debe aparecer"
        cb = row["count"]
        assert cb is not None
        assert cb["difference"] == -0.75, "no debe truncarse a 0"
        assert cb["difference_value"] == -15.0
        assert cb["unit"] == "libra"
    finally:
        await _cleanup(pid)


# ───────────────────────── incidencia de diferencia ─────────────────────────
async def test_incident_created_and_not_autoresolved():
    pid = await _mk(stock=10.0, cost=20.0)
    try:
        c = await record_physical_count(await db.products.find_one(
            {"id": pid}, {"_id": 0}), 9.25, ACTOR)
        # record_physical_count ya dispara on_count_recorded; lo reinvocamos
        # explícito para dejar la aserción autocontenida.
        await on_count_recorded(c)
        inc = await _incident(pid)
        assert inc is not None, "una diferencia ≠ 0 DEBE generar incidencia"
        assert inc["status"] != "resuelta", "no puede auto-resolverse como cero"
        assert inc["amount"] == -15.0
        assert "lb" in inc["detail"]
        assert "-0.75" in inc["detail"]
    finally:
        await _cleanup(pid)


async def test_zero_difference_autoresolves():
    """Un conteo que cuadra (dif 0) SÍ debe auto-resolver la incidencia."""
    pid = await _mk(stock=10.0, cost=20.0)
    try:
        c = await record_physical_count(await db.products.find_one(
            {"id": pid}, {"_id": 0}), 10.0, ACTOR)
        await on_count_recorded(c)
        inc = await _incident(pid)
        # cuadra → no hay incidencia abierta (o quedó resuelta)
        assert inc is None or inc["status"] == "resuelta"
    finally:
        await _cleanup(pid)


async def test_larger_fraction_not_truncated():
    """Diferencia mayor con parte decimal (−2,5 lb) tampoco se pierde."""
    pid = await _mk(stock=10.0, cost=20.0)
    try:
        c = await record_physical_count(await db.products.find_one(
            {"id": pid}, {"_id": 0}), 7.5, ACTOR)
        assert c["difference"] == -2.5
        assert c["difference_value"] == -50.0
        report = await build_cutoff_report(today_havana())
        row = next(r for r in report["products"] if r["product_id"] == pid)
        assert row["count"]["difference"] == -2.5
        assert row["count"]["difference_value"] == -50.0
        inc = await _incident(pid)
        assert inc is not None and inc["status"] != "resuelta"
        assert inc["amount"] == -50.0
    finally:
        await _cleanup(pid)
