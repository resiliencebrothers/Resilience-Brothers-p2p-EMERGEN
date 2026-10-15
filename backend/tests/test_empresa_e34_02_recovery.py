"""E34-02 (recuperación) — una intención de envío 'initializing' que quedó a
medias (crash entre fases) se COMPENSA de forma duradera e idempotente:
reembolsa la tarifa retenida y devuelve el inventario reservado, dejando la
solicitud en 'failed_init'."""
import uuid
from datetime import datetime, timezone

import pytest

from db_client import db
from services import company_inventory as ci
from services import company_delivery_billing as billing
from services.credit_recovery import heal_initializing_company_deliveries

pytestmark = pytest.mark.asyncio

CID = "user_test_empresa_e3402_rec"


async def _bal():
    u = await db.users.find_one({"user_id": CID}, {"_id": 0, "vip_balances": 1})
    return round(float((u.get("vip_balances") or {}).get("USDT") or 0), 2)


async def _shelf(pid, sid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "by_store": 1})
    return round(float((p.get("by_store") or {}).get(sid) or 0), 3)


async def _clean():
    await db.users.delete_one({"user_id": CID})
    await db.products.delete_many({"company_id": CID})
    await db.stores.delete_many({"company_id": CID})
    await db.company_delivery_requests.delete_many({"company_id": CID})
    await db.deliveries.delete_many({"kind": "company_delivery",
                                     "created_by": CID})
    await db.company_inventory_ops.delete_many({"company_id": CID})


async def test_recoverer_compensates_half_created_send():
    await _clean()
    await db.users.insert_one({"user_id": CID, "vip_balances": {"USDT": 100.0}})
    sid = str(uuid.uuid4())
    await db.stores.insert_one({"id": sid, "company_id": CID, "name": "S", "active": True})
    pid = str(uuid.uuid4())
    await db.products.insert_one({
        "id": pid, "name": "P", "category": "t", "price_usd": 1.0, "cost_usd": 0.0,
        "stock": 10.0, "distributed": 10.0, "by_store": {sid: 10.0}, "is_active": True,
        "owner_id": CID, "company_id": CID, "approval_status": "approved"})
    reqid = str(uuid.uuid4())
    try:
        # Simula un alta que retuvo tarifa y reservó inventario pero murió antes
        # de crear/activar el trabajo (intención 'initializing' antigua).
        assert await billing.hold_fee(CID, reqid, 5) == "applied"
        assert await ci.dispatch_from_store(CID, pid, sid, 3, op_id=f"cdeliv:{reqid}") == "applied"
        assert await _bal() == 95.0 and await _shelf(pid, sid) == 7
        await db.company_delivery_requests.insert_one({
            "id": reqid, "company_id": CID, "client_key": "K-REC",
            "product_id": pid, "origin_store_id": sid, "quantity": 3,
            "fee_usdt": 5, "fee_status": "held", "inv_reserved": True,
            "inv_returned": False, "status": "initializing", "delivery_id": None,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00"})

        n = await heal_initializing_company_deliveries(max_age_seconds=0)
        assert n >= 1
        # compensado EXACTAMENTE una vez: tarifa reembolsada + inventario devuelto
        assert await _bal() == 100.0
        assert await _shelf(pid, sid) == 10
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r["status"] == "failed_init"
        assert r["fee_status"] == "refunded" and r["inv_returned"] is True

        # idempotente: una segunda pasada no vuelve a mover saldo ni stock
        await heal_initializing_company_deliveries(max_age_seconds=0)
        assert await _bal() == 100.0 and await _shelf(pid, sid) == 10
    finally:
        await _clean()


async def test_recoverer_ignores_activated_send():
    await _clean()
    await db.users.insert_one({"user_id": CID, "vip_balances": {"USDT": 100.0}})
    reqid = str(uuid.uuid4())
    try:
        # Una solicitud ya activada ('requested') no debe tocarse jamás.
        await db.company_delivery_requests.insert_one({
            "id": reqid, "company_id": CID, "client_key": "K-OK",
            "fee_usdt": 5, "fee_status": "held", "inv_reserved": False,
            "inv_returned": False, "status": "requested", "delivery_id": "d1",
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00"})
        await heal_initializing_company_deliveries(max_age_seconds=0)
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r["status"] == "requested"  # intacta
    finally:
        await _clean()
