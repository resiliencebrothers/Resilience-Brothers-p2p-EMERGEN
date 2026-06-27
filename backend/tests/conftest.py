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


@pytest.fixture(autouse=True)
def _autoseed_sessions():
    """Re-seed the four test sessions before every test so logout-style flows
    don't break sibling tests that share the module."""
    try:
        _seed_test_sessions()
    except Exception:
        pass
    yield


# ---------- 2FA helpers (iter13) ----------
# These ensure the VIP test user has TOTP enabled so existing withdrawal tests
# can pass through the step-up gate. Returns a callable that produces fresh codes.

import sys as _sys
_sys.path.insert(0, str((_ROOT / "backend").resolve()))


def _ensure_test_user_totp(user_id: str) -> str:
    """Enable TOTP on a test user with a deterministic secret. Returns the secret."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient as _M
    import totp_service as _ts
    # Fixed secret per user_id so tests are reproducible
    secret = _ts.generate_secret() if False else "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"  # 32-char base32
    encrypted = _ts.encrypt_secret(secret)

    async def _go():
        cli = _M(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await cli.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "totp_enabled": True,
                "totp_secret_encrypted": encrypted,
                "totp_recovery_codes": [],
                "totp_setup_at": "2026-01-01T00:00:00+00:00",
            }},
        )
    asyncio.get_event_loop().run_until_complete(_go()) if False else asyncio.run(_go())
    return secret


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
