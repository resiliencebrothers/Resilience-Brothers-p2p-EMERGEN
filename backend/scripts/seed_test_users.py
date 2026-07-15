"""Seed the 4 test users required by the pytest suite.

Idempotent — safe to re-run. Used by CI (`.github/workflows/ci.yml`) to
prepare a fresh MongoDB before the backend starts.

The users mirror `/app/memory/test_credentials.md`:
  - user_test_admin01     (role=admin)
  - user_test_employee01  (role=employee)
  - user_test_vip01       (role=vip, vip_balance_usd=5000)
  - user_test_normal01    (role=normal)

All 4 get TOTP enabled with the fixed test secret so `conftest.make_*_totp()`
helpers produce codes the backend accepts.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

# Ensure /app/backend is on sys.path so we can import totp_service.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.abspath(os.path.join(_HERE, os.pardir))
sys.path.insert(0, _BACKEND)

from pymongo import MongoClient  # noqa: E402
import totp_service  # noqa: E402


# This is the well-known pyotp docs sample base32 secret — PUBLIC by design
# (published in the pyotp README) and only used to seed TOTP for the 4 test
# users on the local/CI test database. The production TOTP_MASTER_KEY is
# entirely different, so this cannot access real 2FA anywhere.
# Override via TEST_TOTP_SECRET env var if you want to rotate it in CI.
TEST_TOTP_SECRET = os.environ.get(
    "TEST_TOTP_SECRET", "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
)


USERS = [
    {
        "user_id": "user_test_admin01",
        "email": "admin.test@resilience.com",
        "name": "Admin Test",
        "role": "admin",
        "phone": "+5350000001",
        "phone_verified": True,
    },
    {
        "user_id": "user_test_employee01",
        "email": "employee.test@resilience.com",
        "name": "Employee Test",
        "role": "employee",
        "phone": "+5350000002",
        "phone_verified": True,
    },
    {
        "user_id": "user_test_vip01",
        "email": "vip.test@resilience.com",
        "name": "VIP Test",
        "role": "vip",
        "phone": "+5350000003",
        "phone_verified": True,
        "vip_balance_usd": 5000.0,
    },
    {
        "user_id": "user_test_normal01",
        "email": "normal.test@resilience.com",
        "name": "Normal Test",
        "role": "normal",
        "phone": "+5350000004",
        "phone_verified": True,
    },
]


def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("[seed_test_users] MONGO_URL and DB_NAME must be set", file=sys.stderr)
        return 1

    client = MongoClient(mongo_url)
    db = client[db_name]
    encrypted_totp = totp_service.encrypt_secret(TEST_TOTP_SECRET)
    now = datetime.now(timezone.utc).isoformat()

    for u in USERS:
        payload = {
            **u,
            "auth_provider": "google",
            "created_at": now,
            "account_status": "active",
            "totp_enabled": True,
            "totp_secret_encrypted": encrypted_totp,
            "totp_recovery_codes": [],
            "totp_setup_at": now,
            "email_verified": True,
        }
        db.users.update_one(
            {"user_id": u["user_id"]},
            {"$set": payload},
            upsert=True,
        )
        print(f"[seed_test_users] upserted {u['user_id']} ({u['role']})")

    # iter55.36o — plant an approved KYC verification for VIP + Normal test
    # users so the new full-verification gate (email + phone + KYC) does not
    # break the pre-existing order/withdrawal/conversion pytest suite.
    # Admin + employee bypass the gate by role, so no KYC row needed for them.
    for uid in ("user_test_vip01", "user_test_normal01"):
        db.kyc_verifications.update_one(
            {"user_id": uid, "status": "verified"},
            {"$setOnInsert": {
                "id": f"kyc_{uid}",
                "user_id": uid,
                "status": "verified",
                "created_at": now,
                "reviewed_at": now,
                "reviewed_by": "user_test_admin01",
                "risk_score": 0,
                "risk_flags": [],
                "documents": [],
                "review_notes": "seeded by scripts/seed_test_users.py for pytest",
            }},
            upsert=True,
        )
        print(f"[seed_test_users] KYC verified for {uid}")

    client.close()
    print(f"[seed_test_users] ✓ {len(USERS)} test users ready in {db_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
