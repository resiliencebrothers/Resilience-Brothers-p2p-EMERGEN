"""iter339 — IPV H04 (ALTA): un histórico incompleto NO puede presentarse como
cobertura completa.

El servicio solo marcaba 'parcial' cuando la reconstrucción pasaba por saldo
negativo. Pero un producto antiguo con existencia real sin movimiento de
apertura reconstruye de menos y se mostraba 'completa'. Ahora, para un corte
VIGENTE (hoy), si la existencia reconstruida no iguala la real del producto hay
una base sin documentar → coverage='parcial', sin rellenar con la existencia
de hoy.

Casos: base positiva sin actividad, base positiva con actividad posterior,
producto con apertura documentada (control = completa) y corte PASADO (no se
marca porque no es verificable contra la existencia actual).
"""
import uuid

import pytest

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import today_havana
from services.inventory_history import build_cutoff_report

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk(stock, cost=20.0):
    pid = f"TEST_IPV339_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 40.0,
        "cost_usd": cost, "stock": float(stock), "unit": "unidad",
        "is_active": True, "owner_id": ""})
    return pid


async def _mov(pid, mtype, qty, unit_cost=20.0, created_at=None):
    await db.inventory_movements.insert_one({
        "id": str(uuid.uuid4()), "product_id": pid, "product_name": pid,
        "type": mtype, "quantity": float(qty), "unit": "unidad",
        "unit_price": 0.0, "unit_cost": float(unit_cost),
        "total": float(qty) * float(unit_cost), "cost_of_sale": 0.0,
        "profit": 0.0, "note": "", "source": "manual", "ref_id": "",
        "actor_id": "", "actor_email": "",
        "created_at": created_at or iso(now_utc())})


async def _cleanup(pid):
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})


async def _row(pid, cutoff=None):
    rep = await build_cutoff_report(cutoff or today_havana())
    return next((r for r in rep["products"] if r["product_id"] == pid), None)


async def test_positive_stock_no_activity_is_partial():
    """Base positiva sin ningún movimiento → parcial (sin evidencia)."""
    pid = await _mk(stock=10)
    try:
        row = await _row(pid)
        assert row is not None, "un producto con existencia real debe aparecer"
        assert row["coverage"] == "parcial"
        assert row["undocumented_base"] is True
        assert row["base_gap"] == 10.0
        # No se reconstruye el pasado con la existencia de hoy.
        assert row["final_stock"] == 0.0
    finally:
        await _cleanup(pid)


async def test_positive_stock_with_later_activity_is_partial():
    """Existencia real 12 con solo una entrada de 2 documentada → parcial."""
    pid = await _mk(stock=12)
    try:
        await _mov(pid, "entrada", 2, unit_cost=20.0)
        row = await _row(pid)
        assert row is not None
        assert row["final_stock"] == 2.0, "no se rellena con la existencia real"
        assert row["coverage"] == "parcial"
        assert row["undocumented_base"] is True
        assert row["base_gap"] == 10.0
    finally:
        await _cleanup(pid)


async def test_documented_opening_is_complete():
    """Apertura documentada (movimiento que explica toda la existencia) →
    completa."""
    pid = await _mk(stock=10)
    try:
        await _mov(pid, "entrada", 10, unit_cost=20.0)  # alta = base documentada
        row = await _row(pid)
        assert row is not None
        assert row["final_stock"] == 10.0
        assert row["coverage"] == "completa"
        assert row["undocumented_base"] is False
        assert row["base_gap"] == 0.0
    finally:
        await _cleanup(pid)


async def test_past_cutoff_with_undocumented_base_is_partial():
    """iter350b (RV-03/H04) — un corte PASADO con base sin documentar debe
    seguir PARCIAL: la integridad de la base es invariante en el tiempo y el
    paso de jornada no puede convertir un corte incompleto en completo.
    (Antes este caso se daba por 'completa', consolidando el residual.)"""
    pid = await _mk(stock=10)
    try:
        # Entrada de 4 documentada en el pasado; faltan 6 de base sin origen.
        await _mov(pid, "entrada", 4, unit_cost=20.0,
                   created_at="2026-01-10T12:00:00+00:00")
        row = await _row(pid, cutoff="2026-01-10")
        assert row is not None
        assert row["undocumented_base"] is True
        assert row["coverage"] == "parcial"
        assert row["base_gap"] == 6.0
        assert row["final_stock"] == 4.0  # no se rellena con la existencia de hoy
        assert row["reliable_from"] is None
    finally:
        await _cleanup(pid)
