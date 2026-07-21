"""iter55.36o — Full-verification gate: email + phone + KYC required to
create orders, convert balances, redeem in the marketplace or withdraw funds.

Covers the four gated endpoints (`POST /orders`, `POST /vip/convert`,
`POST /vip/redeem`, `POST /vip/withdraw`) plus the `/auth/me` verification
snapshot that the SPA uses to render the pre-order banner. Staff (admin,
employee) always bypass.

Business rule agreed with product Feb 14 2026: applies to ALL Normal +
VIP users regardless of tenure or transaction size.
"""
import os

import pytest
import requests
from pymongo import MongoClient

from conftest import (
    BASE_URL,
    ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN,
    make_vip_totp, make_admin_totp,
)


def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


# ---------- helpers ----------

def _reset_user(uid: str, *, email: bool = True, phone: bool = True,
                kyc: bool = True):
    """Bring a test user to a specific verification state.

    Each flag independently controls one of the three requirements. Also
    ensures `phone` string is set (so the `phone_verified` check has
    something to verify against).
    """
    cli, db = _db()
    db.users.update_one(
        {"user_id": uid},
        {"$set": {
            "email_verified": email,
            "phone_verified": phone,
            "phone": "+5350000000",
            "account_status": "active",
        }},
    )
    # Manage KYC row explicitly — delete first to avoid stale rows.
    db.kyc_verifications.delete_many({"user_id": uid})
    if kyc:
        db.kyc_verifications.insert_one({
            "id": f"kyc_{uid}",
            "user_id": uid,
            "status": "verified",
            "created_at": "2026-01-01T00:00:00+00:00",
            "reviewed_at": "2026-01-01T00:00:00+00:00",
            "risk_score": 0,
            "documents": [],
        })
    cli.close()


def _create_order(token: str = NORMAL_TOKEN, amount: float = 1) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/api/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "from_code": "USD", "to_code": "CUP",
            "amount_from": amount, "delivery_method": "accumulate",
            "delivery_details": "", "sender_name": "Tester",
            "proof_image": "",
        },
    )


def _vip_convert(token: str = VIP_TOKEN) -> requests.Response:
    # First plant some USD balance so we don't get a spurious "saldo insuficiente".
    # iter77 — Also seed 0.01 USDT so the fee (separate USDT debit) can be paid.
    cli, db = _db()
    db.users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"vip_balances": {"USD": 500.0, "USDT": 0.01}}},
    )
    cli.close()
    return requests.post(
        f"{BASE_URL}/api/vip/convert",
        headers={"Authorization": f"Bearer {token}"},
        json={"from_code": "USD", "to_code": "CUP", "amount_from": 5,
              "totp_code": make_vip_totp()},
    )


def _vip_withdraw(token: str = VIP_TOKEN) -> requests.Response:
    cli, db = _db()
    db.users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"vip_balance_usd": 500.0}},
    )
    cli.close()
    return requests.post(
        f"{BASE_URL}/api/vip/withdraw",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount_usd": 5, "method": "transfer",
              "beneficiary_name": "Test Holder",
              "details": "Bank details for withdrawal test flow",
              "totp_code": make_vip_totp()},
    )


def _vip_redeem(token: str = VIP_TOKEN) -> requests.Response:
    prods = requests.get(f"{BASE_URL}/api/products").json()
    if not prods:
        pytest.skip("no products seeded")
    cheapest = min(prods, key=lambda p: p["price_usd"])
    cli, db = _db()
    db.users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"vip_balance_usd": cheapest["price_usd"] + 100}},
    )
    cli.close()
    return requests.post(
        f"{BASE_URL}/api/vip/redeem",
        headers={"Authorization": f"Bearer {token}"},
        json={"product_id": cheapest["id"], "quantity": 1,
              "delivery_address": "Calle test 123, Havana"},
    )


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def _cleanup_after():
    """Restore both test users to fully-verified state after every test so
    unrelated sibling tests keep working."""
    yield
    _reset_user("user_test_normal01", email=True, phone=True, kyc=True)
    _reset_user("user_test_vip01", email=True, phone=True, kyc=True)


# ============================================================
# 1. `/auth/me` verification snapshot
# ============================================================

class TestAuthMeVerificationSnapshot:
    def test_fully_verified_user(self):
        _reset_user("user_test_normal01", email=True, phone=True, kyc=True)
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {NORMAL_TOKEN}"},
        )
        assert r.status_code == 200
        v = r.json()["verification"]
        assert v["fully_verified"] is True
        assert v["missing"] == []

    def test_missing_email(self):
        _reset_user("user_test_normal01", email=False, phone=True, kyc=True)
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {NORMAL_TOKEN}"},
        )
        v = r.json()["verification"]
        assert v["fully_verified"] is False
        assert "email" in v["missing"]
        assert v["email_verified"] is False

    def test_missing_phone(self):
        _reset_user("user_test_normal01", email=True, phone=False, kyc=True)
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {NORMAL_TOKEN}"},
        )
        v = r.json()["verification"]
        assert v["fully_verified"] is False
        assert "phone" in v["missing"]

    def test_missing_kyc(self):
        _reset_user("user_test_normal01", email=True, phone=True, kyc=False)
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {NORMAL_TOKEN}"},
        )
        v = r.json()["verification"]
        assert v["fully_verified"] is False
        assert "kyc" in v["missing"]

    def test_all_missing_lists_all_three(self):
        _reset_user("user_test_normal01", email=False, phone=False, kyc=False)
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {NORMAL_TOKEN}"},
        )
        v = r.json()["verification"]
        assert v["fully_verified"] is False
        assert set(v["missing"]) == {"email", "phone", "kyc"}

    def test_admin_always_verified(self):
        # Even if we corrupt admin's flags, the helper returns fully_verified
        # because role bypass applies before any flag is inspected.
        cli, db = _db()
        db.users.update_one(
            {"user_id": "user_test_admin01"},
            {"$set": {"email_verified": False, "phone_verified": False}},
        )
        cli.close()
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert r.status_code == 200
        v = r.json()["verification"]
        assert v["fully_verified"] is True
        # Cleanup
        cli, db = _db()
        db.users.update_one(
            {"user_id": "user_test_admin01"},
            {"$set": {"email_verified": True, "phone_verified": True}},
        )
        cli.close()


