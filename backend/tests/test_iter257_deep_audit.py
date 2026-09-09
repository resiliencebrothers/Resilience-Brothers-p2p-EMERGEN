"""iter257 — Correcciones de la auditoría profunda D01–D14.

D01 credenciales fuera de toda respuesta + token de reset hasheado ·
D02 confirmación de depósito de capital atómica (claim + marker) ·
D03 settlements con guard de saldo y efecto idempotente ·
D04 propiedad del aborto en reactivaciones (el perdedor no compensa al ganador)
· D05 presupuesto de amortización no excedible en concurrencia ·
D06 compactación de registros que preserva ops sin confirmar ·
D07 reverso al vendedor reanudable (deuda explícita si ya gastó) ·
D08 asiento contable antes que la marca (dedupe_key) ·
D09 consumo atómico de códigos de recuperación ·
D10 reset de contraseña de un solo uso + revocación de sesiones ·
D12 cambio de contraseña sin 2FA cuando el 2FA no está activado ·
D13 chat de entregas con el permiso canónico del staff.
"""
import asyncio
import hashlib
import os
import uuid

import bcrypt
import requests
from pymongo import MongoClient

from conftest import (BASE_URL, VIP_TOKEN, ADMIN_TOKEN, NORMAL_TOKEN,
                      EMPLOYEE_TOKEN, with_totp_admin)

API = f"{BASE_URL}/api"
VIP_H = {"Authorization": f"Bearer {VIP_TOKEN}"}
ADM_H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
NORM_H = {"Authorization": f"Bearer {NORMAL_TOKEN}"}
EMP_H = {"Authorization": f"Bearer {EMPLOYEE_TOKEN}"}
UID = "user_test_vip01"
VENDOR_ID = "user_test_normal01"
MARK = "iter257"
OLD_TS = "2026-01-01T00:00:00+00:00"
FUTURE_TS = "2030-01-01T00:00:00+00:00"

