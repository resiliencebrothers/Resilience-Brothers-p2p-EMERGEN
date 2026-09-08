"""Seed admin session + reset employee state before iter251 E2E."""
import os, sys, datetime
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

now = datetime.datetime.utcnow()
exp = now + datetime.timedelta(days=1)

# Ensure admin session
db.user_sessions.update_one(
    {"session_token": "test_session_admin_X"},
    {"$set": {
        "user_id": "user_test_admin01",
        "session_token": "test_session_admin_X",
        "expires_at": exp,
        "created_at": now,
    }},
    upsert=True,
)

# Snapshot & reset employee
emp = db.users.find_one({"user_id": "user_test_employee01"})
if not emp:
    sys.exit("employee not found")

print("BEFORE:", {
    "role": emp.get("role"),
    "allowed_permissions": emp.get("allowed_permissions"),
    "allowed_currencies": emp.get("allowed_currencies"),
})

mode = sys.argv[1] if len(sys.argv) > 1 else "main"
if mode == "main":
    perms = ["support"]
    curs = ["USD"]
elif mode == "viceversa":
    perms = ["orders", "quick_view"]
    curs = ["USD", "USDT"]
elif mode == "restore":
    perms = sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] else []
    curs = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] else []
else:
    sys.exit(f"bad mode {mode}")

db.users.update_one(
    {"user_id": "user_test_employee01"},
    {"$set": {
        "role": "employee",
        "allowed_permissions": perms,
        "allowed_currencies": curs,
    }},
)
after = db.users.find_one({"user_id": "user_test_employee01"})
print("AFTER:", {
    "allowed_permissions": after.get("allowed_permissions"),
    "allowed_currencies": after.get("allowed_currencies"),
})
