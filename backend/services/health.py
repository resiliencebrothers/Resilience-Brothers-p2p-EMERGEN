"""Admin Health Dashboard aggregator — iter37.

Single source for the `/admin/health` panel. Each section is wrapped in
try/except so one slow/failing data source doesn't break the whole page.
"""
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from db_client import db
from services import storage as storage_service
from services.balances import get_defensive_mode
from services.orders_helpers import compute_order_profit
from services.anti_scam import compute_anti_scam_metrics


logger = logging.getLogger(__name__)


# ============================================================
# Helpers
# ============================================================

R2_STORAGE_COST_PER_GB = 0.015      # $/GB/month (Cloudflare standard)
R2_OPERATIONS_COST_PER_M = 0.36     # $/million Class B (GET) ops
LOG_FILE = "/var/log/supervisor/backend.err.log"
# Match Python/uvicorn log lines starting with the level, not the word "ERROR"
# appearing inside an arbitrary HTTP response body or string.
_ERROR_RX = re.compile(r"^(ERROR|CRITICAL)\b|\s(ERROR|CRITICAL):", re.MULTILINE)


def _safe(coroutine_or_fn: Callable[[], Any], default: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap a single section so one failure doesn't tank the dashboard."""
    try:
        return coroutine_or_fn()
    except Exception as e:
        logger.error(f"[health] section failed: {e}")
        return {**default, "error": str(e)}


# ============================================================
# Sections
# ============================================================

def _sentry_status() -> dict:
    """We don't pull live data from Sentry's API (would require an org token).
    Instead we expose the configured environment + a deep link the admin can
    click, plus a rough local error count from supervisor logs (last 24h)."""
    dsn_configured = bool(os.environ.get("SENTRY_DSN", "").strip())
    env_label = os.environ.get("SENTRY_ENV", "preview")
    deep_link = ""
    if dsn_configured:
        # Extract `o<orgId>` from the DSN to build the dashboard URL.
        m = re.search(r"@o(\d+)\.ingest", os.environ["SENTRY_DSN"])
        if m:
            # We don't know the org slug, so use the generic /organizations URL.
            deep_link = "https://sentry.io/organizations/sentry/issues/?statsPeriod=24h"
    # Local error count (cheap O(N) scan of the last 1k lines)
    local_errors = 0
    try:
        # Read tail with subprocess to avoid loading huge log files in memory.
        out = subprocess.run(
            ["tail", "-n", "2000", LOG_FILE],
            capture_output=True, text=True, timeout=2,
        )
        # Count matches of MULTILINE regex on the full block.
        local_errors = len(_ERROR_RX.findall(out.stdout))
    except Exception:
        pass
    return {
        "enabled": dsn_configured,
        "environment": env_label,
        "deep_link": deep_link or "https://sentry.io/",
        "local_errors_recent": local_errors,
    }


def _storage_status() -> dict:
    """Tally object count + bytes in the R2 bucket. Falls back to disabled if
    storage is off, since we can't list objects."""
    if not storage_service.is_enabled():
        return {
            "enabled": False, "provider": "none",
            "bucket": None, "object_count": 0,
            "size_bytes": 0, "size_gb": 0.0,
            "monthly_cost_usd": 0.0,
        }
    # Reach into the module-level client + bucket. We expose them as the public
    # surface for health reporting (acceptable for an admin-only view).
    client = storage_service._client  # noqa: SLF001
    assert client is not None  # narrowed by is_enabled()
    bucket = storage_service._bucket   # noqa: SLF001
    total_count = 0
    total_bytes = 0
    by_prefix: dict = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []) or []:
            total_count += 1
            total_bytes += int(obj["Size"])
            prefix = obj["Key"].split("/", 1)[0] if "/" in obj["Key"] else "(root)"
            by_prefix.setdefault(prefix, {"count": 0, "bytes": 0})
            by_prefix[prefix]["count"] += 1
            by_prefix[prefix]["bytes"] += int(obj["Size"])
    size_gb = total_bytes / (1024 ** 3)
    return {
        "enabled": True,
        "provider": os.environ.get("STORAGE_PROVIDER", "r2"),
        "bucket": bucket,
        "object_count": total_count,
        "size_bytes": total_bytes,
        "size_gb": round(size_gb, 4),
        "monthly_cost_usd": round(size_gb * R2_STORAGE_COST_PER_GB, 4),
        "by_folder": [
            {"folder": k, "count": v["count"],
             "size_mb": round(v["bytes"] / (1024 ** 2), 2)}
            for k, v in sorted(by_prefix.items(), key=lambda x: -x[1]["bytes"])
        ],
    }