CREDENTIAL_FIELDS = ("password_hash", "password_reset_token",
                     "password_reset_token_hash", "password_reset_expires_at",
                     "totp_secret_encrypted", "totp_recovery_codes",
                     "verification_token")


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _bal(code, uid=UID):
    u = _db().users.find_one({"user_id": uid},
                             {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
    amt = float((u.get("vip_balances") or {}).get(code) or 0.0)
    if code == "USD":
        amt += float(u.get("vip_balance_usd") or 0.0)
    return amt


def _run(async_fn):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(async_fn())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


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
        db.vip_settlements.delete_many({"note": MARK})
        db.redemptions.delete_many({"id": {"$regex": f"^red_{MARK}"}})
        db.redemptions.delete_many({"product_id": {"$regex": f"^prod_{MARK}"}})
        db.products.delete_many({"id": {"$regex": f"^prod_{MARK}"}})
        db.capital_requests.delete_many({"id": {"$regex": f"^cr_{MARK}"}})
        db.repayment_plans.delete_many({"order_id": {"$regex": f"^ord_{MARK}"}})
        db.company_fund_adjustments.delete_many(
            {"dedupe_key": {"$regex": MARK}})
        db.company_fund_adjustments.delete_many(
            {"ref_id": {"$regex": f"^(red|dep|prod)_{MARK}"}})
        db.deliveries.delete_many({"id": {"$regex": f"^del_{MARK}"}})
        db.credit_ops.delete_many({"op_id": {"$regex": MARK}})
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
# D01 — credenciales fuera de TODA respuesta de la API
# ======================================================================
class TestD01CredentialLeaks(_Sandbox):
    def test_admin_list_users_hides_credentials(self):
        _db().users.update_one({"user_id": UID}, {"$set": {
            "password_reset_token_hash": "x" * 64,
            "verification_token": "leak_me"}})
        try:
            r = requests.get(f"{API}/admin/users",
                             params={"search": "vip.test"},
                             headers=ADM_H, timeout=20)
            assert r.status_code == 200, r.text
            users = r.json()
            rows = users if isinstance(users, list) else users.get("users", [])
            target = [u for u in rows if u.get("user_id") == UID]
            assert target, "el VIP de prueba debe aparecer"
            for f in CREDENTIAL_FIELDS:
                assert f not in target[0], f"campo filtrado: {f}"
        finally:
            _db().users.update_one({"user_id": UID}, {"$unset": {
                "password_reset_token_hash": "", "verification_token": ""}})

    def test_auth_me_hides_credentials(self):
        r = requests.get(f"{API}/auth/me", headers=VIP_H, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        for f in CREDENTIAL_FIELDS:
            assert f not in body, f"campo filtrado en /auth/me: {f}"


# ======================================================================
# D10/D01 — reset de contraseña: hash, un solo uso, sesiones revocadas
# ======================================================================
class TestD10PasswordReset(_Sandbox):
    def _mk_user(self):
        uid = f"u_{MARK}_{uuid.uuid4().hex[:8]}"
        raw_token = uuid.uuid4().hex + uuid.uuid4().hex
        _db().users.insert_one({
            "user_id": uid, "email": f"{uid}@test.local", "name": "Reset Test",
            "role": "client", "password_hash": bcrypt.hashpw(
                b"ClaveVieja123!", bcrypt.gensalt()).decode(),
            "password_reset_token_hash": hashlib.sha256(
                raw_token.encode()).hexdigest(),
            "password_reset_expires_at": FUTURE_TS,
            "created_at": OLD_TS})
        sess = f"sess_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().user_sessions.insert_one({
            "user_id": uid, "session_token": sess,
            "expires_at": FUTURE_TS, "created_at": OLD_TS})
        return uid, raw_token, sess

    def test_reset_is_single_use_and_revokes_sessions(self):
        uid, token, old_sess = self._mk_user()
        # la sesión vieja funciona antes del reset
        r0 = requests.get(f"{API}/auth/me",
                          headers={"Authorization": f"Bearer {old_sess}"},
                          timeout=20)
        assert r0.status_code == 200, r0.text
        r = requests.post(f"{API}/auth/reset-password",
                          json={"token": token, "password": "ClaveNueva456!"},
                          timeout=20)
        assert r.status_code == 200, r.text
        doc = _db().users.find_one({"user_id": uid}, {"_id": 0})
        assert "password_reset_token_hash" not in doc
        assert int(doc.get("session_version") or 0) == 1
        # la sesión vieja queda revocada
        r2 = requests.get(f"{API}/auth/me",
                          headers={"Authorization": f"Bearer {old_sess}"},
                          timeout=20)
        assert r2.status_code == 401, "la sesión anterior debe morir (D10)"
        # el token es de UN solo uso
        r3 = requests.post(f"{API}/auth/reset-password",
                           json={"token": token, "password": "Otra789!aa"},
                           timeout=20)
        assert r3.status_code == 400, r3.text


# ======================================================================
# D09 — consumo atómico de códigos de recuperación
# ======================================================================
class TestD09RecoveryCodes(_Sandbox):
    def test_recovery_code_consumed_exactly_once(self):
        import totp_service
        plain, hashed = totp_service.generate_recovery_codes(2)
        uid = f"u_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().users.insert_one({
            "user_id": uid, "email": f"{uid}@test.local", "role": "client",
            "totp_enabled": True, "totp_recovery_codes": hashed,
            "created_at": OLD_TS})

        async def flow():
            from auth_utils import _try_recovery_code
            from db_client import db
            user = await db.users.find_one({"user_id": uid}, {"_id": 0})
            first = await _try_recovery_code(user, plain[0])
            # segundo intento con el MISMO código (doc fresco: sigue teniendo
            # el hash 2, pero el hash 1 ya fue retirado atómicamente)
            stale_user = user  # snapshot viejo: aún contiene ambos hashes
            try:
                await _try_recovery_code(stale_user, plain[0])
                replay = "accepted"
            except Exception:
                replay = "rejected"
            return first, replay

        first, replay = _run(flow)
        assert first is True
        assert replay == "rejected", "el mismo código no puede autorizar dos veces"
        doc = _db().users.find_one({"user_id": uid}, {"_id": 0})
        assert len(doc.get("totp_recovery_codes") or []) == 1, \
            "solo se retira el hash que coincidió"


