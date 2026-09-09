"""iter254 — Correcciones de la auditoría externa R01–R11.

R01 claim atómico de transiciones de retiro · R02 reactivación explícita de
canjes rechazados (re-cobra y re-reserva) · R03 protocolo recuperable
initializing + conversión en una sola operación · R04 marker sin preparar en
acumulaciones · R05 dedupe duradero de op_ids · R06 canje exige producto
activo/aprobado · R07 marketplace liquida en USDT · R08 amortización
idempotente y condicional · R09 dashboard excluye canjes rechazados ·
R10 día contable America/Havana · R11 resumen de caja por agregación.
"""
import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests
from pymongo import MongoClient

from conftest import (BASE_URL, VIP_TOKEN, ADMIN_TOKEN, make_vip_totp, today_havana,
                      with_totp_admin)

API = f"{BASE_URL}/api"
VIP_H = {"Authorization": f"Bearer {VIP_TOKEN}"}
ADM_H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
UID = "user_test_vip01"
MARK = "iter254"
OLD_TS = "2026-01-01T00:00:00+00:00"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _bal(code):
    u = _db().users.find_one({"user_id": UID},
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


def _mk_product(price, stock, owner="user_test_normal01", active=True,
                approval="approved"):
    pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
    doc = {"id": pid, "name": f"Audit {pid}", "description": "", "image_url": "",
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
        u = _db().users.find_one({"user_id": UID},
                                 {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
        self._orig = u or {}

    def teardown_method(self, _):
        db = _db()
        db.redemptions.delete_many({"product_id": {"$regex": f"^prod_{MARK}"}})
        db.products.delete_many({"id": {"$regex": f"^prod_{MARK}"}})
        db.withdrawals.delete_many({"user_id": UID, "details": {"$regex": MARK}})
        db.withdrawals.delete_many({"id": {"$regex": f"^w_{MARK}"}})
        db.orders.delete_many({"id": {"$regex": f"^ord_{MARK}"}})
        db.capital_requests.delete_many({"id": {"$regex": f"^cr_{MARK}"}})
        db.inventory_movements.delete_many({"note": {"$regex": MARK}})
        db.inventory_movements.delete_many({"id": {"$regex": f"^mov_{MARK}"}})
        db.users.update_one({"user_id": UID}, {"$set": {
            "vip_balances": self._orig.get("vip_balances") or {},
            "vip_balance_usd": float(self._orig.get("vip_balance_usd") or 0.0)}})

    def _redeem(self, pid, qty=1):
        return requests.post(f"{API}/vip/redeem", json={
            "product_id": pid, "quantity": qty, "delivery_address": ""},
            headers=VIP_H, timeout=30)

    def _set_usdt(self, amount):
        _db().users.update_one({"user_id": UID},
                               {"$set": {"vip_balances.USDT": float(amount)}})


class TestR07MarketplaceSettlesUSDT(_Sandbox):
    def test_redeem_debits_usdt_not_usd(self):
        self._set_usdt(100.0)
        _db().users.update_one({"user_id": UID}, {"$set": {
            "vip_balances.USD": 55.0, "vip_balance_usd": 0.0}})
        pid = _mk_product(40.0, 5)
        r = self._redeem(pid)
        assert r.status_code == 200, r.text
        assert abs(_bal("USDT") - 60.0) < 1e-6, f"USDT: {_bal('USDT')}"
        assert abs(_bal("USD") - 55.0) < 1e-6, "USD no debe tocarse"
        doc = _db().redemptions.find_one({"product_id": pid}, {"_id": 0})
        assert doc["settlement_currency"] == "USDT"
        assert doc["status"] == "pending"
        assert "init_op_id" not in doc

    def test_insufficient_usdt_rejected_even_with_usd(self):
        self._set_usdt(5.0)
        _db().users.update_one({"user_id": UID},
                               {"$set": {"vip_balances.USD": 500.0}})
        pid = _mk_product(40.0, 5)
        r = self._redeem(pid)
        assert r.status_code in (400, 409), r.text
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 5, "el stock reservado debe devolverse"
        assert _db().redemptions.count_documents(
            {"product_id": pid, "status": {"$ne": "failed_init"}}) == 0

    def test_rejection_refunds_settlement_currency(self):
        self._set_usdt(50.0)
        pid = _mk_product(30.0, 3)
        r = self._redeem(pid)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        assert abs(_bal("USDT") - 20.0) < 1e-6
        rej = requests.put(f"{API}/admin/redemptions/{rid}/status",
                           headers=ADM_H,
                           json=with_totp_admin({"status": "rejected",
                                                 "admin_note": MARK}),
                           timeout=20)
        assert rej.status_code == 200, rej.text
        assert abs(_bal("USDT") - 50.0) < 1e-6, "reembolso debe ir a USDT"


class TestR06InactiveOrUnapproved(_Sandbox):
    def test_inactive_product_cannot_be_redeemed(self):
        self._set_usdt(100.0)
        pid = _mk_product(10.0, 5, active=False)
        r = self._redeem(pid)
        assert r.status_code == 400, r.text
        assert "disponible" in r.text

    def test_pending_vendor_product_cannot_be_redeemed(self):
        self._set_usdt(100.0)
        pid = _mk_product(10.0, 5, approval="pending")
        r = self._redeem(pid)
        assert r.status_code == 400, r.text


class TestR02Reactivation(_Sandbox):
    def _reject(self, rid):
        return requests.put(f"{API}/admin/redemptions/{rid}/status",
                            headers=ADM_H,
                            json=with_totp_admin({"status": "rejected",
                                                  "admin_note": MARK}),
                            timeout=20)

    def test_reactivation_recharges_and_reclaims_stock(self):
        self._set_usdt(80.0)
        pid = _mk_product(30.0, 1)
        r = self._redeem(pid)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        assert self._reject(rid).status_code == 200
        assert abs(_bal("USDT") - 80.0) < 1e-6
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 1, "el rechazo restituye stock"
        re = requests.put(f"{API}/admin/redemptions/{rid}/status",
                          headers=ADM_H,
                          json=with_totp_admin({"status": "pending",
                                                "admin_note": MARK}),
                          timeout=20)
        assert re.status_code == 200, f"reactivación falló: {re.text}"
        assert abs(_bal("USDT") - 50.0) < 1e-6, "reactivar debe RE-COBRAR"
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 0, "reactivar debe volver a reservar stock"
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["status"] == "pending"
        assert doc.get("rejection_applied") is False

    def test_reactivation_blocked_without_balance(self):
        self._set_usdt(30.0)
        pid = _mk_product(30.0, 2)
        r = self._redeem(pid)
        rid = r.json()["id"]
        assert self._reject(rid).status_code == 200
        self._set_usdt(3.0)  # gastó el reembolso
        re = requests.put(f"{API}/admin/redemptions/{rid}/status",
                          headers=ADM_H,
                          json=with_totp_admin({"status": "pending",
                                                "admin_note": MARK}),
                          timeout=20)
        assert re.status_code == 409, re.text
        doc = _db().redemptions.find_one({"id": rid}, {"_id": 0})
        assert doc["status"] == "rejected", "sin saldo NO se reactiva"
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 2, "stock compensado tras fallo de cobro"
        assert abs(_bal("USDT") - 3.0) < 1e-6


class TestR01WithdrawalStateMachine(_Sandbox):
    def test_concurrent_reject_and_approve_consistent(self):
        _db().users.update_one({"user_id": UID}, {"$set": {
            "vip_balances.USD": 50.0, "vip_balance_usd": 0.0}})
        r = requests.post(f"{API}/vip/withdraw", json={
            "amount_usd": 30.0, "currency": "USD", "method": "transfer",
            "details": f"Cuenta Zelle sm@example.com {MARK}",
            "beneficiary_name": "QA", "totp_code": make_vip_totp(),
        }, headers=VIP_H, timeout=30)
        assert r.status_code == 200, r.text
        wid = r.json()["id"]
        code = with_totp_admin({})["totp_code"]

        def put(status):
            return requests.put(f"{API}/admin/withdrawals/{wid}/status",
                                headers=ADM_H,
                                json={"status": status, "admin_note": MARK,
                                      "totp_code": code}, timeout=30)

        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(put, "rejected")
            f2 = ex.submit(put, "approved")
            r1, r2 = f1.result(), f2.result()
        doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        bal = _bal("USD")
        if doc["status"] == "rejected":
            assert doc.get("balance_refunded") is True
            assert abs(bal - 50.0) < 1e-6, f"rechazado ⇒ saldo 50, hay {bal}"
        else:
            assert doc["status"] == "approved"
            assert doc.get("balance_refunded") is not True
            assert abs(bal - 20.0) < 1e-6, f"aprobado ⇒ saldo 20, hay {bal}"
        assert not (doc["status"] == "approved"
                    and doc.get("balance_refunded") is True), \
            "estado contradictorio: aprobado con reembolso vigente"

    def test_stale_transition_gets_409(self):
        """La transición usa claim condicional: un doc que ya cambió de estado
        (simulado) responde 409 en vez de aplicar efectos duplicados."""
        wid = f"w_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().withdrawals.insert_one({
            "id": wid, "user_id": UID, "user_email": "vip.test@resilience.com",
            "user_name": "VIP", "amount_usd": 10.0, "currency": "USD",
            "method": "transfer", "status": "cancelled", "details": MARK,
            "balance_refunded": True, "created_at": OLD_TS})
        r = requests.put(f"{API}/admin/withdrawals/{wid}/status",
                         headers=ADM_H,
                         json=with_totp_admin({"status": "approved",
                                               "admin_note": MARK}),
                         timeout=20)
        assert r.status_code == 409, r.text


class TestR03Recovery(_Sandbox):
    def test_convert_is_single_atomic_operation(self):
        _db().users.update_one({"user_id": UID}, {"$set": {
            "vip_balances.USDT": 10.0, "vip_balances.EUR": 0.0,
            "vip_balances.USD": 100.0, "vip_balance_usd": 0.0}})
        r = requests.post(f"{API}/vip/convert", json={
            "from_code": "USD", "to_code": "USDT", "amount_from": 50,
            "totp_code": make_vip_totp()}, headers=VIP_H, timeout=20)
        assert r.status_code == 200, r.text
        assert abs(_bal("USD") - 50.0) < 1e-6

    def test_healer_reverts_stale_initializing_withdrawal(self):
        """Crash simulado tras el débito: el healer detecta por op_id que el
        cobro llegó a aplicarse, reembolsa y anula el doc."""
        self._set_usdt(0)
        _db().users.update_one({"user_id": UID}, {"$set": {
            "vip_balances.USD": 100.0, "vip_balance_usd": 0.0}})
        wid = f"w_{MARK}_{uuid.uuid4().hex[:8]}"
        op = f"withdraw-debit:{wid}"

        async def flow():
            from services.balances import debit_balance_idempotent
            from services.credit_recovery import heal_initializing_ops
            st = await debit_balance_idempotent(UID, "USD", 40.0, op)
            _db().withdrawals.insert_one({
                "id": wid, "user_id": UID, "amount_usd": 40.0,
                "currency": "USD", "method": "transfer", "details": MARK,
                "status": "initializing", "init_op_id": op,
                "created_at": OLD_TS})
            healed = await heal_initializing_ops()
            return st, healed

        st, healed = _run(flow)
        assert st == "applied" and healed >= 1
        assert abs(_bal("USD") - 100.0) < 1e-6, "el healer debió reembolsar"
        doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0, "status": 1})
        assert doc["status"] == "failed_init"

    def test_healer_completes_unapplied_inventory_movement(self):
        pid = _mk_product(10.0, 8, owner=None)
        mid = f"mov_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().inventory_movements.insert_one({
            "id": mid, "product_id": pid, "product_name": "x",
            "type": "venta", "quantity": 3, "needs_stock": True,
            "stock_applied": False, "created_at": OLD_TS, "note": MARK,
            "source": "manual", "total": 30.0, "profit": 0.0,
            "cost_of_sale": 0.0})

        async def flow():
            from services.credit_recovery import heal_initializing_ops
            n1 = await heal_initializing_ops()
            n2 = await heal_initializing_ops()
            return n1, n2

        _run(flow)
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 5, f"stock debió aplicarse UNA vez: {p['stock']}"
        m = _db().inventory_movements.find_one({"id": mid}, {"_id": 0})
        assert m.get("stock_applied") is True


