"""Tests for iter14 behavior changes:
- Normal users can now withdraw (Item 2)
- Employees cannot withdraw to themselves
- Confirmed orders cannot be re-status'd by employees (Item 3)
- Paid withdrawals cannot be re-opened by employees
- Withdrawals require payout proof when marked as paid (Item 5)
- Employee allowed_currencies enforcement (Item 4)
"""
import os
import requests
import pytest
from pymongo import MongoClient

from conftest import (
    BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, EMPLOYEE_TOKEN,
    make_admin_totp, make_vip_totp, make_employee_totp,
)


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _set_normal_balance(usd_amount: float):
    """Directly seed the normal user's USD balance via Mongo."""
    cli = MongoClient(os.environ["MONGO_URL"])
    cli[os.environ["DB_NAME"]].users.update_one(
        {"user_id": "user_test_normal01"},
        {"$set": {"vip_balances.USD": float(usd_amount), "vip_balance_usd": 0}},
    )
    cli.close()


def _enable_totp_normal():
    """Enable TOTP on normal user so they can run the withdrawal flow."""
    import sys
    sys.path.insert(0, "/app/backend")
    import totp_service
    cli = MongoClient(os.environ["MONGO_URL"])
    secret = os.environ.get("TEST_TOTP_SECRET", "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")  # pyotp docs sample, test-only
    cli[os.environ["DB_NAME"]].users.update_one(
        {"user_id": "user_test_normal01"},
        {"$set": {
            "totp_enabled": True,
            "totp_secret_encrypted": totp_service.encrypt_secret(secret),
            "totp_recovery_codes": [],
        }},
    )
    cli.close()
    import pyotp
    return pyotp.TOTP(secret).now()


class TestNormalCanWithdraw:
    def test_normal_with_balance_can_withdraw(self):
        _set_normal_balance(50.0)
        code = _enable_totp_normal()
        r = requests.post(
            f"{BASE_URL}/api/vip/withdraw",
            headers=_h(NORMAL_TOKEN),
            json={"amount_usd": 20, "method": "transfer", "details": "Bank Z",
                  "beneficiary_name": "Normal Holder", "totp_code": code},
        )
        assert r.status_code == 200, r.text
        wid = r.json()["id"]
        # Cleanup: reject the withdrawal
        requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "rejected", "totp_code": make_admin_totp()},
        )

    def test_employee_cannot_withdraw(self):
        r = requests.post(
            f"{BASE_URL}/api/vip/withdraw",
            headers=_h(EMPLOYEE_TOKEN),
            json={"amount_usd": 5, "method": "transfer", "details": "x",
                  "beneficiary_name": "Staff"},
        )
        assert r.status_code == 403


class TestConfirmedOrderLock:
    def _create_and_approve_order(self):
        # VIP creates an accumulate order
        body = {
            "from_code": "USDT", "to_code": "CUP", "amount_from": 10,
            "delivery_method": "accumulate", "delivery_details": "—",
            "sender_name": "VIP Test", "proof_image": "data:image/png;base64,X",
        }
        r = requests.post(f"{BASE_URL}/api/orders", headers=_h(VIP_TOKEN), json=body)
        assert r.status_code == 200
        oid = r.json()["id"]
        # Admin approves
        r2 = requests.put(
            f"{BASE_URL}/api/admin/orders/{oid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "approved", "totp_code": make_admin_totp()},
        )
        assert r2.status_code == 200
        return oid

    def test_employee_cannot_change_confirmed_order(self):
        oid = self._create_and_approve_order()
        r = requests.put(
            f"{BASE_URL}/api/admin/orders/{oid}/status",
            headers=_h(EMPLOYEE_TOKEN),
            json={"status": "rejected", "admin_note": "trying to revert",
                  "totp_code": make_employee_totp()},
        )
        assert r.status_code == 403
        assert "confirmada" in r.json()["detail"].lower() or "admin" in r.json()["detail"].lower()

    def test_admin_can_change_confirmed_order(self):
        oid = self._create_and_approve_order()
        r = requests.put(
            f"{BASE_URL}/api/admin/orders/{oid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "completed", "totp_code": make_admin_totp()},
        )
        assert r.status_code == 200


