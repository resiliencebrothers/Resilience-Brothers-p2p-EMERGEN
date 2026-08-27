"""Seed the FX rates and currency catalog required by the pytest suite.

Idempotent — safe to re-run. Used by CI (`.github/workflows/ci.yml`) so a
fresh MongoDB container has:
  - the currency catalog rows (USDT, USD, CUP, EUR) the admin/company
    funds routes validate against, and
  - the rate pairs (USDT→CUP, USD→CUP, USDT→USDT identity) the legacy
    tests rely on.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from pymongo import MongoClient


CURRENCIES = [
    {"code": "USDT", "name": "Tether", "is_active": True, "is_crypto": True},
    {"code": "USD", "name": "US Dollar", "is_active": True, "is_crypto": False},
    {"code": "CUP", "name": "Cuban Peso", "is_active": True, "is_crypto": False},
    {"code": "EUR", "name": "Euro", "is_active": True, "is_crypto": False},
    {"code": "MXN", "name": "Mexican Peso", "is_active": True, "is_crypto": False},
    {"code": "BRL", "name": "Brazilian Real", "is_active": True, "is_crypto": False},
    {"code": "COP", "name": "Colombian Peso", "is_active": True, "is_crypto": False},
    {"code": "PEN", "name": "Peruvian Sol", "is_active": True, "is_crypto": False},
]

RATES = [
    {
        "id": "seed_ci_usdt_cup",
        "from_code": "USDT", "to_code": "CUP",
        "rate_normal": 380.0, "rate_vip": 395.0, "real_rate": 410.0,
    },
    {
        "id": "seed_ci_usd_cup",
        "from_code": "USD", "to_code": "CUP",
        "rate_normal": 380.0, "rate_vip": 395.0, "real_rate": 350.0,
    },
    {
        "id": "seed_ci_usdt_usdt",
        "from_code": "USDT", "to_code": "USDT",
        "rate_normal": 1.0, "rate_vip": 1.0, "real_rate": 1.0,
    },
    {
        "id": "seed_ci_usdt_usd",
        "from_code": "USDT", "to_code": "USD",
        "rate_normal": 1.0, "rate_vip": 1.0, "real_rate": 1.0,
    },
    {
        "id": "seed_ci_usd_usdt",
        "from_code": "USD", "to_code": "USDT",
        "rate_normal": 1.0, "rate_vip": 1.0, "real_rate": 1.0,
    },
    {
        "id": "seed_ci_eur_usdt",
        "from_code": "EUR", "to_code": "USDT",
        "rate_normal": 1.05, "rate_vip": 1.08, "real_rate": 1.12,
    },
]


def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("[seed_test_rates] MONGO_URL and DB_NAME must be set", file=sys.stderr)
        return 1

    client = MongoClient(mongo_url)
    db = client[db_name]
    now = datetime.now(timezone.utc).isoformat()

    for c in CURRENCIES:
        db.currencies.update_one(
            {"code": c["code"]},
            {"$set": {**c, "updated_at": now},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        print(f"[seed_test_rates] upserted currency {c['code']}")

    for r in RATES:
        db.rates.update_one(
            {"from_code": r["from_code"], "to_code": r["to_code"]},
            {"$set": {**r, "updated_at": now},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        print(f"[seed_test_rates] upserted {r['from_code']}→{r['to_code']}")

    client.close()
    print(f"[seed_test_rates] ✓ {len(CURRENCIES)} currencies + {len(RATES)} rate pairs ready in {db_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
