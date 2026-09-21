"""iter284 — Revisión 805e7d6: regresiones de los 6 hallazgos pendientes
(R01, R02, R05 alta · R03, R04, R06 media) según los criterios de aceptación
del auditor. R06 (chat frontend) se verifica en el backend por contrato de
paginación; la fusión del historial es del componente React.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN
from tests.test_iter279_s01_s07 import _run

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"
MARK = "IT284"
CLIENT_ID = "it284_client"
BUYER_ID = "it284_buyer"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes_ago)).isoformat()


def _bal(uid, code):
    u = _db().users.find_one({"user_id": uid}, {"_id": 0, "vip_balances": 1}) or {}
    return round(float((u.get("vip_balances") or {}).get(code) or 0.0), 6)


def _set_bal(uid, code, amount):
    _db().users.update_one({"user_id": uid},
                           {"$set": {f"vip_balances.{code}": float(amount)}})


def _mk_user(uid, role="vip", **extra):
    _db().users.update_one({"user_id": uid}, {"$set": {
        "user_id": uid, "email": f"{uid}@it284.test", "name": f"{MARK} {uid}",
        "role": role, "account_status": "active", "is_verified": True,
        "vip_balances": {}, **extra}}, upsert=True)


def _cleanup():
    db = _db()
    db.orders.delete_many({"from_code": {"$regex": f"^{MARK}"}})
    db.withdrawals.delete_many({"user_name": {"$regex": MARK}})
    db.redemptions.delete_many({"user_name": {"$regex": MARK}})
    db.products.delete_many({"name": {"$regex": MARK}})
    db.inventory_movements.delete_many(
        {"$or": [{"note": {"$regex": MARK}},
                 {"product_name": {"$regex": MARK}}]})
    db.company_fund_adjustments.delete_many({"note": {"$regex": MARK}})
    bids = [b["id"] for b in db.vip_batches.find(
        {"note": {"$regex": MARK}}, {"id": 1})]
    db.vip_batch_items.delete_many({"batch_id": {"$in": bids}})
    db.vip_batches.delete_many({"id": {"$in": bids}})
    db.users.update_one({"user_id": VIP_ID},
                        {"$unset": {f"vip_balances.{MARK}C": ""}})
    for uid in (CLIENT_ID, BUYER_ID):
        db.users.delete_many({"user_id": uid})


def _heal_credits():
    async def _f():
        from services.credit_recovery import heal_pending_credits
        return await heal_pending_credits(max_age_seconds=0)
    return _run(_f)


def _heal_ops():
    async def _f():
        from services.credit_recovery import heal_initializing_ops
        return await heal_initializing_ops(max_age_seconds=0)
    return _run(_f)


def _order_status(oid, status):
    return requests.put(f"{API}/admin/orders/{oid}/status",
                        headers=_hdr(ADMIN_TOKEN), json={"status": status})


def _mk_accum_order(status="pending", amount_to=100.0, **extra):
    oid = f"o_{uuid.uuid4().hex[:12]}"
    _db().orders.insert_one({
        "id": oid, "user_id": VIP_ID, "user_email": "vip@test",
        "user_name": f"{MARK} VIP", "user_role": "vip",
        "from_code": f"{MARK}Z", "to_code": f"{MARK}C",
        "amount_from": amount_to, "amount_to": float(amount_to),
        "rate_applied": 1.0, "commission_percent": 0.0,
        "delivery_method": "accumulate", "delivery_details": "",
        "sender_name": "S", "proof_image": "", "status": status,
        "created_at": _iso(5), "updated_at": _iso(5), **extra})
    return oid


# ============================================================
# R01 — el rechazo compite con el estado monetario de la orden
# ============================================================

class TestR01RejectAfterClaim:
    def teardown_method(self, _):
        _cleanup()

    def test_reject_blocked_while_credit_in_flight(self):
        """Repro del auditor: abono RECLAMADO (marker en vuelo) → el rechazo
        recibe 409, la orden queda liquidada y el healer completa los 100."""
        _cleanup()
        base = _bal(VIP_ID, f"{MARK}C")
        marker = {"op_id": f"order-accum:{uuid.uuid4().hex[:12]}",
                  "user_id": VIP_ID, "code": f"{MARK}C", "amount": 100.0,
                  "legacy_usd": False, "prepared": True, "at": _iso(10)}
        oid = _mk_accum_order(status="approved",
                              accumulated_at=_iso(10), credit_pending=marker)
        r = _order_status(oid, "rejected")
        assert r.status_code == 409, r.text
        assert "liquid" in r.json()["detail"].lower()
        assert _db().orders.find_one({"id": oid})["status"] == "approved"
        _heal_credits()
        assert abs(_bal(VIP_ID, f"{MARK}C") - base - 100) < 1e-6, \
            "el abono reclamado se completa exactamente una vez"
        _heal_credits()
        assert abs(_bal(VIP_ID, f"{MARK}C") - base - 100) < 1e-6
        # liquidada del todo → el rechazo sigue bloqueado
        assert _order_status(oid, "rejected").status_code == 409

    def test_reject_blocked_after_credit_applied_but_open_when_unclaimed(self):
        _cleanup()
        oid = _mk_accum_order(status="approved", accumulated_at=_iso(10))
        r = _order_status(oid, "rejected")
        assert r.status_code == 409, r.text
        assert _db().orders.find_one({"id": oid})["status"] == "approved"
        # sin claim monetario, el rechazo sigue funcionando normal
        oid2 = _mk_accum_order(status="pending")
        assert _order_status(oid2, "rejected").status_code == 200
        assert _db().orders.find_one({"id": oid2})["status"] == "rejected"

    def test_reject_blocked_after_residue_claim(self):
        _cleanup()
        oid = _mk_accum_order(status="approved",
                              residue_credited_at=_iso(10))
        assert _order_status(oid, "rejected").status_code == 409
        assert _db().orders.find_one({"id": oid})["status"] == "approved"


# ============================================================
# R02 — planes de tarifa con decisión terminal + rechazos coordinados
# ============================================================

def _mk_fee_plan_doc(coll, fee_field, currency):
    """Doc con tarifa PUBLICADA y plan pendiente (claim hecho, débito no
    demostrado) — el estado exacto que el auditor intercala."""
    did = f"{coll[:1]}_{uuid.uuid4().hex[:12]}"
    op = f"courier-fee:{did}:{uuid.uuid4().hex[:8]}"
    doc = {
        "id": did, "user_id": CLIENT_ID, "user_name": f"{MARK} Cliente",
        "status": "pending", "created_at": _iso(30), "updated_at": _iso(30),
        "courier_km": 20.0, "courier_fee_usdt": 10.0, fee_field: 10.0,
        "courier_fee_op_pending": {
            "op_id": op, "delta": 10.0, "currency": currency,
            "revert": {"courier_km": None, "courier_fee_usdt": None,
                       fee_field: 0.0},
            "at": _iso(10)},
    }
    if coll == "withdrawals":
        doc.update({"amount_usd": 100, "currency": currency, "method": "cash"})
    else:
        doc.update({"total_usd": 40.0, "settlement_currency": currency,
                    "product_id": "px", "product_name": f"{MARK} Prod",
                    "quantity": 1})
    _db()[coll].insert_one(doc)
    return did, op


def _late_debit(uid, code, amount, op):
    async def _f():
        from services.balances import debit_balance_idempotent
        return await debit_balance_idempotent(uid, code, amount, op)
    return _run(_f)


class TestR02FeePlanTerminal:
    def teardown_method(self, _):
        _cleanup()

    def _abort_and_retry(self, coll, fee_field):
        _mk_user(CLIENT_ID)
        cur = f"{MARK}C"
        _set_bal(CLIENT_ID, cur, 5.0)
        did, op = _mk_fee_plan_doc(coll, fee_field, cur)
        _heal_ops()  # saldo 5 < 10 → aborta con decisión TERMINAL (quema)
        doc = _db()[coll].find_one({"id": did}, {"_id": 0})
        assert "courier_fee_op_pending" not in doc
        assert float(doc.get(fee_field) or 0) == 0.0, "tarifa restaurada a 0"
        assert _bal(CLIENT_ID, cur) == 5.0
        # entran 100 nuevos y el ejecutor lento intenta su débito original
        _set_bal(CLIENT_ID, cur, 105.0)
        st = _late_debit(CLIENT_ID, cur, 10.0, op)
        assert st == "duplicate", f"el débito tardío queda quemado: {st}"
        assert _bal(CLIENT_ID, cur) == 105.0, "saldo 105, jamás 95"
        _heal_ops()
        assert _bal(CLIENT_ID, cur) == 105.0
        assert float((_db()[coll].find_one({"id": did}) or {})
                     .get(fee_field) or 0) == 0.0

    def test_aborted_withdrawal_fee_never_debits_later(self):
        _cleanup()
        self._abort_and_retry("withdrawals", "courier_fee_currency_amount")

    def test_aborted_redemption_fee_never_debits_later(self):
        _cleanup()
        self._abort_and_retry("redemptions", "courier_fee_usd")

    def test_reject_waits_for_fee_plan_and_refunds_exactly_paid(self):
        """Aceptación: compra de 100 con saldo 0, tarifa 10 publicada cuyo
        débito falla; el rechazo concurrente NO devuelve la tarifa no pagada:
        espera al plan (409) y luego reembolsa exactamente 100."""
        _cleanup()
        _mk_user(BUYER_ID)
        _set_bal(BUYER_ID, "USDT", 0.0)
        db = _db()
        pid = f"p_{uuid.uuid4().hex[:10]}"
        db.products.insert_one({
            "id": pid, "name": f"{MARK} Producto", "description": "t",
            "category": "test", "price_usd": 100.0, "cost_usd": 0.0,
            "stock": 0, "image_url": "", "created_at": _iso()})
        rid = f"r_{uuid.uuid4().hex[:12]}"
        op = f"courier-fee:{rid}:{uuid.uuid4().hex[:8]}"
        db.redemptions.insert_one({
            "id": rid, "user_id": BUYER_ID, "user_name": f"{MARK} Comprador",
            "product_id": pid, "product_name": f"{MARK} Producto",
            "quantity": 1, "total_usd": 100.0, "settlement_currency": "USDT",
            "status": "pending", "created_at": _iso(10),
            "courier_km": 20.0, "courier_fee_usdt": 10.0,
            "courier_fee_usd": 10.0,
            "courier_fee_op_pending": {
                "op_id": op, "delta": 10.0, "currency": "USDT",
                "revert": {"courier_km": None, "courier_fee_usdt": None,
                           "courier_fee_usd": 0.0},
                "at": _iso(10)}})
        r = requests.put(f"{API}/admin/redemptions/{rid}/status",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"status": "rejected", "admin_note": MARK})
        assert r.status_code == 409, r.text
        assert "mensajería en curso" in r.json()["detail"]
        assert _bal(BUYER_ID, "USDT") == 0.0, "sin reembolso fantasma"
        _heal_ops()  # débito imposible (saldo 0) → tarifa restaurada a 0
        r = requests.put(f"{API}/admin/redemptions/{rid}/status",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"status": "rejected", "admin_note": MARK})
        assert r.status_code == 200, r.text
        assert _bal(BUYER_ID, "USDT") == 100.0, \
            "reembolso exacto de lo pagado (100), no 110"
        _heal_credits()
        _heal_ops()
        assert _bal(BUYER_ID, "USDT") == 100.0

    def test_fee_claim_blocked_on_terminal_status(self):
        """El claim del plan exige atómicamente estado no terminal: una copia
        obsoleta (leyó 'pending', ya está 'rejected') recibe 409."""
        _cleanup()
        _mk_user(BUYER_ID)
        db = _db()
        rid = f"r_{uuid.uuid4().hex[:12]}"
        db.redemptions.insert_one({
            "id": rid, "user_id": BUYER_ID, "user_name": f"{MARK} Comprador",
            "product_id": "px", "product_name": f"{MARK} P", "quantity": 1,
            "total_usd": 40.0, "settlement_currency": "USDT",
            "status": "rejected", "courier_fee_usd": 0.0,
            "created_at": _iso(10)})
        stale = db.redemptions.find_one({"id": rid}, {"_id": 0})
        stale["status"] = "pending"

        def _try():
            async def _f():
                from fastapi import HTTPException
                from services.courier_fee import apply_fee_change_plan
                try:
                    await apply_fee_change_plan(
                        "redemptions", stale, BUYER_ID, "USDT",
                        "courier_fee_usd",
                        {"courier_fee_usd": 10.0, "courier_km": 20.0}, 10.0)
                    return 200
                except HTTPException as e:
                    return e.status_code
            return _run(_f)
        assert _try() == 409
        fresh = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert float(fresh.get("courier_fee_usd") or 0) == 0.0
        assert "courier_fee_op_pending" not in fresh


# ============================================================
# R03 — planes de carga de lotes: inserción parcial + cierre sellado
# ============================================================

def _mk_batch():
    r = requests.post(f"{API}/vip/batches", headers=_hdr(VIP_TOKEN),
                      json={"direction": "credit", "currency": "USD",
                            "note": MARK})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _items_payload(n, amount=25):
    return {"items": [{"amount": amount, "holder_name": "Nombre Apellido"}
                      for _ in range(n)]}


def _seed_items(batch_id, n):
    docs = [{"id": f"vitem_{uuid.uuid4().hex[:12]}", "batch_id": batch_id,
             "vip_user_id": VIP_ID, "holder_name": "Nombre Apellido",
             "amount": 10.0, "currency": "USD", "direction": "credit",
             "status": "pending", "created_at": _iso()} for _ in range(n)]
    _db().vip_batch_items.insert_many(docs)
    _db().vip_batches.update_one({"id": batch_id},
                                 {"$set": {"items_reserved": n}})


class TestR03BatchUploadPlans:
    def teardown_method(self, _):
        _cleanup()

    def test_partial_insert_releases_only_uninserted_quota(self):
        """Repro del auditor: reserva de 50, insertó 25 y crasheó. El healer
        libera SOLO 25 y dos cargas de 25 posteriores jamás superan 500."""
        _cleanup()
        bid = _mk_batch()
        _seed_items(bid, 450)
        ids = [f"vitem_{uuid.uuid4().hex[:12]}" for _ in range(50)]
        _db().vip_batch_items.insert_many(
            [{"id": i, "batch_id": bid, "vip_user_id": VIP_ID,
              "holder_name": "Nombre Apellido", "amount": 10.0,
              "currency": "USD", "direction": "credit", "status": "pending",
              "created_at": _iso()} for i in ids[:25]])
        _db().vip_batches.update_one({"id": bid}, {
            "$set": {"items_reserved": 500},
            "$push": {"upload_plans": {"plan_id": f"vbup_{MARK}",
                                       "item_ids": ids, "count": 50,
                                       "at": _iso(20)}}})
        _heal_ops()
        b = _db().vip_batches.find_one({"id": bid}, {"_id": 0})
        assert b["items_reserved"] == 475, \
            f"libera solo el cupo NO insertado: {b['items_reserved']}"
        assert not b.get("upload_plans")
        with ThreadPoolExecutor(max_workers=2) as ex:
            rs = list(ex.map(
                lambda _: requests.post(f"{API}/vip/batches/{bid}/items",
                                        headers=_hdr(VIP_TOKEN),
                                        json=_items_payload(25)), range(2)))
        codes = sorted(r.status_code for r in rs)
        assert codes == [200, 409], codes
        assert _db().vip_batch_items.count_documents({"batch_id": bid}) == 500
        b = _db().vip_batches.find_one({"id": bid}, {"_id": 0})
        assert b["items_reserved"] == 500 and not b.get("upload_plans")

    def test_close_waits_for_inflight_upload(self):
        _cleanup()
        bid = _mk_batch()
        plan = {"plan_id": f"vbup_{uuid.uuid4().hex[:8]}",
                "item_ids": [f"vitem_x{i}" for i in range(3)],
                "count": 3, "at": _iso()}
        _db().vip_batches.update_one(
            {"id": bid}, {"$set": {"items_reserved": 3},
                          "$push": {"upload_plans": plan}})
        r = requests.post(f"{API}/vip/batches/{bid}/close",
                          headers=_hdr(VIP_TOKEN))
        assert r.status_code == 409, r.text
        assert "cargas" in r.json()["detail"].lower()
        assert _db().vip_batches.find_one({"id": bid})["status"] == "open"

        def _resolve():
            async def _f():
                from services.vip_batch_ops import resolve_upload_plan
                await resolve_upload_plan(bid, plan)
            return _run(_f)
        _resolve()
        b = _db().vip_batches.find_one({"id": bid}, {"_id": 0})
        assert b["items_reserved"] == 0 and not b.get("upload_plans")
        r = requests.post(f"{API}/vip/batches/{bid}/close",
                          headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200, r.text
        r = requests.post(f"{API}/vip/batches/{bid}/items",
                          headers=_hdr(VIP_TOKEN), json=_items_payload(1))
        assert r.status_code == 409
        assert _db().vip_batch_items.count_documents({"batch_id": bid}) == 0, \
            "ningún ítem aparece tras un cierre definitivo"

    def test_normal_upload_cleans_its_plan(self):
        _cleanup()
        bid = _mk_batch()
        r = requests.post(f"{API}/vip/batches/{bid}/items",
                          headers=_hdr(VIP_TOKEN), json=_items_payload(5))
        assert r.status_code == 200, r.text
        b = _db().vip_batches.find_one({"id": bid}, {"_id": 0})
        assert b["items_reserved"] == 5
        assert not b.get("upload_plans"), "el plan se limpia al terminar"


# ============================================================
# R04 / R05 — venta de empresa: traza única + fondo neto 0 tras rechazo
# ============================================================

def _mk_company_sale(pend_inv, pend_fund, **extra):
    db = _db()
    pid = f"p_{uuid.uuid4().hex[:10]}"
    db.products.insert_one({
        "id": pid, "name": f"{MARK} Producto Empresa", "description": "t",
        "category": "test", "price_usd": 1000.0, "cost_usd": 600.0,
        "stock": 1, "image_url": "", "created_at": _iso()})
    rid = f"r_{uuid.uuid4().hex[:12]}"
    db.redemptions.insert_one({
        "id": rid, "user_id": VIP_ID, "user_name": f"{MARK} VIP",
        "product_id": pid, "product_name": f"{MARK} Producto Empresa",
        "quantity": 1, "total_usd": 10.0, "cost_usd": 6.0,
        "total_store": 1000.0, "store_currency": "CUP", "fx_rate": 100.0,
        "settlement_currency": "USDT", "status": "pending",
        "created_at": _iso(10),
        "sale_trace_pending": {"inv": pend_inv, "fund": pend_fund,
                               "at": _iso(10)}, **extra})
    return pid, rid


class TestR04SingleSaleTrace:
    def teardown_method(self, _):
        _cleanup()

    def test_creator_and_recoverer_write_single_sale(self):
        """Repro del auditor: creador y recuperador solapados en la misma
        intención → UNA sola venta de 1.000 CUP, no 2.000."""
        _cleanup()
        pid, rid = _mk_company_sale(pend_inv=True, pend_fund=False)

        def _double():
            async def _f():
                import asyncio
                from db_client import db as adb
                from services.credit_recovery import ensure_company_sale_traces
                r = await adb.redemptions.find_one({"id": rid}, {"_id": 0})
                return await asyncio.gather(
                    ensure_company_sale_traces(dict(r)),
                    ensure_company_sale_traces(dict(r)))
            return _run(_f)
        _double()
        movs = list(_db().inventory_movements.find(
            {"ref_id": rid, "type": "venta"}, {"_id": 0}))
        assert len(movs) == 1, f"una sola traza de venta: {len(movs)}"
        assert movs[0].get("dedupe_key") == f"sale-trace:{rid}:c0"
        assert movs[0]["total"] == 1000.0, "1.000 CUP registrados, no 2.000"
        _heal_ops()
        assert _db().inventory_movements.count_documents(
            {"ref_id": rid, "type": "venta"}) == 1
        fresh = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert "sale_trace_pending" not in fresh
        assert _db().products.find_one({"id": pid})["stock"] == 1, \
            "la traza no vuelve a descontar mercancía"


class TestR05LateFundInflow:
    def teardown_method(self, _):
        _cleanup()

    def test_late_inflow_after_rejection_is_reversed(self):
        """Repro del auditor: rechazo completo (reembolso + stock) y la
        entrada c0 aterriza tarde → el ciclo queda con efecto neto 0."""
        _cleanup()
        pid, rid = _mk_company_sale(pend_inv=False, pend_fund=True)
        db = _db()
        db.redemptions.update_one({"id": rid}, {"$set": {
            "status": "rejected", "rejection_cycle": 1,
            "rejection_applied": True, "rejection_effects_done": True,
            "fund_inflow_at": _iso(5), "fund_inflow_amount": 10.0,
            "fund_inflow_currency": "USDT"}})
        db.company_fund_adjustments.insert_one({
            "id": uuid.uuid4().hex, "adjustment_type": "inflow",
            "currency": "USDT", "amount": 10.0, "method": "transfer",
            "source_name": "Marketplace tienda",
            "note": f"{MARK} venta web tardía", "source": "marketplace_auto",
            "ref_id": rid, "dedupe_key": f"fund-inflow:{rid}:c0",
            "created_at": _iso(5)})
        _heal_ops()
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-reverse:{rid}:c1"}) == 1, \
            "el reverso compensa la entrada tardía (neto 0)"
        fresh = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert fresh.get("fund_inflow_reversed_at")
        assert "sale_trace_pending" not in fresh
        _heal_ops()
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-inflow:{rid}:c0"}) == 1
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-reverse:{rid}:c1"}) == 1, "sin duplicados"

    def test_crash_after_inflow_before_marks_still_reversed(self):
        """Crash entre publicar el asiento y marcar el doc: la paridad
        entrada↔reverso se restituye igual (decisión durable por ciclo)."""
        _cleanup()
        pid, rid = _mk_company_sale(pend_inv=False, pend_fund=True)
        db = _db()
        db.redemptions.update_one({"id": rid}, {"$set": {
            "status": "rejected", "rejection_cycle": 1,
            "rejection_applied": True, "rejection_effects_done": True}})
        db.company_fund_adjustments.insert_one({
            "id": uuid.uuid4().hex, "adjustment_type": "inflow",
            "currency": "USDT", "amount": 10.0, "method": "transfer",
            "source_name": "Marketplace tienda",
            "note": f"{MARK} venta web sin marca", "source": "marketplace_auto",
            "ref_id": rid, "dedupe_key": f"fund-inflow:{rid}:c0",
            "created_at": _iso(5)})
        _heal_ops()
        fresh = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert fresh.get("fund_inflow_at"), "la marca se repone del asiento"
        assert fresh.get("fund_inflow_reversed_at")
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-reverse:{rid}:c1"}) == 1
        assert "sale_trace_pending" not in fresh
