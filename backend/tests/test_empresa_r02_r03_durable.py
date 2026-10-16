"""R02/R03 — recuperación de altas de envío Empresa basada en EFECTOS DURADEROS.

R02: aunque el FLAG de la solicitud quede ATRASADO respecto al efecto real
     (débito/reserva ya aplicados pero fee_status/inv_reserved sin escribir), la
     recuperación reconcilia el saldo y el stock VERDADEROS y sella el estado
     real (no marca reembolsos/devoluciones ficticias).
R03: el creador y el recuperador comparten la decisión terminal (CAS sobre
     'initializing'): si el recuperador compensa primero, el creador NO resucita
     la solicitud; si la entrega ya avanzó (delivered/confirmed), el recuperador
     NO la trata como alta incompleta ni reembolsa.
"""
import asyncio
import uuid

import pytest

from db_client import db
from services import company_inventory as ci
from services import company_delivery_billing as billing
from services.credit_recovery import heal_initializing_company_deliveries

pytestmark = pytest.mark.asyncio

CID = "user_test_empresa_r02r03"


async def _bal():
    u = await db.users.find_one({"user_id": CID}, {"_id": 0, "vip_balances": 1})
    return round(float((u.get("vip_balances") or {}).get("USDT") or 0), 2)


async def _shelf(pid, sid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "by_store": 1})
    return round(float((p.get("by_store") or {}).get(sid) or 0), 3)


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return round(float(p.get("stock") or 0), 3)


async def _clean():
    await db.users.delete_one({"user_id": CID})
    await db.products.delete_many({"company_id": CID})
    await db.stores.delete_many({"company_id": CID})
    await db.company_delivery_requests.delete_many({"company_id": CID})
    await db.deliveries.delete_many({"kind": "company_delivery", "created_by": CID})
    await db.company_inventory_ops.delete_many({"company_id": CID})


async def _seed_real(reqid, *, held_flag, reserved_flag):
    """Aplica débito y reserva REALES, pero graba los FLAGS de la solicitud
    como se indique (simulando que su escritura quedó atrasada)."""
    await db.users.insert_one({"user_id": CID, "vip_balances": {"USDT": 100.0}})
    sid = str(uuid.uuid4())
    await db.stores.insert_one({"id": sid, "company_id": CID, "name": "S", "active": True})
    pid = str(uuid.uuid4())
    await db.products.insert_one({
        "id": pid, "name": "P", "company_id": CID, "owner_id": CID,
        "stock": 10.0, "distributed": 3.0, "by_store": {sid: 3.0}, "is_active": True})
    assert await billing.hold_fee(CID, reqid, 5) == "applied"          # saldo 95
    assert await ci.dispatch_from_store(CID, pid, sid, 3, op_id=f"cdeliv:{reqid}") == "applied"  # stock 7
    await db.company_delivery_requests.insert_one({
        "id": reqid, "company_id": CID, "client_key": reqid,
        "product_id": pid, "origin_store_id": sid, "quantity": 3,
        "fee_usdt": 5, "fee_status": ("held" if held_flag else "pending"),
        "inv_reserved": reserved_flag, "inv_returned": False,
        "status": "initializing", "delivery_id": None,
        "created_at": "2020-01-01T00:00:00+00:00",
        "updated_at": "2020-01-01T00:00:00+00:00"})
    return pid, sid


async def test_r02_lagged_flags_still_reconcile_true_effect():
    await _clean()
    reqid = str(uuid.uuid4())
    try:
        # Efecto REAL aplicado (saldo 95, stock 7) pero FLAGS ATRASADOS:
        # fee_status='pending' (no 'held') e inv_reserved=False.
        pid, sid = await _seed_real(reqid, held_flag=False, reserved_flag=False)
        assert await _bal() == 95.0 and await _stock(pid) == 7.0

        n = await heal_initializing_company_deliveries(max_age_seconds=0)
        assert n >= 1
        # Reconciliado por EFECTO DURADERO: saldo y stock vuelven a su sitio.
        assert await _bal() == 100.0
        assert await _stock(pid) == 10.0 and await _shelf(pid, sid) == 3.0
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r["status"] == "failed_init"
        assert r["fee_status"] == "refunded" and r["inv_returned"] is True
        # Idempotente.
        await heal_initializing_company_deliveries(max_age_seconds=0)
        assert await _bal() == 100.0 and await _stock(pid) == 10.0
    finally:
        await _clean()


async def test_r02_no_real_effect_is_not_marked_refunded_falsely():
    await _clean()
    reqid = str(uuid.uuid4())
    try:
        # Flag dice 'held' pero NUNCA hubo débito real (saldo intacto 100).
        await db.users.insert_one({"user_id": CID, "vip_balances": {"USDT": 100.0}})
        await db.company_delivery_requests.insert_one({
            "id": reqid, "company_id": CID, "client_key": reqid,
            "fee_usdt": 5, "fee_status": "held",
            "inv_reserved": False, "inv_returned": False,
            "status": "initializing", "delivery_id": None,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00"})
        await heal_initializing_company_deliveries(max_age_seconds=0)
        assert await _bal() == 100.0  # el saldo nunca se movió
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        # No se marca 'refunded' ficticio: el débito nunca movió dinero → 'void'.
        assert r["fee_status"] == "void"
    finally:
        await _clean()


async def test_r03_creator_cannot_resurrect_compensated_request():
    await _clean()
    reqid = str(uuid.uuid4())
    try:
        pid, sid = await _seed_real(reqid, held_flag=True, reserved_flag=True)
        # El recuperador COMPENSA primero (reclama initializing → failed_init).
        await heal_initializing_company_deliveries(max_age_seconds=0)
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r["status"] == "failed_init"
        assert await _bal() == 100.0 and await _stock(pid) == 10.0
        # Un intento del creador de "activar" con CAS sobre 'initializing' NO
        # debe resucitar la solicitud ya compensada.
        res = await db.company_delivery_requests.update_one(
            {"id": reqid, "status": "initializing"},
            {"$set": {"status": "requested"}})
        assert res.modified_count == 0  # CAS falla → no se resucita
        r2 = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r2["status"] == "failed_init"
    finally:
        await _clean()


async def test_r03_delivered_is_not_refunded():
    await _clean()
    reqid = str(uuid.uuid4())
    try:
        pid, sid = await _seed_real(reqid, held_flag=True, reserved_flag=True)
        # La entrega vinculada ya está ENTREGADA (movimiento físico sellado).
        await db.deliveries.insert_one({
            "id": f"d-{reqid}", "kind": "company_delivery", "ref_id": reqid,
            "status": "delivered", "created_by": CID,
            "created_at": "2020-01-01T00:00:00+00:00"})
        await heal_initializing_company_deliveries(max_age_seconds=0)
        # NO se reembolsa ni se devuelve stock: no es un alta incompleta.
        assert await _bal() == 95.0 and await _stock(pid) == 7.0
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r["status"] == "requested"  # reactivada como válida
    finally:
        await _clean()