# ======================================================================
# D12 — cambio de contraseña sin 2FA activado
# ======================================================================
class TestD12ChangePasswordWithout2FA(_Sandbox):
    def test_change_password_when_totp_disabled(self):
        db = _db()
        uid = f"u_{MARK}_{uuid.uuid4().hex[:8]}"
        sess = f"sess_{MARK}_{uuid.uuid4().hex[:8]}"
        db.users.insert_one({
            "user_id": uid, "email": f"{uid}@test.local", "name": "D12",
            "role": "client", "auth_provider": "password",
            "totp_enabled": False,
            "password_hash": bcrypt.hashpw(b"Prueba123!",
                                           bcrypt.gensalt()).decode(),
            "created_at": OLD_TS})
        db.user_sessions.insert_one({
            "user_id": uid, "session_token": sess,
            "expires_at": FUTURE_TS, "created_at": OLD_TS})
        r = requests.post(f"{API}/profile/password/change",
                          headers={"Authorization": f"Bearer {sess}"},
                          json={"current_password": "Prueba123!",
                                "new_password": "Prueba456!!"},
                          timeout=20)
        assert r.status_code == 200, \
            f"sin 2FA activado no debe exigir TOTP (era 412): {r.status_code} {r.text}"


# ======================================================================
# D02 — confirmación de depósito de capital: atómica y recuperable
# ======================================================================
class TestD02CapitalDeposit(_Sandbox):
    def _mk_dep(self):
        dep = f"dep_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().vip_capital_deposits.insert_one({
            "id": dep, "vip_user_id": UID, "amount": 100.0,
            "currency": "USDT", "status": "pending",
            "created_at": OLD_TS, "updated_at": OLD_TS})
        return dep

    def test_double_confirm_credits_once(self):
        self._set_usdt(0.0)
        dep = self._mk_dep()
        r1 = requests.post(f"{API}/admin/vip-capital-deposits/{dep}/confirm",
                           headers=ADM_H, json=with_totp_admin({}), timeout=20)
        assert r1.status_code == 200, r1.text
        r2 = requests.post(f"{API}/admin/vip-capital-deposits/{dep}/confirm",
                           headers=ADM_H, json=with_totp_admin({}), timeout=20)
        assert r2.status_code == 409, r2.text
        assert abs(_bal("USDT") - 100.0) < 1e-6, "un solo abono"
        doc = _db().vip_capital_deposits.find_one({"id": dep}, {"_id": 0})
        assert doc["status"] == "confirmed"
        assert "credit_pending" not in doc, "marker aplicado y limpio"

    def test_crash_after_claim_healed(self):
        self._set_usdt(0.0)
        dep = self._mk_dep()

        async def flow():
            from services.credit_recovery import (pending_marker,
                                                  heal_pending_credits)
            from db_client import db
            marker = pending_marker(UID, "USDT", 100.0, "capital-deposit")
            marker["at"] = OLD_TS  # el healer solo toma markers viejos
            await db.vip_capital_deposits.update_one(
                {"id": dep, "status": "pending"},
                {"$set": {"status": "confirmed", "credit_pending": marker,
                          "balance_delta_usdt": 100.0}})
            await heal_pending_credits()
            await heal_pending_credits()

        _run(flow)
        assert abs(_bal("USDT") - 100.0) < 1e-6, "el healer completa una vez"
        doc = _db().vip_capital_deposits.find_one({"id": dep}, {"_id": 0})
        assert "credit_pending" not in doc


