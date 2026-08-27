"""iter196 — Email bounce alert (3 consecutive failures → notify admins).

Validates:
  1. `record_failure_and_maybe_alert` opens an alert row only after
     `STREAK_THRESHOLD` (3) consecutive failures within the lookback window.
  2. Existing open alerts are updated (streak_count++) instead of duplicated.
  3. A successful send resolves the open alert (`resolved_at` set).
  4. `dispatch_pending_alerts` fans out a notification to every admin and
     stamps the alert as `dispatched_at`.
  5. Second call to `dispatch_pending_alerts` is a no-op (idempotent).
"""
import os
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from pymongo import MongoClient

from tests.conftest import BASE_URL  # noqa: F401 — dotenv loading side-effect

from services.email_bounce_alerts import (
    record_failure_and_maybe_alert,
    clear_alert_on_success,
    dispatch_pending_alerts,
    STREAK_THRESHOLD,
)


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(seconds=offset_seconds)).isoformat()


def _seed_events(to: str, statuses: list[str]) -> None:
    """Insert email_events for `to` in chronological order (oldest first)."""
    db = _sync_db()
    for i, s in enumerate(statuses):
        db.email_events.insert_one({
            "id": f"emev_bt_{to}_{i}_{int(time.time()*1000)}",
            "to": to.lower(),
            "subject": f"seed {i} · {s}",
            "kind": "withdrawal_paid",
            "status": s,
            "error": f"seed error {i}" if s == "failed" else "",
            "provider_id": "",
            "attempts": 1,
            "created_at": _iso(offset_seconds=i),  # increasing timestamps
        })


@pytest.fixture(autouse=True)
def _cleanup():
    db = _sync_db()
    yield
    db.email_events.delete_many({"to": {"$regex": "^bounce_"}})
    db.email_bounce_alerts.delete_many({"to": {"$regex": "^bounce_"}})
    db.notifications.delete_many({"data.target_email": {"$regex": "^bounce_"}})


# ------------------------------------------------------------------
# Detection
# ------------------------------------------------------------------

def test_detection_needs_three_failures_to_open_alert():
    to = "bounce_a@ex.com"

    _seed_events(to, ["failed", "failed"])
    opened = record_failure_and_maybe_alert(to, MongoClient(os.environ["MONGO_URL"]))
    assert opened is False, "2 failures should not trigger alert yet"
    assert _sync_db().email_bounce_alerts.count_documents({"to": to}) == 0

    # 3rd failure lands, threshold met
    _seed_events(to, ["failed"])
    opened = record_failure_and_maybe_alert(to, MongoClient(os.environ["MONGO_URL"]))
    assert opened is True
    row = _sync_db().email_bounce_alerts.find_one({"to": to}, {"_id": 0})
    assert row and row["streak_count"] == STREAK_THRESHOLD
    assert row["dispatched_at"] is None
    assert row["resolved_at"] is None


def test_intervening_success_prevents_alert():
    """A `sent` row inside the last 3 events should NOT be treated as a
    streak — we only alert on 3 straight `failed`."""
    to = "bounce_mix@ex.com"
    _seed_events(to, ["failed", "sent", "failed", "failed"])
    opened = record_failure_and_maybe_alert(to, MongoClient(os.environ["MONGO_URL"]))
    assert opened is False, "the sent row breaks the streak"


def test_repeat_failure_updates_streak_but_doesnt_duplicate_alert():
    to = "bounce_dupe@ex.com"
    _seed_events(to, ["failed", "failed", "failed"])
    record_failure_and_maybe_alert(to, MongoClient(os.environ["MONGO_URL"]))
    _seed_events(to, ["failed"])  # 4th failure
    record_failure_and_maybe_alert(to, MongoClient(os.environ["MONGO_URL"]))

    alerts = list(_sync_db().email_bounce_alerts.find({"to": to}))
    assert len(alerts) == 1, "should not duplicate alerts"
    assert alerts[0]["streak_count"] == STREAK_THRESHOLD + 1


def test_success_resolves_open_alert():
    to = "bounce_heal@ex.com"
    _seed_events(to, ["failed", "failed", "failed"])
    record_failure_and_maybe_alert(to, MongoClient(os.environ["MONGO_URL"]))

    clear_alert_on_success(to, MongoClient(os.environ["MONGO_URL"]))
    row = _sync_db().email_bounce_alerts.find_one({"to": to}, {"_id": 0})
    assert row["resolved_at"] is not None


# ------------------------------------------------------------------
# Dispatch (async APScheduler job)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_fans_out_to_every_admin_and_marks_alert():
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

    to = "bounce_disp@ex.com"
    _seed_events(to, ["failed", "failed", "failed"])
    record_failure_and_maybe_alert(to, MongoClient(os.environ["MONGO_URL"]))

    # Count admins on the test DB
    admin_count = await db.users.count_documents({"role": "admin"})
    assert admin_count >= 1, "test DB must have at least one admin"

    with patch("push_service.send_push_to_user",
               new=_async_noop):
        result = await dispatch_pending_alerts(db)
    assert result["dispatched"] == 1

    # Alert is marked dispatched
    row = _sync_db().email_bounce_alerts.find_one({"to": to}, {"_id": 0})
    assert row["dispatched_at"] is not None

    # One notification per admin was inserted
    notifs = await db.notifications.count_documents({
        "type": "email_bounce_alert", "data.target_email": to,
    })
    assert notifs == admin_count, f"expected {admin_count} notifications, got {notifs}"


@pytest.mark.asyncio
async def test_dispatch_is_idempotent():
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

    to = "bounce_idem@ex.com"
    _seed_events(to, ["failed", "failed", "failed"])
    record_failure_and_maybe_alert(to, MongoClient(os.environ["MONGO_URL"]))

    with patch("push_service.send_push_to_user", new=_async_noop):
        r1 = await dispatch_pending_alerts(db)
        r2 = await dispatch_pending_alerts(db)
    assert r1["dispatched"] >= 1
    assert r2["dispatched"] == 0  # nothing left pending


async def _async_noop(*args, **kwargs):
    return None
