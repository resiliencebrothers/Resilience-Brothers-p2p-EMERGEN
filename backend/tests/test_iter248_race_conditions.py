"""iter248 — TOCTOU: la comprobación de saldo y el descuento ocurrían por
separado; dos solicitudes simultáneas podían gastar el mismo dinero y dejar
saldo negativo. Fix: débito atómico condicional (guard $gte + $inc en UNA
operación MongoDB) en decrement_balance + claim atómico de stock en canjes +
claim de reembolso exactamente-una-vez en rechazos de retiros/canjes.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests
from pymongo import MongoClient

from conftest import BASE_URL, VIP_TOKEN, ADMIN_TOKEN, make_vip_totp, make_admin_totp

API = f"{BASE_URL}/api"
VIP_H = {"Authorization": f"Bearer {VIP_TOKEN}"}
ADM_H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
UID = "user_test_vip01"
MARK = "iter248"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _get_usd():
    u = _db().users.find_one({"user_id": UID},
                             {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
    return (float((u.get("vip_balances") or {}).get("USD") or 0.0),
            float(u.get("vip_balance_usd") or 0.0))


def _set_usd(modern, legacy=0.0):
    _db().users.update_one({"user_id": UID}, {"$set": {
        "vip_balances.USD": modern, "vip_balance_usd": legacy}})


def _mk_product(price, stock):
    pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
    _db().products.insert_one({
        "id": pid, "name": f"Race Test {pid}", "description": "", "image_url": "",
        "price_usd": float(price), "cost_usd": 0.0, "stock": int(stock),
        "category": "general", "is_active": True,
        "owner_id": "user_test_normal01", "owner_name": "Normal Test",
        "approval_status": "approved", "rejection_reason": "",
        "available_store_ids": [], "created_at": "2026-06-01T00:00:00+00:00"})
    return pid


class _UsdSandbox:
    """Guarda/restaura el saldo USD del VIP y limpia docs creados."""

    def setup_method(self, _):
        self._orig = _get_usd()

    def teardown_method(self, _):
        db = _db()
        db.withdrawals.delete_many({"user_id": UID, "details": {"$regex": MARK}})
        db.redemptions.delete_many({"product_id": {"$regex": f"^prod_{MARK}"}})
        db.products.delete_many({"id": {"$regex": f"^prod_{MARK}"}})
        _set_usd(self._orig[0], self._orig[1])


class TestWithdrawRace(_UsdSandbox):
    def test_concurrent_withdrawals_cannot_double_spend(self):
        _set_usd(100.0, 0.0)
        code = make_vip_totp()

        def fire(_):
            return requests.post(f"{API}/vip/withdraw", json={
                "amount_usd": 100.0, "currency": "USD", "method": "transfer",
                "details": f"Cuenta Zelle race@example.com {MARK}",
                "beneficiary_name": "Iter248 QA", "totp_code": code,
            }, headers=VIP_H, timeout=30)

        with ThreadPoolExecutor(max_workers=4) as ex:
            rs = list(ex.map(fire, range(4)))
        codes = [r.status_code for r in rs]
        ok = [r for r in rs if r.status_code == 200]
        assert len(ok) == 1, f"DOBLE GASTO: {len(ok)} retiros de 100 aceptados con saldo 100 ({codes})"
        modern, legacy = _get_usd()
        total = modern + legacy
        assert total > -1e-9, f"Saldo NEGATIVO tras la carrera: {total}"
        assert abs(total) < 1e-6, f"Saldo final debería ser 0, es {total}"
        for r in rs:
            if r.status_code != 200:
                assert r.status_code in (400, 409), r.text

    def test_withdraw_debits_legacy_then_modern_usd(self):
        """El débito atómico de USD respeta el orden legacy-primero."""
        _set_usd(50.0, 60.0)
        r = requests.post(f"{API}/vip/withdraw", json={
            "amount_usd": 100.0, "currency": "USD", "method": "transfer",
            "details": f"Cuenta Zelle legacy@example.com {MARK}",
            "beneficiary_name": "Iter248 QA", "totp_code": make_vip_totp(),
        }, headers=VIP_H, timeout=30)
        assert r.status_code == 200, r.text
        modern, legacy = _get_usd()
        assert abs(legacy) < 1e-6, f"legacy debió quedar en 0, es {legacy}"
        assert abs(modern - 10.0) < 1e-6, f"modern debió quedar en 10, es {modern}"


class TestRedeemRace(_UsdSandbox):
    def _redeem(self, pid):
        return requests.post(f"{API}/vip/redeem", json={
            "product_id": pid, "quantity": 1, "delivery_address": "",
        }, headers=VIP_H, timeout=30)

    def test_concurrent_redeems_cannot_double_spend_balance(self):
        _set_usd(60.0, 0.0)
        pid = _mk_product(price=60.0, stock=10)
        with ThreadPoolExecutor(max_workers=4) as ex:
            rs = list(ex.map(lambda _: self._redeem(pid), range(4)))
        codes = [r.status_code for r in rs]
        ok = [r for r in rs if r.status_code == 200]
        assert len(ok) == 1, f"DOBLE GASTO en canje: {len(ok)} aceptados con saldo 60 ({codes})"
        modern, legacy = _get_usd()
        assert modern + legacy > -1e-9, f"Saldo NEGATIVO: {modern + legacy}"
        assert abs(modern + legacy) < 1e-6
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 9, f"stock debió quedar 9, es {p['stock']}"
        n = _db().redemptions.count_documents({"product_id": pid})
        assert n == 1, f"debió crearse 1 canje, hay {n}"

    def test_concurrent_redeems_cannot_oversell_stock(self):
        _set_usd(50.0, 0.0)
        pid = _mk_product(price=1.0, stock=1)
        with ThreadPoolExecutor(max_workers=4) as ex:
            rs = list(ex.map(lambda _: self._redeem(pid), range(4)))
        ok = [r for r in rs if r.status_code == 200]
        assert len(ok) == 1, f"SOBREVENTA: {len(ok)} canjes con stock 1"
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 0, f"stock debió quedar 0, es {p['stock']}"
        modern, legacy = _get_usd()
        assert abs(modern + legacy - 49.0) < 1e-6, f"saldo debió quedar 49, es {modern + legacy}"

    def test_failed_debit_restores_stock(self):
        """Sin saldo: el stock reclamado se devuelve y no queda canje huérfano."""
        _set_usd(0.0, 0.0)
        pid = _mk_product(price=60.0, stock=5)
        r = self._redeem(pid)
        assert r.status_code in (400, 409), r.text
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 5, f"stock debió restaurarse a 5, es {p['stock']}"
        assert _db().redemptions.count_documents({"product_id": pid}) == 0


class TestAdminDoubleRejectRace(_UsdSandbox):
    def test_concurrent_rejects_refund_exactly_once(self):
        _set_usd(40.0, 0.0)
        r = requests.post(f"{API}/vip/withdraw", json={
            "amount_usd": 30.0, "currency": "USD", "method": "transfer",
            "details": f"Cuenta Zelle reject@example.com {MARK}",
            "beneficiary_name": "Iter248 QA", "totp_code": make_vip_totp(),
        }, headers=VIP_H, timeout=30)
        assert r.status_code == 200, r.text
        wid = r.json()["id"]
        modern, legacy = _get_usd()
        assert abs(modern + legacy - 10.0) < 1e-6

        code = make_admin_totp()

        def reject(_):
            return requests.put(f"{API}/admin/withdrawals/{wid}/status", json={
                "status": "rejected", "admin_note": f"race {MARK}",
                "totp_code": code,
            }, headers=ADM_H, timeout=30)

        with ThreadPoolExecutor(max_workers=2) as ex:
            rs = list(ex.map(reject, range(2)))
        assert any(x.status_code == 200 for x in rs), [x.text for x in rs]
        modern, legacy = _get_usd()
        total = modern + legacy
        assert abs(total - 40.0) < 1e-6, (
            f"DOBLE REEMBOLSO: saldo final {total}, esperado 40 (reembolso único de 30)")
