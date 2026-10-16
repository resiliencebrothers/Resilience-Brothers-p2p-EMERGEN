"""H01–H04 — correcciones de condiciones de CARRERA del alta/compensación de
envíos Empresa (informe de auditoría del commit 93a6b44).

H01: un POST PERDEDOR del CAS final NUNCA cancela el envío que un POST HERMANO
     con la MISMA clave acaba de activar. Se distingue la causa del CAS perdido
     (otro POST ganó vs. aborto duradero del recuperador) ANTES de cancelar nada.
H02: una compensación INTERRUMPIDA (la fila ya pasó a 'failed_init' con efectos
     sin restituir) se REINTENTA hasta sellar; no queda fuera del barrido por
     haber cambiado de estado.
H03: tras decidir ABORTAR un intento, un creador lento NO puede reservar stock
     TARDE: el token de quema se evalúa en la MISMA escritura del producto, así
     la reserva tardía fracasa ('burned') y no deja unidades fantasma.
H04: una devolución con LECTURA ANTIGUA reanudada DESPUÉS del cierre de la tienda
     NO deja estantería huérfana — se reubica al central (self-heal) y el
     reconciliador duradero barre cualquier huérfano superviviente a fallos.
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from starlette.requests import Request

from db_client import db
from auth_utils import now_utc, iso
from services import company_inventory as ci
from services import company_delivery_billing as billing
from services.credit_recovery import heal_initializing_company_deliveries
import services.deliveries as deliv_svc
import services.company_inventory as ci_mod
from routes.company import create_company_delivery, CompanyDeliveryCreate

pytestmark = pytest.mark.asyncio

CID = "user_test_empresa_h0x"
TOKEN = "test_session_empresa_h0x_X"


def _emp_request():
    scope = {
        "type": "http", "method": "POST", "path": "/api/company/deliveries",
        "raw_path": b"/api/company/deliveries", "query_string": b"",
        "headers": [(b"authorization", f"Bearer {TOKEN}".encode())],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("testclient", 12345),
    }
    return Request(scope)


async def _bal():
    u = await db.users.find_one({"user_id": CID}, {"_id": 0, "vip_balances": 1})
    return round(float((u.get("vip_balances") or {}).get("USDT") or 0), 2)


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return round(float((p or {}).get("stock") or 0), 3)


async def _shelf(pid, sid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "by_store": 1})
    return round(float(((p or {}).get("by_store") or {}).get(sid) or 0), 3)


async def _clean():
    await db.users.delete_one({"user_id": CID})
    await db.user_sessions.delete_one({"session_token": TOKEN})
    await db.products.delete_many({"company_id": CID})
    await db.stores.delete_many({"company_id": CID})
    await db.company_delivery_requests.delete_many({"company_id": CID})
    await db.deliveries.delete_many({"kind": "company_delivery", "created_by": CID})
    await db.company_inventory_ops.delete_many({"company_id": CID})


async def _seed_company(stock=10.0):
    """Empresa ACTIVA con sesión, una tienda vigente y un producto con 3 unidades
    distribuidas a esa tienda (central = stock − 3)."""
    now = datetime.now(timezone.utc)
    await db.users.insert_one({
        "user_id": CID, "email": "h0x@example.com", "name": "Empresa H0x",
        "role": "empresa", "account_status": "active", "account_type": "business",
        "email_verified": True, "phone_verified": True,
        "vip_balances": {"USDT": 100.0}})
    await db.user_sessions.insert_one({
        "session_token": TOKEN, "user_id": CID,
        "expires_at": (now + timedelta(days=30)).isoformat()})
    sid = str(uuid.uuid4())
    await db.stores.insert_one({
        "id": sid, "company_id": CID, "name": "Tienda H0x", "active": True,
        "address": "Calle 1", "created_at": iso(now_utc())})
    pid = str(uuid.uuid4())
    await db.products.insert_one({
        "id": pid, "name": "P", "company_id": CID, "owner_id": CID,
        "stock": stock, "distributed": 3.0, "by_store": {sid: 3.0},
        "unit": "unidad", "is_active": True})
    return pid, sid


# ─────────────────────────────────────────────────────────────────────── H01
async def test_h01_losing_post_does_not_cancel_winning_delivery(monkeypatch):
    await _clean()
    saved = await db.settings.find_one(
        {"id": "global"}, {"_id": 0, "company_delivery_fee_usdt": 1})
    await db.settings.update_one(
        {"id": "global"}, {"$set": {"company_delivery_fee_usdt": 5.0}}, upsert=True)
    try:
        pid, sid = await _seed_company()
        assert await billing.get_company_delivery_fee() == 5.0

        # Simula el POST HERMANO ganando el CAS JUSTO antes del nuestro: al crear
        # el trabajo, activamos la solicitud (initializing → requested).
        real_ensure = deliv_svc.ensure_delivery_job

        async def racing_ensure(kind, ref, **kw):
            job = await real_ensure(kind, ref, **kw)
            await db.company_delivery_requests.update_one(
                {"id": ref["id"], "status": "initializing"},
                {"$set": {"status": "requested", "delivery_id": job["id"]}})
            return job

        monkeypatch.setattr(deliv_svc, "ensure_delivery_job", racing_ensure)

        # Espía de cancelación: el perdedor NO debe cancelar nada.
        cancel_calls = []
        real_cancel = deliv_svc.cancel_active_delivery

        async def spy_cancel(kind, ref_id, **kw):
            cancel_calls.append(ref_id)
            return await real_cancel(kind, ref_id, **kw)

        monkeypatch.setattr(deliv_svc, "cancel_active_delivery", spy_cancel)

        key = f"H01-{uuid.uuid4().hex[:8]}"
        payload = CompanyDeliveryCreate(
            receiver_name="Juan", receiver_phone="+5350000000",
            delivery_address="Calle 100", province="La Habana",
            municipality="Centro", note="H01",
            product_id=pid, origin_store_id=sid, quantity=3, client_key=key)
        res = await create_company_delivery(payload, _emp_request())
        monkeypatch.undo()

        # El envío ganador se conserva: ninguna cancelación del perdedor.
        assert cancel_calls == [], cancel_calls
        assert res["delivery_status"] != "cancelled"
        d = await db.deliveries.find_one(
            {"id": res["delivery_id"]}, {"_id": 0, "status": 1})
        assert d is not None and d["status"] != "cancelled"
        # UN solo cargo (100 − 5) y UNA sola reserva de stock (10 − 3).
        assert await _bal() == 95.0
        assert await _stock(pid) == 7.0
        # Una única solicitud y una única entrega activa para esa clave.
        assert await db.company_delivery_requests.count_documents(
            {"company_id": CID, "client_key": key}) == 1
        assert await db.deliveries.count_documents(
            {"kind": "company_delivery", "ref_id": res["id"],
             "status": {"$ne": "cancelled"}}) == 1
    finally:
        monkeypatch.undo()
        await _clean()
        if saved and saved.get("company_delivery_fee_usdt") is not None:
            await db.settings.update_one(
                {"id": "global"},
                {"$set": {"company_delivery_fee_usdt":
                          saved["company_delivery_fee_usdt"]}})


# ─────────────────────────────────────────────────────────────────────── H02
async def test_h02_interrupted_compensation_is_retried_until_sealed():
    await _clean()
    reqid = str(uuid.uuid4())
    try:
        pid, sid = await _seed_company()
        # Efectos REALES aplicados: débito (saldo 95) y reserva (stock 7).
        assert await billing.hold_fee(CID, reqid, 5) == "applied"
        assert await ci.dispatch_from_store(
            CID, pid, sid, 3, op_id=f"cdeliv:{reqid}") == "applied"
        assert await _bal() == 95.0 and await _stock(pid) == 7.0
        # Una primera pasada del recuperador reclamó 'failed_init' pero su
        # compensación se INTERRUMPIÓ: fee_status sigue 'held' y el stock sin
        # devolver. Antes del fix esta fila NUNCA volvía a entrar al barrido
        # (solo miraba 'initializing').
        await db.company_delivery_requests.insert_one({
            "id": reqid, "company_id": CID, "client_key": reqid,
            "product_id": pid, "origin_store_id": sid, "quantity": 3,
            "fee_usdt": 5, "fee_status": "held",
            "inv_reserved": True, "inv_returned": False,
            "status": "failed_init", "delivery_id": None,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00"})

        n = await heal_initializing_company_deliveries(max_age_seconds=0)
        assert n >= 1
        # La compensación interrumpida se completó EXACTAMENTE UNA VEZ.
        assert await _bal() == 100.0
        assert await _stock(pid) == 10.0 and await _shelf(pid, sid) == 3.0
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r["fee_status"] == "refunded" and r["inv_returned"] is True
        # Idempotente: una segunda pasada no mueve saldo ni stock.
        await heal_initializing_company_deliveries(max_age_seconds=0)
        assert await _bal() == 100.0 and await _stock(pid) == 10.0
    finally:
        await _clean()


# ─────────────────────────────────────────────────────────────────────── H03
async def test_h03_late_reservation_after_abort_is_burned():
    await _clean()
    reqid = str(uuid.uuid4())
    try:
        pid, sid = await _seed_company()
        # El creador alcanzó FASE 1 (retuvo la tarifa, saldo 95) y se PAUSÓ
        # ANTES de FASE 2 (reserva de inventario): intent 'initializing' sin
        # reserva.
        assert await billing.hold_fee(CID, reqid, 5) == "applied"
        await db.company_delivery_requests.insert_one({
            "id": reqid, "company_id": CID, "client_key": reqid,
            "product_id": pid, "origin_store_id": sid, "quantity": 3,
            "fee_usdt": 5, "fee_status": "held",
            "inv_reserved": False, "inv_returned": False,
            "status": "initializing", "delivery_id": None,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00"})
        assert await _bal() == 95.0 and await _stock(pid) == 10.0

        # El recuperador reclama failed_init, reembolsa y CONGELA la reserva
        # (token de quema) sin ver aún ninguna reserva aplicada.
        await heal_initializing_company_deliveries(max_age_seconds=0)
        assert await _bal() == 100.0
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r["status"] == "failed_init" and r["inv_returned"] is True

        # El creador REANUDA FASE 2: su reserva TARDÍA debe fracasar ('burned'),
        # NUNCA descontar stock fantasma.
        status = await ci.dispatch_from_store(
            CID, pid, sid, 3, op_id=f"cdeliv:{reqid}")
        assert status == "burned"
        assert await _stock(pid) == 10.0       # nada descontado
        assert await _shelf(pid, sid) == 3.0   # estantería intacta
    finally:
        await _clean()


# ─────────────────────────────────────────────────────────────────────── H04
async def test_h04_stale_return_after_store_close_goes_to_central(monkeypatch):
    await _clean()
    reqid = str(uuid.uuid4())
    try:
        pid, sid = await _seed_company()
        # Producto sin distribución para el escenario de devolución de 2 uds.
        await db.products.update_one({"id": pid}, {"$set": {
            "stock": 8.0, "distributed": 0.0, "by_store": {}}})

        real_db = ci_mod.db
        state = {"deleted": False}

        class _Stores:
            def __getattr__(self, n):
                return getattr(real_db.stores, n)

            async def find_one(self, *a, **k):
                res = await real_db.stores.find_one(*a, **k)
                # Tras la PRIMERA lectura (decisión 'estantería'), el cierre
                # BORRA la tienda → la escritura usa una lectura ANTIGUA (H04).
                if res is not None and not state["deleted"]:
                    state["deleted"] = True
                    await real_db.stores.delete_one(
                        {"id": sid, "company_id": CID})
                return res

        stores_proxy = _Stores()

        class _Db:
            def __getattr__(self, n):
                if n == "stores":
                    return stores_proxy
                return getattr(real_db, n)

        monkeypatch.setattr(ci_mod, "db", _Db())
        status = await ci.return_dispatch(
            CID, pid, sid, 2, op_id=f"cdeliv-ret:{reqid}")
        monkeypatch.undo()

        assert status == "applied"
        # Sin estantería huérfana: las unidades quedaron en el CENTRAL.
        assert await _shelf(pid, sid) == 0.0
        p = await db.products.find_one({"id": pid}, {"_id": 0})
        assert round(float(p["stock"]), 3) == 10.0
        assert round(float(p.get("distributed") or 0), 3) == 0.0
        assert sid not in (p.get("by_store") or {})
    finally:
        monkeypatch.undo()
        await _clean()


async def test_h04_durable_reconciler_sweeps_orphan_shelves():
    await _clean()
    try:
        pid, _sid = await _seed_company()
        # Estantería HUÉRFANA: by_store apunta a una tienda inexistente (una
        # devolución con lectura antigua murió antes del self-heal).
        gone = "tienda-borrada-xyz"
        await db.products.update_one({"id": pid}, {"$set": {
            "stock": 10.0, "distributed": 2.0, "by_store": {gone: 2.0}}})

        n = await ci.heal_orphan_store_shelves(company_id=CID)
        assert n >= 1
        p = await db.products.find_one({"id": pid}, {"_id": 0})
        assert gone not in (p.get("by_store") or {})
        assert round(float(p["stock"]), 3) == 10.0          # total intacto
        assert round(float(p.get("distributed") or 0), 3) == 0.0  # al central
        # Idempotente: un segundo barrido no encuentra nada que sanear.
        assert await ci.heal_orphan_store_shelves(company_id=CID) == 0
    finally:
        await _clean()
