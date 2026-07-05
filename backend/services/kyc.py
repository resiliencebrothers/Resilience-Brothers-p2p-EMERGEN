"""KYC verification service (iter52).

Encapsulates persistence + risk-scoring logic for the client identity
verification flow. Kept small on purpose — the route file `routes/kyc.py`
is the transport layer; this module is where business logic lives.

Data shape (`kyc_verifications` collection):

    {
      id: str (uuid),
      user_id: str,
      user_email: str,
      user_name: str,
      user_phone: str,
      status: 'pending' | 'verified' | 'rejected' | 'needs_more_info',
      documents: [
        { doc_type: 'id_front' | 'id_back' | 'selfie', ref: '/api/files/...' },
        ...
      ],
      risk_score: int (0-100),
      risk_flags: [
        { code, message, severity: 'low' | 'medium' | 'high' }
      ],
      submit_ip: str,
      submit_user_agent: str,
      reviewed_by: str | None,
      reviewed_by_email: str | None,
      reviewed_at: iso str | None,
      review_notes: str,
      rejection_reasons: [str],
      created_at: iso str,
      updated_at: iso str,
    }

Users' collection gains 2 fields at approval time:
- `kyc_status` — mirror of the verification status (default 'unverified')
- `kyc_verified_at` — iso str set on approval
"""
import logging
import uuid
from typing import Any, Optional

from auth_utils import now_utc, iso

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Risk scoring — no country/geo checks per operator's explicit request.
# ----------------------------------------------------------------------------

# Free / disposable / temporary email domains. Any client using one gets
# flagged. This list is intentionally short (~15 popular ones); expand as
# fraud patterns evolve.
_DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com", "tempmail.com", "guerrillamail.com", "10minutemail.com",
    "trashmail.com", "yopmail.com", "throwawaymail.com", "getnada.com",
    "sharklasers.com", "dispostable.com", "temp-mail.org", "fakeinbox.com",
    "maildrop.cc", "getairmail.com", "mytemp.email",
}


async def _flag_disposable_email(email: str) -> Optional[dict]:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    if domain in _DISPOSABLE_EMAIL_DOMAINS:
        return {
            "code": "disposable_email",
            "message": f"Email desechable detectado ({domain}).",
            "severity": "high",
        }
    return None


async def _flag_duplicate_name(db: Any, user_id: str, name: str) -> Optional[dict]:
    """3+ accounts sharing the same normalised full name → possible identity fraud."""
    if not name or len(name.strip()) < 3:
        return None
    norm = name.strip().lower()
    count = await db.users.count_documents({
        "name": {"$regex": f"^{norm}$", "$options": "i"},
        "user_id": {"$ne": user_id},
    })
    if count >= 2:  # this user + 2 others = 3 accounts with same name
        return {
            "code": "duplicate_name",
            "message": f"{count + 1} cuentas comparten el mismo nombre completo.",
            "severity": "medium",
        }
    return None


async def _flag_shared_ip(db: Any, ip: str, user_id: str) -> Optional[dict]:
    """5+ accounts submitting KYC from same IP within 24h → possible bot farm."""
    if not ip or ip == "unknown":
        return None
    from datetime import timedelta
    since = iso(now_utc() - timedelta(hours=24))
    count = await db.kyc_verifications.count_documents({
        "submit_ip": ip,
        "user_id": {"$ne": user_id},
        "created_at": {"$gte": since},
    })
    if count >= 4:  # this user + 4 others = 5 in 24h
        return {
            "code": "shared_ip",
            "message": f"{count + 1} verificaciones desde la misma IP en 24h.",
            "severity": "medium",
        }
    return None


