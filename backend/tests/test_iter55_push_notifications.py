"""iter55 — Push notification payload builders.

The `send_push` HTTP hop cannot be tested E2E (no real push endpoint); we test
the payload builders and the fanout side effect via a fake `send_push`.
"""
import os
import uuid
import asyncio
from unittest.mock import patch, MagicMock

import pytest

# Load backend module path
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str((Path(__file__).resolve().parents[1]).resolve()))

import push_service
from push_service import (
    build_order_completed_payload,
    build_rate_changed_payload,
)


class TestOrderCompletedPayload:
    def test_transfer_completed(self):
        p = build_order_completed_payload({
            "id": "a" * 32,
            "delivery_method": "transfer",
            "amount_to": 25000,
            "to_code": "CUP",
        })
        assert "completada" in p["title"].lower()
        assert "25000" in p["body"] or "25,000" in p["body"]
        assert "CUP" in p["body"]
        # tag prevents duplicate device notifications for the same order-completion
        assert p["tag"].startswith("order-") and p["tag"].endswith("-completed")

    def test_accumulate_uses_credit_wording(self):
        p = build_order_completed_payload({
            "id": "b" * 32,
            "delivery_method": "accumulate",
            "amount_to": 1000,
            "to_code": "USDT",
        })
        assert "saldo" in p["body"].lower()

    def test_crypto_mentions_wallet(self):
        p = build_order_completed_payload({
            "id": "c" * 32,
            "delivery_method": "crypto",
            "amount_to": 50,
            "to_code": "USDT",
        })
        assert "wallet" in p["body"].lower() or "tx" in p["body"].lower()


class TestRateChangedPayload:
    def test_normal_uses_normal_rate(self):
        p = build_rate_changed_payload("USDT", "CUP", 400.0, 405.5, for_role="normal")
        assert "USDT" in p["title"] and "CUP" in p["title"]
        assert "400" in p["body"]  # normal rate
        assert "VIP" not in p["body"]

    def test_vip_uses_vip_rate_with_label(self):
        p = build_rate_changed_payload("USDT", "CUP", 400.0, 405.5, for_role="vip")
        assert "405.5" in p["body"]
        assert "VIP" in p["body"]

    def test_same_tag_for_same_pair(self):
        p1 = build_rate_changed_payload("USDT", "CUP", 400, 405, for_role="normal")
        p2 = build_rate_changed_payload("USDT", "CUP", 401, 406, for_role="normal")
        assert p1["tag"] == p2["tag"]  # replaces on device


class TestRateChangeFanoutIntegration:
    """Ensures the PUT /admin/rates endpoint doesn't crash the request even when
    push subscriptions exist (fanout is best-effort — errors must NOT bubble
    up to the client). Verifies via HTTP 200."""

    def test_rate_update_survives_fanout(self):
        import requests
        from tests.conftest import BASE_URL, ADMIN_TOKEN, make_admin_totp

        from pymongo import MongoClient
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        sub_id = str(uuid.uuid4())
        db.push_subscriptions.insert_one({
            "id": sub_id, "user_id": "user_test_vip01",
            "subscription": {"endpoint": "https://push.example.test/vip", "keys": {}},
        })
        try:
            r = requests.get(f"{BASE_URL}/api/rates", timeout=10)
            assert r.status_code == 200
            rates = r.json()
            assert rates, "at least one rate must be seeded"
            rate = rates[0]
            new_body = {
                "from_code": rate["from_code"],
                "to_code": rate["to_code"],
                "rate_normal": float(rate["rate_normal"]) + 0.001,
                "rate_vip": float(rate.get("rate_vip") or rate["rate_normal"]) + 0.001,
                "real_rate": float(rate.get("real_rate") or rate["rate_normal"]),
                "totp_code": make_admin_totp(),
            }
            rr = requests.put(
                f"{BASE_URL}/api/admin/rates/{rate['id']}",
                json=new_body,
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                timeout=15,
            )
            assert rr.status_code == 200, rr.text
            # rate value updated
            assert abs(float(rr.json()["rate_normal"]) - new_body["rate_normal"]) < 1e-6
        finally:
            db.push_subscriptions.delete_one({"id": sub_id})

    def test_no_op_rate_update_still_returns_200(self):
        """Saving the same rate values (no delta) must not fanout push either,
        but the endpoint must still succeed."""
        import requests
        from tests.conftest import BASE_URL, ADMIN_TOKEN, make_admin_totp

        r = requests.get(f"{BASE_URL}/api/rates", timeout=10)
        rate = r.json()[0]
        rr = requests.put(
            f"{BASE_URL}/api/admin/rates/{rate['id']}",
            json={
                "from_code": rate["from_code"],
                "to_code": rate["to_code"],
                "rate_normal": rate["rate_normal"],
                "rate_vip": rate.get("rate_vip") or rate["rate_normal"],
                "real_rate": rate.get("real_rate") or rate["rate_normal"],
                "totp_code": make_admin_totp(),
            },
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=15,
        )
        assert rr.status_code == 200


