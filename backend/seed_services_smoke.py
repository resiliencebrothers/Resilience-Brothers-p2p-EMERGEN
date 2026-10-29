import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc)
exp = (now + timedelta(days=5)).isoformat()


def seed(user_id, token):
    db.user_sessions.update_one(
        {"session_token": token},
        {"$set": {"user_id": user_id, "session_token": token,
                  "session_version": 0, "expires_at": exp,
                  "created_at": now.isoformat()}},
        upsert=True,
    )
    print("seeded", token, "->", user_id, bool(db.users.find_one({"user_id": user_id})))


seed("user_test_admin01", "svc_smoke_admin")
seed("user_test_empresa_e2e", "svc_smoke_empresa")
