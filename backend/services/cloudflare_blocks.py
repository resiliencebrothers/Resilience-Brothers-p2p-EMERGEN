"""Persistent record of every Cloudflare IP block created by the platform.

Backing collection: `cloudflare_ip_blocks`. Each doc tracks:
  ip, cf_rule_id, notes, source ('scanner'|'admin'), user_id (nullable),
  status ('active'|'pending_create'|'pending_delete'|'deleted'|'failed'),
  created_at, updated_at.

MongoDB is treated as the source of truth for our own operations — Cloudflare
is treated as a best-effort enforcement sink so an outage does not corrupt
our audit log.
"""
import logging
import uuid
from typing import Any, Optional

from auth_utils import now_utc, iso
from services import cloudflare_client

logger = logging.getLogger(__name__)


STATUS_ACTIVE = "active"
STATUS_PENDING_CREATE = "pending_create"
STATUS_PENDING_DELETE = "pending_delete"
STATUS_DELETED = "deleted"
STATUS_FAILED = "failed"


async def ensure_indexes(db: Any) -> None:
    try:
        await db.cloudflare_ip_blocks.create_index([("ip", 1), ("status", 1)])
        await db.cloudflare_ip_blocks.create_index([("cf_rule_id", 1)])
        await db.cloudflare_ip_blocks.create_index([("created_at", -1)])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"cloudflare_ip_blocks index setup failed: {e}")


async def create_block(
    db: Any, ip: str, notes: str, source: str,
    *, user_id: Optional[str] = None, user_email: Optional[str] = None,
) -> dict:
    """Persist a block record and try to enforce it at Cloudflare.

    Idempotent — if an ACTIVE block already exists for this IP, we return it
    without touching Cloudflare a second time.

    The persistence order is: insert local (pending_create) → call CF → update
    local (active | failed). This means every attempt is auditable even when CF
    is down.
    """
    # Idempotency: return existing active block if any.
    existing = await db.cloudflare_ip_blocks.find_one(
        {"ip": ip, "status": STATUS_ACTIVE}, {"_id": 0},
    )
    if existing:
        return {"already_blocked": True, "block": existing}

    now = iso(now_utc())
    doc: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "ip": ip,
        "cf_rule_id": None,
        "notes": notes,
        "source": source,
        "user_id": user_id,
        "user_email": user_email,
        "status": STATUS_PENDING_CREATE,
        "created_at": now,
        "updated_at": now,
    }
    await db.cloudflare_ip_blocks.insert_one(doc)
    doc.pop("_id", None)

    if not cloudflare_client._is_configured():
        # No CF creds → keep the local record but mark it FAILED so admin
        # dashboards surface the misconfiguration.
        await _update(db, doc["id"], status=STATUS_FAILED,
                      extra={"error": "Cloudflare not configured"})
        return {"created": True, "block_id": doc["id"], "cf_ok": False,
                "reason": "not_configured"}

    cf = await cloudflare_client.create_block_rule(ip, notes)
    if cf.get("ok"):
        await _update(db, doc["id"], status=STATUS_ACTIVE,
                      extra={"cf_rule_id": cf["rule_id"]})
        return {"created": True, "block_id": doc["id"], "cf_ok": True,
                "cf_rule_id": cf["rule_id"]}

    # Duplicate at Cloudflare but we didn't have a local record → attach the
    # existing rule id and mark active so admin UI shows the truth.
    if cf.get("existing_rule_id"):
        await _update(db, doc["id"], status=STATUS_ACTIVE,
                      extra={"cf_rule_id": cf["existing_rule_id"],
                             "note_sync": "attached to pre-existing CF rule"})
        return {"created": True, "block_id": doc["id"], "cf_ok": True,
                "cf_rule_id": cf["existing_rule_id"], "duplicate": True}

    await _update(db, doc["id"], status=STATUS_FAILED,
                  extra={"error": cf.get("error"), "http_status": cf.get("status")})
    return {"created": True, "block_id": doc["id"], "cf_ok": False,
            "reason": cf.get("error")}


async def delete_block(db: Any, block_id: str) -> dict:
    """Manual unblock. Local record is always transitioned to DELETED so
    admins can trust the UI even when CF was down at the moment of delete."""
    doc = await db.cloudflare_ip_blocks.find_one({"id": block_id}, {"_id": 0})
    if not doc:
        return {"ok": False, "error": "not_found"}
    await _update(db, block_id, status=STATUS_PENDING_DELETE)

    rule_id = doc.get("cf_rule_id")
    if rule_id and cloudflare_client._is_configured():
        cf = await cloudflare_client.delete_rule(rule_id)
        if not cf.get("ok"):
            logger.error(f"[cf-blocks] CF delete failed for rule={rule_id}: {cf.get('error')}")

    await _update(db, block_id, status=STATUS_DELETED)
    fresh = await db.cloudflare_ip_blocks.find_one({"id": block_id}, {"_id": 0})
    return {"ok": True, "block": fresh}


async def list_blocks(db: Any, status: Optional[str] = None,
                      limit: int = 200) -> list:
    q: dict = {}
    if status:
        q["status"] = status
    cursor = db.cloudflare_ip_blocks.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    return await cursor.to_list(limit)


async def _update(db: Any, block_id: str, *, status: Optional[str] = None,
                  extra: Optional[dict] = None) -> None:
    upd: dict = {"updated_at": iso(now_utc())}
    if status:
        upd["status"] = status
    if extra:
        upd.update(extra)
    await db.cloudflare_ip_blocks.update_one({"id": block_id}, {"$set": upd})
