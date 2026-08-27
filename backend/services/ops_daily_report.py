"""iter176 — Daily ops digest: fraud/attention cases older than 48h.

Sections (only cases stale > STALE_HOURS):
  1. users in `under_review` (anti-fraud) nobody resolved
  2. pending `appeals` awaiting staff
  3. `support_tickets` still open without a staff answer

Sent 08:00 America/Havana. Silent when there is nothing pending.
Opt-out: settings.global.auto_send_daily_ops_report = False.
"""
import logging
from typing import Any
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

STALE_HOURS = 48


def _cutoff_iso(hours: int = STALE_HOURS) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _age_hours(ts: Any) -> int | None:
    try:
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - dt).total_seconds() // 3600)
    except (TypeError, ValueError):
        return None


async def collect_stale_cases(db: Any, hours: int = STALE_HOURS) -> dict:
    cutoff = _cutoff_iso(hours)
    under_review = await db.users.find(
        {"account_status": "under_review",
         "$or": [{"under_review_since": {"$lte": cutoff}},
                 {"under_review_since": {"$in": [None, ""]}},
                 {"under_review_since": {"$exists": False}}]},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "phone": 1,
         "under_review_since": 1},
    ).sort("under_review_since", 1).to_list(500)
    appeals = await db.appeals.find(
        {"status": "pending", "created_at": {"$lte": cutoff}},
        {"_id": 0, "id": 1, "user_id": 1, "user_name": 1, "user_email": 1,
         "message": 1, "created_at": 1},
    ).sort("created_at", 1).to_list(500)
    tickets = await db.support_tickets.find(
        {"status": "open", "updated_at": {"$lte": cutoff}},
        {"_id": 0, "id": 1, "user_name": 1, "user_email": 1, "subject": 1,
         "category": 1, "created_at": 1, "updated_at": 1},
    ).sort("updated_at", 1).to_list(500)
    for u in under_review:
        u["age_hours"] = _age_hours(u.get("under_review_since"))
    for a in appeals:
        a["age_hours"] = _age_hours(a.get("created_at"))
    for t in tickets:
        t["age_hours"] = _age_hours(t.get("updated_at"))
    return {"under_review": under_review, "appeals": appeals,
            "tickets": tickets, "hours": hours,
            "total": len(under_review) + len(appeals) + len(tickets)}


async def run_daily_ops_fraud_report(db: Any) -> dict:
    """08:00 America/Havana — email ops the >48h backlog."""
    import email_service
    from admin_alerts import resolve_admin_email_recipients
    try:
        settings = await db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
    except Exception:
        settings = {}
    if not settings.get("auto_send_daily_ops_report", True):
        logger.info("Daily ops report: skipped (opt-out flag)")
        return {"sent": 0, "skipped": "opt_out", "total": 0}
    report = await collect_stale_cases(db)
    if report["total"] == 0:
        logger.info("Daily ops report: nothing older than %sh — not sent",
                    report["hours"])
        return {"sent": 0, "skipped": "empty", "total": 0,
                "under_review": 0, "appeals": 0, "tickets": 0}
    recipients = await resolve_admin_email_recipients(db)
    sent = 0
    for to in recipients:
        try:
            if email_service.notify_daily_ops_report(to, report):
                sent += 1
        except Exception:
            logger.exception("Daily ops report to %s failed", to)
    logger.info("Daily ops report: %s casos → sent to %s/%s recipient(s)",
                report["total"], sent, len(recipients))
    return {"sent": sent, "recipients": len(recipients),
            "under_review": len(report["under_review"]),
            "appeals": len(report["appeals"]),
            "tickets": len(report["tickets"]),
            "total": report["total"]}
