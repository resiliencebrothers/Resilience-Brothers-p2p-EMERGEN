"""Seed empresa e2e user + session for UI test."""
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

EMP_ID = "user_test_empresa_e2e"
EMP_TOKEN = "test_session_empresa_e2e_X"
ADMIN_ID = "user_test_admin01"
ADMIN_TOKEN = "test_session_admin_X"

exp = datetime.now(timezone.utc) + timedelta(days=30)

db.users.update_one({"user_id": EMP_ID}, {"$set": {
    "user_id": EMP_ID, "email": "empresa.e2e@example.com", "name": "Empresa E2E",
    "role": "empresa", "account_status": "active", "account_type": "business",
    "email_verified": True, "phone_verified": True, "phone": "+5350000888",
    "kyc_status": "unverified"}}, upsert=True)

db.user_sessions.update_one({"session_token": EMP_TOKEN},
    {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_ID,
              "expires_at": exp.isoformat()}}, upsert=True)

# ensure admin seeded
db.users.update_one({"user_id": ADMIN_ID}, {"$set": {
    "user_id": ADMIN_ID, "email": "admin@test.com", "name": "Admin",
    "role": "admin", "account_status": "active",
    "email_verified": True, "phone_verified": True}}, upsert=True)
db.user_sessions.update_one({"session_token": ADMIN_TOKEN},
    {"$set": {"session_token": ADMIN_TOKEN, "user_id": ADMIN_ID,
              "expires_at": exp.isoformat()}}, upsert=True)

# clear any previous kyc for this user
db.kyc_verifications.delete_many({"user_id": EMP_ID})
print("seeded empresa e2e OK")
