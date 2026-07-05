"""Tests for iter15:
- /admin/company-funds dynamic balance
- /admin/company-withdrawals CRUD with 2FA + scope + admin-only status changes
- /admin/queue scoped + admin sees all pending
"""
import os
import requests
from pymongo import MongoClient

from conftest import (
    BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN, EMPLOYEE_TOKEN,
    make_admin_totp, make_employee_totp,
)


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _cleanup_company():
    cli = MongoClient(os.environ["MONGO_URL"])
    cli[os.environ["DB_NAME"]].company_withdrawals.delete_many(
        {"beneficiary": {"$regex": "^TEST"}}
    )
    cli.close()


class TestCompanyFunds:
    def test_admin_sees_all_currencies(self):
        r = requests.get(f"{BASE_URL}/api/admin/company-funds", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        for row in data:
            assert {"currency", "inflow", "outflow_clients", "outflow_company", "balance"}.issubset(row.keys())

    def test_employee_scope_restricts_currencies(self):
        cli = MongoClient(os.environ["MONGO_URL"])
        cli[os.environ["DB_NAME"]].users.update_one(
            {"user_id": "user_test_employee01"},
            {"$set": {"allowed_currencies": ["BRL"]}},
        )
        cli.close()
        try:
            r = requests.get(f"{BASE_URL}/api/admin/company-funds", headers=_h(EMPLOYEE_TOKEN))
            assert r.status_code == 200
            currencies = {f["currency"] for f in r.json()}
            assert currencies <= {"BRL"}, f"leaked currencies {currencies}"
        finally:
            cli = MongoClient(os.environ["MONGO_URL"])
            cli[os.environ["DB_NAME"]].users.update_one(
                {"user_id": "user_test_employee01"},
                {"$set": {"allowed_currencies": []}},
            )
            cli.close()

    def test_normal_user_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/admin/company-funds", headers=_h(NORMAL_TOKEN))
        assert r.status_code in (401, 403)


class TestCompanyWithdrawalCreate:
    def setup_method(self, _): _cleanup_company()
    def teardown_method(self, _): _cleanup_company()

    def test_admin_creates_with_totp(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-withdrawals",
            headers=_h(ADMIN_TOKEN),
            json={
                "amount": 5, "currency": "USD",
                "beneficiary": "TEST Banco · cuenta operativa",
                "concept": "Pago proveedor",
                "totp_code": make_admin_totp(),
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "pending"
        # iter15: authorized_by auto-detected from session
        assert body["authorized_by_id"] == "user_test_admin01"
        assert body["amount"] == 5
        assert body["currency"] == "USD"

    def test_missing_totp_returns_401(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-withdrawals",
            headers=_h(ADMIN_TOKEN),
            json={"amount": 5, "currency": "USD", "beneficiary": "TEST"},
        )
        assert r.status_code == 401

    def test_insufficient_funds_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-withdrawals",
            headers=_h(ADMIN_TOKEN),
            json={
                "amount": 99_999_999, "currency": "USD",
                "beneficiary": "TEST Big Spender",
                "totp_code": make_admin_totp(),
            },
        )
        assert r.status_code == 400
        assert "insuficiente" in r.json()["detail"].lower()

    def test_employee_scope_blocks_currency(self):
        # employee scoped to BRL only
        cli = MongoClient(os.environ["MONGO_URL"])
        cli[os.environ["DB_NAME"]].users.update_one(
            {"user_id": "user_test_employee01"},
            {"$set": {"allowed_currencies": ["BRL"]}},
        )
        cli.close()
        try:
            r = requests.post(
                f"{BASE_URL}/api/admin/company-withdrawals",
                headers=_h(EMPLOYEE_TOKEN),
                json={
                    "amount": 1, "currency": "USD",
                    "beneficiary": "TEST",
                    "totp_code": make_employee_totp(),
                },
            )
            assert r.status_code == 403
        finally:
            cli = MongoClient(os.environ["MONGO_URL"])
            cli[os.environ["DB_NAME"]].users.update_one(
                {"user_id": "user_test_employee01"},
                {"$set": {"allowed_currencies": []}},
            )
            cli.close()


class TestCompanyWithdrawalStatus:
    def setup_method(self, _): _cleanup_company()
    def teardown_method(self, _): _cleanup_company()

    def _create(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-withdrawals",
            headers=_h(ADMIN_TOKEN),
            json={
                "amount": 1, "currency": "USD",
                "beneficiary": "TEST Status",
                "totp_code": make_admin_totp(),
            },
        )
        assert r.status_code == 200
        return r.json()["id"]

    def test_employee_cannot_change_status(self):
        cwid = self._create()
        r = requests.put(
            f"{BASE_URL}/api/admin/company-withdrawals/{cwid}/status",
            headers=_h(EMPLOYEE_TOKEN),
            json={"status": "approved", "totp_code": make_employee_totp()},
        )
        # require_admin returns 403 for employee
        assert r.status_code == 403

    def test_admin_can_approve_and_pay(self):
        cwid = self._create()
        r1 = requests.put(
            f"{BASE_URL}/api/admin/company-withdrawals/{cwid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "approved", "totp_code": make_admin_totp()},
        )
        assert r1.status_code == 200
        assert r1.json()["status"] == "approved"
        r2 = requests.put(
            f"{BASE_URL}/api/admin/company-withdrawals/{cwid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "paid", "totp_code": make_admin_totp()},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "paid"

    def test_paid_locked(self):
        cwid = self._create()
        requests.put(
            f"{BASE_URL}/api/admin/company-withdrawals/{cwid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "paid", "totp_code": make_admin_totp()},
        )
        r = requests.put(
            f"{BASE_URL}/api/admin/company-withdrawals/{cwid}/status",
            headers=_h(ADMIN_TOKEN),
            json={"status": "rejected", "totp_code": make_admin_totp()},
        )
        # admin trying to revert paid → 403 (already paid)
        assert r.status_code == 403


class TestQueue:
    def test_admin_sees_pending_orders_and_withdrawals(self):
        r = requests.get(f"{BASE_URL}/api/admin/queue", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        d = r.json()
        assert "orders" in d and "withdrawals" in d and "counts" in d
        # statuses on orders must be pending-like
        for o in d["orders"][:50]:
            assert o["status"] in ("pending", "requires_double_approval")
        # withdrawals must be pending
        for w in d["withdrawals"][:50]:
            assert w["status"] == "pending"

    def test_employee_scope_filters(self):
        cli = MongoClient(os.environ["MONGO_URL"])
        cli[os.environ["DB_NAME"]].users.update_one(
            {"user_id": "user_test_employee01"},
            {"$set": {"allowed_currencies": ["BRL"]}},
        )
        cli.close()
        try:
            r = requests.get(f"{BASE_URL}/api/admin/queue", headers=_h(EMPLOYEE_TOKEN))
            assert r.status_code == 200
            d = r.json()
            for o in d["orders"]:
                assert "BRL" in (o["from_code"], o["to_code"])
            for w in d["withdrawals"]:
                assert w["currency"] == "BRL"
        finally:
            cli = MongoClient(os.environ["MONGO_URL"])
            cli[os.environ["DB_NAME"]].users.update_one(
                {"user_id": "user_test_employee01"},
                {"$set": {"allowed_currencies": []}},
            )
            cli.close()
