"""iter299 — Auditoría de Depósitos y Retiros (informe 8a23c0b): DR01–DR09.

DR01 Precisión por activo en depósitos (cripto 8 dec, fiat 2) + rechazo
     explícito de exceso de precisión y de importes que normalizan a cero.
DR02 Reserva durable de la evidencia cripto: el mismo pago on-chain nunca
     respalda dos acreditaciones.
DR03 La cancelación del cliente aplica las mismas guardas monetarias que el
     rechazo administrativo (tarifa en vuelo, reactivación, abono pendiente).
DR04 Cierres de recuperación con burn_or_undo_debit: un ejecutor atrasado
     jamás consume saldo nuevo con un débito ya abortado.
DR05 Ninguna transición avanza con redebit_pending en vuelo (ruta admin y
     sincronización desde entregas).
DR06 Alcance de monedas del empleado en listar/contar/confirmar/rechazar
     depósitos.
DR07 El proxy de archivos reconoce el comprobante de un depósito propio.
DR09 Decisión durable compartida entre cancelación del retiro y entrega
     física: gana exactamente una operación.
(DR08 es un cambio de frontend — verificado por revisión de UI.)
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN, make_admin_totp

API = f"{BASE_URL}/api"
MARK = "iter299"

CLIA_ID = "user_test_cli299a"
CLIA_TOKEN = f"test_session_{uuid.uuid4().hex}"
CLIB_ID = "user_test_cli299b"
CLIB_TOKEN = f"test_session_{uuid.uuid4().hex}"
COURIER_ID = "user_test_cou299"
COURIER_TOKEN = f"test_session_{uuid.uuid4().hex}"
EMP_EUR_ID = "user_test_emp299eur"
EMP_EUR_TOKEN = f"test_session_{uuid.uuid4().hex}"

CRYPTO_CODE = "TB8"   # moneda cripto de prueba (8 decimales)
FIAT_CODE = "TF2"     # moneda fiat de prueba (2 decimales)


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro_fn):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro_fn())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _now():
    return datetime.now(timezone.utc).isoformat()


def _old(minutes=15):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _bal(uid, code):
    u = _db().users.find_one({"user_id": uid},
                             {"vip_balances": 1, "vip_balance_usd": 1}) or {}
    total = float((u.get("vip_balances") or {}).get(code) or 0.0)
    if code == "USD":
        # el saldo USD de la plataforma = vip_balances.USD + campo legacy
        total += float(u.get("vip_balance_usd") or 0.0)
    return total


def _set_bal(uid, code, amount):
    sets = {f"vip_balances.{code}": float(amount)}
    if code == "USD":
        sets["vip_balance_usd"] = 0.0
    _db().users.update_one({"user_id": uid}, {"$set": sets})


def setup_module():
    db = _db()
    for uid, tok, extra in (
        (CLIA_ID, CLIA_TOKEN, {"role": "vip"}),
        (CLIB_ID, CLIB_TOKEN, {"role": "vip"}),
        (COURIER_ID, COURIER_TOKEN, {"role": "vip", "is_courier": True}),
        (EMP_EUR_ID, EMP_EUR_TOKEN, {"role": "employee",
                                     "allowed_permissions": ["withdrawals"],
                                     "allowed_currencies": ["EUR"],
                                     "totp_enabled": True}),
    ):
        db.users.update_one(
            {"user_id": uid},
            {"$set": {"user_id": uid, "email": f"{uid}@test.com", "name": uid,
                      "vip_balances": {}, "applied_credit_ops": [], **extra}},
            upsert=True)
        db.user_sessions.update_one(
            {"session_token": tok},
            {"$set": {"session_token": tok, "user_id": uid,
                      "expires_at": "2099-01-01T00:00:00+00:00"}},
            upsert=True)
    for code, ctype in ((CRYPTO_CODE, "crypto"), (FIAT_CODE, "fiat")):
        db.currencies.update_one(
            {"code": code},
            {"$set": {"code": code, "name": f"Test {code}", "type": ctype,
                      "is_active": True,
                      "delivery_methods": ["crypto"] if ctype == "crypto"
                      else ["cash"]}},
            upsert=True)
    _cleanup_data()


def teardown_module():
    db = _db()
    db.users.delete_many({"user_id": {"$in": [CLIA_ID, CLIB_ID, COURIER_ID,
                                              EMP_EUR_ID]}})
    db.user_sessions.delete_many({"session_token": {
        "$in": [CLIA_TOKEN, CLIB_TOKEN, COURIER_TOKEN, EMP_EUR_TOKEN]}})
    db.currencies.delete_many({"code": {"$in": [CRYPTO_CODE, FIAT_CODE]}})
    _cleanup_data()


def _cleanup_data():
    db = _db()
    db.withdrawals.delete_many({"id": {"$regex": f"^wd_{MARK}"}})
    db.deposits.delete_many({"id": {"$regex": f"^dep_{MARK}"}})
    db.deposits.delete_many({"user_id": {"$in": [CLIA_ID, CLIB_ID]}})
    db.deliveries.delete_many({"id": {"$regex": f"^dv_{MARK}"}})
    db.crypto_evidence_claims.delete_many({"tx_hash": {"$regex": MARK}})
    db.credit_ops.delete_many({"op_id": {"$regex": MARK}})


def _mk_withdrawal(wid, user_id=CLIA_ID, amount=100.0, currency="USD",
                   method="cash", status="pending", **extra):
    doc = {
        "id": wid, "user_id": user_id, "user_email": f"{user_id}@test.com",
        "user_name": user_id, "amount_usd": float(amount),
        "currency": currency, "method": method, "details": "detalle prueba",
        "status": status, "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().withdrawals.insert_one(dict(doc))
    return doc


def _mk_delivery(dvid, wid, status="arrived", courier=COURIER_ID, **extra):
    doc = {
        "id": dvid, "kind": "withdrawal", "ref_id": wid, "status": status,
        "courier_id": courier, "courier_name": courier,
        "user_id": CLIA_ID, "client_name": "Cliente Prueba",
        "amount_label": "100 USD", "timeline": [],
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().deliveries.insert_one(dict(doc))
    return doc


def _mk_deposit(dep_id, user_id=CLIA_ID, amount=100.0, currency="USD",
                method="cash", status="pending", **extra):
    doc = {
        "id": dep_id, "user_id": user_id, "user_email": f"{user_id}@test.com",
        "user_name": user_id, "user_role": "vip", "currency": currency,
        "amount": float(amount), "method": method, "cash_mode": None,
        "network": None, "usdt_equivalent": None, "account_holder": None,
        "tx_hash": None, "proof_url": None, "note": None, "status": status,
        "admin_note": None, "reviewed_at": None, "reviewed_by": None,
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().deposits.insert_one(dict(doc))
    return doc


# ---------------------------------------------------------------------------
# DR01 — precisión por activo en depósitos
# ---------------------------------------------------------------------------
class TestDR01Precision:
    def _post(self, token, body):
        return requests.post(f"{API}/deposits", headers=_h(token), json=body)

    def test_crypto_amount_keeps_8_decimals(self):
        r = self._post(CLIA_TOKEN, {"currency": CRYPTO_CODE, "amount": 0.006,
                                    "method": "crypto",
                                    "tx_hash": f"{MARK}hash_prec_ok_1"})
        assert r.status_code == 200, r.text
        assert r.json()["amount"] == 0.006, "0.006 no debe redondearse a 0.01"

    def test_crypto_minimum_unit_accepted(self):
        r = self._post(CLIA_TOKEN, {"currency": CRYPTO_CODE,
                                    "amount": 0.00000001, "method": "crypto",
                                    "tx_hash": f"{MARK}hash_prec_ok_2"})
        assert r.status_code == 200, r.text
        assert r.json()["amount"] == 0.00000001

    def test_crypto_below_precision_rejected(self):
        r = self._post(CLIA_TOKEN, {"currency": CRYPTO_CODE,
                                    "amount": 0.000000001, "method": "crypto",
                                    "tx_hash": f"{MARK}hash_prec_bad_1"})
        assert r.status_code == 422, r.text
        assert "precisión" in r.json()["detail"]

    def test_fiat_below_precision_rejected(self):
        r = self._post(CLIA_TOKEN, {"currency": FIAT_CODE, "amount": 0.004,
                                    "method": "cash"})
        assert r.status_code == 422, r.text

    def test_fiat_excess_precision_rejected_explicitly(self):
        r = self._post(CLIA_TOKEN, {"currency": FIAT_CODE, "amount": 10.555,
                                    "method": "cash"})
        assert r.status_code == 422, r.text
        assert "decimales" in r.json()["detail"]

    def test_confirm_refuses_zero_amount(self):
        dep = _mk_deposit(f"dep_{MARK}_zero", amount=0.0)
        r = requests.post(f"{API}/admin/deposits/{dep['id']}/confirm",
                          headers=_h(ADMIN))
        assert r.status_code == 409, r.text
        assert _db().deposits.find_one({"id": dep["id"]})["status"] == "pending"


# ---------------------------------------------------------------------------
# DR02 — la misma evidencia on-chain no respalda dos acreditaciones
# ---------------------------------------------------------------------------
class TestDR02EvidenceClaim:
    def test_same_hash_same_amount_credits_once(self):
        h = f"{MARK}hash_dup_a"
        d1 = _mk_deposit(f"dep_{MARK}_ev1", user_id=CLIA_ID, amount=50.0,
                         currency=CRYPTO_CODE, method="crypto", tx_hash=h)
        d2 = _mk_deposit(f"dep_{MARK}_ev2", user_id=CLIB_ID, amount=50.0,
                         currency=CRYPTO_CODE, method="crypto", tx_hash=h)
        _set_bal(CLIA_ID, CRYPTO_CODE, 0)
        _set_bal(CLIB_ID, CRYPTO_CODE, 0)
        r1 = requests.post(f"{API}/admin/deposits/{d1['id']}/confirm",
                           headers=_h(ADMIN))
        assert r1.status_code == 200, r1.text
        r2 = requests.post(f"{API}/admin/deposits/{d2['id']}/confirm",
                           headers=_h(ADMIN))
        assert r2.status_code == 409, r2.text
        assert d1["id"][:16] in r2.json()["detail"]
        assert _bal(CLIA_ID, CRYPTO_CODE) == 50.0
        assert _bal(CLIB_ID, CRYPTO_CODE) == 0.0, "jamás doble acreditación"
        assert _db().deposits.find_one({"id": d2["id"]})["status"] == "pending"

    def test_distinct_transfers_in_same_tx_allowed(self):
        """Dos transferencias reales de una misma transacción (importes
        distintos) sí pueden acreditarse por separado."""
        h = f"{MARK}hash_multi_b"
        d1 = _mk_deposit(f"dep_{MARK}_ev3", user_id=CLIA_ID, amount=10.0,
                         currency=CRYPTO_CODE, method="crypto", tx_hash=h)
        d2 = _mk_deposit(f"dep_{MARK}_ev4", user_id=CLIB_ID, amount=20.0,
                         currency=CRYPTO_CODE, method="crypto", tx_hash=h)
        for d in (d1, d2):
            r = requests.post(f"{API}/admin/deposits/{d['id']}/confirm",
                              headers=_h(ADMIN))
            assert r.status_code == 200, r.text

    def test_confirm_retry_is_idempotent(self):
        h = f"{MARK}hash_retry_c"
        d1 = _mk_deposit(f"dep_{MARK}_ev5", user_id=CLIA_ID, amount=5.0,
                         currency=CRYPTO_CODE, method="crypto", tx_hash=h)
        r1 = requests.post(f"{API}/admin/deposits/{d1['id']}/confirm",
                           headers=_h(ADMIN))
        assert r1.status_code == 200, r1.text
        r2 = requests.post(f"{API}/admin/deposits/{d1['id']}/confirm",
                           headers=_h(ADMIN))
        assert r2.status_code == 409  # ya procesado, sin doble abono

    def test_listing_flags_reused_evidence(self):
        h = f"{MARK}hash_flag_d"
        d1 = _mk_deposit(f"dep_{MARK}_ev6", user_id=CLIA_ID, amount=7.0,
                         currency=CRYPTO_CODE, method="crypto", tx_hash=h)
        d2 = _mk_deposit(f"dep_{MARK}_ev7", user_id=CLIB_ID, amount=7.0,
                         currency=CRYPTO_CODE, method="crypto", tx_hash=h)
        requests.post(f"{API}/admin/deposits/{d1['id']}/confirm",
                      headers=_h(ADMIN))
        r = requests.get(f"{API}/admin/deposits", headers=_h(ADMIN),
                         params={"status": "pending"})
        row = next(x for x in r.json()["items"] if x["id"] == d2["id"])
        assert row.get("evidence_already_used_by") == d1["id"]


# ---------------------------------------------------------------------------
# DR03 — guardas monetarias en la cancelación del cliente
# ---------------------------------------------------------------------------
class TestDR03CancelGuards:
    def _cancel(self, wid, token=CLIA_TOKEN):
        return requests.post(f"{API}/vip/withdrawals/{wid}/cancel",
                             headers=_h(token))

    def test_normal_cancel_refunds_exactly_once(self):
        wid = f"wd_{MARK}_c1"
        _mk_withdrawal(wid, amount=100.0, courier_fee_currency_amount=30.0)
        _set_bal(CLIA_ID, "USD", 0)
        r = self._cancel(wid)
        assert r.status_code == 200, r.text
        assert _bal(CLIA_ID, "USD") == 130.0
        r2 = self._cancel(wid)
        assert r2.status_code == 409
        assert _bal(CLIA_ID, "USD") == 130.0, "el reembolso es único"

    def test_cancel_blocked_with_fee_charge_in_flight(self):
        """Reproducción del informe: cobro de tarifa EN VUELO (plan
        publicado, débito sin demostrar) — cancelar devolvería 130 de una
        reserva de 100."""
        wid = f"wd_{MARK}_c2"
        _mk_withdrawal(wid, amount=100.0, courier_fee_currency_amount=30.0,
                       courier_fee_op_pending={"op_id": f"courier-fee:{wid}:x",
                                               "delta": 30.0,
                                               "currency": "USD",
                                               "at": _now()})
        _set_bal(CLIA_ID, "USD", 0)
        r = self._cancel(wid)
        assert r.status_code == 409, r.text
        assert _bal(CLIA_ID, "USD") == 0.0, "nada se reembolsa con cobro en vuelo"
        assert _db().withdrawals.find_one({"id": wid})["status"] == "pending"

    def test_cancel_blocked_with_redebit_in_flight(self):
        wid = f"wd_{MARK}_c3"
        _mk_withdrawal(wid, amount=100.0,
                       redebit_pending={"op_id": f"withdrawal-redebit:{wid}:x",
                                        "amount": 100.0, "currency": "USD",
                                        "at": _now()})
        _set_bal(CLIA_ID, "USD", 0)
        r = self._cancel(wid)
        assert r.status_code == 409, r.text
        assert _bal(CLIA_ID, "USD") == 0.0


# ---------------------------------------------------------------------------
# DR09 — cancelación vs entrega física: gana exactamente una
# ---------------------------------------------------------------------------
class TestDR09CancelVsDelivery:
    def _cancel(self, wid):
        return requests.post(f"{API}/vip/withdrawals/{wid}/cancel",
                             headers=_h(CLIA_TOKEN))

    def test_cancel_blocked_after_delivery_sealed(self):
        wid = f"wd_{MARK}_d1"
        _mk_withdrawal(wid, amount=100.0)
        _mk_delivery(f"dv_{MARK}_d1", wid, status="delivered")
        _set_bal(CLIA_ID, "USD", 0)
        r = self._cancel(wid)
        assert r.status_code == 409, r.text
        assert "entreg" in r.json()["detail"].lower()
        assert _bal(CLIA_ID, "USD") == 0.0, "sin reembolso con entrega sellada"

    def test_courier_cannot_seal_with_cancel_intent(self):
        wid = f"wd_{MARK}_d2"
        _mk_withdrawal(wid, amount=100.0)
        dv = _mk_delivery(f"dv_{MARK}_d2", wid, status="arrived",
                          origin_cancel_intent={"at": _now(), "by": CLIA_ID})
        r = requests.post(f"{API}/courier/deliveries/{dv['id']}/status",
                          headers=_h(COURIER_TOKEN),
                          json={"status": "delivered"})
        assert r.status_code == 409, r.text
        assert "cancelando" in r.json()["detail"].lower()
        assert _db().deliveries.find_one({"id": dv["id"]})["status"] == "arrived"

    def test_courier_seals_normally_without_intent(self):
        wid = f"wd_{MARK}_d3"
        _mk_withdrawal(wid, amount=100.0)
        dv = _mk_delivery(f"dv_{MARK}_d3", wid, status="arrived")
        r = requests.post(f"{API}/courier/deliveries/{dv['id']}/status",
                          headers=_h(COURIER_TOKEN),
                          json={"status": "delivered"})
        assert r.status_code == 200, r.text
        assert _db().deliveries.find_one({"id": dv["id"]})["status"] == "delivered"
        # y a partir de aquí la cancelación queda bloqueada sin reembolso
        _set_bal(CLIA_ID, "USD", 0)
        r2 = self._cancel(wid)
        assert r2.status_code == 409
        assert _bal(CLIA_ID, "USD") == 0.0

    def test_successful_cancel_marks_intent_and_kills_delivery(self):
        wid = f"wd_{MARK}_d4"
        _mk_withdrawal(wid, amount=100.0)
        dv = _mk_delivery(f"dv_{MARK}_d4", wid, status="accepted")
        _set_bal(CLIA_ID, "USD", 0)
        r = self._cancel(wid)
        assert r.status_code == 200, r.text
        assert _bal(CLIA_ID, "USD") == 100.0
        fresh = _db().deliveries.find_one({"id": dv["id"]})
        # la entrega quedó cancelada (o con la intención sellada): el
        # mensajero ya no puede sellar 'delivered'.
        assert fresh["status"] == "cancelled" or fresh.get("origin_cancel_intent")
        r2 = requests.post(f"{API}/courier/deliveries/{dv['id']}/status",
                           headers=_h(COURIER_TOKEN),
                           json={"status": "delivered"})
        assert r2.status_code in (400, 409)


# ---------------------------------------------------------------------------
# DR04 — débitos tardíos bloqueados de forma durable (burn-or-undo)
# ---------------------------------------------------------------------------
class TestDR04LateDebits:
    def test_healer_burns_unapplied_creation_debit(self):
        """Variante 1 del informe: el healer aborta un retiro a medio crear
        cuyo débito NUNCA se aplicó — el creador atrasado ya no puede cobrar,
        ni siquiera cuando el cliente recibe saldo nuevo."""
        wid = f"wd_{MARK}_h1_{uuid.uuid4().hex[:6]}"
        op = f"withdraw-debit:{wid}"
        _mk_withdrawal(wid, amount=50.0, status="initializing",
                       init_op_id=op, created_at=_old(15))

        async def flow():
            from services.credit_recovery import heal_initializing_ops
            from services.balances import debit_balance_idempotent
            await heal_initializing_ops()
            # llega saldo nuevo y el creador atrasado intenta su débito:
            _set_bal(CLIA_ID, "USD", 100.0)
            return await debit_balance_idempotent(CLIA_ID, "USD", 50.0, op)
        st = _run(flow)
        assert _db().withdrawals.find_one({"id": wid})["status"] == "failed_init"
        assert st == "duplicate", f"el débito quemado no debe aplicarse: {st}"
        assert _bal(CLIA_ID, "USD") == 100.0, "el saldo nuevo queda intacto"

    def test_healer_undoes_applied_creation_debit(self):
        wid = f"wd_{MARK}_h2_{uuid.uuid4().hex[:6]}"
        op = f"withdraw-debit:{wid}"
        _set_bal(CLIA_ID, "USD", 100.0)

        async def flow():
            from services.balances import debit_balance_idempotent
            from services.credit_recovery import heal_initializing_ops
            st = await debit_balance_idempotent(CLIA_ID, "USD", 40.0, op)
            _mk_withdrawal(wid, amount=40.0, status="initializing",
                           init_op_id=op, created_at=_old(15))
            await heal_initializing_ops()
            return st
        assert _run(flow) == "applied"
        assert _bal(CLIA_ID, "USD") == 100.0, "el débito aplicado se compensa"

    def test_healer_burns_unapplied_redebit(self):
        """Variante 2 del informe: reactivación con re-débito pendiente e
        insuficiente — tras rechazarla, un ejecutor atrasado no puede cobrar
        el re-débito cuando llega un depósito nuevo."""
        wid = f"wd_{MARK}_h3_{uuid.uuid4().hex[:6]}"
        op = f"withdrawal-redebit:{wid}:{uuid.uuid4().hex[:8]}"
        _set_bal(CLIA_ID, "USD", 0.0)
        _mk_withdrawal(wid, amount=80.0, status="approved",
                       balance_refunded=False,
                       redebit_pending={"op_id": op, "amount": 80.0,
                                        "currency": "USD", "at": _old(15)})

        async def flow():
            from services.credit_recovery import heal_initializing_ops
            from services.balances import debit_balance_idempotent
            await heal_initializing_ops()
            # depósito nuevo + ejecutor atrasado:
            _set_bal(CLIA_ID, "USD", 200.0)
            return await debit_balance_idempotent(CLIA_ID, "USD", 80.0, op)
        st = _run(flow)
        fresh = _db().withdrawals.find_one({"id": wid})
        assert fresh["status"] == "rejected"
        assert fresh.get("balance_refunded") is True
        assert "redebit_pending" not in fresh
        assert st == "duplicate", f"re-débito quemado no debe aplicarse: {st}"
        assert _bal(CLIA_ID, "USD") == 200.0


# ---------------------------------------------------------------------------
# DR05 — ninguna transición avanza con re-débito en vuelo
# ---------------------------------------------------------------------------
class TestDR05RedebitBlocksTransitions:
    def test_paid_blocked_while_redebit_pending(self):
        wid = f"wd_{MARK}_p1"
        _mk_withdrawal(wid, amount=60.0, method="crypto", status="approved",
                       redebit_pending={"op_id": f"withdrawal-redebit:{wid}:x",
                                        "amount": 60.0, "currency": "USD",
                                        "at": _now()})
        r = requests.put(f"{API}/admin/withdrawals/{wid}/status",
                         headers=_h(ADMIN),
                         json={"status": "paid",
                               "payout_tx_hash": "0xabc123def456789",
                               "totp_code": make_admin_totp()})
        assert r.status_code == 409, r.text
        assert "reactivaci" in r.json()["detail"].lower()
        assert _db().withdrawals.find_one({"id": wid})["status"] == "approved"

    def test_delivery_sync_postponed_while_redebit_pending(self):
        wid = f"wd_{MARK}_p2"
        _mk_withdrawal(wid, amount=60.0, method="cash", status="approved",
                       redebit_pending={"op_id": f"withdrawal-redebit:{wid}:y",
                                        "amount": 60.0, "currency": "USD",
                                        "at": _now()})

        async def flow():
            from routes.admin_withdrawals import mark_paid_from_delivery
            return await mark_paid_from_delivery(
                wid, {"user_id": "sys", "name": "Sistema", "role": "admin"})
        assert _run(flow) is None
        assert _db().withdrawals.find_one({"id": wid})["status"] == "approved"


# ---------------------------------------------------------------------------
# DR06 — alcance de monedas del empleado en depósitos
# ---------------------------------------------------------------------------
class TestDR06DepositScope:
    def test_listing_and_counters_scoped(self):
        usd = _mk_deposit(f"dep_{MARK}_s1", currency="USD", amount=10.0)
        _mk_deposit(f"dep_{MARK}_s2", currency="EUR", amount=10.0)
        r = requests.get(f"{API}/admin/deposits", headers=_h(EMP_EUR_TOKEN))
        assert r.status_code == 200, r.text
        curs = {d["currency"] for d in r.json()["items"]}
        assert "USD" not in curs
        assert all(d["currency"] == "EUR" or d["currency"] in ("EUR",)
                   for d in r.json()["items"])
        # contador pending también con alcance
        usd_visible = [d for d in r.json()["items"] if d["id"] == usd["id"]]
        assert not usd_visible
        hub = requests.get(f"{API}/admin/deposits-hub/pending-count",
                           headers=_h(EMP_EUR_TOKEN)).json()
        admin_hub = requests.get(f"{API}/admin/deposits-hub/pending-count",
                                 headers=_h(ADMIN)).json()
        assert hub["deposits_pending"] <= admin_hub["deposits_pending"]

    def test_confirm_and_reject_scoped(self):
        usd = _mk_deposit(f"dep_{MARK}_s3", currency="USD", amount=10.0)
        r1 = requests.post(f"{API}/admin/deposits/{usd['id']}/confirm",
                           headers=_h(EMP_EUR_TOKEN))
        assert r1.status_code == 403, r1.text
        r2 = requests.post(f"{API}/admin/deposits/{usd['id']}/reject",
                           headers=_h(EMP_EUR_TOKEN), json={"admin_note": "x"})
        assert r2.status_code == 403, r2.text
        assert _db().deposits.find_one({"id": usd["id"]})["status"] == "pending"


# ---------------------------------------------------------------------------
# DR07 — comprobante de depósito propio visible por su dueño
# ---------------------------------------------------------------------------
class TestDR07DepositProofAccess:
    KEY = f"deposits/{MARK}/proof_x.png"

    def test_owner_authorized_stranger_forbidden(self):
        _mk_deposit(f"dep_{MARK}_f1", user_id=CLIA_ID,
                    proof_url=f"/api/files/{self.KEY}")
        r_owner = requests.get(f"{API}/files/{self.KEY}", headers=_h(CLIA_TOKEN))
        # autorizado (404 = objeto no existe en storage, pero pasó el permiso)
        assert r_owner.status_code in (200, 404), r_owner.text
        r_other = requests.get(f"{API}/files/{self.KEY}", headers=_h(CLIB_TOKEN))
        assert r_other.status_code == 403, r_other.text
