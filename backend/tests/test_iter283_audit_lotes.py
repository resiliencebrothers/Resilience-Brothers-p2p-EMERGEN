"""iter283 — Auditoría funcional de lotes, intercambios, mensajería y mercado
(commit 795176e): regresiones de los 10 hallazgos EX01/EX02, ME01–ME04,
MR01/MR02, LO01/LO02 según los criterios de aceptación del auditor.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, make_admin_totp
from tests.test_iter279_s01_s07 import _run

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"
MARK = "IT283"
COURIER_ID = "it283_courier"
COURIER_TOKEN = "it283_courier_session"
BLOCKVIP_ID = "it283_blockvip"
BLOCKVIP_TOKEN = "it283_blockvip_session"


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
    db = _db()
    db.users.update_one({"user_id": uid}, {"$set": {
        "user_id": uid, "email": f"{uid}@it283.test", "name": f"{MARK} {uid}",
        "role": role, "account_status": "active", "is_verified": True,
        "vip_balances": {}, **extra}}, upsert=True)


def _mk_session(uid, token):
    _db().user_sessions.update_one(
        {"session_token": token},
        {"$set": {"user_id": uid, "session_token": token,
                  "expires_at": "2027-12-31T00:00:00+00:00",
                  "created_at": _iso()}}, upsert=True)


def _cleanup():
    db = _db()
    db.orders.delete_many({"from_code": {"$regex": f"^{MARK}"}})
    db.rates.delete_many({"$or": [{"from_code": {"$regex": f"^{MARK}"}},
                                  {"to_code": {"$regex": f"^{MARK}"}}]})
    db.currencies.delete_many({"code": {"$regex": f"^{MARK}"}})
    db.withdrawals.delete_many({"user_name": {"$regex": MARK}})
    db.redemptions.delete_many({"user_name": {"$regex": MARK}})
    db.products.delete_many({"name": {"$regex": MARK}})
    db.deliveries.delete_many({"client_name": {"$regex": MARK}})
    db.delivery_chat.delete_many({"delivery_id": {"$regex": f"^{MARK}"}})
    db.deposits.delete_many({"user_name": {"$regex": MARK}})
    db.inventory_movements.delete_many({"note": {"$regex": MARK}})
    db.company_fund_adjustments.delete_many({"note": {"$regex": MARK}})
    bids = [b["id"] for b in db.vip_batches.find(
        {"note": {"$regex": MARK}}, {"id": 1})]
    db.vip_batch_items.delete_many({"batch_id": {"$in": bids}})
    db.vip_batches.delete_many({"id": {"$in": bids}})
    db.users.update_one({"user_id": VIP_ID},
                        {"$unset": {f"vip_balances.{MARK}C": "",
                                    f"vip_balances.{MARK}R": ""}})
    for uid in (COURIER_ID, BLOCKVIP_ID, "it283_client", "it283_vendor",
                "it283_buyer", "it283_othercourier"):
        db.users.delete_many({"user_id": uid})
    db.user_sessions.delete_many(
        {"session_token": {"$in": [COURIER_TOKEN, BLOCKVIP_TOKEN]}})


def _seed_exchange_pair():
    """Moneda destino fiat con entrega cash + tasa 1.015 (repro del auditor)."""
    db = _db()
    now = _iso()
    for code, methods in ((f"{MARK}Z", ["transfer"]),
                          (f"{MARK}C", ["cash", "transfer"])):
        db.currencies.update_one(
            {"code": code},
            {"$set": {"code": code, "name": f"Test {code}", "type": "fiat",
                      "is_active": True, "delivery_methods": methods,
                      "updated_at": now},
             "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": now}},
            upsert=True)
    db.rates.update_one(
        {"from_code": f"{MARK}Z", "to_code": f"{MARK}C"},
        {"$set": {"from_code": f"{MARK}Z", "to_code": f"{MARK}C",
                  "rate_normal": 1.015, "rate_vip": 1.015, "updated_at": now},
         "$setOnInsert": {"id": uuid.uuid4().hex}}, upsert=True)


def _create_cash_order(amount=50):
    r = requests.post(f"{API}/orders", headers=_hdr(VIP_TOKEN), json={
        "from_code": f"{MARK}Z", "to_code": f"{MARK}C",
        "amount_from": amount, "delivery_method": "cash",
        "delivery_details": "Nombre: X\nCelular: +5300\nDirección: y",
        "sender_name": "Test Sender", "proof_image": ""})
    assert r.status_code == 200, r.text
    return r.json()


def _order_status(oid, status, tok=ADMIN_TOKEN):
    return requests.put(f"{API}/admin/orders/{oid}/status",
                        headers=_hdr(tok), json={"status": status})


def _mk_accum_order(status="pending", amount_to=100.0):
    oid = f"o_{uuid.uuid4().hex[:12]}"
    _db().orders.insert_one({
        "id": oid, "user_id": VIP_ID, "user_email": "vip@test",
        "user_name": f"{MARK} VIP", "user_role": "vip",
        "from_code": f"{MARK}Z", "to_code": f"{MARK}C",
        "amount_from": amount_to, "amount_to": float(amount_to),
        "rate_applied": 1.0, "commission_percent": 0.0,
        "delivery_method": "accumulate", "delivery_details": "",
        "sender_name": "S", "proof_image": "", "status": status,
        "created_at": _iso(5), "updated_at": _iso(5)})
    return oid


# ============================================================
# EX01 — residuo solo al liquidar
# ============================================================

class TestEX01Residue:
    def teardown_method(self, _):
        _cleanup()

    def test_pending_and_rejected_orders_never_credit_residue(self):
        """Repro del auditor: dos órdenes de 50 @ 1.015 (residuo 0.75 c/u)
        pendientes → saldo intacto; rechazarlas → saldo intacto."""
        _cleanup()
        _seed_exchange_pair()
        base = _bal(VIP_ID, f"{MARK}C")
        o1 = _create_cash_order(50)
        o2 = _create_cash_order(50)
        assert o1["amount_to"] == 50.0
        assert _bal(VIP_ID, f"{MARK}C") == base, \
            "con órdenes pendientes el saldo no puede aumentar"
        for oid in (o1["id"], o2["id"]):
            r = _order_status(oid, "rejected")
            assert r.status_code == 200, r.text
        assert _bal(VIP_ID, f"{MARK}C") == base, \
            "rechazar órdenes sin ingreso confirmado deja el saldo intacto"

    def test_settled_order_credits_once_and_recovers(self):
        _cleanup()
        _seed_exchange_pair()
        base = _bal(VIP_ID, f"{MARK}C")
        o = _create_cash_order(50)  # residuo 0.75
        assert _order_status(o["id"], "approved").status_code == 200
        assert abs(_bal(VIP_ID, f"{MARK}C") - base - 0.75) < 1e-6
        # repetir y completar no duplica
        assert _order_status(o["id"], "completed").status_code == 200
        assert abs(_bal(VIP_ID, f"{MARK}C") - base - 0.75) < 1e-6

        # crash entre el claim y el abono → el healer completa una sola vez
        o2 = _create_cash_order(50)
        db = _db()
        marker = {"op_id": f"order-residue:{uuid.uuid4().hex[:12]}",
                  "user_id": VIP_ID, "code": f"{MARK}C", "amount": 0.75,
                  "legacy_usd": False, "prepared": True, "at": _iso(10)}
        db.orders.update_one({"id": o2["id"]}, {"$set": {
            "status": "approved", "residue_credited_at": _iso(10),
            "credit_pending": marker}})

        def _heal():
            async def _f():
                from services.credit_recovery import heal_pending_credits
                return await heal_pending_credits(max_age_seconds=0)
            return _run(_f)
        _heal()
        assert abs(_bal(VIP_ID, f"{MARK}C") - base - 1.5) < 1e-6
        _heal()
        assert abs(_bal(VIP_ID, f"{MARK}C") - base - 1.5) < 1e-6, \
            "el recuperador no duplica el residuo"


# ============================================================
# EX02 — transición y abono recuperables
# ============================================================

class TestEX02Transitions:
    def teardown_method(self, _):
        _cleanup()

    def test_retry_after_crash_completes_accumulation_once(self):
        """Variante 1 del auditor: 'approved' guardado, crash antes del claim
        del abono. Repetir la MISMA aprobación completa los 100 una vez."""
        _cleanup()
        base = _bal(VIP_ID, f"{MARK}C")
        oid = _mk_accum_order(status="approved")  # crash: sin accumulated_at
        r = _order_status(oid, "approved")
        assert r.status_code == 200, r.text
        assert abs(_bal(VIP_ID, f"{MARK}C") - base - 100) < 1e-6, \
            "el reintento completa el abono perdido"
        r = _order_status(oid, "approved")
        assert r.status_code == 200
        assert abs(_bal(VIP_ID, f"{MARK}C") - base - 100) < 1e-6, \
            "sin duplicados al repetir"

    def test_concurrent_approve_reject_single_winner(self):
        _cleanup()
        base = _bal(VIP_ID, f"{MARK}C")
        oid = _mk_accum_order(status="pending")
        with ThreadPoolExecutor(max_workers=2) as ex:
            rs = list(ex.map(lambda s: (s, _order_status(oid, s)),
                             ["approved", "rejected"]))
        codes = sorted(r.status_code for _, r in rs)
        # Carrera real → el perdedor recibe 409. Si el sistema serializó las
        # peticiones ([200, 200]) son dos transiciones legítimas encadenadas
        # (pending→approved→rejected por admin) y el abono queda representado.
        assert codes in ([200, 409], [200, 200]), codes
        final = _db().orders.find_one({"id": oid}, {"_id": 0})
        delta = _bal(VIP_ID, f"{MARK}C") - base
        credited = "accumulated_at" in final
        assert credited == (abs(delta - 100) < 1e-6), \
            "el abono SIEMPRE está representado en la orden"
        if codes == [200, 409] and final["status"] == "rejected":
            assert not credited and abs(delta) < 1e-6, \
                "una orden rechazada en carrera jamás queda con abono"

    def test_stale_write_after_reject_gets_conflict(self):
        """La escritura obsoleta (leyó 'pending', otro ya rechazó) recibe
        conflicto y sus efectos monetarios nunca corren."""
        _cleanup()
        base = _bal(VIP_ID, f"{MARK}C")
        oid = _mk_accum_order(status="pending")
        assert _order_status(oid, "rejected").status_code == 200
        # reintento con lectura obsoleta imposible vía HTTP (el route relee),
        # pero un approve posterior legítimo por admin sí transiciona; el
        # guard de estado del CLAIM es lo que protege el abono tardío:
        stale_order = {**_db().orders.find_one({"id": oid}, {"_id": 0}),
                       "status": "pending"}

        def _try():
            async def _f():
                from services.balances import accumulate_vip_balance
                return await accumulate_vip_balance(stale_order)
            return _run(_f)
        assert _try() is False
        assert _bal(VIP_ID, f"{MARK}C") == base
        assert _db().orders.find_one({"id": oid})["status"] == "rejected"

    def test_stale_credit_claim_requires_settled_state(self):
        _cleanup()
        base = _bal(VIP_ID, f"{MARK}C")
        oid = _mk_accum_order(status="rejected")
        order = _db().orders.find_one({"id": oid}, {"_id": 0})

        def _try():
            async def _f():
                from services.balances import accumulate_vip_balance
                return await accumulate_vip_balance(order)
            return _run(_f)
        assert _try() is False, "el claim exige estado liquidado"
        assert _bal(VIP_ID, f"{MARK}C") == base


# ============================================================
# ME01 — tarifa de mensajería exactamente-una-vez
# ============================================================

def _seed_fee_env():
    db = _db()
    db.settings.update_one({"id": "global"}, {"$set": {
        "courier_rate_usdt_per_km": 0.5, "courier_min_fee_usdt": 2.0,
        "courier_free_min_usdt": 1000.0}}, upsert=True)
    now = _iso()
    db.rates.update_one(
        {"from_code": "USDT", "to_code": f"{MARK}C"},
        {"$set": {"from_code": "USDT", "to_code": f"{MARK}C",
                  "rate_normal": 1.0, "rate_vip": 1.0, "updated_at": now},
         "$setOnInsert": {"id": uuid.uuid4().hex}}, upsert=True)


def _mk_cash_withdrawal():
    wid = f"w_{uuid.uuid4().hex[:12]}"
    _db().withdrawals.insert_one({
        "id": wid, "user_id": VIP_ID, "user_email": "vip@test",
        "user_name": f"{MARK} VIP", "amount_usd": 100,
        "currency": f"{MARK}C", "method": "cash",
        "details": "Receptor Prueba 12345678 +5355555555 dir",
        "status": "pending", "province": "La Habana",
        "created_at": _iso(), "updated_at": _iso()})
    return wid


class TestME01CourierFee:
    def teardown_method(self, _):
        _cleanup()

    def _fee(self, wid, km, code):
        return requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                             headers=_hdr(ADMIN_TOKEN),
                             json={"km": km, "totp_code": code})

    def test_concurrent_charge_and_annul_apply_once(self):
        _cleanup()
        _seed_fee_env()
        wid = _mk_cash_withdrawal()
        _set_bal(VIP_ID, f"{MARK}C", 100.0)
        code = make_admin_totp()
        with ThreadPoolExecutor(max_workers=2) as ex:
            rs = list(ex.map(lambda _: self._fee(wid, 20, code), range(2)))
        codes = sorted(r.status_code for r in rs)
        # [200, 409] si compiten por el claim; [200, 200] si se serializan
        # (la 2ª ve delta 0 y no mueve saldo). El saldo prueba exactamente-una-vez.
        assert codes in ([200, 409], [200, 200]), f"solo un cobro: {codes}"
        assert _bal(VIP_ID, f"{MARK}C") == 90.0, "saldo 100 − 10 = 90"
        w = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w["courier_fee_currency_amount"] == 10.0
        assert "courier_fee_op_pending" not in w

        # dos anulaciones simultáneas → una sola devolución
        code = make_admin_totp()
        with ThreadPoolExecutor(max_workers=2) as ex:
            rs = list(ex.map(lambda _: self._fee(wid, 0, code), range(2)))
        codes = sorted(r.status_code for r in rs)
        assert codes in ([200, 409], [200, 200]), f"solo una devolución: {codes}"
        assert _bal(VIP_ID, f"{MARK}C") == 100.0, "saldo vuelve a 100, no 110"

    def test_interrupted_charge_completed_once_by_healer(self):
        """Cobrar 10, fallar antes del débito y repetir → UN solo cobro."""
        _cleanup()
        _seed_fee_env()
        wid = _mk_cash_withdrawal()
        _set_bal(VIP_ID, f"{MARK}C", 100.0)
        # estado exacto tras el claim (tarifa guardada, débito pendiente)
        plan = {"op_id": f"courier-fee:{wid}:{uuid.uuid4().hex[:8]}",
                "delta": 10.0, "currency": f"{MARK}C",
                "revert": {"courier_fee_currency_amount": None,
                           "courier_fee_usdt": None, "courier_km": None},
                "at": _iso(10)}
        _db().withdrawals.update_one({"id": wid}, {"$set": {
            "courier_km": 20.0, "courier_fee_usdt": 10.0,
            "courier_fee_currency_amount": 10.0,
            "courier_fee_currency": f"{MARK}C",
            "courier_fee_op_pending": plan}})
        # reintento del operador mientras el plan sigue pendiente → conflicto
        r = self._fee(wid, 20, make_admin_totp())
        assert r.status_code == 409, r.text
        assert _bal(VIP_ID, f"{MARK}C") == 100.0

        def _heal():
            async def _f():
                from services.courier_fee import heal_courier_fee_plans
                return await heal_courier_fee_plans(_iso())
            return _run(_f)
        _heal()
        assert _bal(VIP_ID, f"{MARK}C") == 90.0, "el healer completa el cobro"
        _heal()
        assert _bal(VIP_ID, f"{MARK}C") == 90.0, "una sola vez"
        w = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert "courier_fee_op_pending" not in w
        # repetir el mismo cobro ya liquidado → delta 0, sin movimiento
        r = self._fee(wid, 20, make_admin_totp())
        assert r.status_code == 200, r.text
        assert _bal(VIP_ID, f"{MARK}C") == 90.0

    def test_redemption_fee_concurrent_single_delta(self):
        _cleanup()
        _seed_fee_env()
        rid = f"r_{uuid.uuid4().hex[:12]}"
        _db().redemptions.insert_one({
            "id": rid, "user_id": VIP_ID, "user_name": f"{MARK} VIP",
            "product_id": "px", "product_name": "Prod", "quantity": 1,
            "total_usd": 50.0, "status": "pending",
            "settlement_currency": "USDT", "created_at": _iso()})
        _set_bal(VIP_ID, "USDT", 100.0)
        code = make_admin_totp()

        def _rfee(km):
            return requests.post(
                f"{API}/admin/redemptions/{rid}/courier-fee",
                headers=_hdr(ADMIN_TOKEN), json={"km": km, "totp_code": code})
        with ThreadPoolExecutor(max_workers=2) as ex:
            rs = list(ex.map(lambda _: _rfee(20), range(2)))
        codes = sorted(r.status_code for r in rs)
        assert codes in ([200, 409], [200, 200]), f"solo un cobro: {codes}"
        assert _bal(VIP_ID, "USDT") == 90.0
        code = make_admin_totp()
        with ThreadPoolExecutor(max_workers=2) as ex:
            rs = list(ex.map(lambda _: _rfee(0), range(2)))
        assert sorted(r.status_code for r in rs) in ([200, 409], [200, 200])
        assert _bal(VIP_ID, "USDT") == 100.0, "sin devolución doble"


# ============================================================
# ME02 — transiciones de mensajería condicionadas
# ============================================================

def _mk_delivery(status="available", courier_id=None, share=8.0, **extra):
    did = f"d_{uuid.uuid4().hex[:12]}"
    _db().deliveries.insert_one({
        "id": did, "kind": "withdrawal", "ref_id": f"wref_{did}",
        "user_id": VIP_ID, "client_name": f"{MARK} Cliente",
        "amount_label": "100 USD", "status": status,
        "courier_id": courier_id, "courier_name": "Mensajero" if courier_id else None,
        "fee_usdt": 10.0, "courier_share_usdt": share,
        "platform_share_usdt": round(10.0 - share, 2),
        "created_at": _iso(), "updated_at": _iso(), "timeline": [], **extra})
    return did


class TestME02DeliveryRaces:
    def teardown_method(self, _):
        _cleanup()

    def test_claim_respects_fresh_reservation(self):
        _cleanup()
        _mk_user(COURIER_ID, role="client", is_courier=True)
        _mk_session(COURIER_ID, COURIER_TOKEN)
        did = _mk_delivery(status="available",
                           assigned_to_courier_id="it283_othercourier")
        r = requests.post(f"{API}/courier/deliveries/{did}/claim",
                          headers=_hdr(COURIER_TOKEN), json={})
        assert r.status_code == 403, r.text
        d = _db().deliveries.find_one({"id": did}, {"_id": 0})
        assert d["assigned_to_courier_id"] == "it283_othercourier", \
            "la reserva del otro mensajero queda intacta"
        assert d["status"] == "available"
        # sin reserva sí puede tomarla
        did2 = _mk_delivery(status="available")
        r = requests.post(f"{API}/courier/deliveries/{did2}/claim",
                          headers=_hdr(COURIER_TOKEN), json={})
        assert r.status_code == 200, r.text

    def test_stale_confirm_after_cancel_gets_conflict(self):
        """Intercalación del auditor: A lee 'delivered', B cancela, A sigue.
        La confirmación tardía recibe conflicto y NO paga la comisión."""
        _cleanup()
        _mk_user(COURIER_ID, role="client", is_courier=True)
        did = _mk_delivery(status="delivered", courier_id=COURIER_ID)
        d_stale = _db().deliveries.find_one({"id": did}, {"_id": 0})
        # B cancela mientras A espera
        _db().deliveries.update_one({"id": did},
                                    {"$set": {"status": "cancelled"}})
        base = _bal(COURIER_ID, "USDT")

        def _confirm_stale():
            async def _f():
                from fastapi import HTTPException
                from services.deliveries import do_confirm_delivery
                try:
                    await do_confirm_delivery(
                        d_stale, {"user_id": "user_test_admin01",
                                  "name": "Admin"})
                    return 200
                except HTTPException as e:
                    return e.status_code
            return _run(_f)
        assert _confirm_stale() == 409, "la confirmación obsoleta no se aplica"
        d = _db().deliveries.find_one({"id": did}, {"_id": 0})
        assert d["status"] == "cancelled", "la cancelación ganadora se respeta"
        assert not d.get("payout_credited")
        assert _bal(COURIER_ID, "USDT") == base, "sin comisión pagada"

    def test_cancel_blocked_after_payout_claim(self):
        _cleanup()
        _mk_user(COURIER_ID, role="client", is_courier=True)
        did = _mk_delivery(status="delivered", courier_id=COURIER_ID)
        _db().deliveries.update_one(
            {"id": did}, {"$set": {"payout_credited": True}})
        r = requests.post(f"{API}/admin/deliveries/{did}/cancel",
                          headers=_hdr(ADMIN_TOKEN), json={})
        assert r.status_code == 409, r.text
        assert _db().deliveries.find_one(
            {"id": did}, {"_id": 0})["status"] == "delivered"

    def test_assign_conditional_on_state(self):
        _cleanup()
        _mk_user(COURIER_ID, role="client", is_courier=True)
        did = _mk_delivery(status="cancelled")
        r = requests.post(f"{API}/admin/deliveries/{did}/assign",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"courier_id": COURIER_ID})
        assert r.status_code == 409, r.text


# ============================================================
# ME03 — liquidación del depósito recuperable
# ============================================================

class TestME03PickupSettlement:
    def teardown_method(self, _):
        _cleanup()

    def test_failed_deposit_settlement_recovered_once(self):
        """Repro del auditor: recogida de 100, comisión 8. Falla el handler
        del depósito → la entrega queda confirmada con TAREA pendiente; el
        recuperador acredita los 100 una sola vez y la comisión queda en 8."""
        _cleanup()
        _mk_user(COURIER_ID, role="client", is_courier=True)
        _mk_user("it283_client", role="vip")
        db = _db()
        dep_id = f"dep_{uuid.uuid4().hex[:10]}"
        db.deposits.insert_one({
            "id": dep_id, "user_id": "it283_client",
            "user_name": f"{MARK} Cliente", "amount": 100.0,
            "currency": "USD", "method": "cash", "cash_mode": "courier",
            "status": "pending", "created_at": _iso()})
        did = _mk_delivery(status="delivered", courier_id=COURIER_ID,
                           share=8.0, kind="deposit")
        db.deliveries.update_one({"id": did}, {"$set": {"kind": "deposit",
                                                        "ref_id": dep_id}})
        d = db.deliveries.find_one({"id": did}, {"_id": 0})

        def _confirm_with_broken_handler():
            async def _f():
                from services import delivery_settlement as ds
                from services.deliveries import do_confirm_delivery
                import routes.deposits  # noqa: F401 — registra el handler real
                orig = ds._handlers.get("deposit")

                async def boom(ref_id, actor):
                    raise RuntimeError("db down")

                ds._handlers["deposit"] = boom
                try:
                    return await do_confirm_delivery(
                        d, {"user_id": "user_test_admin01", "name": "Admin"})
                finally:
                    if orig is not None:
                        ds._handlers["deposit"] = orig
            return _run(_f)

        _confirm_with_broken_handler()
        fresh = db.deliveries.find_one({"id": did}, {"_id": 0})
        assert fresh["status"] == "confirmed"
        assert fresh.get("settlement_pending", {}).get("ref_id") == dep_id, \
            "queda una tarea recuperable para liquidar el depósito"
        assert _bal(COURIER_ID, "USDT") == 8.0, "comisión pagada una vez"
        assert db.deposits.find_one({"id": dep_id})["status"] == "pending"
        assert _bal("it283_client", "USD") == 0.0

        def _heal():
            async def _f():
                from services.credit_recovery import heal_initializing_ops
                return await heal_initializing_ops(max_age_seconds=0)
            return _run(_f)
        _heal()
        assert db.deposits.find_one({"id": dep_id})["status"] == "confirmed"
        assert _bal("it283_client", "USD") == 100.0, \
            "los 100 se acreditan exactamente una vez"
        fresh = db.deliveries.find_one({"id": did}, {"_id": 0})
        assert "settlement_pending" not in fresh
        _heal()
        assert _bal("it283_client", "USD") == 100.0
        assert _bal(COURIER_ID, "USDT") == 8.0, "la comisión sigue en 8"


# ============================================================
# MR01 — reembolso vs crédito pendiente del vendedor
# ============================================================

def _mk_vendor_scene(with_pending_marker):
    db = _db()
    _mk_user("it283_vendor", role="vip")
    _mk_user("it283_buyer", role="vip")
    pid = f"p_{uuid.uuid4().hex[:10]}"
    db.products.insert_one({
        "id": pid, "name": f"{MARK} Producto Vendedor", "description": "t",
        "category": "test", "price_usd": 100.0, "cost_usd": 0.0, "stock": 0,
        "owner_id": "it283_vendor", "owner_name": "Vendedor",
        "is_active": True, "approval_status": "approved",
        "image_url": "", "created_at": _iso()})
    rid = f"r_{uuid.uuid4().hex[:12]}"
    op_id = f"vendor-credit:{uuid.uuid4().hex[:12]}"
    doc = {
        "id": rid, "user_id": "it283_buyer", "user_name": f"{MARK} Comprador",
        "product_id": pid, "product_name": f"{MARK} Producto Vendedor",
        "quantity": 1, "total_usd": 100.0, "cost_usd": 0.0,
        "courier_fee_usd": 0.0, "settlement_currency": "USDT",
        "vendor_owner_id": "it283_vendor", "vendor_owner_name": "Vendedor",
        "status": "delivered", "delivered_at": _iso(5), "created_at": _iso(10),
        # estado del crash: intención guardada, incremento NO aplicado
        "vendor_credited_at": _iso(5), "vendor_credit_net": 95.0,
        "vendor_commission_pct": 5.0, "vendor_credit_op_id": op_id,
    }
    if with_pending_marker:
        doc["credit_pending"] = {
            "op_id": op_id, "user_id": "it283_vendor", "code": "USDT",
            "amount": 95.0, "legacy_usd": False, "prepared": True,
            "at": _iso(5)}
    db.redemptions.insert_one(doc)
    return pid, rid


class TestMR01VendorCredit:
    def teardown_method(self, _):
        _cleanup()

    def _reject(self, rid):
        return requests.put(f"{API}/admin/redemptions/{rid}/status",
                            headers=_hdr(ADMIN_TOKEN),
                            json={"status": "rejected", "admin_note": MARK})

    def test_interrupted_vendor_credit_then_reject_no_artificial_debt(self):
        """Aceptación del auditor: interrumpir el abono del vendedor,
        rechazar y recuperar → comprador 100, vendedor 0, stock restaurado."""
        _cleanup()
        pid, rid = _mk_vendor_scene(with_pending_marker=True)
        r = self._reject(rid)
        assert r.status_code == 200, r.text
        assert _bal("it283_buyer", "USDT") == 100.0, "comprador recupera 100"
        assert _bal("it283_vendor", "USDT") == 0.0, \
            "el vendedor NO termina con deuda por dinero que nunca recibió"
        assert _db().products.find_one({"id": pid})["stock"] == 1, \
            "la unidad vuelve al stock"

        def _heal():
            async def _f():
                from services.credit_recovery import (heal_pending_credits,
                                                      heal_initializing_ops)
                await heal_pending_credits(max_age_seconds=0)
                return await heal_initializing_ops(max_age_seconds=0)
            return _run(_f)
        _heal()
        _heal()
        assert _bal("it283_buyer", "USDT") == 100.0
        assert _bal("it283_vendor", "USDT") == 0.0, \
            "sin crédito tardío ni deuda artificial tras recuperar"

    def test_lost_intent_without_evidence_skips_debt(self):
        """Estado legado (marker ya sobrescrito/perdido): sin evidencia de
        aplicación no se fuerza el débito al vendedor."""
        _cleanup()
        pid, rid = _mk_vendor_scene(with_pending_marker=False)
        r = self._reject(rid)
        assert r.status_code == 200, r.text
        assert _bal("it283_buyer", "USDT") == 100.0
        assert _bal("it283_vendor", "USDT") == 0.0, \
            "la marca sola no prueba que el dinero llegó"


# ============================================================
# MR02 — rastros de la venta de empresa recuperables
# ============================================================

def _mk_company_sale(pend_inv, pend_fund):
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
                               "at": _iso(10)}})
    return pid, rid


def _heal_traces():
    async def _f():
        from services.credit_recovery import heal_initializing_ops
        return await heal_initializing_ops(max_age_seconds=0)
    return _run(_f)


class TestMR02SaleTraces:
    def teardown_method(self, _):
        _cleanup()

    def test_missing_inventory_movement_recovered_once(self):
        _cleanup()
        pid, rid = _mk_company_sale(pend_inv=True, pend_fund=False)
        db = _db()
        _heal_traces()
        movs = list(db.inventory_movements.find(
            {"ref_id": rid, "type": "venta"}, {"_id": 0}))
        assert len(movs) == 1, "la venta de inventario se repone"
        _heal_traces()
        assert db.inventory_movements.count_documents(
            {"ref_id": rid, "type": "venta"}) == 1, "sin duplicados"
        fresh = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert "sale_trace_pending" not in fresh
        assert db.products.find_one({"id": pid})["stock"] == 1, \
            "recuperar no vuelve a descontar mercancía"

    def test_missing_fund_inflow_recovered_once(self):
        _cleanup()
        pid, rid = _mk_company_sale(pend_inv=False, pend_fund=True)
        db = _db()
        base = _bal(VIP_ID, "USDT")
        _heal_traces()
        adjs = list(db.company_fund_adjustments.find(
            {"dedupe_key": f"fund-inflow:{rid}:c0"}, {"_id": 0}))
        assert len(adjs) == 1, "la entrada al fondo se repone"
        assert adjs[0]["amount"] == 10.0
        fresh = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert fresh.get("fund_inflow_at")
        assert "sale_trace_pending" not in fresh
        _heal_traces()
        assert db.company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-inflow:{rid}:c0"}) == 1, "sin duplicados"
        assert _bal(VIP_ID, "USDT") == base, \
            "recuperar no vuelve a cobrar al cliente"

    def test_rejected_sale_never_records_late_inflow(self):
        _cleanup()
        pid, rid = _mk_company_sale(pend_inv=False, pend_fund=True)
        _db().redemptions.update_one({"id": rid},
                                     {"$set": {"status": "rejected"}})
        _heal_traces()
        assert _db().company_fund_adjustments.count_documents(
            {"dedupe_key": f"fund-inflow:{rid}:c0"}) == 0, \
            "un ciclo ya compensado no recibe capital tardío"
        fresh = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert "sale_trace_pending" not in fresh


# ============================================================
# LO01 / LO02 — lotes: cupo, cierre, visibilidad y cuenta activa
# ============================================================

def _mk_batch(tok=VIP_TOKEN):
    r = requests.post(f"{API}/vip/batches", headers=_hdr(tok),
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


class TestLO01BatchQuota:
    def teardown_method(self, _):
        _cleanup()

    def test_concurrent_uploads_never_exceed_500(self):
        _cleanup()
        bid = _mk_batch()
        _seed_items(bid, 450)
        with ThreadPoolExecutor(max_workers=2) as ex:
            rs = list(ex.map(
                lambda _: requests.post(f"{API}/vip/batches/{bid}/items",
                                        headers=_hdr(VIP_TOKEN),
                                        json=_items_payload(50)), range(2)))
        codes = sorted(r.status_code for r in rs)
        assert codes == [200, 409], \
            f"la solicitud que pierde el cupo recibe conflicto: {codes}"
        total = _db().vip_batch_items.count_documents({"batch_id": bid})
        assert total == 500, f"jamás se supera el máximo: {total}"
        # un ítem más → conflicto de cupo
        r = requests.post(f"{API}/vip/batches/{bid}/items",
                          headers=_hdr(VIP_TOKEN), json=_items_payload(1))
        assert r.status_code == 409

    def test_upload_after_close_rejected(self):
        _cleanup()
        bid = _mk_batch()
        r = requests.post(f"{API}/vip/batches/{bid}/close",
                          headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200, r.text
        r = requests.post(f"{API}/vip/batches/{bid}/items",
                          headers=_hdr(VIP_TOKEN), json=_items_payload(1))
        assert r.status_code == 409, r.text
        assert _db().vip_batch_items.count_documents({"batch_id": bid}) == 0

    def test_detail_returns_every_existing_item(self):
        """Desbordamientos históricos siguen siendo consultables completos."""
        _cleanup()
        bid = _mk_batch()
        _seed_items(bid, 550)
        r = requests.get(f"{API}/vip/batches/{bid}", headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200, r.text
        assert len(r.json()["items"]) == 550, \
            "el detalle no oculta registros existentes"


class TestLO02BlockedAccount:
    def teardown_method(self, _):
        _cleanup()

    def test_blocked_vip_cannot_write_batches(self):
        _cleanup()
        _mk_user(BLOCKVIP_ID, role="vip")
        _mk_session(BLOCKVIP_ID, BLOCKVIP_TOKEN)
        bid = _mk_batch(tok=BLOCKVIP_TOKEN)  # activo: puede crear
        _db().users.update_one({"user_id": BLOCKVIP_ID},
                               {"$set": {"account_status": "blocked"}})
        r = requests.post(f"{API}/vip/batches", headers=_hdr(BLOCKVIP_TOKEN),
                          json={"direction": "credit", "currency": "USD",
                                "note": MARK})
        assert r.status_code == 403, r.text
        r = requests.post(f"{API}/vip/batches/{bid}/items",
                          headers=_hdr(BLOCKVIP_TOKEN),
                          json=_items_payload(1))
        assert r.status_code == 403, r.text
        # la LECTURA de sus lotes se conserva (soporte)
        r = requests.get(f"{API}/vip/batches/{bid}",
                         headers=_hdr(BLOCKVIP_TOKEN))
        assert r.status_code == 200, r.text
        # bajo revisión tampoco escribe
        _db().users.update_one({"user_id": BLOCKVIP_ID},
                               {"$set": {"account_status": "under_review"}})
        r = requests.post(f"{API}/vip/batches/{bid}/items",
                          headers=_hdr(BLOCKVIP_TOKEN),
                          json=_items_payload(1))
        assert r.status_code == 403
        # reactivada → vuelve a operar
        _db().users.update_one({"user_id": BLOCKVIP_ID},
                               {"$set": {"account_status": "active"}})
        r = requests.post(f"{API}/vip/batches/{bid}/items",
                          headers=_hdr(BLOCKVIP_TOKEN),
                          json=_items_payload(1))
        assert r.status_code == 200, r.text


# ============================================================
# ME04 — chat: los mensajes nuevos siempre aparecen
# ============================================================

class TestME04ChatPagination:
    def teardown_method(self, _):
        _cleanup()

    def test_newest_message_visible_after_300_and_reads_scoped(self):
        _cleanup()
        db = _db()
        did = f"{MARK}chat_{uuid.uuid4().hex[:8]}"
        db.deliveries.insert_one({
            "id": did, "kind": "withdrawal", "ref_id": "wx",
            "user_id": VIP_ID, "client_name": f"{MARK} Cliente",
            "courier_id": COURIER_ID, "courier_name": "Mensajero",
            "status": "accepted", "created_at": _iso(), "timeline": []})
        base_t = datetime.now(timezone.utc) - timedelta(hours=2)
        msgs = [{"id": f"dmsg_{i:04d}_{did[-4:]}", "delivery_id": did,
                 "sender_id": COURIER_ID, "sender_name": "Mensajero",
                 "sender_kind": "courier", "text": f"m{i}",
                 "read_by": [COURIER_ID],
                 "created_at": (base_t + timedelta(seconds=i)).isoformat()}
                for i in range(301)]
        db.delivery_chat.insert_many(msgs)
        newest_id = msgs[-1]["id"]
        oldest_id = msgs[0]["id"]

        r = requests.get(f"{API}/deliveries/{did}/chat",
                         headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        returned = body["messages"]
        assert len(returned) == 300
        assert returned[-1]["id"] == newest_id, \
            "el mensaje 301 (el más nuevo) SÍ aparece"
        ids = {m["id"] for m in returned}
        assert oldest_id not in ids, "el más viejo queda para la página anterior"
        assert body["has_more"] is True

        # solo lo devuelto se marca leído
        newest = db.delivery_chat.find_one({"id": newest_id}, {"_id": 0})
        assert VIP_ID in newest["read_by"]
        oldest = db.delivery_chat.find_one({"id": oldest_id}, {"_id": 0})
        assert VIP_ID not in oldest["read_by"], \
            "un mensaje no entregado no se considera leído"

        # página anterior por cursor, sin duplicados
        r2 = requests.get(f"{API}/deliveries/{did}/chat",
                          headers=_hdr(VIP_TOKEN),
                          params={"before": returned[0]["created_at"]})
        assert r2.status_code == 200, r2.text
        older = r2.json()["messages"]
        assert [m["id"] for m in older] == [oldest_id]
        assert r2.json()["has_more"] is False
        assert not ids.intersection({m["id"] for m in older})