class TestR04R08Accumulate(_Sandbox):
    def _mk_debt(self, amount, pct):
        cid = f"cr_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().capital_requests.insert_one({
            "id": cid, "user_id": UID, "amount": amount,
            "currency_code": "USDT", "status": "disbursed",
            "discount_pct": pct, "debt_original": amount,
            "debt_remaining": amount, "disbursed_at": OLD_TS,
            "created_at": OLD_TS})
        return cid

    def test_repayment_idempotent_per_order(self):
        self._set_usdt(0)
        cid = self._mk_debt(50.0, 50.0)
        oid = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"

        async def flow():
            from services.balances import _apply_capital_request_repayment
            n1 = await _apply_capital_request_repayment(UID, "USDT", 100.0, oid)
            n2 = await _apply_capital_request_repayment(UID, "USDT", 100.0, oid)
            return n1, n2

        n1, n2 = _run(flow)
        assert abs(n1 - 50.0) < 1e-6, f"neto primera vez: {n1}"
        assert abs(n2 - 50.0) < 1e-6, f"reejecución debe dar el MISMO neto: {n2}"
        d = _db().capital_requests.find_one({"id": cid}, {"_id": 0})
        assert abs(float(d["debt_remaining"]) - 0.0) < 1e-6
        assert d["status"] == "paid_off"
        evs = [e for e in d.get("repayment_events") or []
               if e.get("order_id") == oid]
        assert len(evs) == 1, "una sola contribución por orden y deuda"

    def test_healer_credits_net_not_gross_on_unprepared_marker(self):
        self._set_usdt(0)
        self._mk_debt(30.0, 30.0)
        oid = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"
        marker = {"op_id": f"order-accum:{uuid.uuid4().hex[:12]}",
                  "user_id": UID, "code": "USDT", "amount": 100.0,
                  "legacy_usd": False, "prepared": False, "at": OLD_TS}
        _db().orders.insert_one({
            "id": oid, "user_id": UID, "to_code": "USDT", "amount_to": 100.0,
            "delivery_method": "accumulate", "status": "approved",
            "accumulated_at": OLD_TS, "credit_pending": marker})

        async def flow():
            from services.credit_recovery import heal_pending_credits
            return await heal_pending_credits()

        _run(flow)
        # bruto 100, presupuesto 30% = 30 → deuda 30 saldada → neto 70
        assert abs(_bal("USDT") - 70.0) < 1e-6, \
            f"healer debió abonar el NETO (70), no el bruto: {_bal('USDT')}"
        doc = _db().orders.find_one({"id": oid}, {"_id": 0})
        assert "credit_pending" not in doc


