"""Regression + happy-path suite for the iter50 Cloudflare WAF IP-block feature.

Covers:
1.  `cloudflare_client._is_configured` returns False without env vars, True with both.
2.  `create_block_rule` success path — returns rule_id on 200.
3.  `create_block_rule` duplicate path — 400 + "already exists" + follow-up lookup
    returns the existing rule id.
4.  `create_block_rule` failure path — non-2xx bubbles up as ok=False.
5.  `delete_rule` — 200/204/404 all treated as success; other statuses return
    ok=False.
6.  `cloudflare_blocks.create_block` short-circuits with `status=failed` and
    `reason=not_configured` when env is missing (audit trail preserved).
7.  `cloudflare_blocks.create_block` idempotency — second call for an
    already-ACTIVE IP returns `already_blocked=True` without hitting CF.
8.  Admin HTTP endpoints:
    - GET /api/admin/security/cloudflare/blocks admin-only (200 admin, 403 employee/vip/normal).
    - POST creates a block (persists in Mongo, source='admin').
    - DELETE moves status to 'deleted' idempotently.
9.  Auto-block: `is_auto_block_enabled` False by default; True when both vars +
    `CLOUDFLARE_AUTO_BLOCK_ENABLED=true`.
10. Auto-block wiring in security_alerts._fire_ip_flood: patches
    `cloudflare_blocks.create_block` and confirms it is called when auto-block
    is enabled and NOT called when disabled.
"""
import os
import asyncio
import json
import requests
import httpx
import pytest
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _cleanup_blocks(ip: str = None):
    q = {"ip": ip} if ip else {}
    _sync_db().cloudflare_ip_blocks.delete_many(q)