# ======================================================================
# D03 — settlements: guard de saldo + efecto idempotente
# ======================================================================
class TestD03Settlements(_Sandbox):
    def test_admin_payout_requires_balance(self):
        self._set_usdt(50.0)
        r = requests.post(f"{API}/admin/vip-settlements", headers=ADM_H,
                          json=with_totp_admin({
                              "vip_user_id": UID, "direction": "payout",
                              "currency": "USDT", "amount": 100.0,
                              "settlement_method": "cash", "note": MARK}),
                          timeout=20)
        assert r.status_code == 409, f"sin saldo no hay pago válido: {r.text}"
        assert abs(_bal("USDT") - 50.0) < 1e-6, "no debe descontar nada"
        assert _db().vip_settlements.count_documents({"note": MARK}) == 0, \
            "no debe quedar un pago 'confirmado' registrado"

    def test_admin_payout_applies_once(self):
        self._set_usdt(50.0)
        r = requests.post(f"{API}/admin/vip-settlements", headers=ADM_H,
                          json=with_totp_admin({
                              "vip_user_id": UID, "direction": "payout",
                              "currency": "USDT", "amount": 30.0,
                              "settlement_method": "cash", "note": MARK}),
                          timeout=20)
        assert r.status_code == 200, r.text
        assert abs(_bal("USDT") - 20.0) < 1e-6
        sid = r.json().get("id") or ""
        doc = _db().vip_settlements.find_one({"id": sid}, {"_id": 0})
        assert doc and "settle_pending" not in doc

    def test_approve_pending_payout_double_click_single_debit(self):
        self._set_usdt(50.0)
        sid = f"vset_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().vip_settlements.insert_one({
            "id": sid, "vip_user_id": UID, "direction": "payout",
            "currency": "USDT", "amount": 30.0, "amount_usdt": 30.0,
            "settlement_method": "cash", "status": "pending", "note": MARK,
            "created_at": OLD_TS, "updated_at": OLD_TS})
        r1 = requests.post(f"{API}/admin/vip-settlements/{sid}/approve",
                           headers=ADM_H, json=with_totp_admin({}), timeout=20)
        assert r1.status_code == 200, r1.text
        r2 = requests.post(f"{API}/admin/vip-settlements/{sid}/approve",
                           headers=ADM_H, json=with_totp_admin({}), timeout=20)
        assert r2.status_code == 409, r2.text
        assert abs(_bal("USDT") - 20.0) < 1e-6, "un solo débito"

    def test_approve_insufficient_returns_to_pending(self):
        self._set_usdt(10.0)
        sid = f"vset_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().vip_settlements.insert_one({
            "id": sid, "vip_user_id": UID, "direction": "payout",
            "currency": "USDT", "amount": 30.0, "amount_usdt": 30.0,
            "settlement_method": "cash", "status": "pending", "note": MARK,
            "created_at": OLD_TS, "updated_at": OLD_TS})
        r = requests.post(f"{API}/admin/vip-settlements/{sid}/approve",
                          headers=ADM_H, json=with_totp_admin({}), timeout=20)
        assert r.status_code == 409, r.text
        doc = _db().vip_settlements.find_one({"id": sid}, {"_id": 0})
        assert doc["status"] == "pending", "sin saldo vuelve a pendiente"
        assert "settle_pending" not in doc
        assert abs(_bal("USDT") - 10.0) < 1e-6


