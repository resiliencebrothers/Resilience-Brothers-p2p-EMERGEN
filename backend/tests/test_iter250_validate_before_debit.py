"""iter250 — Validar comprobantes ANTES de descontar (rechazado → pagado).

Reporte: al cambiar un retiro rechazado a pagado, el re-débito ocurría antes
de validar el comprobante; si la validación fallaba (400/409), la operación
devolvía error pero el dinero YA estaba descontado. Fix: todas las
validaciones (comprobante, tx hash, mensajería, cuenta de origen) corren
primero; el ajuste de saldo y la persistencia del estado van juntos al final.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, VIP_TOKEN, ADMIN_TOKEN, make_vip_totp, with_totp_admin

API = f"{BASE_URL}/api"
VIP_H = {"Authorization": f"Bearer {VIP_TOKEN}"}
ADM_H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
UID = "user_test_vip01"
MARK = "iter250"

PROOF_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAf"
             "FcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _usd_total():
    u = _db().users.find_one({"user_id": UID},
                             {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
    return (float((u.get("vip_balances") or {}).get("USD") or 0.0)
            + float(u.get("vip_balance_usd") or 0.0))


def _set_status(wid, body):
    return requests.put(f"{API}/admin/withdrawals/{wid}/status",
                        headers=ADM_H, json=with_totp_admin(body), timeout=20)


class TestValidateBeforeDebit:
    def setup_method(self, _):
        u = _db().users.find_one({"user_id": UID},
                                 {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
        self._orig = (float((u.get("vip_balances") or {}).get("USD") or 0.0),
                      float(u.get("vip_balance_usd") or 0.0))
        _db().users.update_one({"user_id": UID}, {"$set": {
            "vip_balances.USD": 40.0, "vip_balance_usd": 0.0}})

    def teardown_method(self, _):
        db = _db()
        db.withdrawals.delete_many({"user_id": UID, "details": {"$regex": MARK}})
        db.users.update_one({"user_id": UID}, {"$set": {
            "vip_balances.USD": self._orig[0],
            "vip_balance_usd": self._orig[1]}})

    def _create_and_reject(self):
        r = requests.post(f"{API}/vip/withdraw", json={
            "amount_usd": 30.0, "currency": "USD", "method": "transfer",
            "details": f"Cuenta Zelle proof@example.com {MARK}",
            "beneficiary_name": "Iter250 QA", "totp_code": make_vip_totp(),
        }, headers=VIP_H, timeout=20)
        assert r.status_code == 200, r.text
        wid = r.json()["id"]
        assert abs(_usd_total() - 10.0) < 1e-6
        rj = _set_status(wid, {"status": "rejected", "admin_note": MARK})
        assert rj.status_code == 200, rj.text
        assert abs(_usd_total() - 40.0) < 1e-6, "el rechazo debió reembolsar 30"
        return wid

    def test_paid_without_proof_returns_400_and_does_not_debit(self):
        """El caso reportado: rechazado→pagado sin comprobante debe fallar SIN
        descontar el dinero."""
        wid = self._create_and_reject()
        r = _set_status(wid, {"status": "paid", "admin_note": MARK})
        assert r.status_code == 400, f"debió exigir comprobante: {r.status_code} {r.text}"
        total = _usd_total()
        assert abs(total - 40.0) < 1e-6, (
            f"DINERO DESCONTADO pese al error: saldo {total}, esperado 40")
        doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert doc["status"] == "rejected", "el estado no debió cambiar"
        assert doc.get("balance_refunded") is True, (
            "el flag de reembolso no debió consumirse")

    def test_paid_with_proof_debits_once_and_updates_status(self):
        wid = self._create_and_reject()
        r = _set_status(wid, {"status": "paid", "admin_note": MARK,
                              "payout_proof_image": PROOF_PNG})
        assert r.status_code == 200, r.text
        assert abs(_usd_total() - 10.0) < 1e-6, (
            f"debió re-debitarse 30 exactamente una vez: {_usd_total()}")
        doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert doc["status"] == "paid"
        assert doc.get("balance_refunded") is False

    def test_reactivation_blocked_if_refund_already_spent(self):
        """Si el cliente ya gastó el reembolso, rechazado→pagado (con
        comprobante) debe dar 409 y no dejar saldo negativo."""
        wid = self._create_and_reject()
        _db().users.update_one({"user_id": UID}, {"$set": {
            "vip_balances.USD": 5.0, "vip_balance_usd": 0.0}})
        r = _set_status(wid, {"status": "paid", "admin_note": MARK,
                              "payout_proof_image": PROOF_PNG})
        assert r.status_code == 409, r.text
        assert abs(_usd_total() - 5.0) < 1e-6
        doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0})
        assert doc["status"] == "rejected"
        assert doc.get("balance_refunded") is True
