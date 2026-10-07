"""iter338 — IPV H03 (ALTA): el histórico reconstruye por ORDEN EFECTIVO de
aplicación de stock/WAC, no por el created_at del registro.

Caso del auditor:
1. Apertura documentada: 8 unidades a costo 200 (stock 8, WAC 200).
2. Entrada de 2 @ 500 INSERTADA pero detenida ANTES de aplicar stock
   (needs_stock=True, stock_applied=False), con created_at ANTERIOR a la venta.
3. Venta de 4 (aplicada de inmediato).
4. Se completa/recupera la entrada (aplica stock + WAC).

Antes del fix el histórico ordenaba por created_at → reproducía la entrada
antes de la venta → WAC 260 / valor 1.560. El stock real tras aplicar en orden
efectivo es 6 con WAC 300 / valor 1.800. Ahora deben concordar. Además, durante
la pausa el histórico NO debe contar la entrada pendiente (muestra 8, no 10).
"""
import uuid

import pytest

from db_client import db
from auth_utils import now_utc, iso
from services.inventory import (record_movement, apply_stock_idempotent,
                                today_havana)
from services.inventory_history import build_cutoff_report

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}


async def _mk():
    pid = f"TEST_IPV338_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 1000.0,
        "cost_usd": 0.0, "stock": 0.0, "unit": "unidad", "is_active": True})
    return pid


async def _cleanup(pid):
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_lots.delete_many({"product_id": pid})
    await db.inventory_counts.delete_many({"product_id": pid})
    await db.stock_ops.delete_many({"product_id": pid})
    await db.inventory_incidents.delete_many({"product_id": pid})


async def _p(pid):
    return await db.products.find_one({"id": pid}, {"_id": 0})


async def _row(pid, cutoff=None):
    rep = await build_cutoff_report(cutoff or today_havana())
    return next((r for r in rep["products"] if r["product_id"] == pid), None)


async def test_history_matches_effective_moving_cost_after_interruption():
    pid = await _mk()
    try:
        # 1) Apertura 8 @ 200.
        await record_movement(product=await _p(pid), mtype="entrada",
                              quantity=8, unit_cost=200.0, note="apertura",
                              source="manual", actor=ACTOR)
        p = await _p(pid)
        assert p["stock"] == 8.0 and p["cost_usd"] == 200.0

        # 2) Entrada 2 @ 500 INSERTADA pero detenida antes de aplicar stock.
        #    created_at ANTERIOR a la venta para reproducir el bug de orden.
        entry_id = str(uuid.uuid4())
        early = iso(now_utc())
        await db.inventory_movements.insert_one({
            "id": entry_id, "product_id": pid, "product_name": pid,
            "type": "entrada", "quantity": 2.0, "unit": "unidad",
            "unit_price": 500.0, "unit_cost": 500.0, "total": 1000.0,
            "cost_of_sale": 0.0, "profit": 0.0, "note": "entrada pausada",
            "source": "manual", "ref_id": "", "actor_id": "", "actor_email": "",
            "created_at": early, "needs_stock": True, "stock_applied": False})

        # 3) Durante la pausa: el histórico NO cuenta la entrada pendiente.
        row = await _row(pid)
        assert row["final_stock"] == 8.0, "la entrada pendiente no debe contar"
        assert row["wac"] == 200.0
        assert row["value"] == 1600.0

        # 4) Venta de 4 (aplicada de inmediato, created_at POSTERIOR).
        await record_movement(product=await _p(pid), mtype="venta",
                              quantity=4, note="venta", source="manual",
                              actor=ACTOR)
        assert (await _p(pid))["stock"] == 4.0

        # 5) Se completa la entrada: aplica stock + WAC (como el healer/ruta
        #    normal) y sella applied_at AHORA (posterior a la venta). iter349
        #    (RV-02/H03) — como hace _complete_pending_stock, sella la SECUENCIA
        #    EFECTIVA asignada en esta aplicación (posterior a la venta), que es
        #    el orden real que el histórico debe consumir.
        st = await apply_stock_idempotent(pid, 2.0, f"invmov:{entry_id}",
                                          require_available=False,
                                          cost_fold=(2.0, 500.0))
        assert st == "applied"
        op_rec = await db.stock_ops.find_one(
            {"op_id": f"invmov:{entry_id}"}, {"_id": 0, "effect_seq": 1})
        await db.inventory_movements.update_one(
            {"id": entry_id},
            {"$set": {"stock_applied": True, "applied_at": iso(now_utc()),
                      "effect_seq": (op_rec or {}).get("effect_seq")}})

        # Estado real del producto: stock 6, WAC 300, valor 1.800.
        p = await _p(pid)
        assert p["stock"] == 6.0
        assert p["cost_usd"] == 300.0

        # El histórico debe CONCORDAR con el costo móvil efectivo.
        row = await _row(pid)
        assert row["final_stock"] == 6.0
        assert row["wac"] == 300.0, "WAC histórico debe ser 300, no 260"
        assert row["value"] == 1800.0, "valor histórico debe ser 1.800, no 1.560"
    finally:
        await _cleanup(pid)


async def test_effect_applied_after_cutoff_excluded_from_history():
    """Límite de fecha: un efecto cuyo applied_at cae DESPUÉS del corte del día
    no pertenece al histórico de ese día (aunque se haya registrado antes)."""
    pid = await _mk()
    try:
        await record_movement(product=await _p(pid), mtype="entrada",
                              quantity=5, unit_cost=100.0, source="manual",
                              actor=ACTOR)
        # Movimiento aplicado en el futuro (applied_at > fin del día de corte).
        fut_id = str(uuid.uuid4())
        await db.inventory_movements.insert_one({
            "id": fut_id, "product_id": pid, "product_name": pid,
            "type": "entrada", "quantity": 3.0, "unit": "unidad",
            "unit_price": 0.0, "unit_cost": 999.0, "total": 2997.0,
            "cost_of_sale": 0.0, "profit": 0.0, "note": "aplicada tarde",
            "source": "manual", "ref_id": "", "actor_id": "", "actor_email": "",
            "created_at": iso(now_utc()), "needs_stock": True,
            "stock_applied": True, "applied_at": "2999-01-01T00:00:00+00:00"})
        row = await _row(pid)
        # Solo cuenta la apertura de 5 @ 100; la entrada aplicada "tarde" no.
        assert row["final_stock"] == 5.0
        assert row["wac"] == 100.0
        assert row["value"] == 500.0
    finally:
        await _cleanup(pid)