# ======================================================================
# D04 — propiedad del aborto en reactivaciones
# ======================================================================
class TestD04ReactivationAbortOwnership(_Sandbox):
    def _rejected_redemption(self):
        self._set_usdt(100.0)
        pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().products.insert_one({
            "id": pid, "name": f"D04 {pid}", "description": "",
            "image_url": "", "price_usd": 30.0, "cost_usd": 0.0, "stock": 2,
            "category": "general", "is_active": True, "owner_id": "",
            "available_store_ids": [], "created_at": OLD_TS})
        rid = f"red_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().redemptions.insert_one({
            "id": rid, "user_id": UID, "product_id": pid,
            "product_name": "D04", "quantity": 1, "total_usd": 30.0,
            "status": "rejected", "settlement_currency": "USDT",
            "fulfillment": "delivery", "rejection_flow_started": True,
            "rejection_applied": True, "rejection_effects_done": True,
            "rejection_cycle": 1, "created_at": OLD_TS})
        return pid, rid

    def test_aborting_plan_blocks_endpoint_without_compensating(self):
        pid, rid = self._rejected_redemption()
        stock_op = f"reactivate-stock:{rid}:{MARK}ab"
        _db().redemptions.update_one({"id": rid}, {"$set": {
            "reactivation_pending": {
                "stock_op": stock_op,
                "debit_op": f"reactivate-debit:{rid}:{MARK}ab",
                "amount": 30.0, "currency": "USDT", "quantity": 1,
                "target": "pending", "at": OLD_TS, "state": "aborting"}}})
        bal0 = _bal("USDT")
        r = requests.put(f"{API}/admin/redemptions/{rid}/status",
                         headers=ADM_H,
                         json=with_totp_admin({"status": "pending"}),
                         timeout=20)
        assert r.status_code == 409, r.text
        assert abs(_bal("USDT") - bal0) < 1e-6, "no debe cobrar ni compensar"
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["status"] == "rejected"

    def test_healer_resumes_stale_aborting_plan_once(self):
        pid, rid = self._rejected_redemption()
        stock_op = f"reactivate-stock:{rid}:{MARK}hz"
        debit_op = f"reactivate-debit:{rid}:{MARK}hz"
        _db().redemptions.update_one({"id": rid}, {"$set": {
            "reactivation_pending": {
                "stock_op": stock_op, "debit_op": debit_op, "amount": 30.0,
                "currency": "USDT", "quantity": 1, "target": "pending",
                "at": OLD_TS, "state": "aborting"}}})

        async def flow():
            from services.balances import debit_balance_idempotent
            from services.inventory import apply_stock_idempotent
            from services.credit_recovery import heal_initializing_ops
            await apply_stock_idempotent(pid, -1, stock_op)
            await debit_balance_idempotent(UID, "USDT", 30.0, debit_op)
            await heal_initializing_ops()
            await heal_initializing_ops()

        _run(flow)
        assert abs(_bal("USDT") - 100.0) < 1e-6, "reverso exactamente una vez"
        assert _db().products.find_one({"id": pid})["stock"] == 2
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert "reactivation_pending" not in doc


# ======================================================================
# D05 — el presupuesto por orden no se excede con contribuciones ajenas
# ======================================================================
class TestD05RepaymentBudget(_Sandbox):
    def test_existing_contribution_consumes_budget(self):
        db = _db()
        cr_a = f"cr_{MARK}_{uuid.uuid4().hex[:6]}"
        cr_b = f"cr_{MARK}_{uuid.uuid4().hex[:6]}"
        order_id = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"
        # el "otro ejecutor" ya amortizó 10 en A para esta misma orden
        db.capital_requests.insert_many([
            {"id": cr_a, "user_id": UID, "status": "disbursed",
             "currency_code": "USDT", "discount_pct": 10.0,
             "debt_remaining": 0.0, "disbursed_at": OLD_TS,
             "repayment_events": [{"order_id": order_id, "amount": 10.0}]},
            {"id": cr_b, "user_id": UID, "status": "disbursed",
             "currency_code": "USDT", "discount_pct": 50.0,
             "debt_remaining": 100.0,
             "disbursed_at": "2026-02-01T00:00:00+00:00",
             "repayment_events": []},
        ])
        db.repayment_plans.insert_one({
            "order_id": order_id, "currency": "USDT", "user_id": UID,
            "gross": 100.0, "pct": 10.0, "budget_total": 10.0, "at": OLD_TS})

        async def flow():
            from services.balances import _apply_capital_request_repayment
            return await _apply_capital_request_repayment(
                UID, "USDT", 100.0, order_id)

        net = _run(flow)
        assert abs(net - 90.0) < 1e-6, f"neto estable: {net}"
        b = db.capital_requests.find_one({"id": cr_b}, {"_id": 0})
        assert abs(float(b["debt_remaining"]) - 100.0) < 1e-6, \
            "B no debe amortizarse: el presupuesto ya se consumió en A"