async def _throughput_status() -> dict:
    """Orders per hour for the last 24h + totals."""
    now = datetime.now(timezone.utc)
    cutoffs = {
        "1h": (now - timedelta(hours=1)).isoformat(),
        "24h": (now - timedelta(hours=24)).isoformat(),
        "7d": (now - timedelta(days=7)).isoformat(),
    }
    counts = {}
    for label, cutoff in cutoffs.items():
        counts[label] = await db.orders.count_documents({"created_at": {"$gte": cutoff}})
    # Hourly histogram for the last 24h.
    hourly = []
    for i in range(24, 0, -1):
        start = (now - timedelta(hours=i)).isoformat()
        end = (now - timedelta(hours=i - 1)).isoformat()
        n = await db.orders.count_documents({"created_at": {"$gte": start, "$lt": end}})
        hourly.append({"hour": (now - timedelta(hours=i)).strftime("%H:00"), "count": n})
    return {
        "orders_last_1h": counts["1h"],
        "orders_last_24h": counts["24h"],
        "orders_last_7d": counts["7d"],
        "hourly_24h": hourly,
    }


async def _defensive_status() -> dict:
    state = await get_defensive_mode()
    return {
        "enabled": bool(state.get("enabled")),
        "reason": state.get("reason", ""),
        "enabled_at": state.get("enabled_at"),
        "enabled_by_email": state.get("enabled_by_email", ""),
    }


async def _negative_margin_status() -> dict:
    """Find pending orders that would lose money at the current real_rate."""
    pending = await db.orders.find(
        {"status": {"$in": ["pending", "requires_double_approval"]}},
        {"_id": 0},
    ).to_list(500)
    losers = []
    rates_cache: dict = {}
    for o in pending:
        pair = (o["from_code"], o["to_code"])
        if pair not in rates_cache:
            rates_cache[pair] = await db.rates.find_one(
                {"from_code": o["from_code"], "to_code": o["to_code"]}, {"_id": 0},
            )
        prof = await compute_order_profit(o, rates_cache[pair])
        if prof and prof["amount"] < 0:
            losers.append({
                "id": o["id"],
                "user_name": o.get("user_name", ""),
                "pair": f"{o['from_code']}→{o['to_code']}",
                "amount_from": o["amount_from"],
                "amount_to": o["amount_to"],
                "loss_amount": round(abs(prof["amount"]), 2),
                "loss_currency": prof["currency"],
                "loss_pct": prof["pct"],
                "status": o["status"],
            })
    losers.sort(key=lambda x: -x["loss_amount"])
    return {"count": len(losers), "items": losers[:20]}


async def _queue_status() -> dict:
    return {
        "pending_orders": await db.orders.count_documents({"status": "pending"}),
        "pending_double_approval": await db.orders.count_documents(
            {"status": "requires_double_approval"}),
        "pending_withdrawals": await db.withdrawals.count_documents({"status": "pending"}),
        "pending_phone_verifications": await db.users.count_documents(
            {"account_status": "under_review", "phone": {"$nin": [None, ""]}}),
        "blocked_contacts": await db.blocked_contacts.count_documents({}),
    }


async def _platform_stats() -> dict:
    return {
        "users_total": await db.users.count_documents({}),
        "users_active": await db.users.count_documents({"account_status": "active"}),
        "users_under_review": await db.users.count_documents({"account_status": "under_review"}),
        "users_blocked": await db.users.count_documents({"account_status": "blocked"}),
        "orders_total": await db.orders.count_documents({}),
        "orders_approved": await db.orders.count_documents(
            {"status": {"$in": ["approved", "completed"]}}),
        "orders_rejected": await db.orders.count_documents({"status": "rejected"}),
        "products_total": await db.products.count_documents({}),
    }


# ============================================================
# Public API
# ============================================================

async def build_health_summary() -> dict:
    """Composite endpoint payload. Wrap each section so one failure surface as
    an `error` key instead of taking down the whole page."""
    # Order matters for the front-end card rendering. Sync sections first
    # (cheap), async sections after (DB-bound).
    sentry = _safe(_sentry_status, {"enabled": False})
    storage = _safe(_storage_status, {"enabled": False})
    throughput = await _throughput_status()
    defensive = await _defensive_status()
    neg_margin = await _negative_margin_status()
    queues = await _queue_status()
    platform = await _platform_stats()
    # iter46 — anti-scam metrics (queue depth, avg resolution time, oldest ticket).
    try:
        anti_scam = await compute_anti_scam_metrics()
    except Exception as e:
        logger.error(f"anti_scam metrics failed: {e}")
        anti_scam = {"error": str(e)}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sentry": sentry,
        "storage": storage,
        "throughput": throughput,
        "defensive_mode": defensive,
        "negative_margin": neg_margin,
        "queues": queues,
        "platform": platform,
        "anti_scam": anti_scam,
    }
