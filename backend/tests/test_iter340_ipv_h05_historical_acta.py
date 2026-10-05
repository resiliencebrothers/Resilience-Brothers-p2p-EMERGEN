"""iter340 — IPV H05 (ALTA): el acta de una fecha pasada NO puede congelar el
stock/costo ACTUALES; debe reflejar la reconstrucción histórica de esa fecha.

Caso del auditor:
- Apertura 12 uds @ 20 el día del corte (D).
- Después, entrada de 3 @ 40 (posterior a D) → existencia actual 15, WAC 24.
- Guardar un cierre vinculado a D.

Antes: el acta de D guardaba 360 CUP (15 × 24, stock/costo de HOY). Ahora debe
guardar 240 CUP (12 × 20) y concordar con el corte histórico de D.
"""
import uuid

import pytest

from db_client import db
from services.inventory_ipv import save_close_review
from services.inventory_history import build_cutoff_report

pytestmark = pytest.mark.asyncio

ACTOR = {"user_id": "user_test_admin01", "email": "admin.test@resilience.com"}
D = "2025-03-15"              # fecha de corte (pasada)
LATER = "2025-03-20T12:00:00+00:00"
D_AT = "2025-03-15T12:00:00+00:00"


async def _mov(pid, qty, unit_cost, created_at):
    await db.inventory_movements.insert_one({
        "id": str(uuid.uuid4()), "product_id": pid, "product_name": pid,
        "type": "entrada", "quantity": float(qty), "unit": "unidad",
        "unit_price": 0.0, "unit_cost": float(unit_cost),
        "total": float(qty) * float(unit_cost), "cost_of_sale": 0.0,
        "profit": 0.0, "note": "", "source": "manual", "ref_id": "",
        "actor_id": "", "actor_email": "", "created_at": created_at})


async def _cleanup(pid):
    await db.products.delete_many({"id": pid})
    await db.inventory_movements.delete_many({"product_id": pid})
    await db.inventory_closes.delete_many({"close_date": D})
    await db.inventory_close_snapshots.delete_many({"close_date": D})


async def test_historical_close_acta_uses_cutoff_values_not_current():
    pid = f"TEST_IPV340_{uuid.uuid4().hex[:8]}"
    # Estado ACTUAL del producto: 15 uds, WAC 24 (tras ambas entradas).
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 40.0,
        "cost_usd": 24.0, "stock": 15.0, "unit": "unidad",
        "is_active": True, "owner_id": ""})
    try:
        await _mov(pid, 12, 20.0, D_AT)      # apertura el día del corte
        await _mov(pid, 3, 40.0, LATER)      # entrada POSTERIOR al corte

        # El corte histórico de D vale 240 (12 × 20), no 360.
        rep = await build_cutoff_report(D)
        hrow = next(r for r in rep["products"] if r["product_id"] == pid)
        assert hrow["final_stock"] == 12.0
        assert hrow["wac"] == 20.0
        assert hrow["value"] == 240.0

        # Guardar el cierre vinculado a D y leer el acta congelada.
        await save_close_review(D, "Resp", "Rev", "F-340", "", ACTOR)
        snap = await db.inventory_close_snapshots.find_one(
            {"close_date": D}, {"_id": 0}, sort=[("version", -1)])
        assert snap is not None
        srow = next(r for r in snap["products"] if r["product_id"] == pid)

        # El acta debe concordar con el corte histórico (no con el stock de hoy).
        assert srow["stock"] == 12.0, "no debe usar el stock actual (15)"
        assert srow["cost_usd"] == 20.0, "no debe usar el WAC actual (24)"
        assert srow["value_cup"] == 240.0, "no debe valorar 360"
        assert snap.get("basis") == "historico"
        assert snap.get("cutoff") == D
    finally:
        await _cleanup(pid)
