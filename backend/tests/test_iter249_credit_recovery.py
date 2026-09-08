"""iter249 — Acreditaciones exactamente-una-vez + healer de recuperación.

Reportes del usuario:
  1. Dos rechazos simultáneos de un retiro podían devolver el dinero dos veces
     (cerrado en iter248 para admin-vs-admin; aquí se cierra el hueco restante
     cancelación-del-cliente vs rechazo-admin con el guard balance_refunded).
  2. Algunas acreditaciones marcaban "procesado" ANTES de sumar el dinero: si
     la BD fallaba entre ambos pasos, el saldo quedaba sin acreditar y el
     reintento se bloqueaba. Fix: marker `credit_pending` en el claim atómico
     + abono idempotente por op_id + healer (heal_pending_credits).
"""
import asyncio
import os
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, VIP_TOKEN, ADMIN_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
VIP_H = {"Authorization": f"Bearer {VIP_TOKEN}"}
ADM_H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
UID = "user_test_vip01"
CUR = "RC249"
OLD_TS = "2026-01-01T00:00:00+00:00"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _bal(code=CUR):
    u = _db().users.find_one({"user_id": UID}, {"_id": 0, "vip_balances": 1})
    return float((u.get("vip_balances") or {}).get(code) or 0.0)


def _run(async_fn):
    """Corre una corrutina en un loop fresco (patrón test_accumulate_idempotent)."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(async_fn())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


class _Sandbox:
    def setup_method(self, _):
        self._orig_usd = _db().users.find_one(
            {"user_id": UID}, {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})

    def teardown_method(self, _):
        db = _db()
        db.users.update_one({"user_id": UID},
                            {"$unset": {f"vip_balances.{CUR}": ""}})
        db.deposits.delete_many({"id": {"$regex": "^dep_t249"}})
        db.orders.delete_many({"id": {"$regex": "^ord_t249"}})
        db.withdrawals.delete_many({"id": {"$regex": "^w_t249"}})
        db.capital_requests.delete_many({"id": {"$regex": "^cr_t249"}})
        orig = self._orig_usd or {}
        db.users.update_one({"user_id": UID}, {"$set": {
            "vip_balances.USD": float((orig.get("vip_balances") or {}).get("USD") or 0.0),
            "vip_balance_usd": float(orig.get("vip_balance_usd") or 0.0)}})


class TestIdempotentCredit(_Sandbox):
    def test_same_op_id_credits_once(self):
        op = f"test-op:{uuid.uuid4().hex[:8]}"

        async def flow():
            from services.balances import credit_balance_idempotent
            first = await credit_balance_idempotent(UID, CUR, 5.0, op)
            second = await credit_balance_idempotent(UID, CUR, 5.0, op)
            return first, second

        first, second = _run(flow)
        assert first is True and second is False
        assert abs(_bal() - 5.0) < 1e-9, f"debió acreditarse UNA vez: {_bal()}"


class TestHealer(_Sandbox):
    def _plant_crashed_deposit(self, amount=7.5):
        """Simula el crash: depósito confirmado con marker sin abonar."""
        dep_id = f"dep_t249_{uuid.uuid4().hex[:8]}"
        marker = {"op_id": f"deposit-confirm:{uuid.uuid4().hex[:12]}",
                  "user_id": UID, "code": CUR, "amount": amount,
                  "legacy_usd": False, "at": OLD_TS}
        _db().deposits.insert_one({
            "id": dep_id, "user_id": UID, "user_email": "vip.test@resilience.com",
            "user_name": "VIP Test", "currency": CUR, "amount": amount,
            "method": "transfer", "status": "confirmed",
            "credit_pending": marker, "created_at": OLD_TS})
        return dep_id

    def test_healer_completes_crashed_credit_exactly_once(self):
        dep_id = self._plant_crashed_deposit(7.5)

        async def flow():
            from services.credit_recovery import heal_pending_credits
            n1 = await heal_pending_credits()
            n2 = await heal_pending_credits()
            return n1, n2

        n1, n2 = _run(flow)
        assert n1 >= 1, "el healer debió sanar el marker"
        assert abs(_bal() - 7.5) < 1e-9, f"saldo debió quedar 7.5, es {_bal()}"
        doc = _db().deposits.find_one({"id": dep_id}, {"_id": 0})
        assert "credit_pending" not in doc, "el marker debió limpiarse"

    def test_healer_skips_fresh_markers(self):
        """Un marker recién escrito (petición en vuelo) NO se toca."""
        from datetime import datetime, timezone
        dep_id = f"dep_t249_{uuid.uuid4().hex[:8]}"
        marker = {"op_id": f"deposit-confirm:{uuid.uuid4().hex[:12]}",
                  "user_id": UID, "code": CUR, "amount": 3.0,
                  "legacy_usd": False,
                  "at": datetime.now(timezone.utc).isoformat()}
        _db().deposits.insert_one({
            "id": dep_id, "user_id": UID, "currency": CUR, "amount": 3.0,
            "status": "confirmed", "credit_pending": marker})

        async def flow():
            from services.credit_recovery import heal_pending_credits
            return await heal_pending_credits()

        _run(flow)
        doc = _db().deposits.find_one({"id": dep_id}, {"_id": 0})
        assert doc.get("credit_pending"), "marker fresco no debe tocarse"
        assert abs(_bal() - 0.0) < 1e-9

    def test_crashed_accumulate_retry_unblocked_by_healer(self):
        """Escenario exacto del reporte: orden marcada accumulated_at sin
        abonar → el reintento devuelve False (flag consumido) pero el healer
        entrega el dinero igualmente."""
        oid = f"ord_t249_{uuid.uuid4().hex[:8]}"
        marker = {"op_id": f"order-accum:{uuid.uuid4().hex[:12]}",
                  "user_id": UID, "code": CUR, "amount": 42.0,
                  "legacy_usd": False, "at": OLD_TS}
        _db().orders.insert_one({
            "id": oid, "user_id": UID, "to_code": CUR, "amount_to": 42.0,
            "delivery_method": "accumulate", "status": "approved",
            "accumulated_at": OLD_TS, "credit_pending": marker})

        async def flow():
            from services.balances import accumulate_vip_balance
            from services.credit_recovery import heal_pending_credits
            order = None
            retry = await accumulate_vip_balance({
                "id": oid, "user_id": UID, "to_code": CUR, "amount_to": 42.0})
            healed = await heal_pending_credits()
            return retry, healed

        retry, healed = _run(flow)
        assert retry is False
        assert healed >= 1
        assert abs(_bal() - 42.0) < 1e-9, f"el healer debió abonar 42: {_bal()}"


class TestCancelVsRejectGuard(_Sandbox):
    def test_cancel_blocked_when_already_refunded(self):
        """Retiro aún 'pending' pero ya reembolsado (rechazo admin en vuelo):
        la cancelación del cliente NO puede reembolsar por segunda vez."""
        _db().users.update_one({"user_id": UID},
                               {"$set": {"vip_balances.USD": 50.0,
                                         "vip_balance_usd": 0.0}})
        wid = f"w_t249_{uuid.uuid4().hex[:8]}"
        _db().withdrawals.insert_one({
            "id": wid, "user_id": UID, "user_email": "vip.test@resilience.com",
            "user_name": "VIP Test", "amount_usd": 30.0, "currency": "USD",
            "method": "transfer", "status": "pending", "details": "t249",
            "balance_refunded": True, "created_at": OLD_TS})
        r = requests.post(f"{API}/vip/withdrawals/{wid}/cancel",
                          headers=VIP_H, timeout=15)
        assert r.status_code == 409, f"DOBLE REEMBOLSO posible: {r.status_code} {r.text}"
        u = _db().users.find_one({"user_id": UID},
                                 {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
        total = (float((u.get("vip_balances") or {}).get("USD") or 0)
                 + float(u.get("vip_balance_usd") or 0))
        assert abs(total - 50.0) < 1e-9, f"saldo no debió cambiar: {total}"


class TestE2EFlows(_Sandbox):
    def test_deposit_confirm_credits_and_clears_marker(self):
        dep_id = f"dep_t249_{uuid.uuid4().hex[:8]}"
        _db().deposits.insert_one({
            "id": dep_id, "user_id": UID, "user_email": "vip.test@resilience.com",
            "user_name": "VIP Test", "currency": CUR, "amount": 12.34,
            "method": "transfer", "status": "pending",
            "created_at": OLD_TS})
        r = requests.post(f"{API}/admin/deposits/{dep_id}/confirm",
                          headers=ADM_H, json=with_totp_admin({}), timeout=15)
        assert r.status_code == 200, r.text
        assert abs(_bal() - 12.34) < 1e-9
        doc = _db().deposits.find_one({"id": dep_id}, {"_id": 0})
        assert doc["status"] == "confirmed"
        assert "credit_pending" not in doc
        # segundo confirm → 409 y sin doble abono
        r2 = requests.post(f"{API}/admin/deposits/{dep_id}/confirm",
                           headers=ADM_H, json=with_totp_admin({}), timeout=15)
        assert r2.status_code == 409, r2.text
        assert abs(_bal() - 12.34) < 1e-9

    def test_capital_double_approve_disburses_once(self):
        cr_id = f"cr_t249_{uuid.uuid4().hex[:8]}"
        _db().capital_requests.insert_one({
            "id": cr_id, "user_id": UID, "user_email": "vip.test@resilience.com",
            "user_name": "VIP Test", "amount": 20.0, "currency_code": CUR,
            "reason": "test iter249", "status": "pending",
            "created_at": OLD_TS})
        body = with_totp_admin({"discount_pct": 10.0, "admin_notes": "t249"})
        r1 = requests.post(f"{API}/admin/capital-requests/{cr_id}/approve",
                           headers=ADM_H, json=body, timeout=15)
        assert r1.status_code == 200, r1.text
        body2 = with_totp_admin({"discount_pct": 10.0, "admin_notes": "t249"})
        r2 = requests.post(f"{API}/admin/capital-requests/{cr_id}/approve",
                           headers=ADM_H, json=body2, timeout=15)
        assert r2.status_code in (400, 409), f"doble desembolso: {r2.text}"
        assert abs(_bal() - 20.0) < 1e-9, f"debió desembolsarse UNA vez: {_bal()}"
        doc = _db().capital_requests.find_one({"id": cr_id}, {"_id": 0})
        assert doc["status"] == "disbursed"
        assert "credit_pending" not in doc
