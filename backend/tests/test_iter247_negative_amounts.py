"""iter247 — Exploit crítico: importes negativos en endpoints financieros.

El servidor aceptaba retiros con `amount_usd` negativo: el chequeo de saldo
(`balance < amount`) pasaba y el débito de un negativo AUMENTABA el saldo del
cliente. Auditoría completa: retiros, canjes marketplace (quantity), órdenes
P2P (amount_from) y productos (price/cost/stock). Todos deben rechazar
importes <= 0 con 422 (validación Pydantic, sin confiar en el frontend).
"""
import os
import requests
from pymongo import MongoClient

from conftest import BASE_URL, VIP_TOKEN, ADMIN_TOKEN, make_vip_totp

API = f"{BASE_URL}/api"
VIP_H = {"Authorization": f"Bearer {VIP_TOKEN}"}
ADM_H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _vip_usd_balance():
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    u = db.users.find_one({"user_id": "user_test_vip01"}, {"_id": 0, "vip_balances": 1})
    return float((u.get("vip_balances") or {}).get("USD") or 0.0)


def _withdraw(amount):
    body = {
        "amount_usd": amount,
        "currency": "USD",
        "method": "transfer",
        "details": "Cuenta Zelle exploit@example.com QA iter247",
        "beneficiary_name": "Iter247 QA",
        "totp_code": make_vip_totp(),
    }
    return requests.post(f"{API}/vip/withdraw", json=body, headers=VIP_H, timeout=15)


class TestNegativeWithdrawal:
    def test_negative_amount_rejected_422(self):
        before = _vip_usd_balance()
        r = _withdraw(-100)
        assert r.status_code == 422, f"EXPLOIT ABIERTO: {r.status_code} {r.text}"
        assert abs(_vip_usd_balance() - before) < 1e-9, "El saldo cambió con un retiro negativo"

    def test_zero_amount_rejected_422(self):
        r = _withdraw(0)
        assert r.status_code == 422, r.text

    def test_absurdly_large_amount_rejected_422(self):
        r = _withdraw(99_000_000_000)
        assert r.status_code == 422, r.text


class TestNegativeRedemption:
    def _redeem(self, qty):
        body = {"product_id": "does-not-matter", "quantity": qty}
        return requests.post(f"{API}/vip/redeem", json=body, headers=VIP_H, timeout=15)

    def test_negative_quantity_rejected_422(self):
        r = self._redeem(-5)
        assert r.status_code == 422, f"EXPLOIT ABIERTO: {r.status_code} {r.text}"

    def test_zero_quantity_rejected_422(self):
        r = self._redeem(0)
        assert r.status_code == 422, r.text


class TestNegativeOrder:
    def _order(self, amount):
        body = {
            "from_code": "USD",
            "to_code": "USDT",
            "amount_from": amount,
            "delivery_method": "crypto",
            "delivery_details": "TXexploitAddr247",
            "sender_name": "Iter247 QA",
        }
        return requests.post(f"{API}/orders", json=body, headers=VIP_H, timeout=15)

    def test_negative_amount_from_rejected_422(self):
        r = self._order(-500)
        assert r.status_code == 422, f"EXPLOIT ABIERTO: {r.status_code} {r.text}"

    def test_zero_amount_from_rejected_422(self):
        r = self._order(0)
        assert r.status_code == 422, r.text


class TestNegativeProductFields:
    def _create(self, **overrides):
        body = {"name": "Producto Exploit 247", "price_usd": 10.0,
                "cost_usd": 5.0, "stock": 3}
        body.update(overrides)
        return requests.post(f"{API}/admin/products", json=body, headers=ADM_H, timeout=15)

    def test_negative_price_rejected_422(self):
        r = self._create(price_usd=-10)
        assert r.status_code == 422, r.text

    def test_negative_cost_rejected_422(self):
        r = self._create(cost_usd=-5)
        assert r.status_code == 422, r.text

    def test_negative_stock_rejected_422(self):
        r = self._create(stock=-3)
        assert r.status_code == 422, r.text


class TestExistingGuardsStillEnforced:
    """Regresión: endpoints que ya tenían gt=0 lo mantienen."""

    def test_convert_negative_rejected(self):
        body = {"from_code": "USD", "to_code": "USDT", "amount_from": -50,
                "totp_code": make_vip_totp()}
        r = requests.post(f"{API}/vip/convert", json=body, headers=VIP_H, timeout=15)
        assert r.status_code == 422, r.text

    def test_deposit_negative_rejected(self):
        body = {"amount": -100, "currency": "USDT", "method": "crypto",
                "details": "TRC20"}
        r = requests.post(f"{API}/deposits", json=body, headers=VIP_H, timeout=15)
        assert r.status_code == 422, r.text

    def test_positive_withdrawal_still_works(self):
        """Un retiro válido sigue funcionando tras el fix (y se cancela)."""
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        u = db.users.find_one({"user_id": "user_test_vip01"},
                              {"_id": 0, "vip_balances": 1})
        cur = float((u.get("vip_balances") or {}).get("USD") or 0.0)
        if cur < 40:
            db.users.update_one({"user_id": "user_test_vip01"},
                                {"$inc": {"vip_balances.USD": 50 - cur}})
        r = _withdraw(25.0)
        assert r.status_code == 200, r.text
        wid = r.json()["id"]
        c = requests.post(f"{API}/vip/withdrawals/{wid}/cancel",
                          headers=VIP_H, timeout=15)
        assert c.status_code == 200, c.text