class TestEmployeeAllowedCurrencies:
    def setup_method(self, _):
        cli = MongoClient(os.environ["MONGO_URL"])
        cli[os.environ["DB_NAME"]].users.update_one(
            {"user_id": "user_test_employee01"},
            {"$set": {"allowed_currencies": ["BRL"]}},
        )
        cli.close()

    def teardown_method(self, _):
        cli = MongoClient(os.environ["MONGO_URL"])
        cli[os.environ["DB_NAME"]].users.update_one(
            {"user_id": "user_test_employee01"},
            {"$set": {"allowed_currencies": []}},
        )
        cli.close()

    def test_orders_filtered_by_currency(self):
        # employee allowed BRL only -> USD/CUP orders must NOT appear
        r = requests.get(f"{BASE_URL}/api/admin/orders", headers=_h(EMPLOYEE_TOKEN))
        assert r.status_code == 200
        for o in r.json():
            assert "BRL" in (o["from_code"], o["to_code"]), (
                f"Order {o['id']} ({o['from_code']}→{o['to_code']}) leaked through"
            )

    def test_cannot_update_unauthorized_rate(self):
        """Iter14 extension: employees may only edit rates that touch their scope."""
        all_rates = requests.get(f"{BASE_URL}/api/rates").json()
        target = next(
            (r for r in all_rates if "BRL" not in (r["from_code"], r["to_code"])),
            None,
        )
        if not target:
            pytest.skip("No non-BRL rates")
        r = requests.put(
            f"{BASE_URL}/api/admin/rates/{target['id']}",
            headers=_h(EMPLOYEE_TOKEN),
            json={**target, "totp_code": make_employee_totp()},
        )
        assert r.status_code == 403

    def test_can_update_authorized_rate(self):
        """Employee with BRL scope can still edit a USDT->BRL rate (BRL is in scope)."""
        all_rates = requests.get(f"{BASE_URL}/api/rates").json()
        target = next(
            (r for r in all_rates if "BRL" in (r["from_code"], r["to_code"])),
            None,
        )
        if not target:
            pytest.skip("No BRL rates to test against")
        body = {
            "from_code": target["from_code"],
            "to_code": target["to_code"],
            "rate_normal": target["rate_normal"],
            "rate_vip": target["rate_vip"],
            "real_rate": target.get("real_rate"),
            "totp_code": make_employee_totp(),
        }
        r = requests.put(
            f"{BASE_URL}/api/admin/rates/{target['id']}",
            headers=_h(EMPLOYEE_TOKEN),
            json=body,
        )
        assert r.status_code == 200, r.text

    def test_cannot_update_unauthorized_order(self):
        # Pick any non-BRL order
        all_orders = requests.get(
            f"{BASE_URL}/api/admin/orders", headers=_h(ADMIN_TOKEN)
        ).json()
        target = next((o for o in all_orders if "BRL" not in (o["from_code"], o["to_code"])), None)
        if not target:
            pytest.skip("No non-BRL orders to test against")
        r = requests.put(
            f"{BASE_URL}/api/admin/orders/{target['id']}/status",
            headers=_h(EMPLOYEE_TOKEN),
            json={"status": "rejected", "totp_code": make_employee_totp()},
        )
        assert r.status_code == 403


class TestWithdrawalPayoutProof:
    def _create_withdrawal(self, method="transfer"):
        # Ensure VIP has USD balance
        cli = MongoClient(os.environ["MONGO_URL"])
        cli[os.environ["DB_NAME"]].users.update_one(
            {"user_id": "user_test_vip01"},
            {"$inc": {"vip_balance_usd": 20.0}},
        )
        cli.close()
        r = requests.post(
            f"{BASE_URL}/api/vip/withdraw",
            headers=_h(VIP_TOKEN),
            json={"amount_usd": 5, "method": method, "details": "—",
                  "beneficiary_name": "Holder", "totp_code": make_vip_totp()},
        )
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def test_paid_requires_proof_for_transfer(self):
        wid = self._create_withdrawal("transfer")
        r = requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "paid", "totp_code": make_admin_totp()},
        )
        assert r.status_code == 400
        assert "captura" in r.json()["detail"].lower()
        # Cleanup
        requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "rejected", "totp_code": make_admin_totp()},
        )

    def test_paid_with_proof_succeeds(self):
        wid = self._create_withdrawal("transfer")
        r = requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "paid",
                  "payout_proof_image": "data:image/png;base64,XXX",
                  "totp_code": make_admin_totp()},
        )
        assert r.status_code == 200, r.text
        assert r.json()["payout_proof_image"]
        # Cleanup: only admins can re-open paid
        requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "rejected", "totp_code": make_admin_totp()},
        )

    def test_employee_cannot_modify_paid_withdrawal(self):
        wid = self._create_withdrawal("transfer")
        # Admin marks paid with proof
        r = requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "paid",
                  "payout_proof_image": "data:image/png;base64,XXX",
                  "totp_code": make_admin_totp()},
        )
        assert r.status_code == 200
        # Employee tries to revert (with valid TOTP — must hit 403 paid-lock, not 401 missing-2FA)
        r2 = requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            headers=_h(EMPLOYEE_TOKEN),
            json={"status": "rejected", "totp_code": make_employee_totp()},
        )
        assert r2.status_code == 403
        # Cleanup via admin
        requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "rejected", "totp_code": make_admin_totp()},
        )