async def _flag_early_large_order(db: Any, user_id: str) -> Optional[dict]:
    """User already tried an order >$500 USDT-eq before submitting KYC."""
    from datetime import timedelta
    since = iso(now_utc() - timedelta(days=30))
    doc = await db.orders.find_one(
        {"user_id": user_id, "created_at": {"$gte": since}, "usdt_equivalent": {"$gte": 500}},
        {"_id": 0, "id": 1, "usdt_equivalent": 1},
    )
    if doc:
        amount = doc.get("usdt_equivalent", 0)
        return {
            "code": "early_large_order",
            "message": f"Intentó orden por {amount:.0f} USDT-eq antes de verificarse.",
            "severity": "medium",
        }
    return None


async def compute_risk(
    db: Any, user_id: str, email: str, name: str, ip: str,
) -> tuple[int, list[dict]]:
    """Return (risk_score 0-100, list of flag dicts).

    Each flag adds points to the score:
      high   → 40
      medium → 20
      low    → 10
    Capped at 100.
    """
    flags: list[dict] = []
    for coro in (
        _flag_disposable_email(email),
        _flag_duplicate_name(db, user_id, name),
        _flag_shared_ip(db, ip, user_id),
        _flag_early_large_order(db, user_id),
    ):
        f = await coro
        if f:
            flags.append(f)
    weight = {"high": 40, "medium": 20, "low": 10}
    score = min(100, sum(weight.get(f["severity"], 10) for f in flags))
    return score, flags


# ----------------------------------------------------------------------------
# Persistence helpers
# ----------------------------------------------------------------------------

async def ensure_indexes(db: Any) -> None:
    """Idempotent index creation. Called on startup."""
    await db.kyc_verifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.kyc_verifications.create_index("status")
    await db.kyc_verifications.create_index("submit_ip")


async def get_active_verification(db: Any, user_id: str) -> Optional[dict]:
    """Return the latest non-rejected verification for a user, or None."""
    doc = await db.kyc_verifications.find_one(
        {"user_id": user_id, "status": {"$ne": "rejected"}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return doc


async def get_latest_verification(db: Any, user_id: str) -> Optional[dict]:
    """Return the most recent verification of ANY status (used for status page)."""
    doc = await db.kyc_verifications.find_one(
        {"user_id": user_id},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return doc


async def submit_verification(
    db: Any,
    user: dict,
    documents: list[dict],
    ip: str,
    user_agent: str,
) -> dict:
    """Create a new `pending` verification. Fails if the user already has a
    pending/verified one — they must wait for staff to reject before re-submitting.

    `documents` is a list of `{doc_type, ref}` dicts. `ref` is a `/api/files/...`
    key produced by `services.proof_upload.maybe_upload_proof`.
    """
    active = await get_active_verification(db, user["user_id"])
    if active:
        raise ValueError(f"already_active_verification:{active['status']}")

    if len(documents) < 3:
        raise ValueError("missing_documents")

    score, flags = await compute_risk(
        db, user["user_id"], user.get("email", ""), user.get("name", ""), ip,
    )

    now = iso(now_utc())
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["user_id"],
        "user_email": user.get("email", ""),
        "user_name": user.get("name", ""),
        "user_phone": user.get("phone", ""),
        "status": "pending",
        "documents": documents,
        "risk_score": score,
        "risk_flags": flags,
        "submit_ip": ip,
        "submit_user_agent": user_agent[:200],
        "reviewed_by": None,
        "reviewed_by_email": None,
        "reviewed_at": None,
        "review_notes": "",
        "rejection_reasons": [],
        "created_at": now,
        "updated_at": now,
    }
    await db.kyc_verifications.insert_one(doc)

    # Mark the user record so `/dashboard` can show a "pendiente de revisión" banner.
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"kyc_status": "pending", "kyc_last_submit_at": now}},
    )
    doc.pop("_id", None)
    return doc