# ============================================================
# 2. `POST /orders` gate
# ============================================================

class TestOrderCreationGate:
    def test_fully_verified_user_can_create_order(self):
        r = _create_order()
        assert r.status_code == 200, r.text

    def test_missing_email_blocks_order(self):
        _reset_user("user_test_normal01", email=False, phone=True, kyc=True)
        r = _create_order()
        assert r.status_code == 403
        detail = r.json()["detail"]
        assert detail["code"] == "EMAIL_NOT_VERIFIED"
        assert "email" in detail["missing"]
        assert detail["cta_url"] == "/dashboard/security"

    def test_missing_phone_blocks_order(self):
        _reset_user("user_test_normal01", email=True, phone=False, kyc=True)
        r = _create_order()
        assert r.status_code == 403
        detail = r.json()["detail"]
        assert detail["code"] == "PHONE_NOT_VERIFIED"

    def test_missing_kyc_blocks_order(self):
        _reset_user("user_test_normal01", email=True, phone=True, kyc=False)
        r = _create_order()
        assert r.status_code == 403
        detail = r.json()["detail"]
        assert detail["code"] == "KYC_NOT_APPROVED"
        assert detail["cta_url"] == "/dashboard/kyc"

    def test_gate_applies_to_vip_too(self):
        """User explicitly required the strict gate for VIPs — no legacy
        bypass on VIP status."""
        _reset_user("user_test_vip01", email=True, phone=True, kyc=False)
        r = _create_order(token=VIP_TOKEN)
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "KYC_NOT_APPROVED"

    def test_email_missing_takes_priority_over_others(self):
        """The primary `code` follows a natural remediation order:
        email → phone → KYC. `missing` still contains all three."""
        _reset_user("user_test_normal01", email=False, phone=False, kyc=False)
        r = _create_order()
        assert r.json()["detail"]["code"] == "EMAIL_NOT_VERIFIED"
        assert set(r.json()["detail"]["missing"]) == {"email", "phone", "kyc"}


# ============================================================
# 3. `POST /vip/convert` gate
# ============================================================

class TestVipConvertGate:
    def test_fully_verified_vip_can_convert(self):
        r = _vip_convert()
        assert r.status_code == 200, r.text

    def test_missing_kyc_blocks_convert(self):
        _reset_user("user_test_vip01", email=True, phone=True, kyc=False)
        r = _vip_convert()
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "KYC_NOT_APPROVED"

    def test_missing_phone_blocks_convert(self):
        _reset_user("user_test_vip01", email=True, phone=False, kyc=True)
        r = _vip_convert()
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "PHONE_NOT_VERIFIED"


# ============================================================
# 4. `POST /vip/redeem` gate (marketplace)
# ============================================================

class TestVipRedeemGate:
    def test_missing_kyc_blocks_redeem(self):
        _reset_user("user_test_vip01", email=True, phone=True, kyc=False)
        r = _vip_redeem()
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "KYC_NOT_APPROVED"

    def test_missing_phone_blocks_redeem(self):
        _reset_user("user_test_vip01", email=True, phone=False, kyc=True)
        r = _vip_redeem()
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "PHONE_NOT_VERIFIED"


# ============================================================
# 5. `POST /vip/withdraw` gate
# ============================================================

class TestVipWithdrawGate:
    def test_fully_verified_can_withdraw(self):
        r = _vip_withdraw()
        assert r.status_code == 200, r.text

    def test_missing_kyc_blocks_withdraw(self):
        _reset_user("user_test_vip01", email=True, phone=True, kyc=False)
        r = _vip_withdraw()
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "KYC_NOT_APPROVED"

    def test_missing_email_blocks_withdraw(self):
        _reset_user("user_test_vip01", email=False, phone=True, kyc=True)
        r = _vip_withdraw()
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "EMAIL_NOT_VERIFIED"


# ============================================================
# 6. Non-verified KYC states also block (pending, rejected, needs_more_info)
# ============================================================

class TestKycNonVerifiedStates:
    """A `kyc_verifications` row must be `status = verified` to unlock the
    gate. Any other status (`pending`, `rejected`, `needs_more_info`) leaves
    the user blocked, mirroring the strict compliance requirement."""

    @pytest.mark.parametrize("kyc_status", ["pending", "rejected", "needs_more_info"])
    def test_non_verified_kyc_status_blocks_order(self, kyc_status):
        cli, db = _db()
        db.users.update_one(
            {"user_id": "user_test_normal01"},
            {"$set": {"email_verified": True, "phone_verified": True,
                      "phone": "+5350000000"}},
        )
        db.kyc_verifications.delete_many({"user_id": "user_test_normal01"})
        db.kyc_verifications.insert_one({
            "id": f"kyc_pending_{kyc_status}",
            "user_id": "user_test_normal01",
            "status": kyc_status,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        cli.close()
        r = _create_order()
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == "KYC_NOT_APPROVED"
