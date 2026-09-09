"""iter256 — Correcciones de la segunda revisión externa S01–S12.

S01 transición de retiro con efectos vinculados en un solo claim ·
S02 rechazo de canje reanudable (efectos idempotentes por ciclo) + recogida
por código condicional · S03 healer reclama antes de compensar ·
S04 plan de reactivación persistente (op_ids estables) · S05 ciclo del
vendedor archivado y re-liquidable · S06 log duradero insert-first de créditos
· S07 log duradero de stock · S08 presupuesto de amortización estable por
orden · S09 mensajería de canjes cotizada en la moneda de liquidación ·
S10 recuperación de stock fallida ≠ aplicada + asiento contable ·
S11 control/rotación excluyen canjes rechazados.
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
VENDOR_ID = "user_test_normal01"
MARK = "iter256"
OLD_TS = "2026-01-01T00:00:00+00:00"


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


def _mk_product(price, stock, owner=VENDOR_ID, active=True,
                approval="approved"):
    pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
    doc = {"id": pid, "name": f"Rev {pid}", "description": "", "image_url": "",
           "price_usd": float(price), "cost_usd": 0.0, "stock": int(stock),
           "category": "general", "is_active": active,
           "owner_id": owner, "owner_name": "Vendor Test",
           "approval_status": approval, "rejection_reason": "",
           "available_store_ids": [], "created_at": OLD_TS}
    if owner is None:
        doc["owner_id"] = ""
        doc.pop("approval_status")
    _db().products.insert_one(doc)
    return pid


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
        db.redemptions.delete_many({"product_id": {"$regex": f"^prod_{MARK}"}})
        db.redemptions.delete_many({"id": {"$regex": f"^red_{MARK}"}})
        db.products.delete_many({"id": {"$regex": f"^prod_{MARK}"}})
        db.withdrawals.delete_many({"id": {"$regex": f"^w_{MARK}"}})
        db.capital_requests.delete_many({"id": {"$regex": f"^cr_{MARK}"}})
        db.repayment_plans.delete_many({"order_id": {"$regex": f"^ord_{MARK}"}})
        db.inventory_movements.delete_many({"note": {"$regex": MARK}})
        db.inventory_movements.delete_many({"id": {"$regex": f"^mov_{MARK}"}})
        db.inventory_movements.delete_many(
            {"product_id": {"$regex": f"^prod_{MARK}"}})
        db.company_fund_adjustments.delete_many(
            {"ref_id": {"$regex": f"^(mov|red|prod)_{MARK}"}})
        db.deliveries.delete_many({"ref_id": {"$regex": f"^red_{MARK}"}})
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

    def _redeem(self, pid, qty=1):
        return requests.post(f"{API}/vip/redeem", json={
            "product_id": pid, "quantity": qty, "delivery_address": ""},
            headers=VIP_H, timeout=30)

    def _put_redemption(self, rid, status):
        return requests.put(f"{API}/admin/redemptions/{rid}/status",
                            headers=ADM_H,
                            json=with_totp_admin({"status": status,
                                                  "admin_note": MARK}),
                            timeout=20)


# ======================================================================
# S01 — retiros: transición + efecto de saldo en un solo claim
# ======================================================================
class TestS01WithdrawalStateMachine(_Sandbox):
    def _mk_w(self, status="pending", amount=25.0, **extra):
        wid = f"w_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().withdrawals.insert_one({
            "id": wid, "user_id": UID, "user_email": "vip@test",
            "user_name": "VIP Test", "amount_usd": float(amount),
            "currency": "USDT", "method": "crypto",
            "details": f"{MARK} TRC20 test", "status": status,
            "created_at": OLD_TS, "updated_at": OLD_TS, **extra})
        return wid

    def _put(self, wid, status):
        return requests.put(f"{API}/admin/withdrawals/{wid}/status",
                            headers=ADM_H,
                            json=with_totp_admin({"status": status,
                                                  "admin_note": MARK}),
                            timeout=20)

    def test_reject_refunds_once_flags_travel_with_status(self):
        self._set_usdt(0.0)
        wid = self._mk_w()
        r = self._put(wid, "rejected")
        assert r.status_code == 200, r.text
        doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert doc["status"] == "rejected"
        assert doc["balance_refunded"] is True
        assert "credit_pending" not in doc, "marker debe quedar aplicado y limpio"
        assert abs(_bal("USDT") - 25.0) < 1e-6
        # repetir el mismo estado no re-reembolsa
        r2 = self._put(wid, "rejected")
        assert r2.status_code == 200, r2.text
        assert abs(_bal("USDT") - 25.0) < 1e-6

    def test_leaving_rejected_redebits_and_reverts_on_insufficient(self):
        self._set_usdt(0.0)
        wid = self._mk_w()
        assert self._put(wid, "rejected").status_code == 200
        assert abs(_bal("USDT") - 25.0) < 1e-6
        # reactivar con saldo → re-débito
        r = self._put(wid, "pending")
        assert r.status_code == 200, r.text
        assert abs(_bal("USDT") - 0.0) < 1e-6
        doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert doc["balance_refunded"] is False
        assert "redebit_pending" not in doc
        # rechazar de nuevo → segundo reembolso legítimo
        assert self._put(wid, "rejected").status_code == 200
        assert abs(_bal("USDT") - 25.0) < 1e-6
        # gastar el reembolso y reactivar → 409 con reverso limpio
        self._set_usdt(0.0)
        r = self._put(wid, "pending")
        assert r.status_code == 409, r.text
        doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert doc["status"] == "rejected"
        assert doc["balance_refunded"] is True
        assert "redebit_pending" not in doc

    def test_legacy_rejected_without_flag_moves_without_money(self):
        self._set_usdt(10.0)
        wid = self._mk_w(status="rejected")
        r = self._put(wid, "pending")
        assert r.status_code == 200, r.text
        assert abs(_bal("USDT") - 10.0) < 1e-6, "no debe debitar sin reembolso previo"

    def test_transient_docs_not_operable(self):
        for st in ("initializing", "failed_init"):
            wid = self._mk_w(status=st)
            r = self._put(wid, "approved")
            assert r.status_code == 409, f"{st}: {r.text}"


# ======================================================================
# S02 — rechazo de canje reanudable + recogida por código condicional
# ======================================================================
class TestS02RejectionResumable(_Sandbox):
    def test_interrupted_rejection_completes_on_retry(self):
        self._set_usdt(100.0)
        pid = _mk_product(30.0, 3, owner=None)  # producto EMPRESA
        r = self._redeem(pid)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        assert abs(_bal("USDT") - 70.0) < 1e-6
        assert _db().products.find_one({"id": pid})["stock"] == 2
        # crash simulado: transición reclamada, CERO efectos aplicados
        _db().redemptions.update_one({"id": rid}, {"$set": {
            "status": "rejected", "rejection_flow_started": True,
            "rejection_applied": False, "rejection_effects_done": False,
            "rejection_cycle": 1}})
        put = self._put_redemption(rid, "rejected")
        assert put.status_code == 200, put.text
        assert abs(_bal("USDT") - 100.0) < 1e-6, "reembolso completado"
        assert _db().products.find_one({"id": pid})["stock"] == 3
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["rejection_applied"] is True
        assert doc["rejection_effects_done"] is True
        # retry adicional: nada se duplica
        put2 = self._put_redemption(rid, "rejected")
        assert put2.status_code == 200, put2.text
        assert abs(_bal("USDT") - 100.0) < 1e-6
        assert _db().products.find_one({"id": pid})["stock"] == 3
        assert _db().inventory_movements.count_documents(
            {"ref_id": rid, "type": "ajuste_pos"}) == 1

    def test_pickup_code_cannot_deliver_rejected(self):
        pid = _mk_product(20.0, 1, owner=None)
        code = "43219876"
        rid = f"red_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().redemptions.insert_one({
            "id": rid, "user_id": UID, "product_id": pid,
            "product_name": "Rev pickup", "quantity": 1, "total_usd": 20.0,
            "status": "rejected", "settlement_currency": "USDT",
            "fulfillment": "store_pickup", "pickup_code": code,
            "vendor_owner_id": VENDOR_ID, "created_at": OLD_TS})
        vend0 = _bal("USDT", VENDOR_ID)
        resp = requests.post(f"{API}/admin/pickups/confirm", headers=ADM_H,
                             json=with_totp_admin({"code": code}), timeout=20)
        assert resp.status_code in (404, 409), resp.text
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["status"] == "rejected", "no debe sobrescribir el rechazo"
        assert not doc.get("vendor_credited_at"), "vendedor no debe cobrar"
        assert abs(_bal("USDT", VENDOR_ID) - vend0) < 1e-6


# ======================================================================
# S03 — healer reclama antes de compensar
# ======================================================================
class TestS03HealerClaimsFirst(_Sandbox):
    def _mk_w(self, status, op, amount=25.0):
        wid = f"w_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().withdrawals.insert_one({
            "id": wid, "user_id": UID, "amount_usd": float(amount),
            "currency": "USDT", "method": "crypto", "details": f"{MARK}",
            "status": status, "init_op_id": op, "created_at": OLD_TS})
        return wid

    def test_stale_initializing_withdrawal_reverted_once(self):
        self._set_usdt(100.0)
        op = f"withdrawal-init:{MARK}:{uuid.uuid4().hex[:8]}"
        wid = self._mk_w("initializing", op)

        async def flow():
            from services.balances import debit_balance_idempotent
            from services.credit_recovery import heal_initializing_ops
            st = await debit_balance_idempotent(UID, "USDT", 25.0, op)
            await heal_initializing_ops()
            await heal_initializing_ops()  # idempotente
            return st

        st = _run(flow)
        assert st == "applied"
        doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert doc["status"] == "failed_init"
        assert "init_op_id" not in doc, "op consumido tras compensar"
        assert abs(_bal("USDT") - 100.0) < 1e-6, "débito revertido una sola vez"

    def test_failed_init_with_pending_op_compensated(self):
        """Crash a mitad de la compensación: el doc quedó failed_init con el
        op_id vivo — la segunda pasada del healer termina el reverso."""
        self._set_usdt(100.0)
        op = f"withdrawal-init:{MARK}:{uuid.uuid4().hex[:8]}"
        wid = self._mk_w("failed_init", op)

        async def flow():
            from services.balances import debit_balance_idempotent
            from services.credit_recovery import heal_initializing_ops
            await debit_balance_idempotent(UID, "USDT", 25.0, op)
            await heal_initializing_ops()

        _run(flow)
        doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert "init_op_id" not in doc
        assert abs(_bal("USDT") - 100.0) < 1e-6


# ======================================================================
# S04 — plan de reactivación persistente
# ======================================================================
class TestS04ReactivationPlan(_Sandbox):
    def _rejected_redemption(self, price=30.0, stock=2):
        self._set_usdt(100.0)
        pid = _mk_product(price, stock, owner=None)
        r = self._redeem(pid)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        assert self._put_redemption(rid, "rejected").status_code == 200
        assert abs(_bal("USDT") - 100.0) < 1e-6
        return pid, rid

    def test_stale_plan_compensated_by_healer(self):
        pid, rid = self._rejected_redemption()
        stock0 = _db().products.find_one({"id": pid})["stock"]
        stock_op = f"reactivate-stock:{rid}:{MARK}dead"
        debit_op = f"reactivate-debit:{rid}:{MARK}dead"
        _db().redemptions.update_one({"id": rid}, {"$set": {
            "reactivation_pending": {
                "stock_op": stock_op, "debit_op": debit_op, "amount": 30.0,
                "currency": "USDT", "quantity": 1, "target": "pending",
                "at": OLD_TS, "by": "user_test_admin01"}}})

        async def flow():
            from services.balances import debit_balance_idempotent
            from services.inventory import apply_stock_idempotent
            from services.credit_recovery import heal_initializing_ops
            await apply_stock_idempotent(pid, -1, stock_op)
            await debit_balance_idempotent(UID, "USDT", 30.0, debit_op)
            await heal_initializing_ops()
            await heal_initializing_ops()  # idempotente

        _run(flow)
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["status"] == "rejected"
        assert "reactivation_pending" not in doc
        assert abs(_bal("USDT") - 100.0) < 1e-6, "cobro del intento muerto revertido"
        assert _db().products.find_one({"id": pid})["stock"] == stock0

    def test_retry_reuses_persisted_plan_single_charge(self):
        pid, rid = self._rejected_redemption()
        stock0 = _db().products.find_one({"id": pid})["stock"]
        from datetime import datetime, timezone
        stock_op = f"reactivate-stock:{rid}:{MARK}retry"
        debit_op = f"reactivate-debit:{rid}:{MARK}retry"
        _db().redemptions.update_one({"id": rid}, {"$set": {
            "reactivation_pending": {
                "stock_op": stock_op, "debit_op": debit_op, "amount": 30.0,
                "currency": "USDT", "quantity": 1, "target": "pending",
                "at": datetime.now(timezone.utc).isoformat(),
                "by": "user_test_admin01"}}})

        async def flow():
            from services.balances import debit_balance_idempotent
            from services.inventory import apply_stock_idempotent
            await apply_stock_idempotent(pid, -1, stock_op)
            await debit_balance_idempotent(UID, "USDT", 30.0, debit_op)

        _run(flow)  # primer intento murió tras cobrar, antes del claim final
        put = self._put_redemption(rid, "pending")
        assert put.status_code == 200, put.text
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["status"] == "pending"
        assert "reactivation_pending" not in doc
        assert abs(_bal("USDT") - 70.0) < 1e-6, "un solo cobro (op_ids reutilizados)"
        assert _db().products.find_one({"id": pid})["stock"] == stock0 - 1


# ======================================================================
# S05 — ciclo del vendedor re-liquidable tras reactivación
# ======================================================================
class TestS05VendorCycleReset(_Sandbox):
    def test_vendor_paid_again_after_reactivation(self):
        _db().settings.update_one({"id": "global"}, {"$set": {
            "vendor_commission_pct": 10.0,
            "courier_rate_usdt_per_km": 0}}, upsert=True)
        self._set_usdt(100.0)
        self._set_usdt(0.0, uid=VENDOR_ID)
        pid = _mk_product(30.0, 1)  # producto de VENDEDOR
        r = self._redeem(pid)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        assert abs(_bal("USDT") - 70.0) < 1e-6
        # entregar → vendedor cobra el neto (30 − 10 %)
        assert self._put_redemption(rid, "delivered").status_code == 200
        assert abs(_bal("USDT", VENDOR_ID) - 27.0) < 1e-6
        # rechazar → todo se revierte
        assert self._put_redemption(rid, "rejected").status_code == 200
        assert abs(_bal("USDT") - 100.0) < 1e-6
        assert abs(_bal("USDT", VENDOR_ID) - 0.0) < 1e-6
        assert _db().products.find_one({"id": pid})["stock"] == 1
        # reactivar a entregado → cliente re-paga y el VENDEDOR COBRA de nuevo
        put = self._put_redemption(rid, "delivered")
        assert put.status_code == 200, put.text
        assert abs(_bal("USDT") - 70.0) < 1e-6
        assert abs(_bal("USDT", VENDOR_ID) - 27.0) < 1e-6, \
            "el nuevo ciclo debe pagar al vendedor (S05)"
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["status"] == "delivered"
        assert doc.get("vendor_credited_at"), "ciclo nuevo liquidado"
        assert not doc.get("vendor_credit_reversed_at")
        assert len(doc.get("settlement_cycles") or []) >= 1, \
            "el ciclo anterior queda archivado para auditoría"


# ======================================================================
# S06 — log duradero de créditos: insert-first + reparación
# ======================================================================
class TestS06DurableCreditLog(_Sandbox):
    def test_eviction_from_embedded_registry_does_not_allow_replay(self):
        self._set_usdt(0.0)
        op = f"credit:{MARK}:{uuid.uuid4().hex[:8]}"

        async def flow():
            from services.balances import credit_balance_idempotent
            first = await credit_balance_idempotent(UID, "USDT", 10.0, op)
            # simular evicción del registro embebido (cap 2000 superado)
            _db().users.update_one({"user_id": UID},
                                   {"$pull": {"applied_credit_ops": op}})
            replay = await credit_balance_idempotent(UID, "USDT", 10.0, op)
            return first, replay

        first, replay = _run(flow)
        assert first is True
        assert replay is False, "el log duradero debe bloquear el replay"
        assert abs(_bal("USDT") - 10.0) < 1e-6
        log = _db().credit_ops.find_one({"op_id": op}, {"_id": 0})
        assert log and log.get("state") == "applied"
        _db().credit_ops.delete_one({"op_id": op})

    def test_retry_repairs_missing_durable_log(self):
        """Caída histórica entre saldo y log: el op vive en el registro
        embebido pero no en credit_ops → el retry repara el log sin duplicar."""
        self._set_usdt(10.0)
        op = f"credit:{MARK}:{uuid.uuid4().hex[:8]}"
        _db().users.update_one({"user_id": UID},
                               {"$push": {"applied_credit_ops": op}})
        assert _db().credit_ops.find_one({"op_id": op}) is None

        async def retry():
            from services.balances import credit_balance_idempotent
            return await credit_balance_idempotent(UID, "USDT", 10.0, op)

        assert _run(retry) is False
        assert abs(_bal("USDT") - 10.0) < 1e-6, "sin doble abono"
        log = _db().credit_ops.find_one({"op_id": op}, {"_id": 0})
        assert log and log.get("state") == "applied", "log reparado"
        _db().credit_ops.delete_one({"op_id": op})
        _db().users.update_one({"user_id": UID},
                               {"$pull": {"applied_credit_ops": op}})


# ======================================================================
# S07 — log duradero de operaciones de stock
# ======================================================================
class TestS07DurableStockLog(_Sandbox):
    def test_eviction_from_product_registry_does_not_allow_replay(self):
        pid = _mk_product(10.0, 5, owner=None)
        op = f"stock:{MARK}:{uuid.uuid4().hex[:8]}"

        async def flow():
            from services.inventory import apply_stock_idempotent
            first = await apply_stock_idempotent(pid, -2, op)
            # simular evicción del registro embebido (cap 500 superado)
            _db().products.update_one({"id": pid},
                                      {"$pull": {"applied_stock_ops": op}})
            replay = await apply_stock_idempotent(pid, -2, op)
            return first, replay

        first, replay = _run(flow)
        assert first == "applied"
        assert replay == "duplicate", "el log duradero bloquea el replay"
        assert _db().products.find_one({"id": pid})["stock"] == 3
        log = _db().stock_ops.find_one({"op_id": op}, {"_id": 0})
        assert log and log.get("state") == "applied"
        _db().stock_ops.delete_one({"op_id": op})


# ======================================================================
# S08 — presupuesto de amortización estable por orden
# ======================================================================
class TestS08StableRepaymentBudget(_Sandbox):
    def test_retry_uses_persisted_budget_not_current_debts(self):
        db = _db()
        cr_a = f"cr_{MARK}_{uuid.uuid4().hex[:6]}"
        cr_b = f"cr_{MARK}_{uuid.uuid4().hex[:6]}"
        db.capital_requests.insert_many([
            {"id": cr_a, "user_id": UID, "status": "disbursed",
             "currency_code": "USDT", "discount_pct": 10.0,
             "debt_remaining": 10.0, "disbursed_at": "2026-01-01T00:00:00+00:00",
             "repayment_events": []},
            {"id": cr_b, "user_id": UID, "status": "disbursed",
             "currency_code": "USDT", "discount_pct": 50.0,
             "debt_remaining": 100.0, "disbursed_at": "2026-02-01T00:00:00+00:00",
             "repayment_events": []},
        ])
        order_id = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"

        async def flow():
            from services.balances import _apply_capital_request_repayment
            net1 = await _apply_capital_request_repayment(
                UID, "USDT", 100.0, order_id)
            # el mundo cambió: la deuda vieja (10 %) ya se pagó; un retry NO
            # debe recalcular con el 50 % de la deuda B.
            net2 = await _apply_capital_request_repayment(
                UID, "USDT", 100.0, order_id)
            return net1, net2

        net1, net2 = _run(flow)
        assert abs(net1 - 90.0) < 1e-6, f"presupuesto = 10 % de 100: {net1}"
        assert abs(net2 - 90.0) < 1e-6, f"neto estable en retry: {net2}"
        a = db.capital_requests.find_one({"id": cr_a}, {"_id": 0})
        assert a["status"] == "paid_off"
        b = db.capital_requests.find_one({"id": cr_b}, {"_id": 0})
        assert abs(float(b["debt_remaining"]) - 100.0) < 1e-6, \
            "la deuda B no debe amortizarse en el retry"
        plan = db.repayment_plans.find_one({"order_id": order_id}, {"_id": 0})
        assert plan and abs(float(plan["budget_total"]) - 10.0) < 1e-6


# ======================================================================
# S09 — mensajería de canjes cotizada en la moneda de liquidación
# ======================================================================
class TestS09CourierFeeSettlementCurrency(_Sandbox):
    def test_admin_fee_uses_usdt_units_not_usd_conversion(self):
        db = _db()
        db.settings.update_one({"id": "global"}, {"$set": {
            "courier_rate_usdt_per_km": 0.5, "courier_min_fee_usdt": 2.0,
            "courier_free_min_usdt": 1000.0}}, upsert=True)
        # tasa divergente USDT→USD: si el fee se cotizara en USD, saldría 4.4
        prev = db.rates.find_one({"from_code": "USDT", "to_code": "USD"})
        db.rates.update_one({"from_code": "USDT", "to_code": "USD"},
                            {"$set": {"rate_normal": 1.1}}, upsert=True)
        try:
            self._set_usdt(100.0)
            pid = _mk_product(30.0, 2, owner=None)
            r = self._redeem(pid)
            assert r.status_code == 200, r.text
            rid = r.json()["id"]
            assert abs(_bal("USDT") - 70.0) < 1e-6
            resp = requests.post(f"{API}/admin/redemptions/{rid}/courier-fee",
                                 headers=ADM_H,
                                 json=with_totp_admin({"km": 8}), timeout=20)
            assert resp.status_code == 200, resp.text
            doc = db.redemptions.find_one({"id": rid}, {"_id": 0})
            assert abs(float(doc["courier_fee_usdt"]) - 4.0) < 1e-6
            assert abs(float(doc["courier_fee_usd"]) - 4.0) < 1e-6, \
                "la cifra cobrada debe estar en USDT (liquidación), no 4.4 USD"
            assert abs(_bal("USDT") - 66.0) < 1e-6, "débito = 4.0 USDT exactos"
        finally:
            if prev:
                db.rates.update_one(
                    {"from_code": "USDT", "to_code": "USD"},
                    {"$set": {"rate_normal": prev.get("rate_normal")}})
            else:
                db.rates.delete_one({"from_code": "USDT", "to_code": "USD"})


# ======================================================================
# S10 — recuperación de stock: fallido ≠ aplicado + asiento contable
# ======================================================================
class TestS10RecoveryAccounting(_Sandbox):
    def _mk_mov(self, pid, qty=2, total=20.0):
        mid = f"mov_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().inventory_movements.insert_one({
            "id": mid, "product_id": pid, "product_name": "Rev mov",
            "type": "venta", "source": "manual", "quantity": int(qty),
            "total": float(total), "profit": 5.0, "needs_stock": True,
            "stock_applied": False, "note": MARK, "created_at": OLD_TS})
        return mid

    def test_failed_recovery_marks_failed_not_applied(self):
        pid = _mk_product(10.0, 0, owner=None)
        mid = self._mk_mov(pid, qty=2)

        async def flow():
            from services.credit_recovery import heal_initializing_ops
            from services.inventory import build_control_rows
            await heal_initializing_ops()
            await heal_initializing_ops()
            return await build_control_rows()

        rows_all = _run(flow)
        doc = _db().inventory_movements.find_one({"id": mid}, {"_id": 0})
        assert doc.get("stock_apply_failed") is True
        assert doc.get("stock_applied") is not True, \
            "fallido y aplicado son estados mutuamente excluyentes"
        assert _db().products.find_one({"id": pid})["stock"] == 0
        rows = [x for x in rows_all if x["product_id"] == pid]
        assert rows and rows[0]["ventas"] == 0, \
            "una venta fallida no cuenta en el control de inventario"

    def test_successful_recovery_records_fund_flow_once(self):
        pid = _mk_product(10.0, 5, owner=None)
        mid = self._mk_mov(pid, qty=1)

        async def flow():
            from services.credit_recovery import heal_initializing_ops
            await heal_initializing_ops()
            await heal_initializing_ops()

        _run(flow)
        doc = _db().inventory_movements.find_one({"id": mid}, {"_id": 0})
        assert doc.get("stock_applied") is True
        assert doc.get("fund_flow_recorded") is True
        assert _db().products.find_one({"id": pid})["stock"] == 4
        n = _db().company_fund_adjustments.count_documents({"ref_id": mid})
        assert n == 1, f"asiento contable exactamente una vez, hay {n}"


# ======================================================================
# S11 — control/rotación excluyen ventas de canjes rechazados
# ======================================================================
class TestS11ControlExcludesRejected(_Sandbox):
    def test_control_rows_exclude_rejected_marketplace_sales(self):
        self._set_usdt(100.0)
        pid = _mk_product(30.0, 3, owner=None)
        r = self._redeem(pid)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        assert self._put_redemption(rid, "rejected").status_code == 200

        async def control():
            from services.inventory import build_control_rows
            return await build_control_rows()

        rows = [x for x in _run(control) if x["product_id"] == pid]
        assert rows, "el producto debe aparecer en el control"
        assert rows[0]["ventas"] == 0, \
            "la venta de un canje rechazado no debe contar"
        assert rows[0]["ajustes_pos"] == 0, \
            "el reverso del rechazo tampoco debe contar (se cancelan)"
        assert rows[0]["stock"] == 3
