"""iter349 — RV-02 / H03 (ALTA): el histórico debe consumir el ORDEN REAL de
los efectos (secuencia efectiva por producto), no la marca `applied_at` (que
puede sellarse fuera de orden tras un retraso/recuperación de la respuesta).

Escenario del auditor:
1. Apertura documentada: 8 uds @ 200.
2. Entrada 2 @ 500 → la escritura atómica deja products en stock 10, WAC 260.
3. La respuesta de esa entrada se RETRASA (applied_at se sella tarde).
4. Venta de 4.
5. Histórico.

Real: stock 6, WAC 260, valor 1.560. Antes del fix el histórico ordenaba la
venta antes de la entrada (por applied_at) → WAC 300, valor 1.800. Con la
secuencia efectiva, producto e histórico coinciden en 6 / 260 / 1.560.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from db_client import db
from services.inventory import record_movement, today_havana
from services.inventory_ipv import register_audited_opening
from services.inventory_history import build_cutoff_report

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk_product(stock, cost):
    pid = f"TEST_IPV349_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 800.0,
        "cost_usd": float(cost), "stock": float(stock), "unit": "unidad",
        "is_active": True})
    return pid


async def _cleanup(pid):
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_lots.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})
    await db.stock_ops.delete_many({"product_id": pid})


async def _row(pid):
    rep = await build_cutoff_report(today_havana())
    return next((r for r in rep["products"] if r["product_id"] == pid), None)


async def test_h03_history_consumes_effect_sequence_not_applied_at():
    pid = await _mk_product(stock=8, cost=200)
    try:
        # 1) Apertura documentada 8 @ 200 (apply_stock=False).
        await register_audited_opening(pid, 200.0, "Apertura 349", ACTOR)
        # 2) Entrada 2 @ 500 → stock 10, WAC 260 (atómico).
        entrada = await record_movement(
            product=await db.products.find_one({"id": pid}, {"_id": 0}),
            mtype="entrada", quantity=2, unit_cost=500.0, note="compra",
            source="manual", actor=ACTOR)
        prod = await db.products.find_one({"id": pid}, {"_id": 0})
        assert prod["stock"] == 10.0
        assert round(prod["cost_usd"], 2) == 260.0
        # 4) Venta de 4 → stock 6.
        venta = await record_movement(
            product=await db.products.find_one({"id": pid}, {"_id": 0}),
            mtype="venta", quantity=4, note="venta", source="manual",
            actor=ACTOR)
        prod = await db.products.find_one({"id": pid}, {"_id": 0})
        assert prod["stock"] == 6.0
        assert round(prod["cost_usd"], 2) == 260.0

        # La entrada y la venta recibieron secuencia efectiva creciente.
        assert entrada["effect_seq"] < venta["effect_seq"]

        # 3) Simular el SELLADO TARDÍO de applied_at de la entrada: queda
        # DESPUÉS de la venta. Si el histórico ordenara por applied_at, pondría
        # la venta antes de la entrada (WAC 300). La secuencia efectiva lo evita.
        v_at = datetime.fromisoformat(venta["applied_at"])
        late = (v_at + timedelta(minutes=5)).isoformat()
        await db.inventory_movements.update_one(
            {"id": entrada["id"]}, {"$set": {"applied_at": late}})

        row = await _row(pid)
        assert row is not None
        assert row["final_stock"] == 6.0
        assert round(row["wac"], 2) == 260.0, f"WAC esperado 260, got {row['wac']}"
        assert round(row["value"], 2) == 1560.0, f"valor 1560, got {row['value']}"
        assert row["coverage"] == "completa"  # producto e histórico coinciden
    finally:
        await _cleanup(pid)


async def test_h03_pending_entry_before_apply_is_ignored():
    """Primer punto de interrupción (antes de aplicar): un movimiento con el
    stock aún sin aplicar (stock_applied=False, sin secuencia) NO cuenta en el
    histórico hasta que su efecto aterriza."""
    pid = await _mk_product(stock=8, cost=200)
    try:
        await register_audited_opening(pid, 200.0, "Apertura 349b", ACTOR)
        await record_movement(
            product=await db.products.find_one({"id": pid}, {"_id": 0}),
            mtype="entrada", quantity=2, unit_cost=500.0, note="compra",
            source="manual", actor=ACTOR)
        # Inyectar una entrada PENDIENTE (interrumpida antes de aplicar stock):
        # ni toca stock ni tiene secuencia efectiva.
        await db.inventory_movements.insert_one({
            "id": str(uuid.uuid4()), "product_id": pid, "product_name": pid,
            "type": "entrada", "quantity": 5.0, "unit": "unidad",
            "unit_price": 0.0, "unit_cost": 999.0, "total": 4995.0,
            "cost_of_sale": 0.0, "profit": 0.0, "note": "pendiente",
            "source": "manual", "ref_id": "", "actor_id": "", "actor_email": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "needs_stock": True, "stock_applied": False})

        row = await _row(pid)
        # El pendiente (5 @ 999) se ignora: stock 10, WAC 260.
        assert row["final_stock"] == 10.0
        assert round(row["wac"], 2) == 260.0
        assert round(row["value"], 2) == 2600.0
    finally:
        await _cleanup(pid)