class TestR05DurableDedupe(_Sandbox):
    def test_replay_blocked_even_after_registry_eviction(self):
        self._set_usdt(0)
        op = f"test-durable:{uuid.uuid4().hex[:10]}"

        async def flow():
            from services.balances import credit_balance_idempotent
            first = await credit_balance_idempotent(UID, "USDT", 9.0, op)
            # simular expulsión del registro embebido (cap 2000)
            _db().users.update_one({"user_id": UID},
                                   {"$pull": {"applied_credit_ops": op}})
            second = await credit_balance_idempotent(UID, "USDT", 9.0, op)
            return first, second

        first, second = _run(flow)
        assert first is True
        assert second is False, "el log duradero debe bloquear el replay"
        assert abs(_bal("USDT") - 9.0) < 1e-6


class TestR09R10R11(_Sandbox):
    def test_dashboard_excludes_rejected_redemption_sales(self):
        self._set_usdt(200.0)
        pid = _mk_product(25.0, 4, owner=None)
        r = self._redeem(pid)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]

        async def flow():
            from services.inventory import build_dashboard
            from datetime import datetime
            today = today_havana()
            before = await build_dashboard(today, today, [pid])
            rej = await asyncio.to_thread(
                requests.put, f"{API}/admin/redemptions/{rid}/status",
                headers=ADM_H,
                json=with_totp_admin({"status": "rejected",
                                      "admin_note": MARK}), timeout=20)
            after = await build_dashboard(today, today, [pid])
            return before, rej, after

        before, rej, after = _run(flow)
        assert abs(before["sales_revenue"] - 25.0) < 1e-6, before
        assert rej.status_code == 200, rej.text
        assert abs(after["sales_revenue"] - 0.0) < 1e-6, \
            f"venta rechazada aún cuenta: {after['sales_revenue']}"

    def test_day_bounds_use_havana(self):
        from services.inventory import _day_bounds
        s, e = _day_bounds("2026-06-15")
        assert s == "2026-06-15T04:00:00+00:00", s  # EDT = UTC-4
        assert e == "2026-06-16T04:00:00+00:00", e

    def test_fund_summary_uses_aggregation_totals(self):
        db = _db()
        box_id = f"box_{MARK}_{uuid.uuid4().hex[:6]}"
        db.cash_boxes.insert_one({
            "id": box_id, "owner_id": "user_test_admin01", "name": MARK,
            "scope": "personal",
            "initial": {"USD": {"amount": 100.0,
                                "denominations": {"20": 5}}},
            "created_at": OLD_TS})
        rows = []
        for i in range(30):
            rows.append({"id": f"cbm_{MARK}_{i}", "box_id": box_id,
                         "fund": "USD",
                         "type": "entrada" if i % 2 == 0 else "salida",
                         "amount": 10.0,
                         "denominations": {"10": 1},
                         "created_at": OLD_TS})
        db.cash_box_movements.insert_many(rows)
        try:
            r = requests.get(f"{API}/cashbox/boxes/{box_id}/resumen",
                             params={"fund": "USD"}, headers=ADM_H, timeout=20)
            assert r.status_code == 200, r.text
            data = r.json()
            assert abs(data["entradas_total"] - 150.0) < 1e-6
            assert abs(data["salidas_total"] - 150.0) < 1e-6
            assert abs(data["balance"] - 100.0) < 1e-6
            assert data["num_movimientos"] == 30
            den10 = next(d for d in data["denominaciones"] if d["denom"] == 10)
            assert den10["qty"] == 0  # +15 entradas −15 salidas
            den20 = next(d for d in data["denominaciones"] if d["denom"] == 20)
            assert den20["qty"] == 5
        finally:
            db.cash_boxes.delete_one({"id": box_id})
            db.cash_box_movements.delete_many({"box_id": box_id})
