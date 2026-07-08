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
    actor: dict with user_id, email, role, name, allowed_permissions fields.
    action: e.g. 'order.approve', 'rate.update', 'user.role_change'.

    iter55.16b — enriched with the actor's permission snapshot at time of
    action so future audits can answer 'who could actually do this at that
    moment?' The snapshot is immutable — even if the admin later revokes the
    employee's permission, the historical record shows what they had when
    they performed the action.
    """
    try:
        raw_perms = list(actor.get("allowed_permissions") or [])
        role = actor.get("role", "")
        # Effective view — collapses admin + empty-list into "all" for humans
        # scanning the log; keeps the raw list for forensic replay.
        if role == "admin":
            effective = "all"
        elif not raw_perms:
            effective = "all_staff_default"  # backward-compat unrestricted employee
        else:
            effective = raw_perms

        entry = {
            "id": str(uuid.uuid4()),
            "actor_id": actor.get("user_id", ""),
            "actor_email": actor.get("email", ""),
            "actor_name": actor.get("name", ""),
            "actor_role": role,
            "actor_permissions": raw_perms,
            "actor_permissions_effective": effective,
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
