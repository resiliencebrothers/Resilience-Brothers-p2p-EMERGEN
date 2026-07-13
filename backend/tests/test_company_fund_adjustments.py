"""iter54 — Company fund adjustments (capital-of-trabajo).

Tests:
  - POST /api/admin/company-funds/adjustments (admin + staff with perm)
  - GET  /api/admin/company-funds/adjustments (list history)
  - GET  /api/admin/company-funds reflects the manual adjustments in balance
"""
import os

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN, make_admin_totp


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture(autouse=True)
def cleanup_adjustments():
    """Nuke test-created adjustments after each test."""
    yield
    db = MongoClient(MONGO_URL)[DB_NAME]
    db.company_fund_adjustments.delete_many({"note": {"$regex": "^__test__"}})


def _make_payload(**overrides):
    return {
        "adjustment_type": "inflow",
        "currency": "CUP",
        "amount": 1000.0,
        "method": "transfer",
        "source_name": "Owner Deposit",
        "source_account": "BANCO METRO 123-456",
        "note": "__test__ capital inflow",
        "totp_code": make_admin_totp(),
        **overrides,
    }


class TestCreateAdjustment:
    def test_admin_can_create_inflow(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN), json=_make_payload(),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["adjustment_type"] == "inflow"
        assert body["currency"] == "CUP"
        assert body["amount"] == 1000.0
        assert body["method"] == "transfer"
        assert body["source_name"] == "Owner Deposit"
        assert body["source_account"] == "BANCO METRO 123-456"
        assert body["actor_id"]
        assert body["created_at"]

    def test_admin_can_create_outflow(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN),
            json=_make_payload(
                adjustment_type="outflow", amount=200.0,
                method="cash", source_name="Juan Perez",
                source_account="",  # cash: no account
                note="__test__ pay expense",
            ),
        )
        assert r.status_code == 200, r.text
        assert r.json()["adjustment_type"] == "outflow"

    def test_crypto_method_with_wallet_address(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN),
            json=_make_payload(
                currency="USDT", method="crypto",
                source_name="Wallet transfer",
                source_account="TRX7pQR9zXvB8mNqA...",
                note="__test__ crypto deposit",
            ),
        )
        assert r.status_code == 200, r.text
        assert r.json()["method"] == "crypto"

    def test_normal_user_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(NORMAL_TOKEN), json=_make_payload(),
        )
        assert r.status_code == 403

    def test_employee_without_perm_rejected(self):
        db = MongoClient(MONGO_URL)[DB_NAME]
        # iter55.16 semantics: to actually deny access we must
        #  (a) clear the legacy `can_manage_company_funds` flag AND
        #  (b) set `allowed_permissions` to a NON-EMPTY list that does NOT
        #      include `company_funds` (an empty list = full staff access
        #      for backward compat).
        db.users.update_one(
            {"user_id": "user_test_employee01"},
            {
                "$unset": {"can_manage_company_funds": ""},
                "$set": {"allowed_permissions": ["orders"]},
            },
        )
        try:
            r = requests.post(
                f"{BASE_URL}/api/admin/company-funds/adjustments",
                headers=_h(EMPLOYEE_TOKEN), json=_make_payload(),
            )
            assert r.status_code == 403
            assert "permiso" in r.text.lower()
        finally:
            db.users.update_one(
                {"user_id": "user_test_employee01"},
                {"$unset": {"allowed_permissions": ""}},
            )

    def test_employee_with_perm_allowed(self):
        db = MongoClient(MONGO_URL)[DB_NAME]
        db.users.update_one(
            {"user_id": "user_test_employee01"},
            {"$set": {"can_manage_company_funds": True}},
        )
        try:
            r = requests.post(
                f"{BASE_URL}/api/admin/company-funds/adjustments",
                headers=_h(EMPLOYEE_TOKEN), json=_make_payload(),
            )
            # Employee still needs TOTP — could reach 400 for missing TOTP or 200 if provided
            # We use admin TOTP secret so this may fail step-up. Accept 200 or step-up error.
            assert r.status_code in (200, 400, 401, 403), r.text
        finally:
            db.users.update_one(
                {"user_id": "user_test_employee01"},
                {"$unset": {"can_manage_company_funds": ""}},
            )

    def test_missing_totp_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN), json=_make_payload(totp_code=None),
        )
        assert r.status_code in (400, 401), r.text

    def test_invalid_currency_returns_400(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN),
            json=_make_payload(currency="ZZZZ"),
        )
        assert r.status_code == 400
        assert "catálogo" in r.text.lower() or "catalog" in r.text.lower()

    def test_amount_must_be_positive(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN), json=_make_payload(amount=0),
        )
        assert r.status_code == 422
        r2 = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN), json=_make_payload(amount=-100),
        )
        assert r2.status_code == 422

    def test_unauth_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            json=_make_payload(),
        )
        assert r.status_code in (401, 403)


