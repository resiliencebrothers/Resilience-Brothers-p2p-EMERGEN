"""Alerta POR TIENDA — la Empresa recibe aviso cuando una SUCURSAL concreta se
queda sin existencias de un producto (no solo el almacén central). Re-armable
al reabastecer; no avisa por tiendas en cierre (vaciado intencional)."""
import uuid

import pytest

from db_client import db
from services import company_inventory as ci

pytestmark = pytest.mark.asyncio

COMPANY = "user_test_empresa_store_oos"


async def _mk(by_store, stock=None, distributed=None):
    pid = f"TEST_OOS_{uuid.uuid4().hex[:8]}"
    dist = distributed if distributed is not None else sum(by_store.values())
    stk = stock if stock is not None else dist
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": 1.0,
        "cost_usd": 0.0, "stock": float(stk), "distributed": float(dist),
        "by_store": {k: float(v) for k, v in by_store.items()},
        "is_active": True, "owner_id": COMPANY, "company_id": COMPANY,
        "approval_status": "approved"})
    return pid


async def _mkstore(status=None):
    sid = f"store_{uuid.uuid4().hex[:8]}"
    doc = {"id": sid, "company_id": COMPANY, "name": f"Sucursal {sid[:4]}",
           "address": "x", "active": True}
    if status:
        doc["status"] = status
    await db.stores.insert_one(doc)
    return sid


async def _clean():
    await db.products.delete_many({"company_id": COMPANY})
    await db.stores.delete_many({"company_id": COMPANY})
    await db.company_inventory_moves.delete_many({"company_id": COMPANY})
    await db.company_inventory_ops.delete_many({"company_id": COMPANY})
    await db.notifications.delete_many({"recipient_user_id": COMPANY})


async def _oos_notifs(pid, store_id):
    return await db.notifications.count_documents({
        "recipient_user_id": COMPANY, "type": "company_store_out_of_stock",
        "data.product_id": pid, "data.store_id": store_id})


async def test_alerts_once_when_store_runs_out_and_rearms():
    await _clean()
    sid = await _mkstore()
    pid = await _mk({sid: 2})
    try:
        # vende las 2 unidades de la tienda (recogida en tienda) → se agota
        assert await ci.reserve_pickup(COMPANY, pid, sid, 2, f"loc:{uuid.uuid4().hex}") == "applied"
        await ci.maybe_alert_store_out_of_stock(COMPANY, pid, sid)
        assert await _oos_notifs(pid, sid) == 1
        p = await db.products.find_one({"id": pid})
        assert (p.get("store_low_alerted") or {}).get(sid) is True

        # segunda evaluación con la tienda aún vacía → NO duplica el aviso
        await ci.maybe_alert_store_out_of_stock(COMPANY, pid, sid)
        assert await _oos_notifs(pid, sid) == 1

        # reabastece la tienda (distribución desde central) → re-arma
        await db.products.update_one({"id": pid}, {"$set": {"stock": 5, "distributed": 0}})
        assert await ci.distribute(COMPANY, pid, sid, 3) == "applied"
        await ci.maybe_alert_store_out_of_stock(COMPANY, pid, sid)
        p = await db.products.find_one({"id": pid})
        assert (p.get("store_low_alerted") or {}).get(sid) is False
        assert await _oos_notifs(pid, sid) == 1  # sin aviso nuevo (hay stock)

        # vuelve a agotarse → nuevo aviso (re-armada)
        assert await ci.reserve_pickup(COMPANY, pid, sid, 3, f"loc:{uuid.uuid4().hex}") == "applied"
        await ci.maybe_alert_store_out_of_stock(COMPANY, pid, sid)
        assert await _oos_notifs(pid, sid) == 2
    finally:
        await _clean()


async def test_no_alert_for_store_in_closing():
    await _clean()
    sid = await _mkstore(status="closing")
    pid = await _mk({sid: 0})  # ya en 0 (vaciado por cierre)
    try:
        await ci.maybe_alert_store_out_of_stock(COMPANY, pid, sid)
        assert await _oos_notifs(pid, sid) == 0  # el cierre no es "agotado"
    finally:
        await _clean()


async def test_each_store_tracked_independently():
    await _clean()
    s1, s2 = await _mkstore(), await _mkstore()
    pid = await _mk({s1: 2, s2: 5})
    try:
        assert await ci.reserve_pickup(COMPANY, pid, s1, 2, f"loc:{uuid.uuid4().hex}") == "applied"
        await ci.maybe_alert_store_out_of_stock(COMPANY, pid, s1)
        await ci.maybe_alert_store_out_of_stock(COMPANY, pid, s2)
        assert await _oos_notifs(pid, s1) == 1   # s1 agotada → aviso
        assert await _oos_notifs(pid, s2) == 0   # s2 con stock → sin aviso
    finally:
        await _clean()
