"""iter260 — Correcciones de la auditoría de continuación E01–E09.

E01 verify-email: permiso granular `users` + respuesta anidada sin credenciales
E02 ítems de lote VIP: claim atómico + abono idempotente (op_id por ciclo)
E03 rechazos con claim de estado: no pisan una confirmación concurrente
E04 exclusividad del movimiento bancario en conciliación (matching_claim)
E05a rollback de orden acumulada: revierte el abono o bloquea explícitamente
E05b rollback de ítem de lote: plan persistente + débito idempotente
E06 amortización concurrente: la deuda recién liquidada consume presupuesto
E07 compactación con horizonte de seguridad (ejecutores en vuelo)
E08 abortar reactivación quema los op_ids (débitos tardíos → duplicate)
E09 crédito al vendedor condicionado a que el canje SIGA en 'delivered'
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from conftest import BASE_URL, VIP_TOKEN, ADMIN_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
VIP_H = {"Authorization": f"Bearer {VIP_TOKEN}"}
ADM_H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
UID = "user_test_vip01"
VENDOR_ID = "user_test_normal01"
MARK = "iter260"
OLD_TS = "2026-01-01T00:00:00+00:00"
FUTURE_TS = "2030-01-01T00:00:00+00:00"

CREDENTIAL_FIELDS = ("password_hash", "password_reset_token",
                     "password_reset_token_hash", "totp_secret_encrypted",
                     "totp_recovery_codes", "totp_secret", "twofa_secret",
                     "recovery_codes", "verification_token")


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _bal(code, uid=UID):
    u = _db().users.find_one({"user_id": uid},
                             {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
    amt = float(((u or {}).get("vip_balances") or {}).get(code) or 0.0)
    if code == "USD":
        amt += float((u or {}).get("vip_balance_usd") or 0.0)
    return amt


def _run(async_fn):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(async_fn())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


ADMIN_ACTOR = {"user_id": "user_test_admin01", "role": "admin",
               "email": "admin.test@resilience.com", "name": "Admin Test"}


async def _stub_permission(*_a, **_k):
    return dict(ADMIN_ACTOR)


class _StaleColl:
    """Proxy de colección: find_one del doc objetivo devuelve un snapshot
    VIEJO (status pending) mientras el resto pasa a la colección real —
    reproduce determinísticamente la lectura obsoleta del rechazo (E03)."""

    def __init__(self, real, doc_key, doc_id, stale_doc):
        self._real, self._key, self._id, self._stale = real, doc_key, doc_id, stale_doc

    async def find_one(self, q, *a, **k):
        if isinstance(q, dict) and q.get(self._key) == self._id:
            return dict(self._stale)
        return await self._real.find_one(q, *a, **k)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _StaleDB:
    def __init__(self, real, coll_name, coll):
        self._real, self._name, self._coll = real, coll_name, coll

    def __getattr__(self, name):
        if name == self._name:
            return self._coll
        return getattr(self._real, name)

    def __getitem__(self, name):
        return self.__getattr__(name)


class _Sandbox:
    def setup_method(self, _):
        db = _db()
        self._orig = db.users.find_one(
            {"user_id": UID},
            {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1}) or {}
        self._orig_vendor = db.users.find_one(
            {"user_id": VENDOR_ID},
            {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1}) or {}

    def teardown_method(self, _):
        db = _db()
        db.users.delete_many({"user_id": {"$regex": f"^u_{MARK}"}})
        db.user_sessions.delete_many({"session_token": {"$regex": f"^sess_{MARK}"}})
        db.vip_capital_deposits.delete_many({"id": {"$regex": f"^dep_{MARK}"}})
        db.vip_settlements.delete_many({"id": {"$regex": f"^vset_{MARK}"}})
        db.deposits.delete_many({"id": {"$regex": f"^dep_{MARK}"}})
        db.capital_requests.delete_many({"id": {"$regex": f"^cr_{MARK}"}})
        db.vip_batch_items.delete_many({"id": {"$regex": f"^vitem_{MARK}"}})
        db.vip_batches.delete_many({"id": {"$regex": f"^vb_{MARK}"}})
        db.bank_transactions.delete_many({"id": {"$regex": f"^tx_{MARK}"}})
        db.orders.delete_many({"id": {"$regex": f"^ord_{MARK}"}})
        db.redemptions.delete_many({"id": {"$regex": f"^red_{MARK}"}})
        db.products.delete_many({"id": {"$regex": f"^prod_{MARK}"}})
        db.repayment_plans.delete_many({"order_id": {"$regex": f"^ord_{MARK}"}})
        db.credit_ops.delete_many({"op_id": {"$regex": MARK}})
        db.stock_ops.delete_many({"op_id": {"$regex": MARK}})
        for uid in (UID, VENDOR_ID):
            db.users.update_one({"user_id": uid}, {"$pull": {
                "applied_credit_ops": {"$regex": MARK}}})
        db.users.update_one({"user_id": UID}, {"$set": {
            "vip_balances": self._orig.get("vip_balances") or {},
            "vip_balance_usd": float(self._orig.get("vip_balance_usd") or 0.0)}})
        db.users.update_one({"user_id": VENDOR_ID}, {"$set": {
            "vip_balances": self._orig_vendor.get("vip_balances") or {},
            "vip_balance_usd": float(
                self._orig_vendor.get("vip_balance_usd") or 0.0)}})

    def _set_usdt(self, amount, uid=UID):
        _db().users.update_one({"user_id": uid},
                               {"$set": {"vip_balances.USDT": float(amount)}})


# ======================================================================
# E01 — verify-email: permiso granular + respuesta sin credenciales
# ======================================================================
class TestE01VerifyEmail(_Sandbox):
    def _mk_target(self, verified):
        uid = f"u_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().users.insert_one({
            "user_id": uid, "email": f"{uid}@test.local", "name": "E01",
            "role": "normal", "email_verified": verified,
            "password_hash": "FAKE_HASH",
            "password_reset_token_hash": "FAKE_TOKEN_HASH",
            "totp_secret_encrypted": "FAKE_CIPHER",
            "totp_recovery_codes": ["FAKE"],
            "created_at": OLD_TS})
        return uid

    def _assert_clean(self, body):
        user = body.get("user") or {}
        for f in CREDENTIAL_FIELDS:
            assert f not in user, f"credencial filtrada en response.user: {f}"

    def test_already_verified_branch_is_sanitized(self):
        uid = self._mk_target(verified=True)
        r = requests.post(f"{API}/admin/users/{uid}/verify-email",
                          headers=ADM_H, json=with_totp_admin({}), timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("already_verified") is True
        self._assert_clean(r.json())

    def test_fresh_verification_branch_is_sanitized(self):
        uid = self._mk_target(verified=False)
        r = requests.post(f"{API}/admin/users/{uid}/verify-email",
                          headers=ADM_H, json=with_totp_admin({}), timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("already_verified") is False
        self._assert_clean(r.json())

    def test_scoped_employee_without_users_permission_gets_403(self):
        emp = f"u_{MARK}_{uuid.uuid4().hex[:8]}"
        sess = f"sess_{MARK}_{uuid.uuid4().hex[:8]}"
        db = _db()
        db.users.insert_one({
            "user_id": emp, "email": f"{emp}@test.local", "name": "Soporte",
            "role": "employee", "allowed_permissions": ["support"],
            "totp_enabled": True, "created_at": OLD_TS})
        db.user_sessions.insert_one({
            "user_id": emp, "session_token": sess,
            "expires_at": FUTURE_TS, "created_at": OLD_TS})
        target = self._mk_target(verified=False)
        r = requests.post(f"{API}/admin/users/{target}/verify-email",
                          headers={"Authorization": f"Bearer {sess}"},
                          json={}, timeout=20)
        assert r.status_code == 403, \
            f"empleado sin permiso 'users' debe recibir 403: {r.status_code} {r.text}"


# ======================================================================
# E02 — ítems de lote VIP: claim atómico, un solo abono
# ======================================================================
class TestE02BatchItemDoubleCredit(_Sandbox):
    def _mk_item(self):
        iid = f"vitem_{MARK}_{uuid.uuid4().hex[:8]}"
        bid = f"vb_{MARK}_{uuid.uuid4().hex[:8]}"
        db = _db()
        db.vip_batches.insert_one({"id": bid, "vip_user_id": UID,
                                   "created_at": OLD_TS})
        db.vip_batch_items.insert_one({
            "id": iid, "batch_id": bid, "vip_user_id": UID,
            "status": "pending", "from_code": "USD", "to_code": "USDT",
            "amount": 100.0, "amount_to": 100.0, "rate_applied": 1.0,
            "holder_name": "Persona Prueba", "created_at": OLD_TS})
        return iid

    def test_overlapping_approvals_credit_once(self):
        self._set_usdt(0)
        iid = self._mk_item()

        async def flow():
            import services.vip_batch_ops as vbo
            from fastapi import HTTPException
            real_rates = vbo.build_rate_lookup
            started, go = asyncio.Event(), asyncio.Event()

            async def paused(*a, **k):
                if not started.is_set():
                    started.set()
                    await go.wait()
                return await real_rates(*a, **k)

            vbo.build_rate_lookup = paused
            try:
                staff = dict(ADMIN_ACTOR)
                task_a = asyncio.create_task(
                    vbo.apply_item_decision(iid, "approved", staff))
                await asyncio.wait_for(started.wait(), timeout=10)
                await vbo.apply_item_decision(iid, "approved", staff)
                go.set()
                try:
                    await task_a
                    return "a_won_too"
                except HTTPException as ex:
                    return ex.status_code
            finally:
                vbo.build_rate_lookup = real_rates

        loser = _run(flow)
        assert loser == 409, f"el perdedor debe recibir 409, no {loser}"
        assert _bal("USDT") == 100.0, \
            f"un solo ítem aprobado debe abonar 100, no {_bal('USDT')}"
        doc = _db().vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert doc["status"] == "approved"
        assert "credit_pending" not in doc

    def test_retry_after_crash_reuses_stable_op_id(self):
        """Crash tras el claim: el marker queda; el healer abona UNA vez."""
        self._set_usdt(0)
        iid = self._mk_item()
        db = _db()
        # simular claim ganado con marker persistido y proceso muerto
        marker = {"op_id": f"vip-item:{iid}:c0", "user_id": UID,
                  "code": "USDT", "amount": 100.0, "legacy_usd": False,
                  "prepared": True, "at": OLD_TS}
        db.vip_batch_items.update_one(
            {"id": iid, "status": "pending"},
            {"$set": {"status": "approved", "credit_pending": marker,
                      "amount_to": 100.0, "balance_delta_usdt": 100.0}})

        async def heal():
            from services.credit_recovery import heal_pending_credits
            await heal_pending_credits()
            await heal_pending_credits()  # segunda pasada: no duplica

        _run(heal)
        assert _bal("USDT") == 100.0, \
            f"el healer debe abonar exactamente una vez: {_bal('USDT')}"
        doc = db.vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert "credit_pending" not in doc


# ======================================================================
# E03 — rechazos con lectura obsoleta no pisan una confirmación
# ======================================================================
class TestE03StaleRejects(_Sandbox):
    def _stale_reject(self, module, coll_name, stale_doc, doc_id, call):
        """Ejecuta el handler de rechazo con un find_one que devuelve el
        snapshot VIEJO (pending) mientras el doc real ya está confirmado."""
        async def flow():
            from fastapi import HTTPException
            from db_client import db as real_db
            real_module_db = module.db
            coll = _StaleColl(getattr(real_db, coll_name), "id", doc_id,
                              stale_doc)
            module.db = _StaleDB(real_db, coll_name, coll)
            orig_perm = module.require_permission
            module.require_permission = _stub_permission
            try:
                await call(module)
                return "overwrote"
            except HTTPException as ex:
                return ex.status_code
            finally:
                module.db = real_module_db
                module.require_permission = orig_perm

        return _run(flow)

    def test_capital_deposit_reject_loses_against_confirm(self):
        self._set_usdt(0)
        dep = f"dep_{MARK}_{uuid.uuid4().hex[:8]}"
        stale = {"id": dep, "vip_user_id": UID, "amount": 100.0,
                 "currency": "USDT", "status": "pending",
                 "created_at": OLD_TS, "updated_at": OLD_TS}
        _db().vip_capital_deposits.insert_one(dict(stale))
        r = requests.post(f"{API}/admin/vip-capital-deposits/{dep}/confirm",
                          headers=ADM_H, timeout=20)
        assert r.status_code == 200, r.text
        assert _bal("USDT") == 100.0

        import routes.vip_ledger_ops as mod

        async def call(m):
            payload = m.RejectPayload(admin_note="carrera E03")
            await m.admin_reject_capital_deposit(dep, payload, None)

        status = self._stale_reject(mod, "vip_capital_deposits", stale, dep, call)
        assert status == 409, f"el rechazo perdedor debe dar 409: {status}"
        doc = _db().vip_capital_deposits.find_one({"id": dep}, {"_id": 0})
        assert doc["status"] == "confirmed", \
            "el rechazo con lectura obsoleta no puede pisar la confirmación"
        assert _bal("USDT") == 100.0

    def test_settlement_reject_loses_against_approve(self):
        self._set_usdt(100)
        sid = f"vset_{MARK}_{uuid.uuid4().hex[:8]}"
        stale = {"id": sid, "vip_user_id": UID, "direction": "payout",
                 "currency": "USDT", "amount": 100.0, "amount_usdt": 100.0,
                 "settlement_method": "cash", "requested_by": "vip",
                 "status": "pending", "created_at": OLD_TS,
                 "updated_at": OLD_TS}
        _db().vip_settlements.insert_one(dict(stale))
        r = requests.post(f"{API}/admin/vip-settlements/{sid}/approve",
                          headers=ADM_H, timeout=20)
        assert r.status_code == 200, r.text
        assert _bal("USDT") == 0.0

        import routes.vip_ledger_ops as mod

        async def call(m):
            payload = m.RejectPayload(admin_note="carrera E03")
            await m.admin_reject_settlement(sid, payload, None)

        status = self._stale_reject(mod, "vip_settlements", stale, sid, call)
        assert status == 409
        doc = _db().vip_settlements.find_one({"id": sid}, {"_id": 0})
        assert doc["status"] == "confirmed"

    def test_client_deposit_reject_loses_against_confirm(self):
        self._set_usdt(0)
        dep = f"dep_{MARK}_{uuid.uuid4().hex[:8]}"
        stale = {"id": dep, "user_id": UID, "user_email": "vip@test.local",
                 "user_name": "VIP", "user_role": "vip", "currency": "USDT",
                 "amount": 100.0, "method": "transfer", "status": "pending",
                 "created_at": OLD_TS, "updated_at": OLD_TS}
        _db().deposits.insert_one(dict(stale))
        r = requests.post(f"{API}/admin/deposits/{dep}/confirm",
                          headers=ADM_H, timeout=20)
        assert r.status_code == 200, r.text
        assert _bal("USDT") == 100.0

        import routes.deposits as mod

        async def call(m):
            payload = m.RejectPayload(admin_note="carrera E03")
            await m.admin_reject_deposit(dep, payload, None)

        status = self._stale_reject(mod, "deposits", stale, dep, call)
        assert status == 409
        doc = _db().deposits.find_one({"id": dep}, {"_id": 0})
        assert doc["status"] == "confirmed"
        assert _bal("USDT") == 100.0

    def test_capital_request_reject_loses_against_disbursement(self):
        req = f"cr_{MARK}_{uuid.uuid4().hex[:8]}"
        stale = {"id": req, "user_id": UID, "user_email": "vip@test.local",
                 "currency_code": "USDT", "amount": 100.0,
                 "debt_remaining": 100.0, "discount_pct": 10.0,
                 "status": "pending", "created_at": OLD_TS}
        _db().capital_requests.insert_one(
            {**stale, "status": "disbursed", "disbursed_at": OLD_TS})

        import routes.capital_requests as mod

        async def call(m):
            payload = m.CapitalRequestReject(reject_reason="carrera E03",
                                             totp_code="000000")
            orig = m._enforce_totp_step_up

            async def _noop(*a, **k):
                return None

            m._enforce_totp_step_up = _noop
            try:
                await m.admin_reject_capital_request(req, payload, None)
            finally:
                m._enforce_totp_step_up = orig

        status = self._stale_reject(mod, "capital_requests", stale, req, call)
        assert status == 409
        doc = _db().capital_requests.find_one({"id": req}, {"_id": 0})
        assert doc["status"] == "disbursed", \
            "una solicitud desembolsada no puede quedar 'rejected' (la amortización la perdería)"


# ======================================================================
# E04 — un movimiento bancario respalda UNA sola orden
# ======================================================================
class TestE04BankTransactionExclusivity(_Sandbox):
    def _mk_item(self):
        iid = f"vitem_{MARK}_{uuid.uuid4().hex[:8]}"
        bid = f"vb_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().vip_batch_items.insert_one({
            "id": iid, "batch_id": bid, "vip_user_id": UID,
            "status": "pending", "from_code": "USD", "to_code": "USDT",
            "amount": 100.0, "amount_to": 100.0, "rate_applied": 1.0,
            "holder_name": "Persona Prueba", "created_at": OLD_TS})
        return iid

    def _mk_tx(self, claim=None):
        tx = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
        doc = {"id": tx, "status": "manual_review", "direction": "credit",
               "amount": 100.0, "currency": "USD", "candidates": [],
               "transaction_date": "2026-01-01", "created_at": OLD_TS,
               "updated_at": OLD_TS}
        if claim:
            doc["matching_claim"] = claim
        _db().bank_transactions.insert_one(doc)
        return tx

    def test_active_claim_blocks_second_order(self):
        self._set_usdt(0)
        i1, i2 = self._mk_item(), self._mk_item()
        now = datetime.now(timezone.utc).isoformat()
        tx = self._mk_tx(claim={"order_id": i1, "at": now, "by": "otro"})
        r = requests.post(
            f"{API}/admin/reconciliation/transactions/{tx}/confirm",
            headers=ADM_H, json={"order_id": i2}, timeout=20)
        assert r.status_code == 409, \
            f"un reclamo activo debe bloquear otra orden: {r.status_code} {r.text}"
        assert _bal("USDT") == 0.0
        doc = _db().vip_batch_items.find_one({"id": i2}, {"_id": 0})
        assert doc["status"] == "pending"

    def test_orphan_claim_is_stolen_and_single_link_wins(self):
        self._set_usdt(0)
        i1 = self._mk_item()
        i2 = self._mk_item()
        # reclamo huérfano viejo hacia una orden que nunca se aprobó
        tx = self._mk_tx(claim={"order_id": "ord_muerta", "at": OLD_TS,
                                "by": "crashed"})
        r = requests.post(
            f"{API}/admin/reconciliation/transactions/{tx}/confirm",
            headers=ADM_H, json={"order_id": i1}, timeout=20)
        assert r.status_code == 200, r.text
        assert _bal("USDT") == 100.0
        txd = _db().bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == i1
        assert "matching_claim" not in txd
        # el mismo movimiento no puede respaldar una segunda orden
        r2 = requests.post(
            f"{API}/admin/reconciliation/transactions/{tx}/confirm",
            headers=ADM_H, json={"order_id": i2}, timeout=20)
        assert r2.status_code == 409
        assert _bal("USDT") == 100.0

    def test_crash_between_approval_and_link_is_resumable(self):
        self._set_usdt(0)
        i1 = self._mk_item()
        tx = self._mk_tx()
        # simular crash: ítem aprobado con sello de ESTE tx, enlace sin escribir
        now = datetime.now(timezone.utc).isoformat()
        _db().bank_transactions.update_one(
            {"id": tx},
            {"$set": {"matching_claim": {"order_id": i1, "at": OLD_TS,
                                         "by": "crashed"}}})
        _db().vip_batch_items.update_one(
            {"id": i1},
            {"$set": {"status": "approved", "amount_to": 100.0,
                      "reviewed_at": now,
                      "reconciliation": {"bank_transaction_id": tx,
                                         "matched_at": now, "auto": False}}})
        r = requests.post(
            f"{API}/admin/reconciliation/transactions/{tx}/confirm",
            headers=ADM_H, json={"order_id": i1}, timeout=20)
        assert r.status_code == 200, \
            f"reanudar el enlace a medias debe funcionar: {r.status_code} {r.text}"
        txd = _db().bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == i1
        # la reanudación NO vuelve a acreditar (el ítem ya estaba aprobado)
        assert _bal("USDT") == 0.0


# ======================================================================
# E05a — rollback de orden acumulada
# ======================================================================
class TestE05aAccumulatedOrderRollback(_Sandbox):
    def _seed(self, balance):
        self._set_usdt(balance)
        oid = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"
        tx = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        _db().orders.insert_one({
            "id": oid, "user_id": UID, "status": "approved",
            "delivery_method": "accumulate", "user_role": "vip",
            "amount_from": 100.0, "from_code": "USD",
            "amount_to": 100.0, "to_code": "USDT",
            "accumulated_at": now,
            "reconciliation": {"bank_transaction_id": tx, "matched_at": now},
            "created_at": OLD_TS, "updated_at": OLD_TS})
        _db().bank_transactions.insert_one({
            "id": tx, "status": "manual_matched", "direction": "credit",
            "amount": 100.0, "currency": "USD", "candidates": [],
            "matched_order_id": oid, "matched_kind": "order",
            "created_at": OLD_TS, "updated_at": OLD_TS})
        return oid, tx

    def _rollback(self, tx):
        return requests.post(
            f"{API}/admin/reconciliation/transactions/{tx}/rollback",
            headers=ADM_H, json={"reason": "prueba E05a rollback"}, timeout=20)

    def test_rollback_reverses_the_accumulated_credit(self):
        oid, tx = self._seed(balance=100)
        r = self._rollback(tx)
        assert r.status_code == 200, r.text
        assert _bal("USDT") == 0.0, \
            "el rollback debe revertir el abono acumulado (E05a)"
        order = _db().orders.find_one({"id": oid}, {"_id": 0})
        assert order["status"] == "pending"
        assert "accumulated_at" not in order, \
            "una futura re-aprobación debe poder volver a acreditar"
        txd = _db().bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "unmatched"

    def test_rollback_blocked_when_credit_already_spent(self):
        oid, tx = self._seed(balance=0)
        r = self._rollback(tx)
        assert r.status_code == 409, \
            "sin saldo que revertir el rollback debe BLOQUEARSE, no liberar el cobro"
        order = _db().orders.find_one({"id": oid}, {"_id": 0})
        assert order["status"] == "approved"
        txd = _db().bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched"

    def test_rollback_blocked_when_order_amortized_debt(self):
        oid, tx = self._seed(balance=100)
        _db().capital_requests.insert_one({
            "id": f"cr_{MARK}_{uuid.uuid4().hex[:8]}", "user_id": UID,
            "currency_code": "USDT", "status": "paid_off",
            "debt_remaining": 0.0,
            "repayment_events": [{"order_id": oid, "amount": 10.0,
                                  "at": OLD_TS}],
            "created_at": OLD_TS})
        r = self._rollback(tx)
        assert r.status_code == 409, \
            "una orden que amortizó deuda no soporta rollback automático"
        assert _bal("USDT") == 100.0
        assert _db().orders.find_one({"id": oid})["status"] == "approved"


# ======================================================================
# E05b — rollback de ítem de lote: idempotente bajo solapamiento
# ======================================================================
class TestE05bBatchRollbackIdempotent(_Sandbox):
    def test_double_rollback_debits_once(self):
        self._set_usdt(100)
        iid = f"vitem_{MARK}_{uuid.uuid4().hex[:8]}"
        tx = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
        snapshot = {
            "id": iid, "batch_id": f"vb_{MARK}_x", "vip_user_id": UID,
            "status": "approved", "from_code": "USD", "to_code": "USDT",
            "amount": 100.0, "amount_to": 100.0, "rate_applied": 1.0,
            "holder_name": "Persona Prueba",
            "reconciliation": {"bank_transaction_id": tx},
            "created_at": OLD_TS}
        _db().vip_batch_items.insert_one(dict(snapshot))

        async def flow():
            from fastapi import HTTPException
            from services.reconciliation_matcher import (
                rollback_batch_item_from_reconciliation as rb)
            await rb(dict(snapshot), tx, dict(ADMIN_ACTOR), "prueba E05b")
            try:
                # segundo rollback con el MISMO snapshot viejo (solapamiento)
                await rb(dict(snapshot), tx, dict(ADMIN_ACTOR), "prueba E05b")
                return "double"
            except HTTPException as ex:
                return ex.status_code

        second = _run(flow)
        assert second == 409, f"el segundo rollback debe dar 409: {second}"
        assert _bal("USDT") == 0.0, \
            f"el reverso debe descontar UNA vez (esperado 0): {_bal('USDT')}"
        doc = _db().vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert doc["status"] == "pending"
        assert int(doc.get("decision_cycle") or 0) == 1, \
            "una re-aprobación futura debe usar op_ids de un ciclo nuevo"
        assert "rollback_pending" not in doc


# ======================================================================
# E06 — la primera deuda liquidada consume presupuesto igualmente
# ======================================================================
class TestE06RepaymentBudget(_Sandbox):
    def test_paid_off_debt_contribution_still_consumes_budget(self):
        db = _db()
        oid = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"
        cra = f"cr_{MARK}_a_{uuid.uuid4().hex[:6]}"
        crb = f"cr_{MARK}_b_{uuid.uuid4().hex[:6]}"
        db.capital_requests.insert_one({
            "id": cra, "user_id": UID, "currency_code": "USDT",
            "status": "disbursed", "debt_remaining": 10.0,
            "discount_pct": 10.0, "disbursed_at": "1", "created_at": OLD_TS})
        db.capital_requests.insert_one({
            "id": crb, "user_id": UID, "currency_code": "USDT",
            "status": "disbursed", "debt_remaining": 100.0,
            "discount_pct": 50.0, "disbursed_at": "2", "created_at": OLD_TS})

        async def flow():
            import services.balances as bal
            real_loader = bal._load_or_create_repayment_plan

            async def loader_with_concurrent_executor(user_id, currency,
                                                      amount, order_id, active):
                # simula que el OTRO ejecutor de la misma orden termina justo
                # aquí: contribuye 10 a la deuda A y la deja liquidada.
                from db_client import db as adb
                await adb.capital_requests.update_one(
                    {"id": cra},
                    {"$set": {"status": "paid_off", "debt_remaining": 0.0},
                     "$push": {"repayment_events": {
                         "order_id": order_id, "amount": 10.0,
                         "at": OLD_TS}}})
                return await real_loader(user_id, currency, amount,
                                         order_id, active)

            bal._load_or_create_repayment_plan = loader_with_concurrent_executor
            try:
                return await bal._apply_capital_request_repayment(
                    UID, "USDT", 100.0, oid)
            finally:
                bal._load_or_create_repayment_plan = real_loader

        net = _run(flow)
        docs = list(_db().capital_requests.find(
            {"id": {"$in": [cra, crb]}}, {"_id": 0}))
        paid = sum(float(ev.get("amount") or 0) for d in docs
                   for ev in (d.get("repayment_events") or []))
        assert paid == 10.0, \
            f"presupuesto 10 → amortización total 10, no {paid} (E06)"
        assert net == 90.0, f"neto esperado 90, no {net}"
        b = next(d for d in docs if d["id"] == crb)
        assert float(b["debt_remaining"]) == 100.0, \
            "la deuda B no puede recibir presupuesto ya consumido en A"


# ======================================================================
# E07 — compactación con horizonte de seguridad
# ======================================================================
class TestE07CompactionHorizon(_Sandbox):
    def test_recent_applied_op_survives_compaction(self):
        db = _db()
        uid = f"u_{MARK}_{uuid.uuid4().hex[:8]}"
        db.users.insert_one({"user_id": uid, "email": f"{uid}@test.local",
                             "role": "vip", "vip_balances": {"USDT": 0.0},
                             "created_at": OLD_TS})
        op = f"op_{MARK}_inflight_{uuid.uuid4().hex[:6]}"
        fakes = [f"f_{MARK}_{i}" for i in range(2000)]
        stale_ts = (datetime.now(timezone.utc)
                    - timedelta(hours=25)).isoformat()

        async def flow():
            from db_client import db as adb
            from services.balances import (credit_balance_idempotent,
                                           compact_credit_registries)
            ok = await credit_balance_idempotent(uid, "USDT", 100.0, op)
            await adb.users.update_one(
                {"user_id": uid},
                {"$push": {"applied_credit_ops": {"$each": fakes}}})
            removed = await compact_credit_registries()
            doc = await adb.users.find_one(
                {"user_id": uid}, {"_id": 0, "applied_credit_ops": 1})
            survived = op in (doc.get("applied_credit_ops") or [])
            retry = await credit_balance_idempotent(uid, "USDT", 100.0, op)
            # envejecer el op más allá del horizonte → ya es compactable
            await adb.credit_ops.update_one(
                {"op_id": op}, {"$set": {"applied_at": stale_ts,
                                         "at": stale_ts}})
            await compact_credit_registries(threshold=1000, keep=500)
            doc2 = await adb.users.find_one(
                {"user_id": uid}, {"_id": 0, "applied_credit_ops": 1})
            gone = op not in (doc2.get("applied_credit_ops") or [])
            return ok, removed, survived, retry, gone

        ok, removed, survived, retry, gone = _run(flow)
        assert ok is True
        assert removed >= 500, f"la compactación debe seguir funcionando: {removed}"
        assert survived, \
            "un op aplicado RECIENTE debe sobrevivir la compactación (E07)"
        assert retry is False, \
            "el reintento tardío no puede volver a acreditar"
        assert _bal("USDT", uid=uid) == 100.0, \
            f"saldo esperado 100 (sin duplicar): {_bal('USDT', uid=uid)}"
        assert gone, \
            "pasado el horizonte, el op debe compactarse (higiene del doc)"
        db.users.delete_one({"user_id": uid})
        db.credit_ops.delete_many({"op_id": {"$regex": MARK}})


# ======================================================================
# E08 — abortar una reactivación quema los op_ids del plan
# ======================================================================
class TestE08AbortBurnsPlanOps(_Sandbox):
    def test_late_debit_after_healer_abort_is_duplicate(self):
        db = _db()
        self._set_usdt(100)
        pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
        rid = f"red_{MARK}_{uuid.uuid4().hex[:8]}"
        stock_op = f"reactivate-stock:{rid}:{MARK}"
        debit_op = f"reactivate-debit:{rid}:{MARK}"
        db.products.insert_one({"id": pid, "name": "E08", "stock": 1,
                                "owner_id": "vendor_x", "is_active": True,
                                "created_at": OLD_TS})
        db.redemptions.insert_one({
            "id": rid, "user_id": UID, "product_id": pid,
            "product_name": "E08", "quantity": 1, "total_usd": 100.0,
            "settlement_currency": "USDT", "status": "rejected",
            "rejection_applied": True, "rejection_effects_done": True,
            "reactivation_pending": {
                "stock_op": stock_op, "debit_op": debit_op,
                "amount": 100.0, "currency": "USDT", "quantity": 1,
                "target": "approved", "at": OLD_TS},
            "created_at": OLD_TS})

        async def flow():
            from services.inventory import apply_stock_idempotent
            from services.credit_recovery import heal_initializing_ops
            from services.balances import debit_balance_idempotent
            # el creador lento ya reservó stock, pero AÚN no cobró
            st = await apply_stock_idempotent(pid, -1, stock_op)
            assert st == "applied", st
            # el recuperador aborta el plan (repone stock, quema el débito)
            await heal_initializing_ops()
            # …y AHORA llega el débito tardío del creador lento
            return await debit_balance_idempotent(UID, "USDT", 100.0, debit_op)

        late = _run(flow)
        assert late == "duplicate", \
            f"el débito tardío tras el aborto debe ser 'duplicate': {late}"
        assert _bal("USDT") == 100.0, \
            f"el saldo del cliente debe quedar intacto (100): {_bal('USDT')}"
        prod = db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert prod["stock"] == 1, "el stock reservado debe reponerse"
        doc = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["status"] == "rejected"
        assert "reactivation_pending" not in doc, \
            "el plan abortado se limpia sin dejar obligaciones huérfanas"


# ======================================================================
# E09 — el crédito al vendedor exige que el canje SIGA en 'delivered'
# ======================================================================
class TestE09VendorCreditRace(_Sandbox):
    def test_late_vendor_credit_after_rejection_is_refused(self):
        db = _db()
        self._set_usdt(0)
        self._set_usdt(0, uid=VENDOR_ID)
        pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
        rid = f"red_{MARK}_{uuid.uuid4().hex[:8]}"
        db.products.insert_one({"id": pid, "name": "E09", "stock": 0,
                                "owner_id": VENDOR_ID, "is_active": True,
                                "created_at": OLD_TS})
        base = {
            "id": rid, "user_id": UID, "product_id": pid,
            "product_name": "E09", "quantity": 1, "total_usd": 100.0,
            "settlement_currency": "USDT", "vendor_owner_id": VENDOR_ID,
            "status": "delivered", "created_at": OLD_TS}
        db.redemptions.insert_one(dict(base))

        async def flow():
            from routes.admin import (_transition_redemption,
                                      _credit_vendor_for_redemption)
            # otro operador rechaza el canje ANTES de que el crédito al
            # vendedor (pausado tras publicar 'delivered') llegue a correr
            await _transition_redemption(dict(base), rid, "rejected",
                                         "carrera E09", dict(ADMIN_ACTOR))
            # …y AHORA llega el crédito tardío con su snapshot viejo
            await _credit_vendor_for_redemption(dict(base))

        _run(flow)
        assert _bal("USDT", uid=VENDOR_ID) == 0.0, \
            "un canje finalmente rechazado no puede dejar neto pagado al vendedor"
        assert _bal("USDT") == 100.0, \
            f"el comprador debe quedar reembolsado (100): {_bal('USDT')}"
        doc = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["status"] == "rejected"
        assert not doc.get("vendor_credited_at"), \
            "no puede quedar marca de crédito al vendedor en un canje rechazado"