async def approve_verification(
    db: Any, verification_id: str, staff: dict, notes: str = "",
) -> Optional[dict]:
    now = iso(now_utc())
    res = await db.kyc_verifications.update_one(
        {"id": verification_id, "status": {"$in": ["pending", "needs_more_info"]}},
        {"$set": {
            "status": "verified",
            "reviewed_by": staff["user_id"],
            "reviewed_by_email": staff.get("email"),
            "reviewed_at": now,
            "review_notes": notes.strip(),
            "updated_at": now,
        }},
    )
    if res.modified_count == 0:
        return None
    v = await db.kyc_verifications.find_one({"id": verification_id}, {"_id": 0})
    if v:
        await db.users.update_one(
            {"user_id": v["user_id"]},
            {"$set": {"kyc_status": "verified", "kyc_verified_at": now}},
        )
    return v


async def reject_verification(
    db: Any, verification_id: str, staff: dict, reasons: list[str], notes: str = "",
) -> Optional[dict]:
    now = iso(now_utc())
    res = await db.kyc_verifications.update_one(
        {"id": verification_id, "status": {"$in": ["pending", "needs_more_info"]}},
        {"$set": {
            "status": "rejected",
            "reviewed_by": staff["user_id"],
            "reviewed_by_email": staff.get("email"),
            "reviewed_at": now,
            "review_notes": notes.strip(),
            "rejection_reasons": [r.strip() for r in reasons if r.strip()],
            "updated_at": now,
        }},
    )
    if res.modified_count == 0:
        return None
    v = await db.kyc_verifications.find_one({"id": verification_id}, {"_id": 0})
    if v:
        await db.users.update_one(
            {"user_id": v["user_id"]},
            {"$set": {"kyc_status": "rejected"}},
        )
    return v


async def request_more_info(
    db: Any, verification_id: str, staff: dict, notes: str,
) -> Optional[dict]:
    """Bump the verification to `needs_more_info` so the user can re-upload."""
    now = iso(now_utc())
    res = await db.kyc_verifications.update_one(
        {"id": verification_id, "status": "pending"},
        {"$set": {
            "status": "needs_more_info",
            "reviewed_by": staff["user_id"],
            "reviewed_by_email": staff.get("email"),
            "reviewed_at": now,
            "review_notes": notes.strip(),
            "updated_at": now,
        }},
    )
    if res.modified_count == 0:
        return None
    v = await db.kyc_verifications.find_one({"id": verification_id}, {"_id": 0})
    if v:
        await db.users.update_one(
            {"user_id": v["user_id"]},
            {"$set": {"kyc_status": "needs_more_info"}},
        )
    return v


async def list_queue(
    db: Any, status: Optional[str] = None, search: str = "",
    min_risk: int = 0, limit: int = 100,
) -> list[dict]:
    q: dict = {}
    if status:
        q["status"] = status
    if min_risk:
        q["risk_score"] = {"$gte": min_risk}
    if search:
        q["$or"] = [
            {"user_email": {"$regex": search, "$options": "i"}},
            {"user_name": {"$regex": search, "$options": "i"}},
            {"user_phone": {"$regex": search, "$options": "i"}},
        ]
    cursor = db.kyc_verifications.find(q, {"_id": 0}).sort([
        ("risk_score", -1), ("created_at", -1),
    ]).limit(limit)
    return await cursor.to_list(limit)


async def compute_funnel(db: Any) -> dict:
    """Aggregate counts per status + total registered users for the admin
    dashboard header card."""
    total_users = await db.users.count_documents({})
    total_pending = await db.kyc_verifications.count_documents({"status": "pending"})
    total_verified = await db.users.count_documents({"kyc_status": "verified"})
    total_rejected = await db.kyc_verifications.count_documents({"status": "rejected"})
    total_needs_info = await db.kyc_verifications.count_documents({"status": "needs_more_info"})
    high_risk = await db.kyc_verifications.count_documents({
        "status": "pending", "risk_score": {"$gte": 40},
    })
    return {
        "total_users": total_users,
        "pending": total_pending,
        "verified": total_verified,
        "rejected": total_rejected,
        "needs_more_info": total_needs_info,
        "high_risk_pending": high_risk,
    }
