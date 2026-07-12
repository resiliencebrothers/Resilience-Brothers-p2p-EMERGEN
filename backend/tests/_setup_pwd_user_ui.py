"""Helper to provision an email/password test user for UI testing (iter58).
Usage:
    python -m tests._setup_pwd_user_ui setup       # 2FA enabled
    python -m tests._setup_pwd_user_ui setup no2fa # 2FA disabled
    python -m tests._setup_pwd_user_ui totp        # print current TOTP
    python -m tests._setup_pwd_user_ui cleanup
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / "backend" / ".env")
sys.path.insert(0, str((_ROOT / "backend").resolve()))

import bcrypt
import pyotp
from pymongo import MongoClient
import totp_service as _ts

TEST_EMAIL = "pwd.change.ui@resilience.com"
TEST_UID = "user_test_pwdchg_ui"
TEST_SESSION = "test_session_pwdchg_ui"
INITIAL_PW = "OldPassword123!"
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def setup(twofa=True):
    db_ = _db()
    doc = {
        "user_id": TEST_UID,
        "email": TEST_EMAIL,
        "name": "PwdChange UI",
        "role": "normal",
        "auth_provider": "password",
        "password_hash": bcrypt.hashpw(INITIAL_PW.encode(), bcrypt.gensalt()).decode(),
        "email_verified": True,
        "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if twofa:
        doc["totp_enabled"] = True
        doc["totp_secret_encrypted"] = _ts.encrypt_secret(TOTP_SECRET)
        doc["totp_recovery_codes"] = []
        doc["totp_setup_at"] = "2026-01-01T00:00:00+00:00"
    else:
        doc["totp_enabled"] = False
        doc.pop("totp_secret_encrypted", None)
    db_.users.update_one({"user_id": TEST_UID}, {"$set": doc, "$unset": {} if twofa else {"totp_secret_encrypted": ""}}, upsert=True)
    exp = datetime.now(timezone.utc) + timedelta(days=30)
    db_.user_sessions.update_one(
        {"session_token": TEST_SESSION},
        {"$set": {"session_token": TEST_SESSION, "user_id": TEST_UID,
                  "expires_at": exp.isoformat(), "created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    print(f"provisioned uid={TEST_UID} session={TEST_SESSION} 2fa={twofa}")


def cleanup():
    db_ = _db()
    db_.users.delete_many({"user_id": TEST_UID})
    db_.user_sessions.delete_many({"user_id": TEST_UID})
    db_.audit_log.delete_many({"actor_id": TEST_UID})
    print("cleaned up")


def totp():
    print(pyotp.TOTP(TOTP_SECRET).now())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "setup"
    if cmd == "setup":
        setup(twofa=("no2fa" not in sys.argv))
    elif cmd == "cleanup":
        cleanup()
    elif cmd == "totp":
        totp()
