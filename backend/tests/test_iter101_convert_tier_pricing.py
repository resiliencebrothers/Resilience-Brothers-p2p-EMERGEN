"""iter101 (actualizado iter287) — tarifa por nivel en la auto-conversión.

iter287 reemplazó el modelo iter101 por un modelo COMPRA/VENTA del operador:
  • Conversión DIRECTA (fila from→to): la empresa COMPRA `from_code` al
    cliente a su tasa de compra por nivel (Normal → rate_normal,
    VIP → rate_vip). `real_rate` ya NO se usa en /vip/convert.
  • Conversión INVERSA (solo existe la fila to→from): el cliente ADQUIERE
    `to_code` y la empresa VENDE a su tasa ÚNICA `effective_sell_rate`
    (igual para todos los niveles; sin `rate_sell` → la mayor tasa de compra).

Estos tests golpean el endpoint real y verifican `amount_to` / `rate`.
"""
import os
import pytest
import httpx
from datetime import datetime, timezone

# We test through the httpx AsyncClient against the running app.
API_URL = os.environ.get("REACT_APP_BACKEND_URL",
                         "https://p2p-exchange-hub-2.preview.emergentagent.com")
from conftest import NORMAL_TOKEN, VIP_TOKEN


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
        """iter287 — conversión INVERSA (solo existe la fila USDT→USD): el
        cliente ADQUIERE USDT y la empresa VENDE a su tasa ÚNICA
        (effective_sell_rate = mayor tasa de compra = real_rate 1.05), igual
        para VIP y normal. 100 USD → 100/1.05 ≈ 95.24 USDT."""
        await _seed_rate("USDT", "USD", rate_normal=1.0, rate_vip=1.035, real_rate=1.05)
        from db_client import db
        await db.rates.delete_many({"from_code": "USD", "to_code": "USDT"})
        await _seed_balance("user_test_vip01", "USD", 500.0)
        await _seed_balance("user_test_vip01", "USDT", 10.0)
        try:
            r = await _post_convert(VIP_TOKEN, "USD", "USDT", 100.0)
            assert r.status_code == 200, r.text
            data = r.json()
            assert abs(data["amount_to"] - 95.2381) < 0.01, (
                f"Expected ~95.24 USDT, got {data['amount_to']}"
            )
            assert abs(data["rate"] - (1.0 / 1.05)) < 0.001, (
                f"Expected rate ≈ 0.9524, got {data['rate']}"
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
        """iter287 — con una fila DIRECTA (USD→USDT) la empresa COMPRA USD al
        cliente a su tasa de compra por nivel: normal → rate_normal=0.90.
        100 USD → 100 * 0.90 = 90.00 USDT (real_rate ya NO se usa en convert)."""
        await _seed_rate("USD", "USDT", rate_normal=0.90, rate_vip=0.92, real_rate=0.95)
        await _seed_balance("user_test_normal01", "USD", 500.0)
        await _seed_balance("user_test_normal01", "USDT", 10.0)
        try:
            r = await _post_convert(NORMAL_TOKEN, "USD", "USDT", 100.0)
            assert r.status_code == 200, r.text
            data = r.json()
            # iter287: normal directa usa rate_normal=0.90 → 90.00
            assert abs(data["amount_to"] - 90.0) < 0.01, (
                f"Expected 90.00 USDT, got {data['amount_to']}"
            )
        finally:
            await _cleanup_rate("USD", "USDT")
