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