class TestFanoutRoleGatingUnit:
    """Unit test for `_fanout_rate_change_push` — role gate is tricky and worth
    covering in-process. Uses direct import + fake send_push."""

    def test_only_client_subs_are_sent(self):
        from routes import market
        # Prepare fake data by directly monkey-patching module attributes
        subs = [
            {"id": "s1", "user_id": "u_vip", "subscription": {"endpoint": "vip"}},
            {"id": "s2", "user_id": "u_normal", "subscription": {"endpoint": "normal"}},
            {"id": "s3", "user_id": "u_admin", "subscription": {"endpoint": "admin"}},
            {"id": "s4", "user_id": "u_staff", "subscription": {"endpoint": "staff"}},
        ]
        users = [
            {"user_id": "u_vip", "role": "vip"},
            {"user_id": "u_normal", "role": "normal"},
            {"user_id": "u_admin", "role": "admin"},
            {"user_id": "u_staff", "role": "employee"},
        ]

        class FakeCursor:
            def __init__(self, data): self._d = data
            async def to_list(self, n): return self._d[:n]

        class FakeCollection:
            def __init__(self, data): self._d = data
            def find(self, q, projection=None):
                # Emulate the `role in ["vip","normal"]` filter for users query
                data = self._d
                if q and "role" in q:
                    allowed = q["role"]["$in"]
                    data = [d for d in data if d.get("role") in allowed]
                if q and "user_id" in q and "$in" in q["user_id"]:
                    ids = q["user_id"]["$in"]
                    data = [d for d in data if d.get("user_id") in ids]
                return FakeCursor(data)
            async def delete_many(self, q): return None

        class FakeDB:
            def __init__(self):
                self.push_subscriptions = FakeCollection(subs)
                self.users = FakeCollection(users)

        called = []
        original_db = market.db
        market.db = FakeDB()
        try:
            with patch("push_service.send_push",
                       side_effect=lambda s, p: called.append(s.get("endpoint")) or "ok"):
                asyncio.run(market._fanout_rate_change_push(
                    {"rate_normal": 400.0, "rate_vip": 405.0},
                    {"from_code": "USDT", "to_code": "CUP",
                     "rate_normal": 401.0, "rate_vip": 406.0},
                ))
        finally:
            market.db = original_db

        assert "vip" in called
        assert "normal" in called
        assert "admin" not in called
        assert "staff" not in called

    def test_no_delta_skips_fanout(self):
        from routes import market
        called = []
        # If dedup returns early, send_push must never be invoked. No DB access needed.
        with patch("push_service.send_push", side_effect=lambda *a, **kw: called.append(1) or "ok"):
            asyncio.run(market._fanout_rate_change_push(
                {"rate_normal": 400.0, "rate_vip": 405.0},
                {"from_code": "USDT", "to_code": "CUP",
                 "rate_normal": 400.0, "rate_vip": 405.0},
            ))
        assert called == []
