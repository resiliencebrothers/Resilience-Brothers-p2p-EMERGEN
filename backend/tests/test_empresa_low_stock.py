"""Alerta de stock bajo (Empresa) — avisa cuando el almacén central cae a/por
debajo del mínimo configurable, y se re-arma al reponer."""
import uuid

import pytest

from db_client import db
from services import company_inventory as ci
import routes.company  # noqa: F401 — asegura efectos de registro del módulo

COMPANY = "user_test_empresa_lowstock"


async def _mk(min_stock=0.0):
    pid = f"TEST_LOW_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": f"Prod {pid}", "category": "test", "price_usd": 1.0,
        "cost_usd": 0.0, "stock": 0.0, "distributed": 0.0, "by_store": {},
        "min_stock": float(min_stock), "unit": "unidad",
        "is_active": True, "owner_id": COMPANY, "company_id": COMPANY,
        "approval_status": "approved"})
    return pid


async def _clean(pid):
    await db.products.delete_many({"company_id": COMPANY})
    await db.company_inventory_moves.delete_many({"company_id": COMPANY})
    await db.company_inventory_ops.delete_many({"company_id": COMPANY})
    await db.notifications.delete_many({"recipient_user_id": COMPANY})


async def _alerts(pid):
    return await db.notifications.count_documents(
        {"recipient_user_id": COMPANY, "type": "company_low_stock",
         "data.product_id": pid})


async def _flag(pid):
    return bool((await db.products.find_one({"id": pid})).get("low_stock_alerted"))


@pytest.mark.asyncio
async def test_no_alert_without_min_stock():
    pid = await _mk(min_stock=0.0)
    try:
        await ci.receive_central(COMPANY, pid, 2, op_key=f"r-{uuid.uuid4().hex}")
        await ci.maybe_alert_low_stock(COMPANY, pid)
        assert await _alerts(pid) == 0        # sin mínimo → sin alerta
    finally:
        await _clean(pid)


@pytest.mark.asyncio
async def test_alert_fires_once_then_rearms():
    pid = await _mk(min_stock=5.0)
    sid = f"store-{uuid.uuid4().hex[:6]}"
    await db.stores.insert_one({"id": sid, "company_id": COMPANY, "name": "T"})
    try:
        # central 10 > 5 → sin alerta
        await ci.receive_central(COMPANY, pid, 10, op_key=f"r1-{uuid.uuid4().hex}")
        await ci.maybe_alert_low_stock(COMPANY, pid)
        assert await _alerts(pid) == 0 and not await _flag(pid)
        # distribuir 6 → central 4 (<=5) → alerta UNA vez
        await ci.distribute(COMPANY, pid, sid, 6, op_key=f"d-{uuid.uuid4().hex}")
        await ci.maybe_alert_low_stock(COMPANY, pid)
        assert await _alerts(pid) == 1 and await _flag(pid)
        # re-llamar sin cambios → no duplica
        await ci.maybe_alert_low_stock(COMPANY, pid)
        assert await _alerts(pid) == 1
        # recibir 10 → central 14 (>5) → re-arma (limpia bandera)
        await ci.receive_central(COMPANY, pid, 10, op_key=f"r2-{uuid.uuid4().hex}")
        await ci.maybe_alert_low_stock(COMPANY, pid)
        assert not await _flag(pid)
        # volver a bajar → alerta de nuevo
        await ci.distribute(COMPANY, pid, sid, 12, op_key=f"d2-{uuid.uuid4().hex}")
        await ci.maybe_alert_low_stock(COMPANY, pid)
        assert await _alerts(pid) == 2 and await _flag(pid)
    finally:
        await db.stores.delete_many({"company_id": COMPANY})
        await _clean(pid)
