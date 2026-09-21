"""iter285 — Retiro de empresa en 1 paso + visibilidad de pendientes +
marketplace para clientes normales.

Cubre las 3 peticiones del operador:
1. Retiro en 1 paso: «Pagar ahora desde caja» — nace pagado, descuenta el
   fondo, exige y registra el desglose de billetes, aparece en Transacciones.
   Si el pago falla, no queda ningún retiro fantasma ni reserva huérfana.
2. Retiros pendientes visibles: aparecen en /admin/transactions marcados
   «pending» y el dashboard por moneda expone
   `pending_company_withdrawals` (comprometido).
3. Marketplace: los clientes NORMALES pueden canjear su saldo (antes era
   exclusivo VIP); los empleados siguen bloqueados.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN,
    make_admin_totp, make_employee_totp,
)

API = f"{BASE_URL}/api"
MARK = "ITER285"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _cleanup():
    db = _db()
    acc_ids = [a["id"] for a in db.fund_accounts.find(
        {"name": {"$regex": MARK}}, {"id": 1})]
    db.fund_accounts.delete_many({"id": {"$in": acc_ids}})
    db.fund_account_denoms.delete_many({"account_id": {"$in": acc_ids}})
    db.company_fund_adjustments.delete_many({"source_name": {"$regex": MARK}})
    db.company_withdrawals.delete_many({"beneficiary": {"$regex": MARK}})
    db.cash_box_movements.delete_many({"concept": {"$regex": MARK}})
    prod_ids = [p["id"] for p in db.products.find(
        {"name": {"$regex": MARK}}, {"id": 1})]
    db.products.delete_many({"id": {"$in": prod_ids}})
    db.redemptions.delete_many({"product_id": {"$in": prod_ids}})


def _mk_cash_account(name):
    r = requests.post(f"{API}/admin/company-funds/accounts",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"name": name, "currency": "CUP", "method": "cash"})
    assert r.status_code == 200, r.text
    return r.json()


def _cup_available():
    r = requests.get(f"{API}/admin/company-funds", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    row = next((f for f in r.json() if f["currency"] == "CUP"), None)
    return row or {"balance_available": 0.0, "pending_company_withdrawals": 0.0}


def _plant_cup_inflow(acc, bills_of_1000):
    """Aporte de capital en efectivo atribuido a la cuenta: da disponible
    global, saldo por cuenta y billetes de 1000 en el inventario derivado."""
    db = _db()
    amount = float(bills_of_1000 * 1000)
    db.company_fund_adjustments.insert_one({
        "id": str(uuid.uuid4()),
        "adjustment_type": "inflow",
        "currency": "CUP",
        "amount": amount,
        "method": "cash",
        "source_name": f"{MARK} aporte",
        "source_account": "",
        "note": MARK,
        "account_id": acc["id"],
        "account_label": acc.get("name", ""),
        "denominations": {"1000": bills_of_1000},
        "actor_id": "admin", "actor_email": "", "actor_name": "Admin",
        "created_at": _iso(10),
        # ya replicado a caja para que el backfill no lo espeje (la cuenta de
        # prueba no es la caja canónica de empresa)
        "cash_box_movement_id": "na",
    })
    return amount


def _seed_liquid_account():
    """Cuenta de caja CUP con billetes suficientes y disponible global > 0."""
    acc = _mk_cash_account(f"{MARK} caja principal")
    avail = float(_cup_available()["balance_available"])
    deficit_bills = max(0, int((-avail) // 1000) + 1) if avail < 0 else 0
    _plant_cup_inflow(acc, deficit_bills + 100)  # margen de 100 000 CUP
    return acc


class TestPayNowOneStep:
    def setup_method(self, _):
        _cleanup()

    def teardown_method(self, _):
        _cleanup()

    def test_pay_now_cash_full_flow(self):
        acc = _seed_liquid_account()
        before = _cup_available()
        r = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(ADMIN_TOKEN),
            json={
                "amount": 3000, "currency": "CUP",
                "beneficiary": f"{MARK} proveedor pagado",
                "concept": "compra insumos",
                "totp_code": make_admin_totp(),
                "pay_now": True,
                "paid_from_account_id": acc["id"],
                "denominations": {"1000": 3},
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "paid"
        assert body["paid_from_account_id"] == acc["id"]
        assert body["denominations"] == {"1000": 3}
        assert body.get("paid_at")

        # descuenta el fondo (outflow_company sube, disponible baja 3000)
        after = _cup_available()
        assert abs((float(before["balance_available"])
                    - float(after["balance_available"])) - 3000) < 0.01
        assert abs((float(after["outflow_company"])
                    - float(before["outflow_company"])) - 3000) < 0.01
        # no queda comprometido: nació pagado
        assert abs(float(after["pending_company_withdrawals"])
                   - float(before["pending_company_withdrawals"])) < 0.01

        # aparece de inmediato en el registro de Transacciones como pagado
        rt = requests.get(f"{API}/admin/transactions",
                          params={"currency": "CUP", "holder": MARK},
                          headers=_hdr(ADMIN_TOKEN))
        assert rt.status_code == 200, rt.text
        rows = [it for it in rt.json()["items"] if it["ref_id"] == body["id"]]
        assert rows, "el retiro pagado no aparece en /admin/transactions"
        assert rows[0]["status"] == "paid"
        assert rows[0]["direction"] == "out"
        assert rows[0]["ref_type"] == "company_withdrawal"

        # el desglose descuenta billetes de la cuenta (inventario derivado)
        rb = requests.get(f"{API}/admin/company-funds/accounts/CUP",
                          headers=_hdr(ADMIN_TOKEN))
        assert rb.status_code == 200, rb.text
        row = next((a for a in rb.json()["accounts"] if a["id"] == acc["id"]), None)
        assert row is not None
        assert float(row["balance"]) > 0  # la cuenta absorbe la salida

    def test_pay_now_denoms_mismatch_leaves_no_ghost(self):
        acc = _seed_liquid_account()
        db = _db()
        r = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(ADMIN_TOKEN),
            json={
                "amount": 3000, "currency": "CUP",
                "beneficiary": f"{MARK} fantasma",
                "totp_code": make_admin_totp(),
                "pay_now": True,
                "paid_from_account_id": acc["id"],
                "denominations": {"1000": 1},  # suma 1000 ≠ 3000
            })
        assert r.status_code == 400, r.text
        assert "coincidir" in r.json()["detail"].lower()
        # sin retiro fantasma…
        assert db.company_withdrawals.count_documents(
            {"beneficiary": f"{MARK} fantasma"}) == 0
        # …y la reserva liberada: un retiro válido posterior sigue pasando
        r2 = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(ADMIN_TOKEN),
            json={
                "amount": 3000, "currency": "CUP",
                "beneficiary": f"{MARK} segundo intento",
                "totp_code": make_admin_totp(),
                "pay_now": True,
                "paid_from_account_id": acc["id"],
                "denominations": {"1000": 3},
            })
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "paid"

    def test_pay_now_cash_without_denoms_rejected(self):
        acc = _seed_liquid_account()
        r = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(ADMIN_TOKEN),
            json={
                "amount": 2000, "currency": "CUP",
                "beneficiary": f"{MARK} sin billetes",
                "totp_code": make_admin_totp(),
                "pay_now": True,
                "paid_from_account_id": acc["id"],
            })
        assert r.status_code == 400, r.text
        assert "desglose" in r.json()["detail"].lower()
        assert _db().company_withdrawals.count_documents(
            {"beneficiary": f"{MARK} sin billetes"}) == 0

    def test_pay_now_employee_forbidden(self):
        acc = _seed_liquid_account()
        r = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(EMPLOYEE_TOKEN),
            json={
                "amount": 1000, "currency": "CUP",
                "beneficiary": f"{MARK} empleado",
                "totp_code": make_employee_totp(),
                "pay_now": True,
                "paid_from_account_id": acc["id"],
                "denominations": {"1000": 1},
            })
        assert r.status_code == 403, r.text

    def test_pending_withdrawal_visible_and_committed(self):
        _seed_liquid_account()
        before = _cup_available()
        r = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(ADMIN_TOKEN),
            json={
                "amount": 5000, "currency": "CUP",
                "beneficiary": f"{MARK} pendiente visible",
                "totp_code": make_admin_totp(),
            })
        assert r.status_code == 200, r.text
        cw = r.json()
        assert cw["status"] == "pending"
        try:
            # visible en Transacciones marcado «pending»
            rt = requests.get(f"{API}/admin/transactions",
                              params={"currency": "CUP", "holder": MARK},
                              headers=_hdr(ADMIN_TOKEN))
            assert rt.status_code == 200, rt.text
            rows = [it for it in rt.json()["items"] if it["ref_id"] == cw["id"]]
            assert rows, "el retiro pendiente no aparece en /admin/transactions"
            assert rows[0]["status"] == "pending"
            # comprometido en el dashboard por moneda
            after = _cup_available()
            assert (float(after["pending_company_withdrawals"])
                    - float(before["pending_company_withdrawals"])) >= 4999.99
        finally:
            # rechazar libera la reserva (limpieza correcta)
            rr = requests.put(
                f"{API}/admin/company-withdrawals/{cw['id']}/status",
                headers=_hdr(ADMIN_TOKEN),
                json={"status": "rejected", "totp_code": make_admin_totp()})
            assert rr.status_code == 200, rr.text


class TestMarketplaceNormalClients:
    def setup_method(self, _):
        _cleanup()
        db = _db()
        u = db.users.find_one({"user_id": "user_test_normal01"},
                              {"vip_balances": 1}) or {}
        self._prev_usdt = float((u.get("vip_balances") or {}).get("USDT", 0.0))

    def teardown_method(self, _):
        _cleanup()
        _db().users.update_one(
            {"user_id": "user_test_normal01"},
            {"$set": {"vip_balances.USDT": self._prev_usdt}})

    def _plant_vendor_product(self, price=5.0, stock=10):
        db = _db()
        prod = {
            "id": f"prd_{uuid.uuid4().hex[:10]}",
            "name": f"{MARK} Arroz vendedor",
            "description": "producto de prueba",
            "image_url": "", "price_usd": price, "cost_usd": 0.0,
            "stock": stock, "category": "iter285", "is_active": True,
            "owner_id": "user_test_vip01", "owner_name": "VIP Test",
            "approval_status": "approved",
            "created_at": _iso(5),
        }
        db.products.insert_one(prod)
        return prod

    def test_normal_client_can_redeem(self):
        db = _db()
        prod = self._plant_vendor_product()
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"vip_balances.USDT": 500.0}})
        r = requests.post(
            f"{API}/vip/redeem", headers=_hdr(NORMAL_TOKEN),
            json={"product_id": prod["id"], "quantity": 2,
                  "delivery_address": f"Direccion {MARK} sin referencia"})
        assert r.status_code == 200, r.text
        red = r.json()
        assert red["user_id"] == "user_test_normal01"
        assert red["quantity"] == 2
        assert red["total_usd"] == 10.0
        # stock descontado y saldo USDT debitado (total + mensajería)
        assert db.products.find_one({"id": prod["id"]})["stock"] == 8
        u = db.users.find_one({"user_id": "user_test_normal01"},
                              {"vip_balances": 1})
        fee = float(red.get("courier_fee_usd") or 0.0)
        expected = 500.0 - 10.0 - fee
        assert abs(float(u["vip_balances"]["USDT"]) - expected) < 0.01

    def test_normal_redeem_insufficient_balance_rejected(self):
        db = _db()
        prod = self._plant_vendor_product(price=100.0)
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"vip_balances.USDT": 5.0}})
        r = requests.post(
            f"{API}/vip/redeem", headers=_hdr(NORMAL_TOKEN),
            json={"product_id": prod["id"], "quantity": 1,
                  "delivery_address": f"Direccion {MARK} sin referencia"})
        assert r.status_code == 400, r.text
        assert "insuficiente" in r.json()["detail"].lower()

    def test_employee_cannot_redeem(self):
        prod = self._plant_vendor_product()
        r = requests.post(
            f"{API}/vip/redeem", headers=_hdr(EMPLOYEE_TOKEN),
            json={"product_id": prod["id"], "quantity": 1,
                  "delivery_address": f"Direccion {MARK}"})
        assert r.status_code == 403, r.text
