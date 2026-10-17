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


async def _dist(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "distributed": 1})
    return round(float((p or {}).get("distributed") or 0), 3)


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
        # Restaura EXACTAMENTE el estado previo del ajuste global compartido
        # (valor anterior o AUSENTE): nunca dejar un valor filtrado que pudiera
        # acoplar otros tests que leen la tarifa global.
        orig_fee = (saved or {}).get("company_delivery_fee_usdt")
        if orig_fee is not None:
            await db.settings.update_one(
                {"id": "global"},
                {"$set": {"company_delivery_fee_usdt": orig_fee}})
        else:
            await db.settings.update_one(
                {"id": "global"},
                {"$unset": {"company_delivery_fee_usdt": ""}})


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



# ─────────────────────────────────────────────────────────────────── H02-R
# El reintento NO puede depender de marcas atrasadas (fee_status/inv_reserved):
# R02 incluye efectos aplicados ANTES de escribir esas marcas. La selección usa
# el estado INDEPENDIENTE `comp_sealed`.
async def test_h02r_retry_selects_despite_stale_fee_flag(monkeypatch):
    await _clean()
    reqid = str(uuid.uuid4())
    try:
        await _seed_company()
        # Débito REAL aplicado (saldo 95) pero la marca fee_status NO se escribió
        # (quedó 'pending'): efecto aplicado ANTES de la marca → la marca MIENTE.
        assert await billing.hold_fee(CID, reqid, 5) == "applied"
        assert await _bal() == 95.0
        await db.company_delivery_requests.insert_one({
            "id": reqid, "company_id": CID, "client_key": reqid,
            "product_id": None, "origin_store_id": None, "quantity": 0,
            "fee_usdt": 5, "fee_status": "pending",   # marca ATRASADA
            "inv_reserved": False, "inv_returned": False,
            "status": "failed_init", "delivery_id": None,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00"})

        # 1ª pasada: fallo transitorio al reembolsar → NO sella, saldo sigue 95,
        # pero la fila DEBE seguir siendo seleccionable (no se perdió).
        async def boom_refund(*a, **k):
            raise RuntimeError("fallo transitorio de reembolso")
        monkeypatch.setattr(billing, "refund_fee", boom_refund)
        await heal_initializing_company_deliveries(max_age_seconds=0)
        monkeypatch.undo()
        assert await _bal() == 95.0
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r.get("comp_sealed") is not True

        # 2ª pasada sin fallo: la fila SIGUE seleccionada pese a fee_status
        # 'pending' → se reconcilia por EFECTO DURADERO → saldo 100 y sellada.
        n = await heal_initializing_company_deliveries(max_age_seconds=0)
        assert n >= 1
        assert await _bal() == 100.0
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r["fee_status"] == "refunded" and r.get("comp_sealed") is True
    finally:
        monkeypatch.undo()
        await _clean()


async def test_h02r_retry_selects_despite_stale_inv_flag():
    await _clean()
    reqid = str(uuid.uuid4())
    try:
        pid, sid = await _seed_company()
        # Reserva REAL aplicada de forma duradera (stock 7) pero inv_reserved NO
        # se escribió (quedó False): con la selección ANTIGUA ({inv_reserved:
        # True}) esta fila jamás se reintentaría → stock atascado en 7.
        assert await ci.dispatch_from_store(
            CID, pid, sid, 3, op_id=f"cdeliv:{reqid}") == "applied"
        assert await _stock(pid) == 7.0
        await db.company_delivery_requests.insert_one({
            "id": reqid, "company_id": CID, "client_key": reqid,
            "product_id": pid, "origin_store_id": sid, "quantity": 3,
            "fee_usdt": 0, "fee_status": "none",
            "inv_reserved": False,    # marca ATRASADA (la reserva SÍ se aplicó)
            "inv_returned": False,
            "status": "failed_init", "delivery_id": None,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00"})

        n = await heal_initializing_company_deliveries(max_age_seconds=0)
        assert n >= 1
        # Seleccionada pese a inv_reserved=False → devolución por efecto duradero.
        assert await _stock(pid) == 10.0 and await _shelf(pid, sid) == 3.0
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r["inv_returned"] is True and r.get("comp_sealed") is True
    finally:
        await _clean()


async def test_h02r_first_phase_failure_does_not_block_retries(monkeypatch):
    await _clean()
    bad = str(uuid.uuid4())    # 'initializing' que hará fallar la FASE 1
    good = str(uuid.uuid4())   # 'failed_init' pendiente que debe reintentarse igual
    try:
        await _seed_company()
        # 'good': débito REAL (saldo 95), failed_init sin sellar.
        assert await billing.hold_fee(CID, good, 5) == "applied"
        assert await _bal() == 95.0
        await db.company_delivery_requests.insert_one({
            "id": good, "company_id": CID, "client_key": good,
            "product_id": None, "origin_store_id": None, "quantity": 0,
            "fee_usdt": 5, "fee_status": "held",
            "inv_reserved": False, "inv_returned": False,
            "status": "failed_init", "delivery_id": None,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00"})
        # 'bad': initializing antiguo cuya cancelación en FASE 1 lanzará error.
        await db.company_delivery_requests.insert_one({
            "id": bad, "company_id": CID, "client_key": bad,
            "product_id": None, "origin_store_id": None, "quantity": 0,
            "fee_usdt": 0, "fee_status": "none",
            "inv_reserved": False, "inv_returned": False,
            "status": "initializing", "delivery_id": None,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00"})

        real_cancel = deliv_svc.cancel_active_delivery

        async def selective_cancel(kind, ref_id, **kw):
            if ref_id == bad:
                raise RuntimeError("fallo transitorio de FASE 1")
            return await real_cancel(kind, ref_id, **kw)

        monkeypatch.setattr(deliv_svc, "cancel_active_delivery", selective_cancel)
        await heal_initializing_company_deliveries(max_age_seconds=0)
        monkeypatch.undo()

        # Pese al fallo aislado en 'bad' (FASE 1), 'good' SÍ se reintentó y selló.
        assert await _bal() == 100.0
        rg = await db.company_delivery_requests.find_one({"id": good}, {"_id": 0})
        assert rg["fee_status"] == "refunded" and rg.get("comp_sealed") is True
    finally:
        monkeypatch.undo()
        await _clean()


# ─────────────────────────────────────────────────────────────────── H03-R
# La prohibición de reservar TARDE no puede vivir solo en el array `inv_ops`
# (truncado a 1000): debe ser una decisión TERMINAL DURADERA en
# company_inventory_ops que sobreviva a la rotación del array.
async def test_h03r_burn_decision_survives_inv_ops_rotation():
    await _clean()
    reqid = str(uuid.uuid4())
    opid = f"cdeliv:{reqid}"
    burn_token = f"{opid}:burn"
    try:
        pid, sid = await _seed_company()   # stock 10, by_store {sid: 3}
        # El recuperador CONGELA una reserva aún NO ejecutada (aborto).
        assert await ci.freeze_dispatch(CID, pid, sid, 3, opid) is False
        # Decisión TERMINAL DURADERA registrada (independiente del array).
        rec = await db.company_inventory_ops.find_one(
            {"company_id": CID, "op_key": opid}, {"_id": 0})
        assert rec and rec["status"] == "done" and rec["result"] == "burned"
        # Simula la ROTACIÓN del guard embebido (>1000 movimientos lo desalojan).
        await db.products.update_one(
            {"id": pid}, {"$pull": {"inv_ops": burn_token}})
        p = await db.products.find_one({"id": pid}, {"_id": 0, "inv_ops": 1})
        assert burn_token not in (p.get("inv_ops") or [])
        # El creador REANUDA la reserva: pese a que el token salió del array, la
        # decisión duradera fuerza 'burned' y NO descuenta stock fantasma.
        status = await ci.dispatch_from_store(CID, pid, sid, 3, op_id=opid)
        assert status == "burned"
        assert await _stock(pid) == 10.0
        assert await _shelf(pid, sid) == 3.0
    finally:
        await _clean()


# ────────────────────────────────────────────────────────────────── H03-R2
# Un ejecutor de la reserva YA EN VUELO (leyó 'pending' y está a punto de
# escribir el producto) debe respetar la decisión de aborto DURADERA aunque el
# array acotado `inv_ops` rote por completo mientras estaba pausado. La decisión
# vive en `inv_burned` (conjunto no truncado), no en el array que puede
# desalojarse, y `_run_idempotent` no pisa 'burned' con 'applied'.
async def test_h03r2_inflight_reservation_respects_durable_abort(monkeypatch):
    await _clean()
    reqid = str(uuid.uuid4())
    opid = f"cdeliv:{reqid}"
    try:
        pid, sid = await _seed_company()   # stock 10, by_store {sid: 3}
        real_db = ci_mod.db
        state = {"fired": False}

        async def _abort_and_rotate():
            # El recuperador ABORTA (congela) este intento aún no ejecutado…
            assert await ci.freeze_dispatch(CID, pid, sid, 3, opid) is False
            # …y suficiente actividad del producto ROTA el array acotado inv_ops
            # (desalojaría cualquier marcador que viviese dentro de él).
            for i in range(ci.INV_OPS_CAP + 5):
                assert await ci.receive_central(
                    CID, pid, 1, op_key=f"recv:{reqid}:{i}") == "applied"

        class _Products:
            def __getattr__(self, n):
                return getattr(real_db.products, n)

            async def find_one_and_update(self, *a, **k):
                # La PRIMERA escritura de producto es la reserva EN VUELO: justo
                # ANTES de ejecutarla ocurren el aborto y la rotación.
                if not state["fired"]:
                    state["fired"] = True
                    await _abort_and_rotate()
                return await real_db.products.find_one_and_update(*a, **k)

        products_proxy = _Products()

        class _Db:
            def __getattr__(self, n):
                if n == "products":
                    return products_proxy
                return getattr(real_db, n)

        monkeypatch.setattr(ci_mod, "db", _Db())
        status = await ci.dispatch_from_store(CID, pid, sid, 3, op_id=opid)
        monkeypatch.undo()

        # La reserva tardía NO se aplica pese a la rotación total de inv_ops.
        assert status == "burned"
        assert await _stock(pid) == float(10 + ci.INV_OPS_CAP + 5)  # solo receives
        assert await _shelf(pid, sid) == 3.0                        # estantería intacta
        # El registro duradero sigue 'burned' (el ejecutor en vuelo no lo pisó).
        rec = await db.company_inventory_ops.find_one(
            {"company_id": CID, "op_key": opid}, {"_id": 0, "result": 1})
        assert rec and rec["result"] == "burned"
    finally:
        monkeypatch.undo()
        await _clean()


# ───────────────────────────────────────────────────────────────── H03-R3
# CIERRE del residual A- : el ejecutor EN VUELO de la reserva (op 'pending',
# pausado justo ANTES de escribir el producto) se reanuda DESPUÉS de que la
# RUTA COMPLETA DE RECUPERACIÓN abortó la solicitud (freeze + reembolso +
# comp_sealed) y de que el array acotado `inv_ops` rotó por completo. Se
# verifica CONJUNTAMENTE (criterio de cierre del informe H03-R): stock total y
# por ubicación intactos, resultado terminal 'burned' no sobrescrito, saldo
# correcto (tarifa reembolsada), NINGUNA entrega válida, y que nuevas pasadas
# de recuperación + un reintento del creador NO producen efectos adicionales.
async def test_h03r3_inflight_reservation_through_full_recovery_is_burned(monkeypatch):
    await _clean()
    reqid = str(uuid.uuid4())
    opid = f"cdeliv:{reqid}"
    try:
        pid, sid = await _seed_company()          # stock 10, by_store {sid: 3}, saldo 100
        # El creador alcanzó FASE 1 (tarifa retenida, saldo 95) y la intención
        # 'initializing' quedó registrada SIN reservar aún (inv_reserved=False).
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

        real_db = ci_mod.db
        state = {"fired": False}

        async def _full_recovery_then_rotate():
            # RUTA COMPLETA de recuperación: reclama initializing→failed_init,
            # reembolsa la tarifa, CONGELA la reserva (inv_burned durable) y
            # SELLA la compensación (comp_sealed) — todo sin ver reserva aplicada.
            healed = await heal_initializing_company_deliveries(max_age_seconds=0)
            assert healed >= 1
            r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
            assert r["status"] == "failed_init"
            assert r["inv_returned"] is True and r.get("comp_sealed") is True
            assert await _bal() == 100.0          # tarifa reembolsada
            # …y la actividad del producto ROTA por completo el array acotado.
            for i in range(ci.INV_OPS_CAP + 5):
                assert await ci.receive_central(
                    CID, pid, 1, op_key=f"recv:{reqid}:{i}") == "applied"

        class _Products:
            def __getattr__(self, n):
                return getattr(real_db.products, n)

            async def find_one_and_update(self, *a, **k):
                # La PRIMERA escritura de producto = la reserva EN VUELO del
                # creador. Justo ANTES ocurren la recuperación COMPLETA y la rotación.
                if not state["fired"]:
                    state["fired"] = True
                    await _full_recovery_then_rotate()
                return await real_db.products.find_one_and_update(*a, **k)

        class _Db:
            def __getattr__(self, n):
                if n == "products":
                    return products_proxy
                return getattr(real_db, n)

        products_proxy = _Products()
        monkeypatch.setattr(ci_mod, "db", _Db())
        # El creador REANUDA su reserva tardía (mismo op_id que congeló el recuperador).
        status = await ci.dispatch_from_store(CID, pid, sid, 3, op_id=opid)
        monkeypatch.undo()

        # (1) Resultado TERMINAL: la reserva tardía fracasa, NO descuenta stock.
        assert status == "burned"
        # (2) Stock total y por ubicación INTACTOS (solo cuentan los receives).
        assert await _stock(pid) == float(10 + ci.INV_OPS_CAP + 5)
        assert await _shelf(pid, sid) == 3.0
        # (3) Registro duradero sigue 'burned' (el ejecutor en vuelo no lo pisó).
        rec = await db.company_inventory_ops.find_one(
            {"company_id": CID, "op_key": opid}, {"_id": 0, "status": 1, "result": 1})
        assert rec and rec["status"] == "done" and rec["result"] == "burned"
        # (4) Saldo correcto (tarifa reembolsada, sin doble cargo).
        assert await _bal() == 100.0
        # (5) NINGUNA entrega válida para esta solicitud.
        assert await db.deliveries.count_documents(
            {"kind": "company_delivery", "ref_id": reqid,
             "status": {"$ne": "cancelled"}}) == 0
        r = await db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert r["status"] == "failed_init" and r.get("comp_sealed") is True

        # (6) Nuevas pasadas de recuperación + reintento del creador: SIN efectos.
        await heal_initializing_company_deliveries(max_age_seconds=0)
        from services.company_delivery_recovery import heal_cancelled_company_deliveries
        await heal_cancelled_company_deliveries()
        assert await ci.dispatch_from_store(CID, pid, sid, 3, op_id=opid) == "burned"
        assert await _stock(pid) == float(10 + ci.INV_OPS_CAP + 5)
        assert await _shelf(pid, sid) == 3.0
        assert await _bal() == 100.0
        rec2 = await db.company_inventory_ops.find_one(
            {"company_id": CID, "op_key": opid}, {"_id": 0, "result": 1})
        assert rec2["result"] == "burned"
    finally:
        monkeypatch.undo()
        await _clean()


# ─────────────────────────────────────────────────────────────────── H04-R
# Muchos productos SANOS no pueden tapar a un huérfano: el barrido filtra
# huérfanos ANTES de limitar, así que el cupo no se agota con productos sanos.
async def test_h04r_orphan_reclaimed_despite_many_healthy_products():
    await _clean()
    try:
        _pid, sid = await _seed_company()
        healthy_ids = []
        for i in range(5):
            hid = str(uuid.uuid4())
            healthy_ids.append(hid)
            await db.products.insert_one({
                "id": hid, "name": f"H{i}", "company_id": CID, "owner_id": CID,
                "stock": 10.0, "distributed": 2.0, "by_store": {sid: 2.0},
                "unit": "unidad", "is_active": True})
        orphan = str(uuid.uuid4())
        await db.products.insert_one({
            "id": orphan, "name": "ORPHAN", "company_id": CID, "owner_id": CID,
            "stock": 10.0, "distributed": 2.0, "by_store": {"GONE-STORE": 2.0},
            "unit": "unidad", "is_active": True})

        # Con límite PEQUEÑO (1): los sanos NO consumen el cupo (se filtran antes
        # de limitar) → el huérfano se recupera igualmente en la misma pasada.
        n = await ci.heal_orphan_store_shelves(company_id=CID, limit=1)
        assert n >= 1
        p = await db.products.find_one({"id": orphan}, {"_id": 0})
        assert "GONE-STORE" not in (p.get("by_store") or {})
        assert round(float(p.get("distributed") or 0), 3) == 0.0
        # Los productos sanos NO se tocaron.
        for hid in healthy_ids:
            hp = await db.products.find_one({"id": hid}, {"_id": 0, "by_store": 1})
            assert round(float((hp.get("by_store") or {}).get(sid) or 0), 3) == 2.0
    finally:
        await db.products.delete_many({"company_id": CID})


# ───────────────────────────────────────────────────────────────── P01
# PICKUP: abortar una reserva YA APLICADA debe RESTITUIR la tienda aunque el
# token haya salido del array acotado `inv_ops` por rotación. El bug:
# `burn_or_undo_pickup` miraba solo `inv_ops` y, tras la rotación, devolvía
# 'burned' omitiendo el reverso → la estantería quedaba sin restituir. Se usan
# MÁS DE 2.000 movimientos sanos (2×INV_OPS_CAP) para que la expulsión del
# token del array acotado sea INEQUÍVOCA.
async def test_p01_pickup_undo_restores_shelf_after_inv_ops_rotation():
    await _clean()
    ROT = 2 * ci.INV_OPS_CAP + 5          # > 2.000 movimientos sanos
    try:
        pid, sid = await _seed_company()          # stock 10, by_store {sid:3}, distributed 3
        # Reserva de ubicación de una recogida: aplica (tienda 3→0, distributed 3→0).
        assert await ci.reserve_pickup(CID, pid, sid, 3, op_id="pickup") == "applied"
        assert await _shelf(pid, sid) == 0.0
        assert await _dist(pid) == 0.0
        # Rotar `inv_ops` con >2.000 recepciones expulsa 'pickup' del array acotado.
        for i in range(ROT):
            assert await ci.receive_central(CID, pid, 1, op_key=f"recv:{i}") == "applied"
        # La evidencia DURADERA en company_inventory_ops es ahora la ÚNICA fuente de
        # verdad: el token NO está en inv_ops, pero `pickup_applied` lo confirma.
        prod = await db.products.find_one({"id": pid}, {"_id": 0, "inv_ops": 1})
        assert "pickup" not in (prod.get("inv_ops") or [])
        assert await ci.pickup_applied(CID, "pickup") is True
        # Abortar la MISMA reserva: restituye la tienda pese a la rotación (P01).
        assert await ci.burn_or_undo_pickup(CID, pid, sid, 3, op_id="pickup") == "undone"
        assert await _shelf(pid, sid) == 3.0
        assert await _dist(pid) == 3.0
        # Repetir el aborto NO duplica cantidades.
        assert await ci.burn_or_undo_pickup(CID, pid, sid, 3, op_id="pickup") == "undone"
        assert await _shelf(pid, sid) == 3.0
        assert await _dist(pid) == 3.0
        # La evidencia ORIGINAL de la reserva se conserva 'applied' (reverso en
        # clave separada 'pickup:undo'); no se pisó con 'burned'.
        rec = await db.company_inventory_ops.find_one(
            {"company_id": CID, "op_key": "pickup"}, {"_id": 0, "result": 1})
        assert rec["result"] == "applied"
        # Stock total = 10 + recepciones (pickup no toca el total).
        assert await _stock(pid) == float(10 + ROT)
    finally:
        await _clean()


# PICKUP: abortar una reserva que NUNCA se aplicó sella la decisión TERMINAL
# 'burned' de forma DURADERA (trazabilidad), bloquea una reserva tardía y es
# idempotente al repetir.
async def test_p01_pickup_burn_seals_terminal_when_never_applied():
    await _clean()
    try:
        pid, sid = await _seed_company()
        assert await ci.burn_or_undo_pickup(CID, pid, sid, 3, op_id="never") == "burned"
        rec = await db.company_inventory_ops.find_one(
            {"company_id": CID, "op_key": "never"}, {"_id": 0, "status": 1, "result": 1})
        assert rec and rec["status"] == "done" and rec["result"] == "burned"
        # Una reserva TARDÍA con esa clave recibe 'burned' por _run_idempotent, sin mutar.
        assert await ci.reserve_pickup(CID, pid, sid, 3, op_id="never") == "burned"
        assert await _shelf(pid, sid) == 3.0
        assert await _dist(pid) == 3.0
        # Repetir el aborto: idempotente, sin efectos adicionales.
        assert await ci.burn_or_undo_pickup(CID, pid, sid, 3, op_id="never") == "burned"
        assert await _shelf(pid, sid) == 3.0
    finally:
        await _clean()


# PICKUP (H03-R, capa de ubicación): un ejecutor de reserva EN VUELO (op
# 'pending', pausado antes del write) se reanuda tras que el recuperador abortó
# (inv_burned + sellado 'burned') y tras rotar `inv_ops`: devuelve 'burned', NO
# descuenta la estantería y el registro duradero queda 'burned' (no pisado).
async def test_p01_pickup_inflight_reservation_is_burned_and_sealed(monkeypatch):
    await _clean()
    try:
        pid, sid = await _seed_company()
        real_db = ci_mod.db
        state = {"fired": False}

        async def _abort_then_rotate():
            # Recuperador: congela (inv_burned) + sella 'burned' en los ops.
            assert await ci.burn_or_undo_pickup(CID, pid, sid, 3, op_id="pk") == "burned"
            for i in range(2 * ci.INV_OPS_CAP + 5):   # >2.000 movimientos sanos
                assert await ci.receive_central(CID, pid, 1, op_key=f"r:{i}") == "applied"

        class _Products:
            def __getattr__(self, n):
                return getattr(real_db.products, n)

            async def find_one_and_update(self, *a, **k):
                if not state["fired"]:
                    state["fired"] = True
                    await _abort_then_rotate()
                return await real_db.products.find_one_and_update(*a, **k)

        class _Db:
            def __getattr__(self, n):
                return products_proxy if n == "products" else getattr(real_db, n)

        products_proxy = _Products()
        monkeypatch.setattr(ci_mod, "db", _Db())
        status = await ci.reserve_pickup(CID, pid, sid, 3, op_id="pk")
        monkeypatch.undo()

        assert status == "burned"
        assert await _shelf(pid, sid) == 3.0          # estantería intacta
        assert await _dist(pid) == 3.0
        rec = await db.company_inventory_ops.find_one(
            {"company_id": CID, "op_key": "pk"}, {"_id": 0, "result": 1})
        assert rec["result"] == "burned"             # no pisado con 'applied'
    finally:
        monkeypatch.undo()
        await _clean()


# P01 end-to-end — RECUPERADOR TRAS CAÍDA/REINICIO: un canje con recogida en
# tienda cuya reserva de ubicación SÍ se aplicó pero quedó 'initializing'
# (proceso interrumpido). Tras rotar >2.000 movimientos y EJECUTAR EL
# RECUPERADOR real (`heal_initializing_ops`, el mismo job del scheduler que
# corre al reiniciar el proceso), la estantería debe restituirse exactamente
# una vez por EVIDENCIA DURADERA, no por el array acotado `inv_ops`.
async def test_p01_pickup_restored_by_recoverer_after_rotation():
    await _clean()
    rid = str(uuid.uuid4())
    uid = f"buyer_{uuid.uuid4().hex[:8]}"
    loc_op = f"locpk:{rid}"
    ROT = 2 * ci.INV_OPS_CAP + 5
    try:
        pid, sid = await _seed_company()
        # La reserva de UBICACIÓN del canje se aplicó (tienda 3→0, distributed 3→0).
        assert await ci.reserve_pickup(CID, pid, sid, 3, op_id=loc_op) == "applied"
        assert await _shelf(pid, sid) == 0.0
        # Canje interrumpido a medio crear (como lo dejaría una caída de proceso).
        await db.redemptions.insert_one({
            "id": rid, "user_id": uid, "status": "initializing",
            "created_at": "2020-01-01T00:00:00+00:00",
            "product_id": pid, "quantity": 3,
            "loc_op_id": loc_op, "pickup_from_store": True,
            "store_id": sid, "pickup_company_id": CID,
            "settlement_currency": "USDT", "total_usd": 0, "courier_fee_usd": 0})
        # Rotación >2.000 → el token sale de inv_ops; solo queda la evidencia durable.
        for i in range(ROT):
            assert await ci.receive_central(CID, pid, 1, op_key=f"rc:{i}") == "applied"
        prod = await db.products.find_one({"id": pid}, {"_id": 0, "inv_ops": 1})
        assert loc_op not in (prod.get("inv_ops") or [])

        # EL RECUPERADOR (job del scheduler que corre al reiniciar) restituye.
        from services.credit_recovery import heal_initializing_ops
        await heal_initializing_ops(max_age_seconds=-5)

        assert await _shelf(pid, sid) == 3.0          # estantería restituida
        assert await _dist(pid) == 3.0
        r = await db.redemptions.find_one({"id": rid}, {"_id": 0, "status": 1})
        assert r["status"] == "failed_init"
        # La evidencia ORIGINAL sigue 'applied'; el reverso vive en loc_op:undo.
        assert await ci.pickup_applied(CID, loc_op) is True
        undo = await db.company_inventory_ops.find_one(
            {"company_id": CID, "op_key": f"{loc_op}:undo"}, {"_id": 0, "result": 1})
        assert undo and undo["result"] == "applied"

        # Repetir el recuperador NO duplica la restitución (idempotente).
        await heal_initializing_ops(max_age_seconds=-5)
        assert await _shelf(pid, sid) == 3.0
        assert await _dist(pid) == 3.0
    finally:
        await db.redemptions.delete_one({"id": rid})
        await _clean()


# ───────────────────────────────────────────────────────────────── OBS-01
# Observabilidad del guard `inv_burned`: tamaño por producto reportado.
async def test_obs_inv_burned_stats_reports_sizes():
    await _clean()
    try:
        pid, sid = await _seed_company()
        await db.products.update_one(
            {"id": pid}, {"$set": {"inv_burned": [f"g{i}" for i in range(7)]}})
        stats = await ci.inv_burned_stats(threshold=7)
        assert stats["products_with_guards"] >= 1
        assert stats["total_guard_entries"] >= 7
        mine = next((p for p in stats["top"] if p["id"] == pid), None)
        assert mine and mine["size"] == 7
        # Con umbral 7 mi producto (size 7) aparece como sobre-umbral.
        assert pid in [p["id"] for p in stats["over_threshold"]]
        assert stats["over_threshold_count"] >= 1
        # Con umbral 8 ya NO está sobre-umbral.
        stats8 = await ci.inv_burned_stats(threshold=8)
        assert pid not in [p["id"] for p in stats8["over_threshold"]]
    finally:
        await _clean()


# RET-R — RETENCIÓN SEGURA: la poda retira un guard SOLO cuando la operación es
# terminal ('done'), antigua Y lleva una INVALIDACIÓN VERIFICABLE del escritor
# (`writer_invalidated_at`). El tiempo + estado por sí solos NO bastan (no prueban
# que no quede un escritor suspendido), así que SIN el sello las marcas se conservan.
async def test_retr_prune_requires_verifiable_writer_invalidation():
    await _clean()
    try:
        pid, sid = await _seed_company()
        await db.products.update_one(
            {"id": pid}, {"$set": {"inv_burned": [
                "old_sealed", "old_unsealed", "recent_sealed",
                "pending_op", "no_record_op"]}})
        old = iso(now_utc() - timedelta(days=120))
        recent = iso(now_utc() - timedelta(days=1))
        await db.company_inventory_ops.insert_many([
            # terminal + antiguo + INVALIDACIÓN VERIFICABLE → ÚNICO podable
            {"company_id": CID, "op_key": "old_sealed", "op_type": "pickup",
             "status": "done", "result": "burned", "done_at": old, "created_at": old,
             "writer_invalidated_at": old},
            # terminal + antiguo PERO SIN sello → se CONSERVA (tiempo/estado no bastan)
            {"company_id": CID, "op_key": "old_unsealed", "op_type": "pickup",
             "status": "done", "result": "burned", "done_at": old, "created_at": old},
            # terminal + sellado pero RECIENTE → se conserva
            {"company_id": CID, "op_key": "recent_sealed", "op_type": "pickup",
             "status": "done", "result": "burned", "done_at": recent, "created_at": recent,
             "writer_invalidated_at": recent},
            {"company_id": CID, "op_key": "pending_op", "op_type": "pickup",
             "status": "pending", "created_at": recent},
            # 'no_record_op' a propósito SIN registro en company_inventory_ops.
        ])
        pruned = await ci.prune_inv_burned_guards(retention_days=90)
        assert pruned == 1  # solo 'old_sealed'
        prod = await db.products.find_one({"id": pid}, {"_id": 0, "inv_burned": 1})
        remaining = set(prod.get("inv_burned") or [])
        assert "old_sealed" not in remaining             # terminal+antiguo+sellado → podado
        assert "old_unsealed" in remaining               # antiguo+done SIN sello → CONSERVADO
        assert "recent_sealed" in remaining              # sellado pero reciente → se conserva
        assert "pending_op" in remaining                 # EN VUELO → NUNCA se poda
        assert "no_record_op" in remaining               # sin evidencia → NUNCA se poda
        # Idempotente: una segunda pasada no retira nada más.
        assert await ci.prune_inv_burned_guards(retention_days=90) == 0
        prod2 = await db.products.find_one({"id": pid}, {"_id": 0, "inv_burned": 1})
        assert set(prod2.get("inv_burned") or []) == remaining
    finally:
        await _clean()



# OBS-01 — métricas de abortos y detalle por producto.
async def test_obs_product_detail_and_abort_metrics():
    await _clean()
    try:
        pid, sid = await _seed_company()
        old = iso(now_utc() - timedelta(days=120))
        recent = iso(now_utc() - timedelta(days=1))
        await db.products.update_one(
            {"id": pid}, {"$set": {"inv_burned": ["d_old", "d_new", "p_old", "norec"]}})
        before = await ci.inventory_abort_metrics()
        await db.company_inventory_ops.insert_many([
            # terminal + antiguo + INVALIDACIÓN VERIFICABLE → prunable True
            {"company_id": CID, "op_key": "d_old", "op_type": "dispatch",
             "status": "done", "result": "burned", "done_at": old, "created_at": old,
             "guard_blocked_at": recent, "guard_block_count": 3,
             "writer_invalidated_at": old},
            {"company_id": CID, "op_key": "d_new", "op_type": "dispatch",
             "status": "done", "result": "burned", "done_at": recent, "created_at": recent},
            # terminal + antiguo PERO SIN sello verificable → prunable False
            {"company_id": CID, "op_key": "p_old", "op_type": "pickup",
             "status": "done", "result": "burned", "done_at": old, "created_at": old},
            # 'norec' a propósito SIN registro en company_inventory_ops.
        ])
        after = await ci.inventory_abort_metrics()
        assert after["aborted_dispatch"] - before["aborted_dispatch"] == 2
        assert after["aborted_pickup"] - before["aborted_pickup"] == 1
        assert after["blocked_late_dispatch"] - before["blocked_late_dispatch"] == 1
        assert after["blocked_late_attempts"] - before["blocked_late_attempts"] == 3

        detail = await ci.inv_burned_product_detail(pid)
        assert detail["total_guards"] == 4 and detail["shown"] == 4
        by = {e["op_id"]: e for e in detail["entries"]}
        # d_old: terminal+antiguo+sellado → PODABLE
        assert by["d_old"]["prunable"] is True and by["d_old"]["blocked_late"] is True
        assert by["d_old"]["block_attempts"] == 3
        assert by["d_old"]["writer_invalidated_at"] == old
        assert by["d_new"]["prunable"] is False                 # terminal pero reciente
        # p_old: terminal+antiguo PERO SIN sello verificable → NO podable (fix RET-R)
        assert by["p_old"]["prunable"] is False
        assert by["p_old"]["writer_invalidated_at"] is None
        assert by["norec"]["op_type"] is None and by["norec"]["prunable"] is False
    finally:
        await _clean()


# OBS-01 — la métrica 'bloqueo tardío' se incrementa SOLO cuando el guard
# `inv_burned` impide EN VUELO una reserva (no en una llamada tardía que
# resuelve por idempotencia). Reproduce el intercalado real.
async def test_obs_blocked_late_metric_on_inflight_block(monkeypatch):
    await _clean()
    try:
        pid, sid = await _seed_company()
        before = await ci.inventory_abort_metrics()
        real_db = ci_mod.db
        state = {"fired": False}

        class _Products:
            def __getattr__(self, n):
                return getattr(real_db.products, n)

            async def find_one_and_update(self, *a, **k):
                if not state["fired"]:
                    state["fired"] = True
                    await ci.freeze_dispatch(CID, pid, sid, 3, "dx")  # aborta en vuelo
                return await real_db.products.find_one_and_update(*a, **k)

        class _Db:
            def __getattr__(self, n):
                return products_proxy if n == "products" else getattr(real_db, n)

        products_proxy = _Products()
        monkeypatch.setattr(ci_mod, "db", _Db())
        assert await ci.dispatch_from_store(CID, pid, sid, 3, op_id="dx") == "burned"
        monkeypatch.undo()

        after = await ci.inventory_abort_metrics()
        assert after["blocked_late_dispatch"] - before["blocked_late_dispatch"] == 1
        op = await db.company_inventory_ops.find_one(
            {"company_id": CID, "op_key": "dx"}, {"_id": 0, "guard_blocked_at": 1})
        assert op and op.get("guard_blocked_at")
    finally:
        monkeypatch.undo()
        await _clean()



# RET-R — PRUEBA DE CONCURRENCIA (reloj simulado, sin esperar 91 días):
# un escritor que ya pasó su lectura de idempotencia y quedó SUSPENDIDO antes de
# mutar el stock NO modifica el stock aunque la LIMPIEZA corra pasada la ventana.
# Secuencia: (1) pausa el escritor antes de la escritura del producto;
# (2) cancela/congela (inv_burned + sello 'burned'); (3) adelanta 91 días y corre
# la poda; (4) reanuda el escritor. La poda CONSERVA el guard (no hay invalidación
# verificable), así la reserva tardía fracasa ('burned') y el stock sigue intacto.
async def test_retr_suspended_writer_blocked_even_after_prune(monkeypatch):
    await _clean()
    try:
        pid, sid = await _seed_company(stock=10.0)  # central=7, estantería=3
        real_db = ci_mod.db
        state = {"fired": False}

        class _Products:
            def __getattr__(self, n):
                return getattr(real_db.products, n)

            async def find_one_and_update(self, *a, **k):
                # Se dispara en la escritura del producto del escritor (su `apply`),
                # DESPUÉS de que `_run_idempotent` registró la op como 'pending'.
                if not state["fired"]:
                    state["fired"] = True
                    # (2) el recuperador ABORTA este intento: congela + sella 'burned'.
                    await ci.freeze_dispatch(CID, pid, sid, 3, "susp")
                    # (3) "adelanta 91 días": la op burned queda antigua...
                    old = iso(now_utc() - timedelta(days=91))
                    await real_db.company_inventory_ops.update_one(
                        {"company_id": CID, "op_key": "susp"}, {"$set": {"done_at": old}})
                    # ...y corre la LIMPIEZA. NO debe retirar el guard (sin sello verificable).
                    pruned = await ci.prune_inv_burned_guards(retention_days=90)
                    assert pruned == 0, "la poda NO debe retirar un guard sin invalidación verificable"
                return await real_db.products.find_one_and_update(*a, **k)

        class _Db:
            def __getattr__(self, n):
                return products_proxy if n == "products" else getattr(real_db, n)

        products_proxy = _Products()
        monkeypatch.setattr(ci_mod, "db", _Db())
        # (4) el escritor REANUDA su escritura tras la limpieza.
        res = await ci.dispatch_from_store(CID, pid, sid, 3, op_id="susp")
        monkeypatch.undo()

        assert res == "burned", "la reserva tardía NO debe aplicarse tras la limpieza"
        assert await _stock(pid) == 10.0, "el stock NO debe cambiar (10 → 10)"
        assert await _shelf(pid, sid) == 3.0, "la estantería NO debe cambiar"
        # El guard permanece: retención segura mientras no haya invalidación verificable.
        prod = await db.products.find_one({"id": pid}, {"_id": 0, "inv_burned": 1})
        assert "susp" in set(prod.get("inv_burned") or [])
    finally:
        monkeypatch.undo()
        await _clean()
