"""Tests for the Admin Health Dashboard (iter37)."""
import pytest
import requests

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# Auth + role gating
# ============================================================

class TestHealthAuth:
    def test_unauthenticated_rejected(self):
        r = requests.get(f"{BASE_URL}/api/admin/health/summary")
        assert r.status_code == 401

    def test_normal_user_rejected(self):
        r = requests.get(f"{BASE_URL}/api/admin/health/summary", headers=_h(NORMAL_TOKEN))
        assert r.status_code == 403

    def test_vip_rejected(self):
        r = requests.get(f"{BASE_URL}/api/admin/health/summary", headers=_h(VIP_TOKEN))
        assert r.status_code == 403

    def test_employee_rejected(self):
        """The dashboard is admin-only (revenue + sensitive ops)."""
        r = requests.get(f"{BASE_URL}/api/admin/health/summary", headers=_h(EMPLOYEE_TOKEN))
        assert r.status_code == 403

    def test_admin_can_access(self):
        r = requests.get(f"{BASE_URL}/api/admin/health/summary", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200


# ============================================================
# Payload shape
# ============================================================

class TestHealthPayload:
    @pytest.fixture
    def payload(self):
        r = requests.get(f"{BASE_URL}/api/admin/health/summary", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        return r.json()

    def test_payload_has_all_sections(self, payload):
        for k in ("generated_at", "sentry", "storage", "throughput",
                  "defensive_mode", "negative_margin", "queues", "platform"):
            assert k in payload, f"missing section: {k}"

    def test_sentry_section_shape(self, payload):
        s = payload["sentry"]
        assert "enabled" in s
        assert isinstance(s["enabled"], bool)
        assert "environment" in s
        assert "deep_link" in s
        assert isinstance(s["local_errors_recent"], int)
        assert s["local_errors_recent"] >= 0

    def test_storage_section_shape(self, payload):
        s = payload["storage"]
        assert "enabled" in s
        if s["enabled"]:
            assert s["provider"] in ("r2", "s3")
            assert s["bucket"]
            assert isinstance(s["object_count"], int)
            assert s["object_count"] >= 0
            assert isinstance(s["size_gb"], (int, float))
            assert s["size_gb"] >= 0
            assert isinstance(s["monthly_cost_usd"], (int, float))
            assert isinstance(s["by_folder"], list)
            for folder in s["by_folder"]:
                assert "folder" in folder and "count" in folder and "size_mb" in folder

    def test_throughput_section_shape(self, payload):
        t = payload["throughput"]
        for k in ("orders_last_1h", "orders_last_24h", "orders_last_7d"):
            assert k in t and isinstance(t[k], int)
        assert isinstance(t["hourly_24h"], list)
        # 24 buckets covering the past 24 h.
        assert len(t["hourly_24h"]) == 24
        for bucket in t["hourly_24h"]:
            assert "hour" in bucket and "count" in bucket

    def test_throughput_monotonic_windows(self, payload):
        """1h count must never exceed 24h, which must never exceed 7d."""
        t = payload["throughput"]
        assert t["orders_last_1h"] <= t["orders_last_24h"]
        assert t["orders_last_24h"] <= t["orders_last_7d"]

    def test_defensive_section_shape(self, payload):
        d = payload["defensive_mode"]
        assert "enabled" in d and isinstance(d["enabled"], bool)
        assert "reason" in d
        assert "enabled_at" in d
        assert "enabled_by_email" in d

    def test_negative_margin_section_shape(self, payload):
        n = payload["negative_margin"]
        assert "count" in n and isinstance(n["count"], int)
        assert isinstance(n["items"], list)
        # We cap items at 20 in the API.
        assert len(n["items"]) <= 20
        for it in n["items"]:
            for k in ("id", "user_name", "pair", "amount_from", "amount_to",
                      "loss_amount", "loss_currency", "loss_pct", "status"):
                assert k in it, f"negative_margin item missing {k}"
            assert it["loss_amount"] >= 0

    def test_queue_section_shape(self, payload):
        q = payload["queues"]
        for k in ("pending_orders", "pending_double_approval",
                  "pending_withdrawals", "pending_phone_verifications",
                  "blocked_contacts"):
            assert k in q and isinstance(q[k], int)
            assert q[k] >= 0

    def test_platform_section_shape(self, payload):
        p = payload["platform"]
        for k in ("users_total", "users_active", "users_under_review",
                  "users_blocked", "orders_total", "orders_approved",
                  "orders_rejected", "products_total"):
            assert k in p and isinstance(p[k], int)
            assert p[k] >= 0
        # Sum of account_status buckets ≤ users_total (active/under_review/blocked + maybe missing-status legacy).
        assert (p["users_active"] + p["users_under_review"] + p["users_blocked"]) <= p["users_total"]
