"""iter51 — Production remediation script.

Background
----------
A bug in `services/orders_helpers.run_post_status_side_effects` caused
`accumulate`-method orders that went `pending → completed` directly (admin
clicked "Completar" without first clicking "Confirmar") to NEVER credit the
user's `vip_balances`. The fix introduced an idempotent `accumulated_at`
flag and broadens the trigger to fire on ANY first transition into a
money-settled status.

This one-shot script finds existing orders that should have been credited
but weren't, and applies the missing increments retroactively. It's safe to
run multiple times — orders already carrying `accumulated_at` are skipped.

Usage
-----
On the production pod (or wherever your prod-Mongo MONGO_URL/DB_NAME live):
    python -m scripts.backfill_accumulate_balances --dry-run     # preview
    python -m scripts.backfill_accumulate_balances --apply       # execute

Always start with --dry-run and inspect the report.
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("backfill_accumulate")


async def _find_uncredited_orders(db):
    """Return orders that meet ALL of:
      - delivery_method == "accumulate"
      - status in ("approved", "completed")
      - `accumulated_at` is missing (never credited)
    """
    cursor = db.orders.find(
        {
            "delivery_method": "accumulate",
            "status": {"$in": ["approved", "completed"]},
            "accumulated_at": {"$exists": False},
        },
        {
            "_id": 0, "id": 1, "user_id": 1, "user_email": 1,
            "to_code": 1, "amount_to": 1, "status": 1, "created_at": 1,
        },
    )
    return [o async for o in cursor]


async def main(dry_run: bool) -> int:
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    orders = await _find_uncredited_orders(db)
    log.info("Found %d uncredited accumulate orders.", len(orders))

    by_user = {}
    for o in orders:
        u = o["user_id"]
        by_user.setdefault(u, []).append(o)

    total_credited = 0
    for uid, group in by_user.items():
        email = group[0].get("user_email") or "?"
        log.info("User %s (%s) → %d orders to credit:", uid, email, len(group))
        for o in group:
            log.info(
                "  - %s %s %s %.4f %s (status=%s, created=%s)",
                o["id"], "DRY" if dry_run else "CREDIT",
                o["to_code"], o["amount_to"], o["to_code"],
                o["status"], o.get("created_at"),
            )
            if not dry_run:
                # Idempotent: only credits orders still missing the flag.
                res = await db.orders.update_one(
                    {"id": o["id"], "accumulated_at": {"$exists": False}},
                    {"$set": {
                        "accumulated_at": datetime.now(timezone.utc).isoformat(),
                        "accumulated_via": "backfill_iter51",
                    }},
                )
                if res.modified_count == 1:
                    await db.users.update_one(
                        {"user_id": o["user_id"]},
                        {"$inc": {f"vip_balances.{o['to_code']}": o["amount_to"]}},
                    )
                    total_credited += 1

    if dry_run:
        log.info("DRY RUN — no changes applied. Re-run with --apply to commit.")
    else:
        log.info("Done. Credited %d orders across %d users.",
                 total_credited, len(by_user))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="Show what would be credited without writing")
    group.add_argument("--apply", action="store_true",
                       help="Actually credit missing balances (idempotent)")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
