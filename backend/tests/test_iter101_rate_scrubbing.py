"""iter101.1 — `real_rate` privacy scrubbing on GET /api/rates.

The operator's `real_rate` is competitive information (their true market
exit spread). It must NEVER leak to normal/VIP clients or anonymous
callers. Server injects a pre-computed `rate_convert` per caller role so
the client-side self-conversion preview stays correct without ever
seeing the raw margin.

Rules:
  • Anonymous / normal / VIP → `real_rate` MUST NOT appear in the response.
  • Admin / employee         → `real_rate` MUST appear (they audit revenue
                                and edit rates).
  • Every row MUST carry `rate_convert` — the effective self-conversion
    rate for the calling role (VIP → rate_vip; else real_rate ?? rate_normal).
"""
import os
import pytest
import httpx
from datetime import datetime, timezone

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")


async def _seed(from_code: str, to_code: str, *,
                rate_normal: float, rate_vip: float,
                real_rate: float | None) -> None:
    from db_client import db
    await db.rates.replace_one(
        {"from_code": from_code, "to_code": to_code},
        {
            "id": f"scrub_test_{from_code}_{to_code}",
            "from_code": from_code, "to_code": to_code,
            "rate_normal": rate_normal, "rate_vip": rate_vip,
            "real_rate": real_rate,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        upsert=True,
    )


async def _get_rates(token: str | None) -> list:
    async with httpx.AsyncClient(base_url=API_URL, timeout=10.0) as c:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = await c.get("/api/rates", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()


class TestRealRateScrubbing:
    @pytest.mark.asyncio
    async def test_real_rate_hidden_from_anonymous(self):
        await _seed("USDT", "USD", rate_normal=1.0, rate_vip=1.035, real_rate=1.05)
        rates = await _get_rates(None)
        for r in rates:
            assert "real_rate" not in r, (
                f"real_rate LEAKED to anonymous caller on {r.get('from_code')}→{r.get('to_code')}"
            )

    @pytest.mark.asyncio
    async def test_real_rate_hidden_from_normal(self):
        await _seed("USDT", "USD", rate_normal=1.0, rate_vip=1.035, real_rate=1.05)
        rates = await _get_rates("test_session_normal_X")
        for r in rates:
            assert "real_rate" not in r, (
                f"real_rate LEAKED to normal on {r.get('from_code')}→{r.get('to_code')}"
            )

    @pytest.mark.asyncio
    async def test_real_rate_hidden_from_vip(self):
        await _seed("USDT", "USD", rate_normal=1.0, rate_vip=1.035, real_rate=1.05)
        rates = await _get_rates("test_session_vip_X")
        for r in rates:
            assert "real_rate" not in r, (
                f"real_rate LEAKED to VIP on {r.get('from_code')}→{r.get('to_code')}"
            )

    @pytest.mark.asyncio
    async def test_real_rate_visible_to_admin(self):
        await _seed("USDT", "USD", rate_normal=1.0, rate_vip=1.035, real_rate=1.05)
        rates = await _get_rates("test_session_admin_X")
        row = next((r for r in rates
                    if r["from_code"] == "USDT" and r["to_code"] == "USD"), None)
        assert row is not None, "seeded rate row missing from admin response"
        assert "real_rate" in row, "real_rate MISSING from admin response — admin needs it"
        assert row["real_rate"] == 1.05

    @pytest.mark.asyncio
    async def test_rate_convert_matches_tier_picker(self):
        """rate_convert injection tracks the server-side tier picker
        used by /vip/convert (`_pick_tier_rate`)."""
        await _seed("USDT", "USD", rate_normal=1.0, rate_vip=1.035, real_rate=1.05)
        # Normal → real_rate
        rates = await _get_rates("test_session_normal_X")
        row = next(r for r in rates if r["from_code"] == "USDT" and r["to_code"] == "USD")
        assert row["rate_convert"] == 1.05
        # VIP → rate_vip
        rates = await _get_rates("test_session_vip_X")
        row = next(r for r in rates if r["from_code"] == "USDT" and r["to_code"] == "USD")
        assert row["rate_convert"] == 1.035

    @pytest.mark.asyncio
    async def test_rate_convert_falls_back_to_rate_normal_when_real_rate_null(self):
        """Legacy rate rows without real_rate should still expose a valid
        rate_convert (= rate_normal) so the converter preview never
        returns null for legacy data."""
        await _seed("USDT", "USD", rate_normal=1.10, rate_vip=1.05, real_rate=None)
        rates = await _get_rates("test_session_normal_X")
        row = next(r for r in rates if r["from_code"] == "USDT" and r["to_code"] == "USD")
        assert row["rate_convert"] == 1.10