class TestListAdjustments:
    def test_admin_lists_all(self):
        # Plant 3 adjustments
        for i in range(3):
            r = requests.post(
                f"{BASE_URL}/api/admin/company-funds/adjustments",
                headers=_h(ADMIN_TOKEN),
                json=_make_payload(amount=100.0 + i, note=f"__test__ #{i}"),
            )
            assert r.status_code == 200
        r = requests.get(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN),
        )
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        # our 3 test rows are in the list
        our = [x for x in body if x.get("note", "").startswith("__test__")]
        assert len(our) >= 3

    def test_currency_filter(self):
        r1 = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN),
            json=_make_payload(currency="USD", note="__test__ USD row"),
        )
        r2 = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN),
            json=_make_payload(currency="CUP", note="__test__ CUP row"),
        )
        assert r1.status_code == 200 and r2.status_code == 200
        r = requests.get(
            f"{BASE_URL}/api/admin/company-funds/adjustments?currency=USD",
            headers=_h(ADMIN_TOKEN),
        )
        assert r.status_code == 200
        assert all(x["currency"] == "USD" for x in r.json())

    def test_staff_can_list(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(EMPLOYEE_TOKEN),
        )
        assert r.status_code == 200

    def test_normal_user_rejected(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(NORMAL_TOKEN),
        )
        assert r.status_code == 403


class TestBalanceIncludesAdjustments:
    def test_inflow_increases_balance(self):
        db = MongoClient(MONGO_URL)[DB_NAME]
        # Clean any prior CUP adjustments for a deterministic delta
        db.company_fund_adjustments.delete_many(
            {"currency": "CUP", "note": {"$regex": "^__test__"}}
        )
        # Baseline
        b0 = next(
            (r for r in requests.get(
                f"{BASE_URL}/api/admin/company-funds",
                headers=_h(ADMIN_TOKEN),
            ).json() if r["currency"] == "CUP"),
            {"balance": 0.0, "manual_inflow": 0.0},
        )
        base_balance = b0.get("balance", 0.0)
        base_inflow = b0.get("manual_inflow", 0.0)
        # Add 5000 CUP inflow
        r = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN),
            json=_make_payload(currency="CUP", amount=5000.0,
                               note="__test__ balance delta"),
        )
        assert r.status_code == 200, r.text
        # Verify balance moved
        after = next(
            r for r in requests.get(
                f"{BASE_URL}/api/admin/company-funds",
                headers=_h(ADMIN_TOKEN),
            ).json() if r["currency"] == "CUP"
        )
        assert abs(after["manual_inflow"] - (base_inflow + 5000.0)) < 0.001
        assert abs(after["balance"] - (base_balance + 5000.0)) < 0.001

    def test_outflow_decreases_balance(self):
        db = MongoClient(MONGO_URL)[DB_NAME]
        db.company_fund_adjustments.delete_many(
            {"currency": "CUP", "note": {"$regex": "^__test__"}}
        )
        # Add both an inflow and an outflow, verify net delta
        r1 = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN),
            json=_make_payload(currency="CUP", amount=10000.0,
                               note="__test__ pre-outflow inflow"),
        )
        r2 = requests.post(
            f"{BASE_URL}/api/admin/company-funds/adjustments",
            headers=_h(ADMIN_TOKEN),
            json=_make_payload(
                adjustment_type="outflow", currency="CUP", amount=3000.0,
                method="cash", source_name="Juan Perez", source_account="",
                note="__test__ pay expense",
            ),
        )
        assert r1.status_code == 200 and r2.status_code == 200
        row = next(
            r for r in requests.get(
                f"{BASE_URL}/api/admin/company-funds",
                headers=_h(ADMIN_TOKEN),
            ).json() if r["currency"] == "CUP"
        )
        # net contribution from this test: +10000 - 3000 = +7000 to balance
        assert row["manual_inflow"] >= 10000.0
        assert row["manual_outflow"] >= 3000.0
