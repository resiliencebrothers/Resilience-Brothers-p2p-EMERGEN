"""Seed a settled booking + reviews so the Fase 2b flows are E2E-testable:
  - company public reply to a review
  - customer-facing review + reply display
  - rating sort (two services with different averages)
Idempotent: re-running replaces the seeded reviews/bookings.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent / ".env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc)
iso = lambda d: d.isoformat()

VIP = "user_test_vip01"
EMP = "user_test_empresa_e2e"

# Primary service seeded by seed_booking_smoke.py
primary = db.services.find_one({"id": {"$regex": "^TEST_BK_"}, "status": "published"},
                               sort=[("created_at", -1)])
if not primary:
    raise SystemExit("Run seed_booking_smoke.py first")
sid = primary["id"]

# Second published service (lower rating) to make rating-sort observable
sid2 = "TEST_BK_LOWRATED"
db.services.update_one({"id": sid2}, {"$set": {
    "id": sid2, "company_id": EMP, "owner_name": "Empresa QA Servicios",
    "title": "Afeitado clásico QA", "category": "barberia",
    "description": "Segundo servicio de prueba (peor valorado).", "images": [],
    "modality": "local", "pricing_type": "fixed", "price_usdt": 8.0,
    "deposit_type": "none", "deposit_value": 0.0,
    "duration_minutes": 45, "min_notice_hours": 0, "capacity": 1,
    "buffer_minutes": 0, "coverage_zone": "Vedado", "requirements": "",
    "inclusions": "", "exclusions": "", "cancellation_policy": "",
    "payment_methods": ["balance"],
    "availability": [{"day": d, "start": "09:00", "end": "17:00"} for d in range(7)],
    "blocked_dates": [], "timezone": "America/Havana",
    "status": "published", "rejection_reason": "", "is_active": True,
    "created_at": iso(now), "updated_at": iso(now), "approved_at": iso(now),
}}, upsert=True)


def settled_booking(service_id, title, amount):
    bid = f"SEEDBK_{uuid.uuid4().hex[:8]}"
    start = now - timedelta(days=2)
    db.service_bookings.insert_one({
        "id": bid, "service_id": service_id, "service_title": title,
        "company_id": EMP, "company_name": "Empresa QA Servicios",
        "customer_id": VIP, "customer_name": "VIP QA",
        "slot_date": start.date().isoformat(), "slot_start": "10:00",
        "slot_end": "11:00", "slot_start_utc": iso(start),
        "slot_end_utc": iso(start + timedelta(hours=1)),
        "accept_deadline_utc": iso(start), "timezone": "America/Havana",
        "pricing_type": "fixed", "unit_price_usdt": amount, "quantity": 1,
        "amount_usdt": amount, "deposit_usdt": amount, "remainder_usdt": 0.0,
        "frozen_full": True, "remainder_collected": True,
        "company_paid_usdt": amount, "currency": "USDT", "status": "settled",
        "note": "", "reject_reason": "", "pay_op_id": f"svcbk:{bid}:pay",
        "rest_op_id": "", "refund_op_id": "", "settle_op_id": f"svcbk:{bid}:settle",
        "reminded_24h": True, "created_at": iso(start - timedelta(days=1)),
        "updated_at": iso(now), "decided_at": iso(start - timedelta(days=1)),
    })
    return bid


def review(service_id, rating, comment, company_response=""):
    rid = f"RVSEED_{uuid.uuid4().hex[:6]}"
    db.service_reviews.delete_many({"service_id": service_id, "customer_id": VIP})
    doc = {
        "id": rid, "service_id": service_id, "customer_id": VIP,
        "customer_name": "VIP QA", "rating": rating, "comment": comment,
        "created_at": iso(now), "updated_at": iso(now),
    }
    if company_response:
        doc["company_response"] = company_response
        doc["company_response_at"] = iso(now)
    db.service_reviews.insert_one(doc)
    agg = list(db.service_reviews.aggregate([
        {"$match": {"service_id": service_id}},
        {"$group": {"_id": None, "avg": {"$avg": "$rating"}, "n": {"$sum": 1}}}]))
    if agg:
        db.services.update_one({"id": service_id}, {"$set": {
            "rating_avg": round(float(agg[0]["avg"]), 2), "rating_count": int(agg[0]["n"])}})
    return rid


# Clean previous seeded settled bookings for a clean slate
db.service_bookings.delete_many({"id": {"$regex": "^SEEDBK_"}, "customer_id": VIP})

settled_booking(sid, primary.get("title", ""), 10.0)
settled_booking(sid2, "Afeitado clásico QA", 8.0)

# Primary: rating 5, no company reply yet (so company can add one in the test)
rv1 = review(sid, 5, "Excelente servicio, muy recomendable. Puntual y profesional.")
# Second: rating 3, already has a company reply (so customer-side display is testable now)
rv2 = review(sid2, 3, "Estuvo bien pero tardó más de lo esperado.",
             company_response="Gracias por tu comentario, mejoraremos los tiempos de espera.")

print("PRIMARY_SERVICE", sid, "(rating 5, no reply — company adds reply in test)")
print("SECOND_SERVICE", sid2, "(rating 3, pre-set company reply)")
print("REVIEW_PRIMARY", rv1)
print("REVIEW_SECOND", rv2)
