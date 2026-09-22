"""iter291 — Pendientes W01/W02 del informe d66806c + Fase C mensajería.

W01 (V02) · El recuperador de cargas por antigüedad NO descarta una carga
incompleta: solo cuenta como éxito el duplicado cuya fila YA existe; el plan
se retira únicamente cuando TODAS las filas están presentes. Ante un fallo
aislado, el plan queda recuperable y el cierre devuelve 409.

W02 (V03) · La compensación de un ingreso rechazado es DURABLE: la marca
`marks_ensured` se pone solo después de comprobar el rechazo y completar el
reverso (creador), y el barrido decide con el estado leído DESPUÉS de reponer
las marcas. Ambas variantes terminan con fondo neto 0.

Fase C · Mejora #7: destino estructurado (receptor, teléfono, municipio,
provincia por separado) en el documento de entrega. Mejora #8: endpoint de
métricas de tiempos/incidencias/costos con filtros.
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
MARK = "IT291"
CLIENT_ID = "it291_client"
COURIER_ID = "it291_courier"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes_ago)).isoformat()


def _mk_user(uid):
    _db().users.update_one({"user_id": uid}, {"$set": {
        "user_id": uid, "email": f"{uid}@it291.test", "name": f"{MARK} {uid}",
        "role": "vip", "account_status": "active", "is_verified": True,
        "vip_balances": {}}}, upsert=True)


def _cleanup():
    db = _db()
    db.redemptions.delete_many({"user_name": {"$regex": MARK}})
    db.products.delete_many({"name": {"$regex": MARK}})
    db.company_fund_adjustments.delete_many({"note": {"$regex": MARK}})
    db.deliveries.delete_many({"client_name": {"$regex": MARK}})
    bids = [b["id"] for b in db.vip_batches.find(
        {"note": {"$regex": MARK}}, {"id": 1})]
    db.vip_batch_items.delete_many({"batch_id": {"$in": bids}})
    db.vip_batches.delete_many({"id": {"$in": bids}})
    db.users.delete_many({"user_id": {"$in": [CLIENT_ID, COURIER_ID]}})


def _heal_ops():
    async def _f():
        from services.credit_recovery import heal_initializing_ops
        return await heal_initializing_ops(max_age_seconds=0)
    return _run(_f)


class _ProxyDB:
    """Sustituye UNA colección del módulo bajo prueba; el resto pasa directo."""
    def __init__(self, real, name, coll):
        self._real = real
        self._name = name
        self._coll = coll

    def __getattr__(self, n):
        if n == self._name:
            return self._coll
        return getattr(self._real, n)


# ============================================================
# W01 — carga incompleta conserva plan y reserva; cierre bloqueado
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
    _db().vip_batches.update_one({"id": bid}, {"$set": {"items_reserved": n}})


def _plant_pending_upload(bid, n_plan, inserted=0):
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


def _resolve_complete(bid, plan, fail_first=False):
    async def _f():
        import services.vip_batch_ops as ops
        from db_client import db as real_db

        class _FailColl:
            def __init__(self, real):
                self._real = real
                self.n = 0

            def __getattr__(self, n):
                return getattr(self._real, n)

            async def insert_one(self, doc, *a, **kw):
                self.n += 1
                if fail_first and self.n == 1:
                    raise RuntimeError("Synthetic insert failure")
                return await self._real.insert_one(doc, *a, **kw)

        orig = ops.db
        ops.db = _ProxyDB(real_db, "vip_batch_items",
                          _FailColl(real_db.vip_batch_items))
        try:
            return await ops.resolve_upload_plan(bid, plan, mode="complete")
        finally:
            ops.db = orig
    return _run(_f)


class TestW01IncompleteUploadKeptRecoverable:
    def teardown_method(self, _):
        _cleanup()

    def test_failed_insert_keeps_plan_and_blocks_close_until_complete(self):
        """Reproducción del auditor: 450 + plan de 50; la PRIMERA inserción
        del recuperador falla. El plan debe conservarse (499/500), el cierre
        devuelve 409 y el siguiente barrido completa 500 = 500."""
        _cleanup()
        bid = _mk_batch()
        _seed_items(bid, 450)
        plan, docs = _plant_pending_upload(bid, 50, inserted=0)
        assert _resolve_complete(bid, plan, fail_first=True) == "incomplete"
        db = _db()
        b = db.vip_batches.find_one({"id": bid}, {"_id": 0})
        assert len(b.get("upload_plans") or []) == 1, \
            "el plan se conserva ante una carga incompleta"
        assert b["items_reserved"] == 500
        assert db.vip_batch_items.count_documents({"batch_id": bid}) == 499
        r = requests.post(f"{API}/vip/batches/{bid}/close",
                          headers=_hdr(VIP_TOKEN))
        assert r.status_code == 409, \
            f"cierre bloqueado mientras falten filas: {r.status_code} {r.text}"
        # el siguiente barrido (sin fallo) completa la fila que faltaba
        _heal_ops()
        b = db.vip_batches.find_one({"id": bid}, {"_id": 0})
        assert not b.get("upload_plans"), "plan retirado al completar"
        assert b["items_reserved"] == 500
        assert db.vip_batch_items.count_documents({"batch_id": bid}) == 500
        r = requests.post(f"{API}/vip/batches/{bid}/close",
                          headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200, r.text
        # un escritor antiguo que despierte no añade filas tras el cierre
        try:
            db.vip_batch_items.insert_many([dict(d) for d in docs])
            raise AssertionError("el índice único debe bloquear filas tardías")
        except BulkWriteError:
            pass
        assert db.vip_batch_items.count_documents({"batch_id": bid}) == 500

    def test_complete_without_failure_still_resolves_in_one_pass(self):
        """Regresión V02: sin fallos, el barrido completa la carga y retira
        el plan en una pasada (500 filas = 500 plazas)."""
        _cleanup()
        bid = _mk_batch()
        _seed_items(bid, 450)
        plan, _ = _plant_pending_upload(bid, 50, inserted=0)
        assert _resolve_complete(bid, plan) == "complete"
        db = _db()
        b = db.vip_batches.find_one({"id": bid}, {"_id": 0})
        assert not b.get("upload_plans")
        assert b["items_reserved"] == 500
        assert db.vip_batch_items.count_documents({"batch_id": bid}) == 500


# ============================================================
# W02 — la compensación del ingreso rechazado nunca se pierde
# ============================================================

def _mk_company_redemption(status="pending", trace_pending=False):
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
    if trace_pending:
        doc["sale_trace_pending"] = {"fund": True, "at": _iso(10)}
    db.redemptions.insert_one(doc)
    return pid, rid


def _fund_net(rid):
    return sum(float(a["amount"]) * (1 if a["adjustment_type"] == "inflow" else -1)
               for a in _db().company_fund_adjustments.find({"ref_id": rid}))


class TestW02CompensationNeverLost:
    def teardown_method(self, _):
        _cleanup()

    def test_creator_reversal_failure_leaves_entry_visible_to_sweep(self):
        """Variante 1 del auditor: el creador publica el ingreso, el canje se
        rechaza en paralelo y el reverso FALLA. Con el fix, `marks_ensured`
        NO se pone, el barrido reintenta y el fondo termina en neto 0."""
        _cleanup()
        _mk_user(CLIENT_ID)
        pid, rid = _mk_company_redemption(status="pending", trace_pending=True)

        def _creator_with_race():
            async def _f():
                import services.company_funds_common as cfc
                from db_client import db as mdb
                orig = cfc.record_auto_fund_adjustment

                async def wrapper(**kw):
                    if kw.get("adjustment_type") == "inflow":
                        res = await orig(**kw)
                        # el rechazo llega DESPUÉS del asiento y ANTES de la
                        # verificación del creador
                        await mdb.redemptions.update_one(
                            {"id": rid},
                            {"$set": {"status": "rejected",
                                      "rejection_cycle": 1}})
                        return res
                    raise RuntimeError("Synthetic reversal failure")

                cfc.record_auto_fund_adjustment = wrapper
                try:
                    from services.credit_recovery import ensure_company_sale_traces
                    r = await mdb.redemptions.find_one({"id": rid}, {"_id": 0})
                    return await ensure_company_sale_traces(r)
                finally:
                    cfc.record_auto_fund_adjustment = orig
            return _run(_f)

        ok = _creator_with_race()
        assert ok is False, "el creador reporta el fallo del reverso"
        db = _db()
        adj = db.company_fund_adjustments.find_one(
            {"dedupe_key": f"fund-inflow:{rid}:c0"}, {"_id": 0})
        assert adj, "el ingreso quedó publicado"
        assert adj.get("marks_ensured") is not True, \
            "FIX W02: sin marks_ensured hasta completar el reverso"
        assert _fund_net(rid) == 10.0, "precondición: +10 sin compensar aún"
        # el asiento se envejece para que el barrido lo tome de inmediato
        db.company_fund_adjustments.update_one(
            {"dedupe_key": f"fund-inflow:{rid}:c0"},
            {"$set": {"created_at": _iso(5)}})
        _heal_ops()
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-reverse:{rid}:c1"}) == 1
        assert _fund_net(rid) == 0.0, "fondo neto 0 tras el reintento"
        adj = db.company_fund_adjustments.find_one(
            {"dedupe_key": f"fund-inflow:{rid}:c0"}, {"_id": 0})
        assert adj.get("marks_ensured") is True
        _heal_ops()
        _heal_ops()
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-inflow:{rid}:c0"}) == 1
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-reverse:{rid}:c1"}) == 1, "sin duplicados"

    def test_sweep_rechecks_status_after_restoring_marks(self):
        """Variante 2 del auditor: el barrido lee el canje pendiente y el
        rechazo llega justo antes de reponer las marcas. Con el fix, la
        decisión usa el estado VIGENTE y compensa: fondo neto 0."""
        _cleanup()
        _mk_user(CLIENT_ID)
        pid, rid = _mk_company_redemption(status="pending")
        _db().company_fund_adjustments.insert_one({
            "id": uuid.uuid4().hex, "adjustment_type": "inflow",
            "currency": "USDT", "amount": 10.0, "method": "transfer",
            "source_name": "Marketplace tienda",
            "note": f"{MARK} venta web huérfana", "source": "marketplace_auto",
            "ref_id": rid, "dedupe_key": f"fund-inflow:{rid}:c0",
            "created_at": _iso(5)})

        def _sweep_with_race():
            async def _f():
                import services.credit_recovery as cr
                from db_client import db as real_db

                class _FlipColl:
                    def __init__(self, real):
                        self._real = real
                        self.flipped = False

                    def __getattr__(self, n):
                        return getattr(self._real, n)

                    async def update_one(self, q, u, **kw):
                        sets = (u.get("$set") or {}) if isinstance(u, dict) else {}
                        if (not self.flipped and q.get("id") == rid
                                and "fund_inflow_at" in sets):
                            self.flipped = True
                            # el rechazo se cuela ANTES de reponer las marcas
                            await self._real.update_one(
                                {"id": rid},
                                {"$set": {"status": "rejected",
                                          "rejection_cycle": 1}})
                        return await self._real.update_one(q, u, **kw)

                orig = cr.db
                cr.db = _ProxyDB(real_db, "redemptions",
                                 _FlipColl(real_db.redemptions))
                try:
                    return await cr.heal_initializing_ops(max_age_seconds=0)
                finally:
                    cr.db = orig
            return _run(_f)

        _sweep_with_race()
        db = _db()
        fresh = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert fresh["status"] == "rejected"
        assert fresh.get("fund_inflow_at"), "marcas repuestas"
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-reverse:{rid}:c1"}) == 1, \
            "FIX W02: la decisión usa el estado posterior a las marcas"
        assert _fund_net(rid) == 0.0
        adj = db.company_fund_adjustments.find_one(
            {"dedupe_key": f"fund-inflow:{rid}:c0"}, {"_id": 0})
        assert adj.get("marks_ensured") is True
        _heal_ops()
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-reverse:{rid}:c1"}) == 1, "sin duplicados"


# ============================================================
# Fase C · Mejora #7 — destino estructurado en la entrega
# ============================================================

class TestFaseCStructuredDestination:
    def test_withdrawal_delivery_doc_has_structured_fields(self):
        async def _f():
            from services.deliveries import build_delivery_doc
            ref = {"id": "it291_w1", "user_id": "u1",
                   "user_name": f"{MARK} Cliente",
                   "details": "Nombre: Ana\nCelular: +53 5551234",
                   "province": "La Habana",
                   "receiver_name": "Ana Pérez",
                   "receiver_phone": "+53 5551234",
                   "receiver_address": "Calle 23 #456",
                   "courier_municipality": "Playa",
                   "amount_usd": 100, "currency": "USD"}
            return await build_delivery_doc("withdrawal", ref,
                                            km=3, fee_usdt=5)
        doc = _run(_f)
        assert doc["receiver_name"] == "Ana Pérez"
        assert doc["receiver_phone"] == "+53 5551234"
        assert doc["municipality"] == "Playa"
        assert doc["province"] == "La Habana"

    def test_redemption_and_deposit_structured_mapping(self):
        async def _f():
            from services.deliveries import build_delivery_doc
            red = await build_delivery_doc("redemption", {
                "id": "it291_r1", "user_id": "u1",
                "user_name": f"{MARK} Cliente",
                "delivery_address": "Ave 41 #10", "product_name": "Caja",
                "quantity": 1, "receiver_phone": "+53 5887766",
                "courier_municipality": "Marianao"}, km=0, fee_usdt=0)
            dep = await build_delivery_doc("deposit", {
                "id": "it291_d1", "user_id": "u1",
                "user_name": f"{MARK} Cliente",
                "contact_name": "Luis", "pickup_phone": "+53 5001122",
                "pickup_address": "Calle 100", "amount": 500,
                "currency": "CUP"}, km=0, fee_usdt=0)
            return red, dep
        red, dep = _run(_f)
        # canje sin receiver_name → cae al nombre del cliente
        assert red["receiver_name"] == f"{MARK} Cliente"
        assert red["receiver_phone"] == "+53 5887766"
        assert red["municipality"] == "Marianao"
        assert dep["receiver_name"] == "Luis"
        assert dep["receiver_phone"] == "+53 5001122"

    def test_payload_models_accept_structured_contact(self):
        from routes.orders import WithdrawalCreate, RedemptionCreate, Redemption
        w = WithdrawalCreate(
            amount_usd=10, method="cash",
            details="Nombre Apellido 12345678 +53555555555",
            receiver_name="Ana Pérez", receiver_phone="+53 5551234",
            receiver_address="Calle 23 #456")
        assert w.receiver_phone == "+53 5551234"
        rc = RedemptionCreate(product_id="p1", quantity=1,
                              delivery_address="x",
                              receiver_phone="+53 5887766")
        assert rc.receiver_phone == "+53 5887766"
        r = Redemption(user_id="u", user_email="e", user_name="n",
                       product_id="p", product_name="pn", quantity=1,
                       total_usd=1.0, receiver_phone="+53 5")
        assert r.receiver_phone == "+53 5"


# ============================================================
# Fase C · Mejora #8 — métricas de tiempos, incidencias y costos
# ============================================================

def _plant_metric_delivery(status, minutes_ago, timeline, extra=None):
    did = f"it291_d_{uuid.uuid4().hex[:10]}"
    at = _iso(minutes_ago)
    doc = {
        "id": did, "kind": "redemption",
        "ref_id": f"it291_ref_{uuid.uuid4().hex[:8]}",
        "active_key": f"redemption:it291_{uuid.uuid4().hex[:8]}",
        "user_id": CLIENT_ID, "client_name": f"{MARK} client",
        "address": f"{MARK} addr", "province": "La Habana",
        "amount_label": f"{MARK} pkg", "km": 5.0, "fee_usdt": 10.0,
        "share_pct_snapshot": 80.0, "courier_share_usdt": 8.0,
        "platform_share_usdt": 2.0, "status": status,
        "courier_id": COURIER_ID, "courier_name": f"{MARK} courier",
        "payout_credited": False, "created_at": at, "updated_at": at,
        "timeline": timeline,
    }
    doc.update(extra or {})
    _db().deliveries.insert_one(doc)
    return did


class TestFaseCMetricsEndpoint:
    def teardown_method(self, _):
        _cleanup()

    def test_metrics_times_incidents_and_costs(self):
        _cleanup()
        # confirmado: creado -60, aceptado -50 (10 min), entregado -20 (30 min)
        _plant_metric_delivery("confirmed", 60, [
            {"status": "available", "at": _iso(60)},
            {"status": "accepted", "at": _iso(50)},
            {"status": "delivered", "at": _iso(20)},
            {"status": "confirmed", "at": _iso(5)},
        ], extra={"payout_credited": True})
        # entregado sin rendir + incidencia: creado -45, aceptado -40, entregado -10
        _plant_metric_delivery("delivered", 45, [
            {"status": "accepted", "at": _iso(40)},
            {"status": "delivered", "at": _iso(10)},
        ], extra={"incidents": [{"id": "i1", "type": "no_responde",
                                 "status": "open", "note": MARK}],
                  "has_open_incident": True})
        # cancelado sin tiempos
        _plant_metric_delivery("cancelled", 30, [])
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = requests.get(f"{API}/admin/deliveries/metrics",
                         headers=_hdr(ADMIN_TOKEN),
                         params={"date_from": today, "date_to": today,
                                 "courier_id": COURIER_ID})
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["total"] == 3
        assert m["confirmed"] == 1
        assert m["cancelled"] == 1
        assert m["unsettled_count"] == 1
        assert m["incidents_count"] == 1
        assert abs(m["incidents_pct"] - 33.3) < 0.2
        # promedios: aceptación (10+5)/2=7.5 · entrega (30+30)/2=30
        assert abs(m["avg_accept_min"] - 7.5) < 1.0, m["avg_accept_min"]
        assert abs(m["avg_deliver_min"] - 30.0) < 1.0, m["avg_deliver_min"]
        assert m["fees_usdt"] == 10.0
        assert m["courier_paid_usdt"] == 8.0
        assert m["platform_net_usdt"] == 2.0
        assert m["avg_fee_usdt"] == 10.0

    def test_metrics_requires_deliveries_permission(self):
        r = requests.get(f"{API}/admin/deliveries/metrics",
                         headers=_hdr(VIP_TOKEN))
        assert r.status_code in (401, 403)
