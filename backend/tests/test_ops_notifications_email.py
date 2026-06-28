"""Iter39: centralised ops mailbox (`ops_notifications_email`).

Covers:
- GET /api/admin/settings returns the new field (null by default).
- PUT /api/admin/settings persists a valid email + rejects malformed strings.
- Empty / whitespace string is normalised to null on PUT.
- `admin_alerts.resolve_admin_email_recipients` returns the configured inbox
  when set and falls back to per-admin fan-out when cleared.
"""
import asyncio
import os

import pytest
import requests
from pymongo import MongoClient

from conftest import make_admin_totp, BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(autouse=True)
def _restore_settings(db):
    """Reset ops_notifications_email after every test so the suite is hermetic."""
    yield
    requests.put(
        f"{BASE_URL}/api/admin/settings",
        headers=_h(ADMIN_TOKEN),
        json={
            "vip_threshold_usdt": 5000,
            "defensive_margin_pct": None,
            "ops_notifications_email": None,
            "totp_code": make_admin_totp(),
        },
    )


class TestOpsNotificationsEmailSettings:
    def test_get_settings_includes_field_default_null(self, db):
        # Force a clean slate
        db.settings.update_one(
            {"id": "global"},
            {"$unset": {"ops_notifications_email": ""}},
        )
        r = requests.get(f"{BASE_URL}/api/admin/settings", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "ops_notifications_email" in body
        assert body["ops_notifications_email"] is None

    def test_put_persists_valid_email(self, db):
        target = "ops-mailbox@resiliencebrothers.com"
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_h(ADMIN_TOKEN),
            json={
                "vip_threshold_usdt": 5000,
                "defensive_margin_pct": None,
                "ops_notifications_email": target,
                "totp_code": make_admin_totp(),
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["ops_notifications_email"] == target

        g = requests.get(f"{BASE_URL}/api/admin/settings", headers=_h(ADMIN_TOKEN))
        assert g.json()["ops_notifications_email"] == target

        # Mongo doc reflects it too
        doc = db.settings.find_one({"id": "global"})
        assert doc["ops_notifications_email"] == target

    def test_put_rejects_malformed_email_400(self):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_h(ADMIN_TOKEN),
            json={
                "vip_threshold_usdt": 5000,
                "defensive_margin_pct": None,
                "ops_notifications_email": "not-an-email",
                "totp_code": make_admin_totp(),
            },
        )
        assert r.status_code == 400
        assert "ops_notifications_email" in r.text.lower()

    def test_put_empty_string_normalised_to_null(self, db):
        # First set a value
        requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_h(ADMIN_TOKEN),
            json={
                "vip_threshold_usdt": 5000,
                "defensive_margin_pct": None,
                "ops_notifications_email": "tmp@x.com",
                "totp_code": make_admin_totp(),
            },
        )
        # Then clear with whitespace-only string
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_h(ADMIN_TOKEN),
            json={
                "vip_threshold_usdt": 5000,
                "defensive_margin_pct": None,
                "ops_notifications_email": "   ",
                "totp_code": make_admin_totp(),
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["ops_notifications_email"] is None
        doc = db.settings.find_one({"id": "global"})
        assert doc["ops_notifications_email"] is None

    def test_put_normal_role_forbidden(self):
        r = requests.put(
            f"{BASE_URL}/api/admin/settings",
            headers=_h(NORMAL_TOKEN),
            json={
                "vip_threshold_usdt": 5000,
                "ops_notifications_email": "x@y.com",
            },
        )
        assert r.status_code == 403


class TestResolveRecipientsHelper:
    """Direct unit test of the helper used by every email fan-out site."""

    def _run(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_returns_ops_inbox_when_configured(self, db):
        import sys
        sys.path.insert(0, "/app/backend")
        from admin_alerts import resolve_admin_email_recipients
        from motor.motor_asyncio import AsyncIOMotorClient

        async def go():
            motor = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
            await motor.settings.update_one(
                {"id": "global"},
                {"$set": {"ops_notifications_email": "single@inbox.test"}},
                upsert=True,
            )
            recipients = await resolve_admin_email_recipients(motor)
            assert recipients == ["single@inbox.test"]

        self._run(go())

    def test_falls_back_to_admins_when_blank(self, db):
        import sys
        sys.path.insert(0, "/app/backend")
        from admin_alerts import resolve_admin_email_recipients
        from motor.motor_asyncio import AsyncIOMotorClient

        async def go():
            motor = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
            await motor.settings.update_one(
                {"id": "global"},
                {"$set": {"ops_notifications_email": None}},
                upsert=True,
            )
            recipients = await resolve_admin_email_recipients(motor)
            # Should fall back to every admin's email (at least the seeded one)
            assert len(recipients) >= 1
            assert all("@" in r for r in recipients)

        self._run(go())
