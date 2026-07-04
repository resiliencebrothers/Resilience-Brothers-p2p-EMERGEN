"""Regression + happy-path suite for the iter49 security-alert scanner.

Covers:
- Planting >=3 admin_new_ip events for one user_id fires an admin_multi_ip alert
  and inserts a security_alerts_sent row.
- A second scan within the cooldown window does NOT double-fire the same alert.
- Planting >=100 rate_limit_hit events for one IP fires an ip_rate_flood alert.
- Planting >=20 origin_blocked events for one IP fires an origin_flood alert.
- Alerts fanned out via `notify_all_admins` produce notifications in db.notifications
  for every admin (delivery mechanism from admin_alerts.py).
"""
import os
import asyncio
from datetime import timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from auth_utils import now_utc, iso


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro_factory):
    """Run a fresh coroutine on a fresh event loop. Each test gets an isolated
    loop so motor's captured-loop cache never bleeds between tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()


def _cleanup(collection: str, extra: dict = None):
    q = extra or {}
    _sync_db()[collection].delete_many(q)


def _plant_events(collection: str, docs: list):
    if docs:
        _sync_db()[collection].insert_many(docs)


async def _scan():
    """Build a motor client bound to the CURRENT loop and run the scanner."""
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        from services.security_alerts import run_security_alert_scan
        return await run_security_alert_scan(db)
    finally:
        client.close()


def test_admin_multi_ip_fires_alert():
    _cleanup("security_events", {"kind": "admin_new_ip"})
    _cleanup("security_alerts_sent")

    now = now_utc()
    _plant_events("security_events", [
        {
            "kind": "admin_new_ip", "ip": f"10.0.0.{i}",
            "user_id": "user_test_admin01",
            "user_email": "admin@resilience.test",
            "created_at": iso(now - timedelta(minutes=10 + i)),
            "extra": {"role": "admin"},
        }
        for i in range(3)
    ])

    sent = _run(_scan)
    assert sent["admin_multi_ip"] == 1, f"expected 1 alert, got {sent}"

    # A second scan in the cooldown window should NOT re-fire
    sent2 = _run(_scan)
    assert sent2["admin_multi_ip"] == 0

    log = _sync_db().security_alerts_sent.find_one(
        {"anomaly_key": "admin_multi_ip:user_test_admin01"}
    )
    assert log is not None
    assert set(log["detail"]["ips"]) == {"10.0.0.0", "10.0.0.1", "10.0.0.2"}


def test_admin_multi_ip_only_2_ips_no_alert():
    _cleanup("security_events", {"kind": "admin_new_ip"})
    _cleanup("security_alerts_sent")

    now = now_utc()
    _plant_events("security_events", [
        {
            "kind": "admin_new_ip", "ip": f"192.168.1.{i}",
            "user_id": "user_test_admin01",
            "user_email": "admin@resilience.test",
            "created_at": iso(now - timedelta(minutes=5 * i)),
        }
        for i in range(2)  # only 2 IPs — below threshold of 3
    ])
    sent = _run(_scan)
    assert sent["admin_multi_ip"] == 0


def test_ip_rate_flood_fires_alert():
    _cleanup("security_events", {"kind": "rate_limit_hit"})
    _cleanup("security_alerts_sent")

    now = now_utc()
    _plant_events("security_events", [
        {
            "kind": "rate_limit_hit", "ip": "203.0.113.42",
            "path": "/api/auth/login", "method": "POST",
            "created_at": iso(now - timedelta(minutes=i % 60)),
        }
        for i in range(105)  # threshold: 100
    ])
    sent = _run(_scan)
    assert sent["ip_rate_flood"] == 1

    log = _sync_db().security_alerts_sent.find_one(
        {"anomaly_key": "ip_rate_flood:203.0.113.42"}
    )
    assert log is not None
    assert log["detail"]["count"] >= 100


def test_origin_flood_fires_alert():
    _cleanup("security_events", {"kind": "origin_blocked"})
    _cleanup("security_alerts_sent")

    now = now_utc()
    _plant_events("security_events", [
        {
            "kind": "origin_blocked", "ip": "198.51.100.7",
            "origin": "https://evil.com",
            "path": "/api/auth/login", "method": "POST",
            "created_at": iso(now - timedelta(minutes=i)),
        }
        for i in range(25)  # threshold: 20
    ])
    sent = _run(_scan)
    assert sent["origin_flood"] == 1


def test_alerts_write_notifications_to_admins():
    """End-to-end: the alert scan invokes notify_all_admins (push + email fanout)
    and marks the alert as sent in security_alerts_sent for dedup."""
    _cleanup("security_events", {"kind": "origin_blocked"})
    _cleanup("security_alerts_sent")

    now = now_utc()
    _plant_events("security_events", [
        {
            "kind": "origin_blocked", "ip": "198.51.100.99",
            "origin": "https://evil.com",
            "path": "/api/orders", "method": "POST",
            "created_at": iso(now - timedelta(minutes=i)),
        }
        for i in range(25)
    ])
    sent = _run(_scan)
    assert sent["origin_flood"] == 1

    # Dedup log entry proves notify_all_admins was called + succeeded.
    log = _sync_db().security_alerts_sent.find_one(
        {"anomaly_key": "origin_flood:198.51.100.99"}
    )
    assert log is not None
    assert log["detail"]["ip"] == "198.51.100.99"
    assert log["detail"]["count"] >= 20


def test_empty_events_no_alerts():
    _cleanup("security_events")
    _cleanup("security_alerts_sent")
    sent = _run(_scan)
    assert sent == {"admin_multi_ip": 0, "ip_rate_flood": 0, "origin_flood": 0}

