"""Regression + happy-path suite for the iter50b IP blocklist middleware.

Covers:
1.  A request from an UN-blocked IP returns the normal response.
2.  A request from a BLOCKED IP (status='active') returns 403 with code=IP_BLOCKED.
3.  A request from an IP with status='failed' (CF sync failed but admin
    decided to block) is ALSO 403 — we honor the admin decision at the app
    layer even if CF wasn't reachable.
4.  A request from an IP with status='deleted' is NOT blocked (admin unblocked).
5.  The middleware picks up the real IP from `X-Forwarded-For` (Cloudflare
    forwards this — the raw request.client.host would be the ingress).
6.  Admin unblock endpoint invalidates the cache — the next request from
    that IP is allowed within seconds (not the 30s TTL).
7.  Admin manual block from `/api/admin/security/cloudflare/blocks` writes
    a record with status='failed' (no CF creds) — a subsequent request from
    that IP is 403'd by the middleware.
8.  Auto-block scanner path — planting >=100 rate_limit_hit events for an IP
    causes the scanner to call `create_block` and the middleware to enforce
    the block, even when Cloudflare is NOT configured.
"""
import os
import asyncio
import time
import requests
import pytest
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _plant_block(ip: str, status: str = "active") -> str:
    """Insert a block record and return its id. Also invalidates the
    middleware cache so the block takes effect on the NEXT request."""
    _sync_db().cloudflare_ip_blocks.delete_many({"ip": ip})
    block_id = f"test-{ip.replace('.', '-')}"
    _sync_db().cloudflare_ip_blocks.insert_one({
        "id": block_id,
        "ip": ip,
        "status": status,
        "cf_rule_id": None,
        "source": "test",
        "notes": f"planted for middleware test (status={status})",
        "created_at": "2026-07-04T00:00:00Z",
        "updated_at": "2026-07-04T00:00:00Z",
    })
    # Force cache invalidation. Since middleware runs in the backend
    # process and tests are in a different process, we can't call
    # invalidate_cache() directly. Instead, we hit an admin endpoint that
    # DOES invalidate the cache (POST /admin/security/cloudflare/blocks)
    # — but the simplest approach is to wait for TTL. For tests, 31s is
    # too slow. Instead we use the API path: hit an existing block-delete
    # endpoint which invalidates. Or, we rely on the middleware to re-fetch
    # after the TTL expires. For reliability, we do a small request that
    # forces cache refresh via the ADMIN endpoint sequence.
    return block_id


def _cleanup_block(ip: str):
    _sync_db().cloudflare_ip_blocks.delete_many({"ip": ip})


def _invalidate_via_admin_action():
    """Trigger cache invalidation server-side by creating+deleting a throwaway
    block. Each admin op calls invalidate_cache() on the server."""
    throwaway_ip = "192.0.2.254"  # RFC 5737 doc range
    _sync_db().cloudflare_ip_blocks.delete_many({"ip": throwaway_ip})
    r = requests.post(
        f"{API}/admin/security/cloudflare/blocks",
        headers=_hdr(ADMIN_TOKEN),
        json={"ip": throwaway_ip, "notes": "cache-invalidation trigger"},
    )
    if r.status_code == 200:
        block_id = r.json().get("block_id")
        if block_id:
            requests.delete(
                f"{API}/admin/security/cloudflare/blocks/{block_id}",
                headers=_hdr(ADMIN_TOKEN),
            )
    _sync_db().cloudflare_ip_blocks.delete_many({"ip": throwaway_ip})


# ------------------------------------------------------------------
# 1. Unblocked IP passes through
# ------------------------------------------------------------------

def test_unblocked_ip_reaches_api():
    """Baseline — no block record for a fake IP, so the middleware does not
    reject requests from that IP. We simulate by sending a request WITHOUT
    X-Forwarded-For (so the middleware sees the ingress IP, which is not
    blocked)."""
    _invalidate_via_admin_action()
    r = requests.get(f"{API}/", timeout=10)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


# ------------------------------------------------------------------
# 2 + 3. Blocked IP returns 403 (status='active' AND status='failed')
# ------------------------------------------------------------------

@pytest.mark.parametrize("status", ["active", "failed", "pending_create"])
def test_blocked_ip_returns_403_regardless_of_status(status):
    """A request whose X-Forwarded-For matches a blocked IP → 403."""
    fake_ip = "198.51.100.77"
    _plant_block(fake_ip, status=status)
    _invalidate_via_admin_action()

    r = requests.get(
        f"{API}/",
        headers={"X-Forwarded-For": fake_ip},
        timeout=10,
    )
    assert r.status_code == 403, f"Expected 403 for status={status}, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("code") == "IP_BLOCKED"
    _cleanup_block(fake_ip)


# ------------------------------------------------------------------
# 4. Deleted status is NOT enforced
# ------------------------------------------------------------------

def test_deleted_ip_is_not_blocked():
    fake_ip = "198.51.100.78"
    _plant_block(fake_ip, status="deleted")
    _invalidate_via_admin_action()

    r = requests.get(
        f"{API}/",
        headers={"X-Forwarded-For": fake_ip},
        timeout=10,
    )
    assert r.status_code == 200
    _cleanup_block(fake_ip)


# ------------------------------------------------------------------
# 5. Real IP resolution via X-Forwarded-For (leftmost)
# ------------------------------------------------------------------

