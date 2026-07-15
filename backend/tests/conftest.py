"""Shared pytest config for Resilience Brothers backend tests.

Test session tokens are documented dev fixtures (see /app/memory/test_credentials.md);
they only authenticate against locally seeded `user_sessions` rows and are not real
secrets. They can still be overridden via env vars for CI environments.
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load both backend .env (MONGO_URL etc.) and frontend .env (REACT_APP_BACKEND_URL)
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / "backend" / ".env")
load_dotenv(_ROOT / "frontend" / ".env")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set in frontend/.env"

# Default fixture tokens — seeded into user_sessions by the testing harness.
# Override via env (TEST_TOKEN_ADMIN, TEST_TOKEN_VIP, ...) when running in CI.
ADMIN_TOKEN = os.environ.get("TEST_TOKEN_ADMIN", "test_session_admin_X")
VIP_TOKEN = os.environ.get("TEST_TOKEN_VIP", "test_session_vip_X")
NORMAL_TOKEN = os.environ.get("TEST_TOKEN_NORMAL", "test_session_normal_X")
EMPLOYEE_TOKEN = os.environ.get("TEST_TOKEN_EMPLOYEE", "test_session_employee_X")

# ---------- Shared test TOTP secret (iter55.36g) ----------
# This is the well-known pyotp docs sample base32 secret. It's PUBLIC by
# design (published in the pyotp README) and only lives in the local test
# database — the production `TOTP_MASTER_KEY` in the deployed env is entirely
# different, so this secret cannot access any real user's 2FA anywhere.
#
# All test files that need a deterministic TOTP for the seeded test users
# should import from here so the value has a single source of truth. Override
# via `TEST_TOTP_SECRET` env var in CI-alt environments if desired.
TEST_TOTP_SECRET = os.environ.get(
    "TEST_TOTP_SECRET", "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
)


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def tokens():
    return {
        "admin": ADMIN_TOKEN,
        "vip": VIP_TOKEN,
        "normal": NORMAL_TOKEN,
        "employee": EMPLOYEE_TOKEN,
    }


# ---------- Session seeding (iter33) ----------
# The integration tests use Bearer tokens against locally seeded `user_sessions`.
# Some flows (logout, auth refactor) delete sessions, so we re-seed at the start
# of every test FUNCTION to keep the suite self-sufficient end-to-end.

def _seed_test_sessions():
    from datetime import datetime, timezone, timedelta
    from pymongo import MongoClient as _MC
    db = _MC(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    sessions = [
        (ADMIN_TOKEN, "user_test_admin01"),
        (EMPLOYEE_TOKEN, "user_test_employee01"),
        (VIP_TOKEN, "user_test_vip01"),
        (NORMAL_TOKEN, "user_test_normal01"),
    ]
    for tok, uid in sessions:
        db.user_sessions.update_one(
            {"session_token": tok},
            {"$set": {"session_token": tok, "user_id": uid, "expires_at": exp}},
            upsert=True,
        )
    # iter55.36o — re-plant `email_verified`, `phone_verified` and the
    # approved-KYC row for VIP + Normal test users. The full-verification
    # gate on /orders, /vip/convert, /vip/redeem and /vip/withdraw would
    # otherwise leak un-verified state between tests: any test that unsets
    # `phone_verified` (e.g. test_iter23_phone_trust) leaves the DB in a
    # broken state for the next test that creates an order with the same
    # session. Idempotent — no work if already correct.
    now_iso = datetime.now(timezone.utc).isoformat()
    for uid in ("user_test_vip01", "user_test_normal01"):
        db.users.update_one(
            {"user_id": uid},
            {"$set": {
                "email_verified": True,
                "phone_verified": True,
                "phone": db.users.find_one({"user_id": uid}, {"phone": 1}).get("phone") or "+5350000000",
                "account_status": "active",
            }},
        )
        db.kyc_verifications.update_one(
            {"user_id": uid, "status": "verified"},
            {"$setOnInsert": {
                "id": f"kyc_{uid}",
                "user_id": uid,
                "status": "verified",
                "created_at": now_iso,
                "reviewed_at": now_iso,
                "reviewed_by": "user_test_admin01",
                "risk_score": 0,
                "risk_flags": [],
                "documents": [],
                "review_notes": "conftest re-seed",
            }},
            upsert=True,
        )


@pytest.fixture(autouse=True)
def _autoseed_sessions():
    """Re-seed the four test sessions before every test so logout-style flows
    don't break sibling tests that share the module."""
    try:
        _seed_test_sessions()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _reset_motor_client_loop_binding():
    """iter55.36 — Motor's `AsyncIOMotorClient` lazily binds to whatever event
    loop first uses it; when a sibling test finishes and its loop closes (e.g.
    tests using `asyncio.run()`), motor's cached `_io_loop` reference becomes
    stale and subsequent async tests raise `RuntimeError('Event loop is
    closed')`.

    We clear the cached loop reference before every test so motor rebinds
    cleanly to the loop of the CURRENT test — the only side effect is a
    single extra `get_event_loop()` lookup per test.

    Handles the case where `db_client` hasn't been imported yet (rare early-
    collection tests that don't touch the DB).
    """
    try:
        import db_client  # type: ignore
        # Two known cache attributes across motor versions.
        for attr in ("_io_loop", "_framework"):
            if hasattr(db_client.client, attr) and attr == "_io_loop":
                try:
                    setattr(db_client.client, attr, None)
                except Exception:
                    pass
    except Exception:
        pass
    yield