def _run(coro_factory):
    """Run a fresh coroutine on a fresh event loop (motor loop-cache safe)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()


# ------------------------------------------------------------------
# 1. _is_configured / is_auto_block_enabled toggles
# ------------------------------------------------------------------

def test_is_configured_false_without_env(monkeypatch):
    monkeypatch.delenv("CF_API_TOKEN", raising=False)
    monkeypatch.delenv("CF_ZONE_ID", raising=False)
    from services import cloudflare_client
    assert cloudflare_client._is_configured() is False
    assert cloudflare_client.is_auto_block_enabled() is False


def test_is_configured_true_with_env(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "test-token")
    monkeypatch.setenv("CF_ZONE_ID", "test-zone")
    from services import cloudflare_client
    assert cloudflare_client._is_configured() is True


def test_auto_block_enabled_requires_flag(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "test-token")
    monkeypatch.setenv("CF_ZONE_ID", "test-zone")
    monkeypatch.delenv("CLOUDFLARE_AUTO_BLOCK_ENABLED", raising=False)
    from services import cloudflare_client
    assert cloudflare_client.is_auto_block_enabled() is False

    monkeypatch.setenv("CLOUDFLARE_AUTO_BLOCK_ENABLED", "true")
    assert cloudflare_client.is_auto_block_enabled() is True

    monkeypatch.setenv("CLOUDFLARE_AUTO_BLOCK_ENABLED", "false")
    assert cloudflare_client.is_auto_block_enabled() is False


# ------------------------------------------------------------------
# 2-4. create_block_rule paths (mocked httpx)
# ------------------------------------------------------------------

def _mock_httpx_client(handler):
    """Patch httpx.AsyncClient to use MockTransport(handler)."""
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    class _Wrapped(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)
    return _Wrapped


def test_create_block_rule_success(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setenv("CF_ZONE_ID", "zone")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body["mode"] == "block"
        assert body["configuration"] == {"target": "ip", "value": "1.2.3.4"}
        return httpx.Response(200, json={
            "success": True,
            "result": {"id": "cf-rule-abc123"},
        })

    monkeypatch.setattr("httpx.AsyncClient", _mock_httpx_client(handler))
    from services import cloudflare_client
    res = _run(lambda: cloudflare_client.create_block_rule("1.2.3.4", "test note"))
    assert res["ok"] is True
    assert res["rule_id"] == "cf-rule-abc123"


def test_create_block_rule_duplicate_returns_existing(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setenv("CF_ZONE_ID", "zone")

    calls = {"post": 0, "get": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            calls["post"] += 1
            return httpx.Response(400, json={
                "success": False,
                "errors": [{"message": "firewall access rule already exists"}],
            })
        # GET follow-up
        calls["get"] += 1
        return httpx.Response(200, json={
            "success": True,
            "result": [{"id": "cf-existing-xyz"}],
        })

    monkeypatch.setattr("httpx.AsyncClient", _mock_httpx_client(handler))
    from services import cloudflare_client
    res = _run(lambda: cloudflare_client.create_block_rule("5.6.7.8", "dup"))
    assert res["ok"] is False
    assert res["existing_rule_id"] == "cf-existing-xyz"
    assert calls["post"] == 1 and calls["get"] == 1


def test_create_block_rule_failure_generic(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setenv("CF_ZONE_ID", "zone")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={
            "success": False,
            "errors": [{"message": "internal server error"}],
        })

    monkeypatch.setattr("httpx.AsyncClient", _mock_httpx_client(handler))
    from services import cloudflare_client
    res = _run(lambda: cloudflare_client.create_block_rule("9.9.9.9", "test"))
    assert res["ok"] is False
    assert "internal server error" in res["error"]
    assert res["status"] == 500


# ------------------------------------------------------------------
# 5. delete_rule
# ------------------------------------------------------------------

def test_delete_rule_success_and_idempotent(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setenv("CF_ZONE_ID", "zone")

    responses = iter([200, 204, 404, 500])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        status = next(responses)
        if status == 500:
            return httpx.Response(500, json={"success": False, "errors": [{"message": "boom"}]})
        return httpx.Response(status, json={"success": True})

    monkeypatch.setattr("httpx.AsyncClient", _mock_httpx_client(handler))
    from services import cloudflare_client

    # 200, 204, 404 are all "success"
    for _ in range(3):
        r = _run(lambda: cloudflare_client.delete_rule("rule-1"))
        assert r["ok"] is True
    # 500 is a real failure
    r = _run(lambda: cloudflare_client.delete_rule("rule-1"))
    assert r["ok"] is False


# ------------------------------------------------------------------
# 6-7. cloudflare_blocks.create_block persistence
# ------------------------------------------------------------------

def test_create_block_without_cf_config_marks_failed(monkeypatch):
    _cleanup_blocks("10.0.0.1")
    monkeypatch.delenv("CF_API_TOKEN", raising=False)
    monkeypatch.delenv("CF_ZONE_ID", raising=False)

    async def _do():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            from services import cloudflare_blocks
            return await cloudflare_blocks.create_block(
                db, "10.0.0.1", "test-notes", source="admin",
            )
        finally:
            client.close()

    res = _run(_do)
    assert res["cf_ok"] is False
    assert res.get("reason") == "not_configured"
    doc = _sync_db().cloudflare_ip_blocks.find_one({"ip": "10.0.0.1"})
    assert doc is not None
    assert doc["status"] == "failed"
    assert doc["source"] == "admin"
    _cleanup_blocks("10.0.0.1")


def test_create_block_idempotent_for_active_ip(monkeypatch):
    _cleanup_blocks("10.0.0.2")
    # Pre-plant an active block
    _sync_db().cloudflare_ip_blocks.insert_one({
        "id": "pre-active-id",
        "ip": "10.0.0.2",
        "status": "active",
        "cf_rule_id": "cf-pre-rule",
        "source": "admin",
        "notes": "pre",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })

    call_count = {"cf": 0}

    def handler(request):
        call_count["cf"] += 1
        return httpx.Response(200, json={"success": True, "result": {"id": "should-not-be-called"}})

    monkeypatch.setattr("httpx.AsyncClient", _mock_httpx_client(handler))
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setenv("CF_ZONE_ID", "zone")

    async def _do():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            from services import cloudflare_blocks
            return await cloudflare_blocks.create_block(
                db, "10.0.0.2", "second attempt", source="admin",
            )
        finally:
            client.close()

    res = _run(_do)
    assert res.get("already_blocked") is True
    assert call_count["cf"] == 0  # No CF call for idempotent hit.
    _cleanup_blocks("10.0.0.2")


# ------------------------------------------------------------------
# 8. Admin HTTP endpoints
# ------------------------------------------------------------------

def test_cloudflare_blocks_list_admin_ok():
    r = requests.get(f"{API}/admin/security/cloudflare/blocks", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert "items" in d and isinstance(d["items"], list)
    assert "configured" in d
    assert "auto_block_enabled" in d


@pytest.mark.parametrize("tok", [EMPLOYEE_TOKEN, VIP_TOKEN, NORMAL_TOKEN])
def test_cloudflare_blocks_list_forbidden_for_non_admin(tok):
    r = requests.get(f"{API}/admin/security/cloudflare/blocks", headers=_hdr(tok))
    assert r.status_code == 403


def test_cloudflare_block_create_manual_persists():
    _cleanup_blocks("172.31.99.99")
    r = requests.post(
        f"{API}/admin/security/cloudflare/blocks",
        headers=_hdr(ADMIN_TOKEN),
        json={"ip": "172.31.99.99", "notes": "manual test"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("created") is True
    assert d.get("block_id")
    # Without CF creds set in the container, cf_ok will be False and status=failed
    doc = _sync_db().cloudflare_ip_blocks.find_one({"ip": "172.31.99.99"})
    assert doc is not None
    assert doc["source"] == "admin"
    _cleanup_blocks("172.31.99.99")


def test_cloudflare_block_delete_moves_to_deleted():
    _cleanup_blocks("172.31.99.98")
    # Pre-plant an active block
    _sync_db().cloudflare_ip_blocks.insert_one({
        "id": "manual-del-id",
        "ip": "172.31.99.98",
        "status": "active",
        "cf_rule_id": None,  # No CF rule → skip external call
        "source": "admin",
        "notes": "pre",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })
    r = requests.delete(
        f"{API}/admin/security/cloudflare/blocks/manual-del-id",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 200, r.text
    doc = _sync_db().cloudflare_ip_blocks.find_one({"id": "manual-del-id"})
    assert doc["status"] == "deleted"
    _cleanup_blocks("172.31.99.98")


def test_cloudflare_block_delete_unknown_404():
    r = requests.delete(
        f"{API}/admin/security/cloudflare/blocks/does-not-exist",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 404


# ------------------------------------------------------------------
# 10. Auto-block wiring in security_alerts
# ------------------------------------------------------------------

def test_ip_flood_triggers_cloudflare_when_auto_block_on(monkeypatch):
    """Scan sees an IP flood + auto-block ON → create_block IS called."""
    _cleanup_blocks("203.0.113.99")
    _sync_db().security_alerts_sent.delete_many({"anomaly_key": {"$regex": "^ip_rate_flood:203.0.113.99"}})
    _sync_db().security_events.delete_many({"kind": "rate_limit_hit", "ip": "203.0.113.99"})

    from auth_utils import now_utc, iso
    now = now_utc()
    docs = [{
        "kind": "rate_limit_hit",
        "ip": "203.0.113.99",
        "path": "/api/auth/login",
        "method": "POST",
        "created_at": iso(now),
        "_ts": now,
    } for _ in range(101)]
    _sync_db().security_events.insert_many(docs)

    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setenv("CF_ZONE_ID", "zone")
    monkeypatch.setenv("CLOUDFLARE_AUTO_BLOCK_ENABLED", "true")

    called_with = {}

    async def _fake_create_block(db, ip, notes, source, **kwargs):
        called_with["ip"] = ip
        called_with["source"] = source
        return {"cf_ok": True, "cf_rule_id": "cf-fake", "created": True, "block_id": "b1"}

    async def _fake_notify(*args, **kwargs):
        return None

    monkeypatch.setattr("services.cloudflare_blocks.create_block", _fake_create_block)
    monkeypatch.setattr("admin_alerts.notify_all_admins", _fake_notify)

    async def _do():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            from services.security_alerts import run_security_alert_scan
            return await run_security_alert_scan(db)
        finally:
            client.close()

    summary = _run(_do)
    assert summary["ip_rate_flood"] >= 1
    assert called_with.get("ip") == "203.0.113.99"
    assert called_with.get("source") == "scanner"

    _sync_db().security_events.delete_many({"kind": "rate_limit_hit", "ip": "203.0.113.99"})
    _sync_db().security_alerts_sent.delete_many({"anomaly_key": {"$regex": "^ip_rate_flood:203.0.113.99"}})


def test_ip_flood_does_not_call_cloudflare_when_auto_block_off(monkeypatch):
    _cleanup_blocks("203.0.113.98")
    _sync_db().security_alerts_sent.delete_many({"anomaly_key": {"$regex": "^ip_rate_flood:203.0.113.98"}})
    _sync_db().security_events.delete_many({"kind": "rate_limit_hit", "ip": "203.0.113.98"})

    from auth_utils import now_utc, iso
    now = now_utc()
    docs = [{
        "kind": "rate_limit_hit",
        "ip": "203.0.113.98",
        "path": "/api/auth/login",
        "method": "POST",
        "created_at": iso(now),
        "_ts": now,
    } for _ in range(101)]
    _sync_db().security_events.insert_many(docs)

    monkeypatch.delenv("CLOUDFLARE_AUTO_BLOCK_ENABLED", raising=False)

    called_with = {"count": 0}

    async def _fake_create_block(*args, **kwargs):
        called_with["count"] += 1
        return {"cf_ok": True}

    async def _fake_notify(*args, **kwargs):
        return None

    monkeypatch.setattr("services.cloudflare_blocks.create_block", _fake_create_block)
    monkeypatch.setattr("admin_alerts.notify_all_admins", _fake_notify)

    async def _do():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            from services.security_alerts import run_security_alert_scan
            return await run_security_alert_scan(db)
        finally:
            client.close()

    summary = _run(_do)
    assert summary["ip_rate_flood"] >= 1
    assert called_with["count"] == 0  # No CF call when auto-block disabled.

    _sync_db().security_events.delete_many({"kind": "rate_limit_hit", "ip": "203.0.113.98"})
    _sync_db().security_alerts_sent.delete_many({"anomaly_key": {"$regex": "^ip_rate_flood:203.0.113.98"}})