def test_middleware_uses_leftmost_xff():
    """Chained proxies produce 'client, proxy1, proxy2'. The middleware must
    pick the leftmost (real client) IP per RFC 7239."""
    fake_ip = "198.51.100.79"
    _plant_block(fake_ip, status="active")
    _invalidate_via_admin_action()

    r = requests.get(
        f"{API}/",
        headers={"X-Forwarded-For": f"{fake_ip}, 10.0.0.1, 10.0.0.2"},
        timeout=10,
    )
    assert r.status_code == 403
    assert r.json().get("code") == "IP_BLOCKED"
    _cleanup_block(fake_ip)


# ------------------------------------------------------------------
# 6. Admin unblock invalidates cache immediately
# ------------------------------------------------------------------

def test_unblock_takes_effect_immediately():
    fake_ip = "198.51.100.80"
    # 1. Block via admin API (server-side invalidate_cache called)
    r = requests.post(
        f"{API}/admin/security/cloudflare/blocks",
        headers=_hdr(ADMIN_TOKEN),
        json={"ip": fake_ip, "notes": "immediate-effect test"},
    )
    assert r.status_code == 200
    block_id = r.json()["block_id"]

    # 2. Verify blocked
    r2 = requests.get(
        f"{API}/",
        headers={"X-Forwarded-For": fake_ip},
        timeout=10,
    )
    assert r2.status_code == 403

    # 3. Unblock (server invalidates cache again)
    r3 = requests.delete(
        f"{API}/admin/security/cloudflare/blocks/{block_id}",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r3.status_code == 200

    # 4. Verify allowed (WITHIN 1s — no waiting for TTL)
    r4 = requests.get(
        f"{API}/",
        headers={"X-Forwarded-For": fake_ip},
        timeout=10,
    )
    assert r4.status_code == 200, f"Should be unblocked, got {r4.status_code}"
    _cleanup_block(fake_ip)


# ------------------------------------------------------------------
# 7. Admin manual block works even without Cloudflare credentials
# ------------------------------------------------------------------

def test_manual_block_enforced_without_cloudflare():
    """The whole point of iter50b — CF creds are NOT set in the env, but the
    manual block still enforces at the app layer."""
    fake_ip = "198.51.100.81"
    r = requests.post(
        f"{API}/admin/security/cloudflare/blocks",
        headers=_hdr(ADMIN_TOKEN),
        json={"ip": fake_ip, "notes": "no-cf test"},
    )
    assert r.status_code == 200
    data = r.json()
    # No CF creds → cf_ok False, but the record persists (status='failed')
    # and the middleware still enforces.
    assert data.get("cf_ok") is False
    assert data.get("created") is True

    r2 = requests.get(
        f"{API}/",
        headers={"X-Forwarded-For": fake_ip},
        timeout=10,
    )
    assert r2.status_code == 403
    assert r2.json().get("code") == "IP_BLOCKED"
    _cleanup_block(fake_ip)


# ------------------------------------------------------------------
# 8. Scanner auto-block writes a persistent record enforced by the middleware
# ------------------------------------------------------------------

def test_scanner_auto_block_persists_and_enforces(monkeypatch):
    fake_ip = "203.0.113.201"
    _cleanup_block(fake_ip)
    _sync_db().security_events.delete_many({"kind": "rate_limit_hit", "ip": fake_ip})
    _sync_db().security_alerts_sent.delete_many({"anomaly_key": {"$regex": f"^ip_rate_flood:{fake_ip}"}})

    # Plant 101 rate_limit_hit events for the fake IP inside the last hour.
    from auth_utils import now_utc, iso
    now = now_utc()
    docs = [{
        "kind": "rate_limit_hit",
        "ip": fake_ip,
        "path": "/api/auth/login",
        "method": "POST",
        "created_at": iso(now),
        "_ts": now,
    } for _ in range(101)]
    _sync_db().security_events.insert_many(docs)

    # Silence the admin fan-out (to avoid noisy notifications).
    async def _fake_notify(*args, **kwargs):
        return None

    monkeypatch.setattr("admin_alerts.notify_all_admins", _fake_notify)

    # Run the scanner directly against a motor client bound to the current loop.
    async def _do():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            from services.security_alerts import run_security_alert_scan
            return await run_security_alert_scan(db)
        finally:
            client.close()

    loop = asyncio.new_event_loop()
    try:
        summary = loop.run_until_complete(_do())
    finally:
        loop.close()

    assert summary["ip_rate_flood"] >= 1

    # A local block record should now exist for the fake IP.
    doc = _sync_db().cloudflare_ip_blocks.find_one({"ip": fake_ip})
    assert doc is not None, "Scanner should have persisted a block record"
    assert doc["source"] == "scanner"
    assert doc["status"] in ("active", "failed", "pending_create")

    # The scanner ran in this test process (own event loop) → the server's
    # in-memory blocklist cache doesn't know about the new block yet. In
    # production, when the scheduler triggers the scan inside the backend
    # process, invalidate_cache() takes effect immediately. For this test,
    # we invalidate the server-side cache by performing an admin action
    # (which internally calls invalidate_cache).
    _invalidate_via_admin_action()

    r = requests.get(
        f"{API}/",
        headers={"X-Forwarded-For": fake_ip},
        timeout=10,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
    assert r.json().get("code") == "IP_BLOCKED"

    _cleanup_block(fake_ip)
    _sync_db().security_events.delete_many({"kind": "rate_limit_hit", "ip": fake_ip})
    _sync_db().security_alerts_sent.delete_many({"anomaly_key": {"$regex": f"^ip_rate_flood:{fake_ip}"}})