# ---------- 2FA helpers (iter13) ----------
# These ensure the VIP test user has TOTP enabled so existing withdrawal tests
# can pass through the step-up gate. Returns a callable that produces fresh codes.

import sys as _sys  # noqa: E402 — path manipulation must precede local imports below
_sys.path.insert(0, str((_ROOT / "backend").resolve()))


def _ensure_test_user_totp(user_id: str) -> str:
    """Enable TOTP on a test user with a deterministic secret. Returns the secret.

    Uses pymongo (sync) instead of motor (async) — motor requires an event
    loop and calling `asyncio.run()` here would contaminate other async tests
    that share the module-level motor client in `db_client.py` (closed loop
    → RuntimeError on next use). This helper is a pure setup step, so sync
    IO is perfectly fine.
    """
    from pymongo import MongoClient
    import totp_service as _ts
    # Uses TEST_TOTP_SECRET (pyotp docs sample) — see module-level docstring.
    encrypted = _ts.encrypt_secret(TEST_TOTP_SECRET)
    cli = MongoClient(os.environ["MONGO_URL"])
    cli[os.environ["DB_NAME"]].users.update_one(
        {"user_id": user_id},
        {"$set": {
            "totp_enabled": True,
            "totp_secret_encrypted": encrypted,
            "totp_recovery_codes": [],
            "totp_setup_at": "2026-01-01T00:00:00+00:00",
        }},
    )
    cli.close()
    return TEST_TOTP_SECRET


def totp_code_for(secret: str) -> str:
    """Generate a current TOTP code for the given secret."""
    import pyotp
    return pyotp.TOTP(secret).now()


@pytest.fixture(scope="session")
def vip_totp_secret():
    """Ensures the VIP test user has 2FA enabled and returns the secret."""
    return _ensure_test_user_totp("user_test_vip01")


@pytest.fixture
def vip_totp_code(vip_totp_secret):
    """Fresh TOTP code at the moment of test call."""
    return totp_code_for(vip_totp_secret)


# Auto-enable 2FA for the VIP test user at session start so the legacy withdrawal
# tests that don't import the fixture explicitly still work via `make_vip_totp()`.
_VIP_TOTP_SECRET = None


def make_vip_totp() -> str:
    """Module-level convenience used by tests that didn't request the fixture.

    Re-applies the setup every call (idempotent) so tests that disable 2FA mid-suite
    don't leave the VIP user in a broken state for subsequent tests.
    """
    global _VIP_TOTP_SECRET
    _VIP_TOTP_SECRET = _ensure_test_user_totp("user_test_vip01")
    return totp_code_for(_VIP_TOTP_SECRET)


# ---------- Admin / Employee TOTP helpers (iter14 — admin step-up 2FA) ----------
_ADMIN_TOTP_SECRET = None
_EMPLOYEE_TOTP_SECRET = None


def make_admin_totp() -> str:
    """Enable 2FA on the admin test user (idempotent) and return a fresh TOTP code."""
    global _ADMIN_TOTP_SECRET
    _ADMIN_TOTP_SECRET = _ensure_test_user_totp("user_test_admin01")
    return totp_code_for(_ADMIN_TOTP_SECRET)


def make_employee_totp() -> str:
    """Enable 2FA on the employee test user (idempotent) and return a fresh TOTP code."""
    global _EMPLOYEE_TOTP_SECRET
    _EMPLOYEE_TOTP_SECRET = _ensure_test_user_totp("user_test_employee01")
    return totp_code_for(_EMPLOYEE_TOTP_SECRET)


def with_totp_admin(body: dict) -> dict:
    """Return `body` augmented with a fresh admin TOTP code."""
    return {**body, "totp_code": make_admin_totp()}


def with_totp_employee(body: dict) -> dict:
    return {**body, "totp_code": make_employee_totp()}


# Pre-enable 2FA on admin & employee at collection so most existing tests pass
# without needing to call helpers individually.
try:
    make_admin_totp()
    make_employee_totp()
except Exception:
    # Employee user may not exist yet on some envs; ignore — individual tests
    # that need it will re-trigger via helper.
    pass
