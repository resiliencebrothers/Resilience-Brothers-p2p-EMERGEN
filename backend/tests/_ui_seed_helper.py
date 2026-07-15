"""Helper: seed sessions + set user verification state for UI testing.

Usage: python _ui_seed_helper.py <mode>
Modes:
  normal_unverified: set normal user email/phone/kyc = all missing
  normal_verified:   restore normal user (email + phone + KYC verified)
  vip_unverified:    set vip user email/phone/kyc = all missing
  vip_verified:      restore vip user fully verified
  seed_sessions:     ensure test session tokens exist
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")

cli = MongoClient(os.environ["MONGO_URL"])
db = cli[os.environ["DB_NAME"]]


def seed_sessions():
    exp = datetime.now(timezone.utc) + timedelta(days=1)
    for tok, uid in [
        ("test_session_admin_X", "user_test_admin01"),
        ("test_session_vip_X", "user_test_vip01"),
        ("test_session_normal_X", "user_test_normal01"),
        ("test_session_employee_X", "user_test_employee01"),
    ]:
        db.user_sessions.update_one(
            {"session_token": tok},
            {"$set": {"session_token": tok, "user_id": uid, "expires_at": exp}},
            upsert=True,
        )
    print("sessions seeded")


def set_user(uid: str, email: bool, phone: bool, kyc: bool):
    db.users.update_one(
        {"user_id": uid},
        {"$set": {"email_verified": email, "phone_verified": phone,
                  "phone": "+5350000000", "account_status": "active"}},
    )
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
    u = db.users.find_one({"user_id": uid}, {"email_verified": 1, "phone_verified": 1, "role": 1, "_id": 0})
    k = db.kyc_verifications.find_one({"user_id": uid, "status": "verified"}, {"_id": 0, "status": 1})
    print(f"{uid} => user={u} kyc={k}")


mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "seed_sessions":
    seed_sessions()
elif mode == "normal_unverified":
    seed_sessions()
    set_user("user_test_normal01", email=False, phone=False, kyc=False)
elif mode == "normal_verified":
    set_user("user_test_normal01", email=True, phone=True, kyc=True)
elif mode == "vip_unverified":
    seed_sessions()
    set_user("user_test_vip01", email=False, phone=False, kyc=False)
elif mode == "vip_verified":
    set_user("user_test_vip01", email=True, phone=True, kyc=True)
elif mode == "normal_only_kyc_missing":
    seed_sessions()
    set_user("user_test_normal01", email=True, phone=True, kyc=False)
else:
    print(f"unknown mode: {mode}")
    sys.exit(2)

cli.close()
