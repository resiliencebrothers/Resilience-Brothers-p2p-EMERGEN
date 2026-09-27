"""iter301 — Verificación de Depósitos y Retiros (informe 502a4a3):
4 hallazgos parciales DR01, DR02, DR04 y DR09 + regla DE01.

DR09(A) La intención de cancelación es EXCLUSIVA por intento (token): una
        cancelación perdedora jamás limpia la intención de la ganadora ni
        hereda una activa; una huérfana (vieja) sí se retoma.
DR09(B) El rechazo administrativo usa el mismo protocolo: con la entrega ya
        sellada (delivered/confirmed) NO hay reembolso automático (409).
DR02    La identidad de la evidencia cripto es red+hash+activo (sin el
        importe declarado); un histórico confirmado sin reserva bloquea el
        hash; otra transferencia real exige un ID de movimiento explícito.
DR04    El cierre de insuficiencia del recuperador queda condicionado al
        plan (op_id): jamás sobrescribe una reactivación posterior.
DE01    Regla de plataforma: depósito y retiro mínimo en cripto = 1 USDT
        (o su equivalente al cambio vigente).
(DR01 presentación: formatAmount en frontend — verificado por UI.)
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from conftest import (BASE_URL, ADMIN_TOKEN as ADMIN, make_admin_totp,
                      VIP_TOKEN, make_vip_totp)

API = f"{BASE_URL}/api"
MARK = "iter301"

CLIA_ID = "user_test_cli301a"
CLIA_TOKEN = f"test_session_{uuid.uuid4().hex}"
COURIER_ID = "user_test_cou301"
COURIER_TOKEN = f"test_session_{uuid.uuid4().hex}"
VIP01_ID = "user_test_vip01"  # dueño de VIP_TOKEN (conftest)

CRYPTO_NR = "TQ9"   # cripto SIN tasa configurada
CRYPTO_RT = "TR9"   # cripto CON tasa a USDT (1 TR9 = 0.5 USDT)
FIAT_CODE = "TG9"   # fiat de prueba
TRC20_ADDR = "TJRabRWQdrJc7iCPFy4gnPCJcXbc17ncCk"


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
        (COURIER_ID, COURIER_TOKEN, {"role": "vip", "is_courier": True}),
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
    for code, ctype in ((CRYPTO_NR, "crypto"), (CRYPTO_RT, "crypto"),
                        (FIAT_CODE, "fiat")):
        db.currencies.update_one(
            {"code": code},
            {"$set": {"code": code, "name": f"Test {code}", "type": ctype,
                      "is_active": True,
                      "delivery_methods": ["crypto"] if ctype == "crypto"
                      else ["cash"]}},
            upsert=True)
    db.rates.update_one(
        {"from_code": CRYPTO_RT, "to_code": "USDT"},
        {"$set": {"from_code": CRYPTO_RT, "to_code": "USDT",
                  "rate_normal": 0.5, "rate_vip": 0.5, "real_rate": 0.5}},
        upsert=True)
    _cleanup_data()


def teardown_module():
    db = _db()
    db.users.delete_many({"user_id": {"$in": [CLIA_ID, COURIER_ID]}})
    db.user_sessions.delete_many({"session_token": {
        "$in": [CLIA_TOKEN, COURIER_TOKEN]}})
    db.currencies.delete_many({"code": {"$in": [CRYPTO_NR, CRYPTO_RT,
                                                FIAT_CODE]}})
    db.rates.delete_many({"from_code": CRYPTO_RT})
    db.users.update_one({"user_id": VIP01_ID},
                        {"$unset": {f"vip_balances.{CRYPTO_RT}": ""}})
    _cleanup_data()


def _cleanup_data():
    db = _db()
    db.withdrawals.delete_many({"id": {"$regex": f"^wd_{MARK}"}})
    db.withdrawals.delete_many({"currency": {"$in": [CRYPTO_RT, CRYPTO_NR]}})
    db.deposits.delete_many({"id": {"$regex": f"^dep_{MARK}"}})
    db.deposits.delete_many({"user_id": {"$in": [CLIA_ID]}})
    db.deposits.delete_many({"tx_hash": {"$regex": MARK}})
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


def _mk_deposit(dep_id, user_id=CLIA_ID, amount=100.0, currency=CRYPTO_NR,
                method="crypto", status="pending", **extra):
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


def _confirm(dep_id, body=None):
    return requests.post(f"{API}/admin/deposits/{dep_id}/confirm",
                         headers=_h(ADMIN), json=body or {})


def _cancel(wid, token=CLIA_TOKEN):
    return requests.post(f"{API}/vip/withdrawals/{wid}/cancel",
                         headers=_h(token))


def _admin_status(wid, status, **extra):
    return requests.put(f"{API}/admin/withdrawals/{wid}/status",
                        headers=_h(ADMIN),
                        json={"status": status,
                              "totp_code": make_admin_totp(), **extra})


# ---------------------------------------------------------------------------
# DR09(A) — intención de cancelación exclusiva por intento (token)
# ---------------------------------------------------------------------------
class TestDR09AIntentToken:
    def test_second_cancel_does_not_inherit_or_clear_active_intent(self):
        """Reproducción cancel_intent_ownership (pasos 2-4): la segunda
        cancelación encuentra la intención ACTIVA de la primera — recibe 409
        sin heredarla NI limpiarla (la protección del sello sigue viva)."""
        wid = f"wd_{MARK}_a1"
        _mk_withdrawal(wid)
        dv = _mk_delivery(f"dv_{MARK}_a1", wid, status="arrived",
                          origin_cancel_intent={"at": _now(), "by": CLIA_ID,
                                                "token": "tokWIN"})
        _set_bal(CLIA_ID, "USD", 0)
        r = _cancel(wid)
        assert r.status_code == 409, r.text
        fresh = _db().deliveries.find_one({"id": dv["id"]})
        assert (fresh.get("origin_cancel_intent") or {}).get("token") == "tokWIN", \
            "la intención del intento activo debe permanecer intacta"
        assert _db().withdrawals.find_one({"id": wid})["status"] == "pending"
        assert _bal(CLIA_ID, "USD") == 0.0
        # con la intención intacta, el sello del mensajero sigue bloqueado
        r2 = requests.post(f"{API}/courier/deliveries/{dv['id']}/status",
                           headers=_h(COURIER_TOKEN),
                           json={"status": "delivered"})
        assert r2.status_code == 409, r2.text
        assert _db().deliveries.find_one({"id": dv["id"]})["status"] == "arrived"

    def test_stale_orphan_intent_is_taken_over(self):
        """Una intención huérfana (intento interrumpido hace >120s) no deja
        el retiro atascado: la nueva cancelación la retoma y completa."""
        wid = f"wd_{MARK}_a2"
        _mk_withdrawal(wid)
        _mk_delivery(f"dv_{MARK}_a2", wid, status="accepted",
                     origin_cancel_intent={"at": _old(10), "by": CLIA_ID,
                                           "token": "tokOLD"})
        _set_bal(CLIA_ID, "USD", 0)
        r = _cancel(wid)
        assert r.status_code == 200, r.text
        assert _bal(CLIA_ID, "USD") == 100.0
        assert _db().withdrawals.find_one({"id": wid})["status"] == "cancelled"
        assert _db().deliveries.find_one(
            {"id": f"dv_{MARK}_a2"})["status"] == "cancelled"

    def test_losing_cancel_releases_only_own_token(self):
        """La cancelación que pierde el claim del retiro libera SOLO su
        propia intención (token) — nunca deja residuos ni toca ajenas."""
        wid = f"wd_{MARK}_a3"
        # redebit en vuelo → el claim de la cancelación pierde (DR03)
        _mk_withdrawal(wid, redebit_pending={
            "op_id": f"withdrawal-redebit:{wid}:x", "amount": 100.0,
            "currency": "USD", "at": _now()})
        dv = _mk_delivery(f"dv_{MARK}_a3", wid, status="arrived")
        _set_bal(CLIA_ID, "USD", 0)
        r = _cancel(wid)
        assert r.status_code == 409, r.text
        fresh = _db().deliveries.find_one({"id": dv["id"]})
        assert "origin_cancel_intent" not in fresh, \
            "la intención del intento perdedor debe liberarse (token propio)"
        assert _bal(CLIA_ID, "USD") == 0.0


# ---------------------------------------------------------------------------
# DR09(B) — el rechazo administrativo respeta la entrega sellada
# ---------------------------------------------------------------------------
class TestDR09BAdminReject:
    def test_admin_reject_blocked_after_sealed_delivery(self):
        """Reproducción admin_reject_after_delivery: con la entrega sellada
        (PIN verificado) el rechazo YA NO reembolsa — 409 explícito."""
        wid = f"wd_{MARK}_b1"
        _mk_withdrawal(wid)
        _mk_delivery(f"dv_{MARK}_b1", wid, status="delivered",
                     pin_verified=True)
        _set_bal(CLIA_ID, "USD", 0)
        r = _admin_status(wid, "rejected", admin_note="prueba iter301")
        assert r.status_code == 409, r.text
        assert "sellada" in r.json()["detail"] or "entregó" in r.json()["detail"]
        fresh = _db().withdrawals.find_one({"id": wid})
        assert fresh["status"] == "pending"
        assert fresh.get("balance_refunded") is not True
        assert _bal(CLIA_ID, "USD") == 0.0, "jamás reembolso con entrega sellada"

    def test_admin_reject_with_active_delivery_refunds_and_cancels(self):
        wid = f"wd_{MARK}_b2"
        _mk_withdrawal(wid)
        dv = _mk_delivery(f"dv_{MARK}_b2", wid, status="arrived")
        _set_bal(CLIA_ID, "USD", 0)
        r = _admin_status(wid, "rejected", admin_note="prueba iter301")
        assert r.status_code == 200, r.text
        assert _bal(CLIA_ID, "USD") == 100.0
        assert _db().withdrawals.find_one({"id": wid})["status"] == "rejected"
        assert _db().deliveries.find_one({"id": dv["id"]})["status"] == "cancelled"

    def test_admin_reject_blocked_by_foreign_active_intent(self):
        """Con una cancelación del cliente EN CURSO (intención activa), el
        rechazo admin espera (409) sin robar ni limpiar la intención."""
        wid = f"wd_{MARK}_b3"
        _mk_withdrawal(wid)
        dv = _mk_delivery(f"dv_{MARK}_b3", wid, status="arrived",
                          origin_cancel_intent={"at": _now(), "by": CLIA_ID,
                                                "token": "tokCLIENT"})
        _set_bal(CLIA_ID, "USD", 0)
        r = _admin_status(wid, "rejected", admin_note="prueba iter301")
        assert r.status_code == 409, r.text
        fresh = _db().deliveries.find_one({"id": dv["id"]})
        assert (fresh.get("origin_cancel_intent") or {}).get("token") == "tokCLIENT"
        assert _bal(CLIA_ID, "USD") == 0.0
        assert _db().withdrawals.find_one({"id": wid})["status"] == "pending"


# ---------------------------------------------------------------------------
# DR04 — un cierre de recuperación antiguo no sobrescribe el ciclo nuevo
# ---------------------------------------------------------------------------
class TestDR04StaleRecoveryClose:
    def test_stale_recovery_close_cannot_override_new_cycle(self):
        """Reproducción stale_recovery_cycle: el recuperador aborta el plan 1
        (sin saldo) y se pausa; la reactivación 2 publica un plan nuevo,
        debita 100 y aprueba. El cierre atrasado del recuperador (leyó el
        plan 1) queda CONDICIONADO al op_id — no toca el ciclo nuevo."""
        wid = f"wd_{MARK}_h1_{uuid.uuid4().hex[:6]}"
        op1 = f"withdrawal-redebit:{wid}:{MARK}old"
        op2 = f"withdrawal-redebit:{wid}:{MARK}new"
        _set_bal(CLIA_ID, "USD", 0.0)
        _mk_withdrawal(wid, amount=100.0, status="rejected",
                       balance_refunded=True,
                       redebit_pending={"op_id": op1, "amount": 100.0,
                                        "currency": "USD", "at": _old(15)})

        async def flow():
            import services.balances as bal
            from services.credit_recovery import heal_initializing_ops
            from db_client import db as adb
            real_burn = bal.burn_or_undo_debit

            async def burn_then_new_cycle(uid, cur, amt, op):
                res = await real_burn(uid, cur, amt, op)
                if op == op1:
                    # entre el aborto y el cierre atrasado: llegan fondos y la
                    # reactivación 2 debita con un plan NUEVO y aprueba.
                    await bal.credit_balance_idempotent(
                        CLIA_ID, "USD", 100.0, f"{MARK}-late-deposit")
                    st = await bal.debit_balance_idempotent(
                        CLIA_ID, "USD", 100.0, op2)
                    assert st == "applied", st
                    await adb.withdrawals.update_one(
                        {"id": wid},
                        {"$set": {"status": "approved",
                                  "balance_refunded": False},
                         "$unset": {"redebit_pending": ""}})
                return res

            bal.burn_or_undo_debit = burn_then_new_cycle
            try:
                await heal_initializing_ops()
            finally:
                bal.burn_or_undo_debit = real_burn

        _run(flow)
        fresh = _db().withdrawals.find_one({"id": wid})
        assert fresh["status"] == "approved", \
            f"el cierre atrasado no debe sobrescribir el ciclo nuevo: {fresh['status']}"
        assert fresh.get("balance_refunded") is False
        assert "redebit_pending" not in fresh
        assert _bal(CLIA_ID, "USD") == 0.0, \
            "los 100 debitados por la reactivación 2 siguen descontados"


# ---------------------------------------------------------------------------
# DR02 — identidad de la evidencia sin el importe declarado + históricos
# ---------------------------------------------------------------------------
class TestDR02EvidenceIdentity:
    def test_changed_declared_amount_cannot_reuse_evidence(self):
        """Reproducción duplicate_crypto (variante 1): mismo hash con importes
        100 y 99 → solo la primera confirmación acredita."""
        h = f"{MARK}hash_amt"
        d1 = _mk_deposit(f"dep_{MARK}_e1", amount=100.0, tx_hash=h)
        d2 = _mk_deposit(f"dep_{MARK}_e2", amount=99.0, tx_hash=h)
        _set_bal(CLIA_ID, CRYPTO_NR, 0)
        assert _confirm(d1["id"]).status_code == 200
        r2 = _confirm(d2["id"])
        assert r2.status_code == 409, r2.text
        det = r2.json()["detail"]
        assert isinstance(det, dict) and det["code"] == "EVIDENCE_ALREADY_USED"
        assert d1["id"][:16] in det["message"]
        assert _bal(CLIA_ID, CRYPTO_NR) == 100.0, \
            f"jamás 199: {_bal(CLIA_ID, CRYPTO_NR)}"
        assert _db().deposits.find_one({"id": d2["id"]})["status"] == "pending"

    def test_historical_confirmed_without_claim_blocks_reuse(self):
        """Reproducción duplicate_crypto (variante 2): un depósito confirmado
        ANTES del cambio (sin fila en crypto_evidence_claims) no puede volver
        a acreditarse — el hash queda bloqueado."""
        h = f"{MARK}hash_hist"
        hist = _mk_deposit(f"dep_{MARK}_e3", amount=100.0, tx_hash=h,
                           status="confirmed")
        d_new = _mk_deposit(f"dep_{MARK}_e4", amount=100.0, tx_hash=h)
        _set_bal(CLIA_ID, CRYPTO_NR, 100.0)  # saldo del abono histórico
        r = _confirm(d_new["id"])
        assert r.status_code == 409, r.text
        det = r.json()["detail"]
        txt = det["message"] if isinstance(det, dict) else det
        assert hist["id"][:16] in txt
        assert _bal(CLIA_ID, CRYPTO_NR) == 100.0, "nunca pasa de 100 a 200"
        assert _db().deposits.find_one({"id": d_new["id"]})["status"] == "pending"

    def test_movement_id_is_single_use_per_hash(self):
        """Un ID de movimiento identifica UNA transferencia real: reutilizarlo
        con el mismo hash recibe 409; uno distinto sí acredita."""
        h = f"{MARK}hash_mid"
        d1 = _mk_deposit(f"dep_{MARK}_e5", amount=10.0, tx_hash=h)
        d2 = _mk_deposit(f"dep_{MARK}_e6", amount=10.0, tx_hash=h)
        d3 = _mk_deposit(f"dep_{MARK}_e7", amount=10.0, tx_hash=h)
        assert _confirm(d1["id"]).status_code == 200
        r2 = _confirm(d2["id"], {"evidence_movement_id": "m2"})
        assert r2.status_code == 200, r2.text
        assert _db().deposits.find_one(
            {"id": d2["id"]})["evidence_movement_id"] == "m2"
        r3 = _confirm(d3["id"], {"evidence_movement_id": "m2"})
        assert r3.status_code == 409, r3.text
        assert _confirm(d3["id"], {"evidence_movement_id": "m3"}).status_code == 200


# ---------------------------------------------------------------------------
# DE01 — regla de plataforma: mínimo 1 USDT en depósitos y retiros cripto
# ---------------------------------------------------------------------------
class TestDE01MinCrypto:
    def _deposit(self, body, token=CLIA_TOKEN):
        return requests.post(f"{API}/deposits", headers=_h(token), json=body)

    def test_crypto_deposit_below_1_usdt_rejected(self):
        # 1 TR9 = 0.5 USDT < 1 → 422
        r = self._deposit({"currency": CRYPTO_RT, "amount": 1,
                           "method": "crypto",
                           "tx_hash": f"{MARK}hash_min_dep1"})
        assert r.status_code == 422, r.text
        assert "mínimo" in r.json()["detail"]

    def test_crypto_deposit_at_or_above_1_usdt_accepted(self):
        # 2 TR9 = 1.0 USDT → 200
        r = self._deposit({"currency": CRYPTO_RT, "amount": 2,
                           "method": "crypto",
                           "tx_hash": f"{MARK}hash_min_dep2"})
        assert r.status_code == 200, r.text

    def test_crypto_without_rate_not_blocked(self):
        """Sin tasa configurada la equivalencia no es computable: la solicitud
        entra a revisión manual del personal (comportamiento documentado)."""
        r = self._deposit({"currency": CRYPTO_NR, "amount": 0.5,
                           "method": "crypto",
                           "tx_hash": f"{MARK}hash_min_dep3"})
        assert r.status_code == 200, r.text

    def test_fiat_deposit_unaffected_by_crypto_min(self):
        r = self._deposit({"currency": FIAT_CODE, "amount": 0.5,
                           "method": "cash"})
        assert r.status_code == 200, r.text

    def test_crypto_withdrawal_below_1_usdt_rejected(self):
        _db().users.update_one(
            {"user_id": VIP01_ID},
            {"$set": {f"vip_balances.{CRYPTO_RT}": 100.0}})
        r = requests.post(
            f"{API}/vip/withdraw", headers=_h(VIP_TOKEN),
            json={"amount_usd": 1, "currency": CRYPTO_RT, "method": "crypto",
                  "details": TRC20_ADDR, "crypto_network": "TRC20",
                  "totp_code": make_vip_totp()})
        assert r.status_code == 400, r.text
        assert "mínimo" in str(r.json()["detail"])

    def test_crypto_withdrawal_at_or_above_1_usdt_accepted(self):
        _db().users.update_one(
            {"user_id": VIP01_ID},
            {"$set": {f"vip_balances.{CRYPTO_RT}": 100.0}})
        r = requests.post(
            f"{API}/vip/withdraw", headers=_h(VIP_TOKEN),
            json={"amount_usd": 2, "currency": CRYPTO_RT, "method": "crypto",
                  "details": TRC20_ADDR, "crypto_network": "TRC20",
                  "totp_code": make_vip_totp()})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending"


# ---------------------------------------------------------------------------
# CI — la suite queda en el conjunto crítico
# ---------------------------------------------------------------------------
class TestCICoverage:
    def test_makefile_critical_includes_iter301(self):
        from pathlib import Path
        makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
        target = makefile.split("test-critical:")[1].split("test-all:")[0]
        assert "test_iter301_verificacion_dr.py" in target
