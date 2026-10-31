"""Persistent seed for CO-01/02/03 frontend testing (idempotent).
Run: cd /app/backend && python seed_co_fixes_smoke.py
Creates:
  - USDT collection accounts on TRC20 and ERC20 (same tier) → network tests.
  - A confirmed EUR transfer deposit WITHOUT any collection account
    (dep_seed_legacy) → "expected: not recorded" + confirm-account flow.
  - A confirmed EUR transfer deposit WITH an expected account snapshot
    (dep_seed_expected) → shows the expected (prevista) account.
Owner: normal.test@resilience.com (user_test_normal01).
"""
import asyncio
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    try:
        await db.payment_accounts.delete_many(
            {"id": {"$in": ["pa_seed_usdt_trc", "pa_seed_usdt_erc", "pa_seed_eur"]}})
        await db.payment_accounts.insert_many([
            {"id": "pa_seed_usdt_trc", "currency_code": "USDT", "label": "Seed Wallet TRC20",
             "account_details": "TRC20: TSeedAddr111", "network": "TRC20", "min_amount": 1,
             "max_amount": None, "is_active": True,
             "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"},
            {"id": "pa_seed_usdt_erc", "currency_code": "USDT", "label": "Seed Wallet ERC20",
             "account_details": "ERC20: 0xSeedAddr222", "network": "ERC20", "min_amount": 1,
             "max_amount": None, "is_active": True,
             "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"},
            {"id": "pa_seed_eur", "currency_code": "EUR", "label": "Seed Revolut EUR",
             "account_details": "IBAN LT00 1111 2222", "network": "", "min_amount": 1,
             "max_amount": None, "is_active": True,
             "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"},
        ])

        base = {
            "user_id": "user_test_normal01", "user_email": "normal.test@resilience.com",
            "user_name": "QA Normal", "user_role": "normal", "currency": "EUR",
            "amount": 50.0, "method": "transfer", "account_holder": "QA Normal",
            "status": "confirmed", "created_at": "2026-03-01T00:00:00+00:00",
            "updated_at": "2026-03-01T00:00:00+00:00", "reviewed_at": "2026-03-01T00:00:00+00:00",
        }
        # Legacy: no expected account, not yet verified.
        await db.deposits.update_one(
            {"id": "dep_seed_legacy"},
            {"$set": {"id": "dep_seed_legacy", **base},
             "$unset": {"payment_account_id": "", "payment_account_label": "",
                        "payment_account_details": "", "confirmed_account_id": "",
                        "confirmed_account_label": "", "credit_pending": ""}},
            upsert=True)
        # With expected account snapshot (prevista).
        await db.deposits.update_one(
            {"id": "dep_seed_expected"},
            {"$set": {"id": "dep_seed_expected", **base,
                      "payment_account_id": "pa_seed_eur",
                      "payment_account_label": "Seed Revolut EUR",
                      "payment_account_details": "IBAN LT00 1111 2222",
                      "payment_account_network": ""},
             "$unset": {"confirmed_account_id": "", "confirmed_account_label": "",
                        "credit_pending": ""}},
            upsert=True)
        print("Seeded: pa_seed_usdt_trc, pa_seed_usdt_erc, pa_seed_eur, "
              "dep_seed_legacy (no account), dep_seed_expected (expected account).")
    finally:
        c.close()


asyncio.run(main())