# ======================================================================
# D06 — compactación que preserva ops sin confirmar
# ======================================================================
class TestD06Compaction(_Sandbox):
    def test_pending_ops_survive_compaction(self):
        db = _db()
        uid = f"u_{MARK}_{uuid.uuid4().hex[:8]}"
        op_pending = f"credit:{MARK}:pend"
        op_applied = f"credit:{MARK}:appl"
        junk = [f"junk_{MARK}_{i}" for i in range(2100)]
        registry = [op_pending, op_applied] + junk
        db.users.insert_one({"user_id": uid, "email": f"{uid}@t.local",
                             "role": "client", "applied_credit_ops": registry,
                             "created_at": OLD_TS})
        db.credit_ops.insert_one({"op_id": op_pending, "user_id": uid,
                                  "state": "pending", "amount": 5.0,
                                  "kind": "credit", "code": "USDT",
                                  "at": OLD_TS})
        db.credit_ops.insert_one({"op_id": op_applied, "user_id": uid,
                                  "state": "applied", "amount": 5.0,
                                  "kind": "credit", "code": "USDT",
                                  "at": OLD_TS})

        async def flow():
            from services.balances import compact_credit_registries
            return await compact_credit_registries()

        removed = _run(flow)
        assert removed > 0
        ops = (db.users.find_one({"user_id": uid}, {"_id": 0})
               .get("applied_credit_ops") or [])
        assert op_pending in ops, \
            "un op con log 'pending' es evidencia y NUNCA se compacta"
        assert op_applied not in ops, "op confirmado sí se compacta"


# ======================================================================
# D07 — reverso al vendedor reanudable y con deuda explícita
# ======================================================================
class TestD07VendorReversal(_Sandbox):
    def _delivered_vendor_redemption(self):
        _db().settings.update_one({"id": "global"}, {"$set": {
            "vendor_commission_pct": 10.0,
            "courier_rate_usdt_per_km": 0}}, upsert=True)
        self._set_usdt(100.0)
        self._set_usdt(0.0, uid=VENDOR_ID)
        pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().products.insert_one({
            "id": pid, "name": f"D07 {pid}", "description": "",
            "image_url": "", "price_usd": 30.0, "cost_usd": 0.0, "stock": 1,
            "category": "general", "is_active": True, "owner_id": VENDOR_ID,
            "owner_name": "Vendor", "approval_status": "approved",
            "available_store_ids": [], "created_at": OLD_TS})
        r = requests.post(f"{API}/vip/redeem", json={
            "product_id": pid, "quantity": 1, "delivery_address": ""},
            headers=VIP_H, timeout=30)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        pr = requests.put(f"{API}/admin/redemptions/{rid}/status",
                          headers=ADM_H,
                          json=with_totp_admin({"status": "delivered"}),
                          timeout=20)
        assert pr.status_code == 200, pr.text
        assert abs(_bal("USDT", VENDOR_ID) - 27.0) < 1e-6
        return pid, rid

    def test_interrupted_reversal_resumes_without_duplicating(self):
        pid, rid = self._delivered_vendor_redemption()
        # crash simulado: el claim del reverso quedó hecho, el débito no.
        _db().redemptions.update_one({"id": rid}, {"$set": {
            "status": "rejected", "rejection_flow_started": True,
            "rejection_applied": True, "rejection_effects_done": False,
            "rejection_cycle": 1,
            "vendor_credit_reversed_at": OLD_TS,
            "vendor_credit_reversal_pending": {
                "op_id": f"vendor-reverse:{rid}:c1", "amount": 27.0,
                "currency": "USDT"}}})
        r = requests.put(f"{API}/admin/redemptions/{rid}/status",
                         headers=ADM_H,
                         json=with_totp_admin({"status": "rejected"}),
                         timeout=20)
        assert r.status_code == 200, r.text
        assert abs(_bal("USDT", VENDOR_ID) - 0.0) < 1e-6, \
            "el débito pendiente se completa"
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert "vendor_credit_reversal_pending" not in doc
        # retry: no duplica
        r2 = requests.put(f"{API}/admin/redemptions/{rid}/status",
                          headers=ADM_H,
                          json=with_totp_admin({"status": "rejected"}),
                          timeout=20)
        assert r2.status_code == 200, r2.text
        assert abs(_bal("USDT", VENDOR_ID) - 0.0) < 1e-6

    def test_spent_balance_becomes_explicit_debt(self):
        pid, rid = self._delivered_vendor_redemption()
        self._set_usdt(5.0, uid=VENDOR_ID)  # el vendedor gastó 22 del neto
        r = requests.put(f"{API}/admin/redemptions/{rid}/status",
                         headers=ADM_H,
                         json=with_totp_admin({"status": "rejected"}),
                         timeout=20)
        assert r.status_code == 200, r.text
        assert abs(_bal("USDT", VENDOR_ID) - (-22.0)) < 1e-6, \
            "deuda explícita del vendedor (decisión D07)"
        assert abs(_bal("USDT") - 100.0) < 1e-6, \
            "el comprador recupera su dinero SIEMPRE"


