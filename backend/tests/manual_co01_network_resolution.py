"""Manual smoke test — CO-01 strict crypto network resolution for deposits.
Run: cd /app/backend && python tests/manual_co01_network_resolution.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from fastapi import HTTPException  # noqa: E402
from db_client import db  # noqa: E402
from routes.deposits import _resolve_deposit_payment_account  # noqa: E402


async def main():
    code = "SMOKEUSDT"
    currency = {"code": code, "type": "crypto", "payment_account": ""}
    # clean slate
    await db.payment_accounts.delete_many({"currency_code": code})
    await db.payment_accounts.insert_many([
        {"id": "pa_trc", "currency_code": code, "label": "Wallet TRC20",
         "account_details": "T-address", "network": "TRC20",
         "min_amount": 10, "max_amount": None, "is_active": True},
        {"id": "pa_erc", "currency_code": code, "label": "Wallet ERC20",
         "account_details": "0x-address", "network": "ERC20",
         "min_amount": 10, "max_amount": None, "is_active": True},
    ])

    ok = True

    # 1) TRC20 request → TRC20 account (never ERC20)
    acc = await _resolve_deposit_payment_account(currency, "crypto", 50, "TRC20")
    print("TRC20 req →", acc)
    ok &= acc and acc["id"] == "pa_trc" and acc["network"] == "TRC20"

    # 2) ERC20 request → ERC20 account
    acc = await _resolve_deposit_payment_account(currency, "crypto", 50, "ERC20")
    print("ERC20 req →", acc)
    ok &= acc and acc["id"] == "pa_erc" and acc["network"] == "ERC20"

    # 3) BEP20 request (no account) → 400, NEVER falls back to another network
    try:
        acc = await _resolve_deposit_payment_account(currency, "crypto", 50, "BEP20")
        print("BEP20 req → UNEXPECTED", acc)
        ok = False
    except HTTPException as e:
        print("BEP20 req → rejected 400:", e.status_code, str(e.detail)[:60])
        ok &= e.status_code == 400

    # 4) TRC20 below-min only-account scenario
    await db.payment_accounts.delete_many({"currency_code": code})
    await db.payment_accounts.insert_one(
        {"id": "pa_trc2", "currency_code": code, "label": "Wallet TRC20",
         "account_details": "T", "network": "TRC20",
         "min_amount": 100, "max_amount": None, "is_active": True})
    try:
        await _resolve_deposit_payment_account(currency, "crypto", 50, "TRC20")
        print("TRC20 below-min → UNEXPECTED success")
        ok = False
    except HTTPException as e:
        print("TRC20 below-min → rejected 400:", str(e.detail)[:70])
        ok &= e.status_code == 400

    await db.payment_accounts.delete_many({"currency_code": code})
    print("\nRESULT:", "PASS" if ok else "FAIL")


asyncio.run(main())
