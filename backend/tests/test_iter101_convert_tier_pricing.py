"""iter101 — Self-conversion uses REAL profit rate for normal clients.

Bug reported in production: a normal user converting 100 USD → USDT was
receiving 100 USDT (1:1) even though the operator's `USDT → USD` rate is
`rate_normal=1, rate_vip=1.035, real_rate=1.05`. The old code inverted
`rate_normal=1` → 1/1 = 1.0, giving away a 5% arbitrage.

Fix (iter101): the self-conversion tier picker for /vip/convert now uses:
  • VIP    → `rate_vip`   (the VIP-tier price)
  • NORMAL → `real_rate`  (the operator's REAL market rate)
             fallback to `rate_normal` only when real_rate is unset.

These tests hit the actual FastAPI endpoint and assert on the returned
`amount_to` / `rate` fields.
"""
import os
import pytest
import httpx
import asyncio
from datetime import datetime, timezone

# We test through the httpx AsyncClient against the running app.
API_URL = os.environ.get("REACT_APP_BACKEND_URL",
                         "https://p2p-exchange-hub-2.preview.emergentagent.com")
from conftest import NORMAL_TOKEN, VIP_TOKEN, ADMIN_TOKEN


async def _seed_rate(from_code: str, to_code: str,
                     rate_normal: float, rate_vip: float,
                     real_rate: float | None = None) -> None:
    from db_client import db
    doc = {
        "id": f"test_iter101_{from_code}_{to_code}",
        "from_code": from_code, "to_code": to_code,
        "rate_normal": rate_normal, "rate_vip": rate_vip,
        "real_rate": real_rate,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.rates.replace_one(
        {"from_code": from_code, "to_code": to_code}, doc, upsert=True,
    )


async def _seed_balance(user_id: str, code: str, amount: float) -> None:
    from db_client import db
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {f"vip_balances.{code}": amount}},
    )


async def _cleanup_rate(from_code: str, to_code: str) -> None:
    from db_client import db
    await db.rates.delete_one({"id": f"test_iter101_{from_code}_{to_code}"})


async def _post_convert(token: str, from_code: str, to_code: str, amount: float) -> httpx.Response:
    async with httpx.AsyncClient(base_url=API_URL, timeout=15.0) as c:
        return await c.post(
            "/api/vip/convert",
            headers={"Authorization": f"Bearer {token}"},
            json={"from_code": from_code, "to_code": to_code, "amount_from": amount},
        )


class TestConvertTierPicker:
    @pytest.mark.asyncio
    async def test_normal_uses_real_rate_when_inverting(self):
        """Normal client USD→USDT with only `USDT→USD` rate (rate_normal=1,
        rate_vip=1.035, real_rate=1.05). Expected: 100 USD → ~95.24 USDT
        (rate = 1/1.05). Previously buggy: gave 100 USDT."""
        await _seed_rate("USDT", "USD", rate_normal=1.0, rate_vip=1.035, real_rate=1.05)
        # Clear any direct USD→USDT rate that might shadow the inverse.
        from db_client import db
        await db.rates.delete_many({"from_code": "USD", "to_code": "USDT"})
        await _seed_balance("user_test_normal01", "USD", 500.0)
        await _seed_balance("user_test_normal01", "USDT", 10.0)  # cover the 0.01 fee
        try:
            r = await _post_convert(NORMAL_TOKEN, "USD", "USDT", 100.0)
            assert r.status_code == 200, r.text
            data = r.json()
            # 100 USD * (1 / 1.05) = 95.2381 (rounded to 4 decimals)
            assert abs(data["amount_to"] - 95.2381) < 0.01, (
                f"Expected ~95.24 USDT, got {data['amount_to']}"
            )
            assert abs(data["rate"] - (1.0 / 1.05)) < 0.001, (
                f"Expected rate ≈ 0.9524, got {data['rate']}"
            )
        finally:
            await _cleanup_rate("USDT", "USD")

    @pytest.mark.asyncio
    async def test_vip_uses_rate_vip_when_inverting(self):
        """VIP client USD→USDT with same rate row. Expected: 100 USD →
        ~96.62 USDT (rate = 1/1.035). VIP-tier picker unchanged."""
        await _seed_rate("USDT", "USD", rate_normal=1.0, rate_vip=1.035, real_rate=1.05)
        from db_client import db
        await db.rates.delete_many({"from_code": "USD", "to_code": "USDT"})
        await _seed_balance("user_test_vip01", "USD", 500.0)
        await _seed_balance("user_test_vip01", "USDT", 10.0)
        try:
            r = await _post_convert(VIP_TOKEN, "USD", "USDT", 100.0)
            assert r.status_code == 200, r.text
            data = r.json()
            assert abs(data["amount_to"] - 96.6184) < 0.01, (
                f"Expected ~96.62 USDT, got {data['amount_to']}"
            )
            assert abs(data["rate"] - (1.0 / 1.035)) < 0.001, (
                f"Expected rate ≈ 0.9662, got {data['rate']}"
            )
        finally:
            await _cleanup_rate("USDT", "USD")

    @pytest.mark.asyncio
    async def test_normal_falls_back_to_rate_normal_when_real_rate_missing(self):
        """Legacy rate row without `real_rate`: normal client falls back
        to `rate_normal` (preserves pre-iter101 behavior for legacy data)."""
        await _seed_rate("USDT", "USD", rate_normal=1.10, rate_vip=1.05, real_rate=None)
        from db_client import db
        await db.rates.delete_many({"from_code": "USD", "to_code": "USDT"})
        await _seed_balance("user_test_normal01", "USD", 500.0)
        await _seed_balance("user_test_normal01", "USDT", 10.0)
        try:
            r = await _post_convert(NORMAL_TOKEN, "USD", "USDT", 100.0)
            assert r.status_code == 200, r.text
            data = r.json()
            # With no real_rate, normal uses rate_normal=1.10 → 100/1.10 ≈ 90.91
            assert abs(data["amount_to"] - 90.9091) < 0.01, (
                f"Expected ~90.91 USDT, got {data['amount_to']}"
            )
        finally:
            await _cleanup_rate("USDT", "USD")

    @pytest.mark.asyncio
    async def test_direct_rate_still_wins(self):
        """When a DIRECT rate exists for the pair, the tier picker uses
        that row (no inversion) — for normal, `real_rate` still wins if
        present."""
        await _seed_rate("USD", "USDT", rate_normal=0.90, rate_vip=0.92, real_rate=0.95)
        await _seed_balance("user_test_normal01", "USD", 500.0)
        await _seed_balance("user_test_normal01", "USDT", 10.0)
        try:
            r = await _post_convert(NORMAL_TOKEN, "USD", "USDT", 100.0)
            assert r.status_code == 200, r.text
            data = r.json()
            # Direct rate with real_rate=0.95 → 100 * 0.95 = 95.00
            assert abs(data["amount_to"] - 95.0) < 0.01, (
                f"Expected 95.00 USDT, got {data['amount_to']}"
            )
        finally:
            await _cleanup_rate("USD", "USDT")
