"""Audit log for staff actions (admin + employee)."""
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def log_action(
    db,
    actor: dict,
    action: str,
    entity_type: str,
    entity_id: str = "",
    summary: str = "",
    details: dict = None,
):
    """Insert a single audit log entry. Never raises.
    actor: dict with user_id, email, role, name fields.
    action: e.g. 'order.approve', 'rate.update', 'user.role_change'.
    """
    try:
        entry = {
            "id": str(uuid.uuid4()),
            "actor_id": actor.get("user_id", ""),
            "actor_email": actor.get("email", ""),
            "actor_name": actor.get("name", ""),
            "actor_role": actor.get("role", ""),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "summary": summary,
            "details": details or {},
            "created_at": _iso_now(),
        }
        await db.audit_log.insert_one(entry)
    except Exception as e:
        logger.error(f"Audit log failed for action {action}: {e}")