# ======================================================================
# D08 — asiento contable idempotente por dedupe_key
# ======================================================================
class TestD08FundDedup(_Sandbox):
    def test_dedupe_key_prevents_double_posting(self):
        key = f"dedupe:{MARK}:{uuid.uuid4().hex[:8]}"

        async def flow():
            from services.company_funds_common import record_auto_fund_adjustment
            a = await record_auto_fund_adjustment(
                adjustment_type="inflow", currency="USDT", amount=10.0,
                source_name="Test", note=MARK, ref_id=f"red_{MARK}_x",
                dedupe_key=key)
            b = await record_auto_fund_adjustment(
                adjustment_type="inflow", currency="USDT", amount=10.0,
                source_name="Test", note=MARK, ref_id=f"red_{MARK}_x",
                dedupe_key=key)
            return a["id"], b["id"]

        a_id, b_id = _run(flow)
        assert a_id == b_id, "el reintento devuelve el asiento existente"
        n = _db().company_fund_adjustments.count_documents({"dedupe_key": key})
        assert n == 1


# ======================================================================
# D13 — chat de entregas con el permiso canónico del staff
# ======================================================================
class TestD13DeliveryChatPermission(_Sandbox):
    def test_staff_with_allowed_permissions_can_view_chat(self):
        db = _db()
        prev = db.users.find_one({"user_id": "user_test_employee01"},
                                 {"_id": 0, "allowed_permissions": 1,
                                  "permissions": 1})
        db.users.update_one({"user_id": "user_test_employee01"}, {
            "$addToSet": {"allowed_permissions": "deliveries"},
            "$unset": {"permissions": ""}})
        did = f"del_{MARK}_{uuid.uuid4().hex[:8]}"
        db.deliveries.insert_one({
            "id": did, "user_id": UID, "courier_id": "courier_x",
            "status": "assigned", "created_at": OLD_TS})
        try:
            r = requests.get(f"{API}/deliveries/{did}/chat", headers=EMP_H,
                             timeout=20)
            assert r.status_code == 200, \
                f"el staff con permiso canónico debe ver el chat: {r.status_code} {r.text}"
            assert r.json().get("my_kind") == "staff"
        finally:
            sets = {}
            if prev.get("allowed_permissions") is not None:
                sets["allowed_permissions"] = prev["allowed_permissions"]
            if prev.get("permissions") is not None:
                sets["permissions"] = prev["permissions"]
            if sets:
                db.users.update_one({"user_id": "user_test_employee01"},
                                    {"$set": sets})
