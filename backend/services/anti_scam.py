"""iter46 — Anti-scam analytics helpers.

Provides 3 small async helpers used across `routes/auth.py` and
`routes/blocklist.py` to track the `under_review` lifecycle without
sprinkling timestamp logic across the codebase:

- `mark_user_under_review`: idempotently moves a user into `under_review`
  and stamps `under_review_since` on the first transition only (does NOT
  overwrite a still-pending under_review timestamp).
- `mark_user_active`: moves a user to `active`, computes elapsed hours
  since `under_review_since` and stores them in `last_under_review_hours`
  for the analytics endpoint.
- `compute_anti_scam_metrics`: aggregate metrics for the Admin Health
  dashboard.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from db_client import db

ISO_FMT = "%Y-%m-%dT%H:%M:%S"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(s: str) -> Optional[datetime]:
    """Best-effort parse of an ISO timestamp produced by `_iso(...)`. Returns
    None on any error; analytics treat None as 'not stamped yet'."""
    if not s:
        return None
    try:
        # Python's fromisoformat handles +HH:MM offsets natively.
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


async def mark_user_under_review(
    user_id: str, extra_set: Optional[dict] = None
) -> None:
    """Move `user_id` to `under_review`. Only stamps `under_review_since`
    if the user is NOT already in `under_review` (preserves the original
    open-ticket timestamp on idempotent re-blocks)."""
    existing = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "account_status": 1, "under_review_since": 1},
    )
    set_dict: dict[str, Any] = {
        "account_status": "under_review",
        "phone_verified": False,
    }
    if extra_set:
        set_dict.update(extra_set)
    already_under_review = (
        existing and existing.get("account_status") == "under_review"
        and existing.get("under_review_since")
    )
    if not already_under_review:
        set_dict["under_review_since"] = _iso(_now())
    await db.users.update_one({"user_id": user_id}, {"$set": set_dict})


async def mark_user_active(user_id: str) -> None:
    """Move `user_id` to `active`. If they had `under_review_since` stamped,
    compute elapsed hours and persist in `last_under_review_hours` so the
    analytics endpoint can compute averages."""
    existing = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "under_review_since": 1},
    )
    set_dict: dict[str, Any] = {
        "account_status": "active",
        "phone_verified": True,
    }
    unset_dict: dict[str, Any] = {}
    since = _parse_iso((existing or {}).get("under_review_since") or "")
    if since is not None:
        delta_hours = (_now() - since).total_seconds() / 3600.0
        # Clamp ridiculous negatives (server clock skew) to 0.
        set_dict["last_under_review_hours"] = max(0.0, round(delta_hours, 4))
        unset_dict["under_review_since"] = ""
    update: dict[str, Any] = {"$set": set_dict}
    if unset_dict:
        update["$unset"] = unset_dict
    await db.users.update_one({"user_id": user_id}, update)


async def compute_anti_scam_metrics() -> dict:
    """Aggregate metrics for the Admin Health dashboard.

    Returns:
        {
          "users_under_review": int,             # active queue depth right now
          "avg_resolution_hours": float | None,  # mean over resolved cases
          "resolved_count": int,                 # how many cases contribute to the average
          "oldest_pending_hours": float | None,  # how long the oldest open ticket has been waiting
        }
    """
    queue_depth = await db.users.count_documents(
        {"account_status": "under_review"}
    )

    # avg(last_under_review_hours) over users with that field (resolved cases)
    pipeline = [
        {"$match": {"last_under_review_hours": {"$exists": True}}},
        {"$group": {
            "_id": None,
            "avg_hours": {"$avg": "$last_under_review_hours"},
            "count": {"$sum": 1},
        }},
    ]
    rows = await db.users.aggregate(pipeline).to_list(1)
    if rows:
        avg_hours = round(float(rows[0]["avg_hours"]), 2)
        resolved_count = int(rows[0]["count"])
    else:
        avg_hours = None
        resolved_count = 0

    # Oldest pending ticket (the under_review user whose timestamp is earliest)
    oldest = await db.users.find_one(
        {"account_status": "under_review",
         "under_review_since": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "under_review_since": 1},
        sort=[("under_review_since", 1)],
    )
    oldest_hours: Optional[float] = None
    if oldest:
        ts = _parse_iso(oldest.get("under_review_since") or "")
        if ts is not None:
            oldest_hours = round(
                max(0.0, (_now() - ts).total_seconds() / 3600.0), 2
            )

    return {
        "users_under_review": queue_depth,
        "avg_resolution_hours": avg_hours,
        "resolved_count": resolved_count,
        "oldest_pending_hours": oldest_hours,
    }
