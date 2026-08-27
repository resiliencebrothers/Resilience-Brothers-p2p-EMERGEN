"""iter196 — Email bounce alerts.

Monitor `email_events` and raise a staff notification when the same
recipient accumulates 3 consecutive `failed` sends within a rolling 24h
window. Typical causes: blocked domain, mailbox full, hard bounce.

Two entry points:
  - `record_failure_and_maybe_alert(to)` — called synchronously from
    `email_service._send` after every failed send. Uses the shared pymongo
    client (no async loop dependency).
  - `dispatch_pending_alerts(db)` — APScheduler job that fans-out
    push/in-app notifications for any pending alert. Decoupled from the
    detection so a slow Resend outage never blocks the caller.

De-duplication: at most one open alert per recipient. When a `sent` event
lands for that recipient we close the alert automatically so a healed
mailbox stops the noise.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

STREAK_THRESHOLD = 3   # 3 consecutive failed sends → alert
LOOKBACK_HOURS = 24    # only consider events within the last day


# ------------------------------------------------------------------
# Detection (sync — called from email_service._send)
# ------------------------------------------------------------------

def record_failure_and_maybe_alert(to: str, mongo_client: Any) -> bool:
    """Return True when this failure crossed the threshold and created an
    (or reused an existing) alert row. Idempotent + best-effort — any
    exception is swallowed so email delivery flow is never affected."""
    if not to or mongo_client is None:
        return False
    try:
        db = mongo_client[os.environ["DB_NAME"]]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).isoformat()
        recent = list(db.email_events.find(
            {"to": to.lower(), "created_at": {"$gte": cutoff}},
            {"_id": 0, "status": 1, "created_at": 1, "kind": 1, "error": 1, "subject": 1},
        ).sort("created_at", -1).limit(STREAK_THRESHOLD))
        if len(recent) < STREAK_THRESHOLD:
            return False
        if not all(e.get("status") == "failed" for e in recent):
            return False

        # 3 consecutive failures — open/reuse alert row.
        existing = db.email_bounce_alerts.find_one(
            {"to": to.lower(), "resolved_at": None},
            {"_id": 0, "id": 1, "streak_count": 1},
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        if existing:
            db.email_bounce_alerts.update_one(
                {"id": existing["id"]},
                {"$set": {"streak_count": existing.get("streak_count", 3) + 1,
                          "last_error": recent[0].get("error", ""),
                          "last_subject": recent[0].get("subject", ""),
                          "last_failure_at": now_iso}},
            )
            return False  # already alerted — scheduler won't re-dispatch
        alert_id = f"emba_{recent[0]['created_at'][:10].replace('-', '')}_{to.lower().replace('@','_at_')[:24]}"
        db.email_bounce_alerts.insert_one({
            "id": alert_id,
            "to": to.lower(),
            "streak_count": STREAK_THRESHOLD,
            "first_failure_at": recent[-1]["created_at"],
            "last_failure_at": recent[0]["created_at"],
            "last_error": recent[0].get("error", ""),
            "last_subject": recent[0].get("subject", ""),
            "kind_sample": recent[0].get("kind", ""),
            "created_at": now_iso,
            "dispatched_at": None,   # scheduler will pick it up
            "resolved_at": None,
        })
        return True
    except Exception as e:
        logger.error(f"[bounce] record_failure_and_maybe_alert({to}): {e}")
        return False


def clear_alert_on_success(to: str, mongo_client: Any) -> None:
    """Called after a successful send — closes any open alert so the same
    recipient doesn't stay flagged after they recover."""
    if not to or mongo_client is None:
        return
    try:
        db = mongo_client[os.environ["DB_NAME"]]
        db.email_bounce_alerts.update_many(
            {"to": to.lower(), "resolved_at": None},
            {"$set": {"resolved_at": datetime.now(timezone.utc).isoformat()}},
        )
    except Exception as e:
        logger.error(f"[bounce] clear_alert_on_success({to}): {e}")


# ------------------------------------------------------------------
# Dispatch (async — APScheduler job)
# ------------------------------------------------------------------

async def dispatch_pending_alerts(db: Any) -> dict:
    """Find alerts with `dispatched_at is None` and fan-out push + in-app
    notifications to every admin. Returns a summary for logging/testing."""
    now = datetime.now(timezone.utc).isoformat()
    pending = await db.email_bounce_alerts.find(
        {"dispatched_at": None, "resolved_at": None},
        {"_id": 0},
    ).to_list(20)
    if not pending:
        return {"dispatched": 0}

    # Load owning user info once per alert (email → user for the deep link)
    dispatched = 0
    for alert in pending:
        try:
            owner = await db.users.find_one(
                {"email": alert["to"]},
                {"_id": 0, "user_id": 1, "name": 1, "email": 1},
            ) or {"user_id": None, "name": alert["to"], "email": alert["to"]}
            await _fanout_to_staff(db, alert, owner)
            await db.email_bounce_alerts.update_one(
                {"id": alert["id"]},
                {"$set": {"dispatched_at": now}},
            )
            dispatched += 1
        except Exception as e:
            logger.error(f"[bounce] dispatch failed for {alert.get('id')}: {e}")
    return {"dispatched": dispatched, "total_pending": len(pending)}


async def _fanout_to_staff(db: Any, alert: dict, owner: dict) -> None:
    """Push + in-app to every admin. Kept in this module (rather than
    routes/notifications.py) so tests can mock the fanout cleanly."""
    from routes.notifications import _insert_notification
    from push_service import send_push_to_user, build_generic_admin_alert_payload

    recipients = [r async for r in db.users.find(
        {"role": "admin"},
        {"_id": 0, "user_id": 1, "preferred_language": 1},
    )]

    name = owner.get("name") or alert["to"]
    title_es = "3 fallos de correo consecutivos"
    title_en = "3 consecutive email failures"
    msg_es = (f"{name} ({alert['to']}) acumuló {alert['streak_count']} fallos "
              f"de correo. Último error: {alert.get('last_error') or 'sin detalle'}.")
    msg_en = (f"{name} ({alert['to']}) racked up {alert['streak_count']} email "
              f"failures. Last error: {alert.get('last_error') or 'no detail'}.")

    data = {
        "alert_id": alert["id"],
        "target_email": alert["to"],
        "target_user_id": owner.get("user_id"),
        "streak_count": alert["streak_count"],
        "last_error": alert.get("last_error", ""),
        "last_subject": alert.get("last_subject", ""),
    }

    for r in recipients:
        try:
            lang = r.get("preferred_language") or "es"
            await _insert_notification(
                recipient_user_id=r["user_id"],
                type="email_bounce_alert",
                title=title_en if lang == "en" else title_es,
                message=msg_en if lang == "en" else msg_es,
                data=data,
            )
            payload = build_generic_admin_alert_payload(
                title=title_en if lang == "en" else title_es,
                body=msg_en if lang == "en" else msg_es,
                url=(f"/admin/users/{owner['user_id']}/stats"
                     if owner.get("user_id") else "/admin/users"),
            )
            await send_push_to_user(db, r["user_id"], payload)
        except Exception as e:
            logger.error(f"[bounce] fanout to {r.get('user_id')}: {e}")
