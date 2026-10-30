import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

# Load the repo-local backend/.env for local runs; in CI the file is absent and
# MONGO_URL/DB_NAME come from the job environment instead.
load_dotenv(Path(__file__).resolve().parent / ".env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc)
exp = (now + timedelta(days=5)).isoformat()

VIP = "user_test_vip01"
EMP = "user_test_empresa_e2e"


def session(user_id, token):
    db.user_sessions.update_one(
        {"session_token": token},
        {"$set": {"user_id": user_id, "session_token": token,
                  "session_version": 0, "expires_at": exp,
                  "created_at": now.isoformat()}}, upsert=True)


# Sessions
session(VIP, "bk_smoke_vip")
session(EMP, "bk_smoke_emp")

# Ensure empresa active + role
db.users.update_one({"user_id": EMP}, {"$set": {
    "role": "empresa", "account_status": "active",
    "name": "Empresa QA Servicios", "offers_services": True}}, upsert=True)

# Ensure vip funded
db.users.update_one({"user_id": VIP}, {"$set": {"vip_balances.USDT": 5000.0}})

# Published service with weekday availability (Mon-Sun 09:00-17:00, 60 min)
db.services.delete_many({"id": {"$regex": "^TEST_BK_"}})
sid = f"TEST_BK_{uuid.uuid4().hex[:8]}"
db.services.insert_one({
    "id": sid, "company_id": EMP, "owner_name": "Empresa QA Servicios",
    "title": "Corte de pelo QA", "category": "barberia",
    "description": "Servicio de prueba para reservas.", "images": [],
    "modality": "local", "pricing_type": "fixed", "price_usdt": 10.0,
    "deposit_type": "none", "deposit_value": 0.0,
    "duration_minutes": 60, "min_notice_hours": 0, "capacity": 1,
    "buffer_minutes": 0, "coverage_zone": "Vedado", "requirements": "",
    "inclusions": "", "exclusions": "", "cancellation_policy": "",
    "payment_methods": ["balance"],
    "availability": [{"day": d, "start": "09:00", "end": "17:00"} for d in range(7)],
    "blocked_dates": [], "timezone": "America/Havana",
    "status": "published", "rejection_reason": "", "is_active": True,
    "created_at": now.isoformat(), "updated_at": now.isoformat(),
    "approved_at": now.isoformat(),
})
print("SERVICE_ID", sid)
print("vip balance", db.users.find_one({"user_id": VIP}).get("vip_balances", {}).get("USDT"))
