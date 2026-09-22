"""iter287 — Auditoría eeed556: criterios de aceptación de V01, V02 y V03.

V01 (alta) · Una tarifa de mensajería ABORTADA de forma durable (débito
'burned'/'undone') jamás debe terminar guardada como cobrada: la
recuperación debe completar la restauración `plan.revert`, y el rechazo
devuelve exactamente lo pagado.

V02 (media) · El recuperador de planes de carga por antigüedad NO libera el
cupo de un escritor que podría seguir vivo: COMPLETA la carga persistida
(identidad estable + índice único). Nunca >500 ítems, ni filas tras el
cierre, ni cupo distinto del contenido.

V03 (alta) · Un ingreso de venta publicado tarde (canje ya rechazado y plan
`sale_trace_pending` eliminado por otro ejecutor, sin marcas) se detecta por
su propio asiento (clave fund-inflow:{rid}:c0) y se compensa: fondo neto 0.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient
from pymongo.errors import BulkWriteError

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN
from tests.test_iter279_s01_s07 import _run

API = f"{BASE_URL}/api"
MARK = "IT287"
CLIENT_ID = "it287_client"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes_ago)).isoformat()


def _bal(uid, code="USDT"):
    u = _db().users.find_one({"user_id": uid}, {"_id": 0, "vip_balances": 1}) or {}
    return round(float((u.get("vip_balances") or {}).get(code) or 0.0), 6)


def _mk_user(uid):
    _db().users.update_one({"user_id": uid}, {"$set": {
        "user_id": uid, "email": f"{uid}@it287.test", "name": f"{MARK} {uid}",
        "role": "vip", "account_status": "active", "is_verified": True,
        "vip_balances": {}}}, upsert=True)


def _cleanup():
    db = _db()
    db.redemptions.delete_many({"user_name": {"$regex": MARK}})
    db.products.delete_many({"name": {"$regex": MARK}})
    db.company_fund_adjustments.delete_many({"note": {"$regex": MARK}})
    db.credit_ops.delete_many({"op_id": {"$regex": MARK}})
    bids = [b["id"] for b in db.vip_batches.find(
        {"note": {"$regex": MARK}}, {"id": 1})]
    db.vip_batch_items.delete_many({"batch_id": {"$in": bids}})
    db.vip_batches.delete_many({"id": {"$in": bids}})
    db.users.delete_many({"user_id": CLIENT_ID})


def _heal_ops():
    async def _f():
        from services.credit_recovery import heal_initializing_ops
        return await heal_initializing_ops(max_age_seconds=0)
    return _run(_f)


# ============================================================
# V01 — tarifa abortada jamás se reembolsa como cobrada
# ============================================================

def _plant_burned_fee_plan(balance_usdt):
    """Estado exacto del auditor: compra pagada (100), tarifa 10 PUBLICADA
    con plan pendiente, débito abortado de forma DURABLE ('burned' + token)
    y el escritor muerto ANTES de restaurar la tarifa a 0."""
    db = _db()
    _mk_user(CLIENT_ID)
    db.users.update_one({"user_id": CLIENT_ID},
                        {"$set": {"vip_balances.USDT": float(balance_usdt)}})
    pid = f"p_{uuid.uuid4().hex[:10]}"
    db.products.insert_one({
        "id": pid, "name": f"{MARK} Producto", "description": "t",
        "category": "test", "price_usd": 100.0, "cost_usd": 0.0,
        "stock": 0, "image_url": "", "created_at": _iso()})
    rid = f"r_{uuid.uuid4().hex[:12]}"
    op = f"courier-fee:{rid}:{MARK}{uuid.uuid4().hex[:4]}"
    plan = {"op_id": op, "delta": 10.0, "currency": "USDT",
            "revert": {"courier_km": None, "courier_fee_usdt": None,
                       "courier_fee_usd": 0.0},
            "at": _iso(10)}
    db.redemptions.insert_one({
        "id": rid, "user_id": CLIENT_ID, "user_name": f"{MARK} Comprador",
        "product_id": pid, "product_name": f"{MARK} Producto",
        "quantity": 1, "total_usd": 100.0, "settlement_currency": "USDT",
        "status": "pending", "created_at": _iso(10),
        "courier_km": 20.0, "courier_fee_usdt": 10.0,
        "courier_fee_usd": 10.0, "courier_fee_op_pending": plan})
    # débito ABORTADO durable (burn_or_undo_debit completado)
    db.credit_ops.insert_one({
        "op_id": op, "user_id": CLIENT_ID, "code": "USDT", "amount": 10.0,
        "kind": "debit", "state": "burned", "burned": True, "at": _iso(10)})
    db.users.update_one({"user_id": CLIENT_ID},
                        {"$push": {"applied_credit_ops": f"{op}:burn"}})
    return rid, op, plan


class TestV01BurnedFeeNeverRefunded:
    def teardown_method(self, _):
        _cleanup()

    def test_recovery_restores_fee_and_reject_refunds_exactly_paid(self):
        """Criterio del auditor: tarifa termina en 0; el rechazo devuelve
        exactamente 100 (no 110); recuperaciones sucesivas no alteran."""
        _cleanup()
        rid, op, _ = _plant_burned_fee_plan(balance_usdt=0.0)
        _heal_ops()
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert "courier_fee_op_pending" not in doc, \
            "el plan queda resuelto tras la recuperación"
        assert float(doc.get("courier_fee_usd") or 0) == 0.0, \
            f"la tarifa abortada se restaura a 0, no queda en {doc.get('courier_fee_usd')}"
        assert _bal(CLIENT_ID) == 0.0
        r = requests.put(f"{API}/admin/redemptions/{rid}/status",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"status": "rejected", "admin_note": MARK})
        assert r.status_code == 200, r.text
        assert _bal(CLIENT_ID) == 100.0, \
            "reembolso EXACTO de lo pagado (100), jamás 110"
        _heal_ops()
        _heal_ops()
        assert _bal(CLIENT_ID) == 100.0
        assert float((_db().redemptions.find_one({"id": rid}) or {})
                     .get("courier_fee_usd") or 0) == 0.0

    def test_recovery_with_new_income_never_charges_burned_debit(self):
        """Variante: llegan fondos nuevos ANTES de la recuperación. El
        débito quemado no cobra jamás y la tarifa igualmente vuelve a 0."""
        _cleanup()
        rid, op, _ = _plant_burned_fee_plan(balance_usdt=110.0)
        _heal_ops()
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert "courier_fee_op_pending" not in doc
        assert float(doc.get("courier_fee_usd") or 0) == 0.0
        assert _bal(CLIENT_ID) == 110.0, "el saldo nuevo queda intacto"

    def test_late_writer_settle_after_recovery_is_noop(self):
        """El escritor original despierta DESPUÉS de la recuperación y
        re-ejecuta su settle con el plan viejo: sin efecto."""
        _cleanup()
        rid, op, plan = _plant_burned_fee_plan(balance_usdt=50.0)
        _heal_ops()

        def _late():
            async def _f():
                from services.courier_fee import settle_fee_change_plan
                return await settle_fee_change_plan(
                    "redemptions", rid, CLIENT_ID, plan)
            return _run(_f)
        _late()
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert float(doc.get("courier_fee_usd") or 0) == 0.0
        assert "courier_fee_op_pending" not in doc
        assert _bal(CLIENT_ID) == 50.0


# ============================================================
# V02 — el recuperador COMPLETA (no libera) cargas con escritor vivo
# ============================================================

def _mk_batch():
    r = requests.post(f"{API}/vip/batches", headers=_hdr(VIP_TOKEN),
                      json={"direction": "credit", "currency": "USD",
                            "note": MARK})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _item_doc(bid, iid):
    return {"id": iid, "batch_id": bid, "vip_user_id": "user_test_vip01",
            "holder_name": "Nombre Apellido", "amount": 10.0,
            "currency": "USD", "direction": "credit", "status": "pending",
            "created_at": _iso()}


def _seed_items(bid, n):
    _db().vip_batch_items.insert_many(
        [_item_doc(bid, f"vitem_{uuid.uuid4().hex[:12]}") for _ in range(n)])
    _db().vip_batches.update_one({"id": bid},
                                 {"$set": {"items_reserved": n}})


def _plant_pending_upload(bid, n_plan, inserted=0):
    """Estado del auditor: escritor A reservó cupo y sigue PAUSADO antes de
    (terminar de) insertar. El plan persiste el contenido completo."""
    ids = [f"vitem_{uuid.uuid4().hex[:12]}" for _ in range(n_plan)]
    docs = [_item_doc(bid, i) for i in ids]
    if inserted:
        _db().vip_batch_items.insert_many([dict(d) for d in docs[:inserted]])
    plan = {"plan_id": f"vbup_{MARK}{uuid.uuid4().hex[:6]}",
            "item_ids": ids, "count": n_plan, "at": _iso(20), "docs": docs}
    _db().vip_batches.update_one(
        {"id": bid},
        {"$inc": {"items_reserved": n_plan}, "$push": {"upload_plans": plan}})
    return plan, docs


def _items_payload(n, amount=25):
    return {"items": [{"amount": amount, "holder_name": "Nombre Apellido"}
                      for _ in range(n)]}


class TestV02StaleWriterCannotOverflow:
    def teardown_method(self, _):
        _cleanup()

    def test_close_after_recovery_keeps_batch_consistent(self):
        """Secuencia 1 del auditor: cerrar tras la recuperación. El lote
        cerrado conserva 500 filas = 500 reservadas y el escritor tardío no
        añade NADA después del cierre."""
        _cleanup()
        bid = _mk_batch()
        _seed_items(bid, 450)
        plan, docs = _plant_pending_upload(bid, 50, inserted=0)
        _heal_ops()  # por antigüedad: COMPLETA la carga, sin liberar cupo
        b = _db().vip_batches.find_one({"id": bid}, {"_id": 0})
        assert b["items_reserved"] == 500, b["items_reserved"]
        assert not b.get("upload_plans")
        assert _db().vip_batch_items.count_documents({"batch_id": bid}) == 500
        r = requests.post(f"{API}/vip/batches/{bid}/close",
                          headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200, r.text
        # el escritor A despierta y ejecuta su insert_many original
        try:
            _db().vip_batch_items.insert_many([dict(d) for d in docs])
            raise AssertionError("el índice único debe bloquear las filas tardías")
        except BulkWriteError:
            pass
        assert _db().vip_batch_items.count_documents({"batch_id": bid}) == 500, \
            "cero filas añadidas después del cierre"
        # y su resolución de escritor reconoce el 'complete' sin liberar cupo
        def _writer_resolve():
            async def _f():
                from services.vip_batch_ops import resolve_upload_plan
                return await resolve_upload_plan(bid, plan, mode="release")
            return _run(_f)
        assert _writer_resolve() == "complete"
        b = _db().vip_batches.find_one({"id": bid}, {"_id": 0})
        assert b["items_reserved"] == 500 and b["status"] == "closed"
        _heal_ops()
        _heal_ops()
        assert _db().vip_batch_items.count_documents({"batch_id": bid}) == 500

    def test_second_upload_cannot_exceed_limit_after_recovery(self):
        """Secuencia 2 del auditor: otra carga de 50 tras la recuperación.
        Nunca más de 500 ítems ni cupo por encima del contenido."""
        _cleanup()
        bid = _mk_batch()
        _seed_items(bid, 450)
        plan, docs = _plant_pending_upload(bid, 50, inserted=0)
        _heal_ops()
        r = requests.post(f"{API}/vip/batches/{bid}/items",
                          headers=_hdr(VIP_TOKEN), json=_items_payload(50))
        assert r.status_code == 409, \
            f"el cupo sigue reservado (500/500): {r.status_code} {r.text}"
        assert _db().vip_batch_items.count_documents({"batch_id": bid}) == 500
        b = _db().vip_batches.find_one({"id": bid}, {"_id": 0})
        assert b["items_reserved"] == 500

    def test_writer_own_failure_still_releases_remaining_quota(self):
        """Criterio conservado (R03): 450 + 25 insertadas de una carga de 50
        que FALLÓ para el propio escritor → 475 filas y 475 plazas."""
        _cleanup()
        bid = _mk_batch()
        _seed_items(bid, 450)
        plan, docs = _plant_pending_upload(bid, 50, inserted=25)

        def _writer_resolve():
            async def _f():
                from services.vip_batch_ops import resolve_upload_plan
                return await resolve_upload_plan(bid, plan, mode="release")
            return _run(_f)
        assert _writer_resolve() == "release"
        b = _db().vip_batches.find_one({"id": bid}, {"_id": 0})
        assert b["items_reserved"] == 475
        assert not b.get("upload_plans")
        assert _db().vip_batch_items.count_documents({"batch_id": bid}) == 475


# ============================================================
# V03 — ingreso tardío con plan eliminado: compensación durable
# ============================================================

def _mk_company_redemption(status="rejected"):
    db = _db()
    pid = f"p_{uuid.uuid4().hex[:10]}"
    db.products.insert_one({
        "id": pid, "name": f"{MARK} Producto Empresa", "description": "t",
        "category": "test", "price_usd": 1000.0, "cost_usd": 600.0,
        "stock": 2, "image_url": "", "created_at": _iso()})
    rid = f"r_{uuid.uuid4().hex[:12]}"
    doc = {
        "id": rid, "user_id": CLIENT_ID, "user_name": f"{MARK} Comprador",
        "product_id": pid, "product_name": f"{MARK} Producto Empresa",
        "quantity": 1, "total_usd": 10.0, "cost_usd": 6.0,
        "total_store": 1000.0, "store_currency": "CUP", "fx_rate": 100.0,
        "settlement_currency": "USDT", "status": status,
        "created_at": _iso(10)}
    if status == "rejected":
        doc.update({"rejection_cycle": 1, "rejection_applied": True,
                    "rejection_effects_done": True})
    db.redemptions.insert_one(doc)
    return pid, rid


def _plant_orphan_inflow(rid):
    """El escritor original insertó el asiento y MURIÓ antes de marcar el
    canje; el plan sale_trace_pending ya fue eliminado por otro ejecutor."""
    _db().company_fund_adjustments.insert_one({
        "id": uuid.uuid4().hex, "adjustment_type": "inflow",
        "currency": "USDT", "amount": 10.0, "method": "transfer",
        "source_name": "Marketplace tienda",
        "note": f"{MARK} venta web huérfana", "source": "marketplace_auto",
        "ref_id": rid, "dedupe_key": f"fund-inflow:{rid}:c0",
        "created_at": _iso(5)})


class TestV03OrphanInflowCompensated:
    def teardown_method(self, _):
        _cleanup()

    def test_orphan_inflow_of_rejected_sale_is_reversed(self):
        """Criterio del auditor: tras recuperar → fondo neto 0, un solo
        ingreso y un solo reverso del ciclo; repetir la recuperación
        mantiene esos valores."""
        _cleanup()
        _mk_user(CLIENT_ID)
        pid, rid = _mk_company_redemption(status="rejected")
        _plant_orphan_inflow(rid)
        db = _db()
        assert "sale_trace_pending" not in (db.redemptions.find_one(
            {"id": rid}, {"_id": 0}) or {}), "precondición: sin plan"
        _heal_ops()
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-reverse:{rid}:c1"}) == 1, \
            "el reverso compensa el ingreso huérfano (neto 0)"
        fresh = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert fresh.get("fund_inflow_at"), "marcas repuestas desde el asiento"
        assert fresh.get("fund_inflow_reversed_at")
        adj = db.company_fund_adjustments.find_one(
            {"dedupe_key": f"fund-inflow:{rid}:c0"}, {"_id": 0})
        assert adj.get("marks_ensured") is True
        net = sum(float(a["amount"]) * (1 if a["adjustment_type"] == "inflow" else -1)
                  for a in db.company_fund_adjustments.find({"ref_id": rid}))
        assert net == 0.0, f"efecto neto de la venta sobre el fondo: {net}"
        _heal_ops()
        _heal_ops()
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-inflow:{rid}:c0"}) == 1
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-reverse:{rid}:c1"}) == 1, "sin duplicados"

    def test_orphan_inflow_of_active_sale_repairs_marks_for_later_reject(self):
        """Canje NO rechazado: el barrido solo repone las marcas (sin
        reverso). Un rechazo POSTERIOR encuentra las marcas y compensa por
        la vía normal."""
        _cleanup()
        _mk_user(CLIENT_ID)
        pid, rid = _mk_company_redemption(status="pending")
        _plant_orphan_inflow(rid)
        db = _db()
        _heal_ops()
        fresh = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert fresh.get("fund_inflow_at"), "marcas repuestas"
        assert not fresh.get("fund_inflow_reversed_at")
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": {"$regex": f"^fund-reverse:{rid}:"}}) == 0
        r = requests.put(f"{API}/admin/redemptions/{rid}/status",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"status": "rejected", "admin_note": MARK})
        assert r.status_code == 200, r.text
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": {"$regex": f"^fund-reverse:{rid}:"}}) == 1, \
            "el rechazo posterior compensa gracias a las marcas repuestas"
        net = sum(float(a["amount"]) * (1 if a["adjustment_type"] == "inflow" else -1)
                  for a in db.company_fund_adjustments.find({"ref_id": rid}))
        assert net == 0.0
