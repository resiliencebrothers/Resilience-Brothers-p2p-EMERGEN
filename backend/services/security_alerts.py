"""Automated anomaly scanner over `security_events` (iter49).

Runs every 5 minutes via APScheduler and delivers push + email alerts to every
admin (via `admin_alerts.notify_all_admins`) when it detects:

* `admin_multi_ip`   — a single staff account (admin/employee) logged in from
  3 or more DISTINCT IPs within the last 24 hours. Textbook credential-theft
  or shared-account signal.
* `ip_rate_flood`    — a single IP hit >=100 rate_limit_hit events in the last
  1 hour. Likely brute-force or automated abuse.
* `origin_flood`     — a single IP triggered >=20 origin_blocked events in the
  last 1 hour. Very likely a CSRF probe or scripted attacker.

De-duplication: every anomaly gets a stable `anomaly_key`. Before firing, we
check `db.security_alerts_sent` for an entry with the same key inserted in the
last `COOLDOWN_HOURS` (default 6h) — if present, we skip the alert. This keeps
inboxes clean during a sustained incident but still surfaces new patterns.

Retention: alert sent-log has a 7-day TTL index so it doesn't grow unbounded.
"""
import logging
import os
from datetime import timedelta
from typing import Any, Optional

from db_client import db as default_db
from auth_utils import now_utc, iso

logger = logging.getLogger(__name__)

# Alert thresholds — tune here without touching consumers.
ADMIN_MULTI_IP_WINDOW = timedelta(hours=24)
ADMIN_MULTI_IP_THRESHOLD = 3

IP_RATE_FLOOD_WINDOW = timedelta(hours=1)
IP_RATE_FLOOD_THRESHOLD = 100

ORIGIN_FLOOD_WINDOW = timedelta(hours=1)
ORIGIN_FLOOD_THRESHOLD = 20

# How long to suppress duplicate alerts for the same anomaly key. Tunable at
# runtime via env so ops can loosen/tighten during an active incident without
# a code deploy.
COOLDOWN_HOURS = int(os.environ.get("SECURITY_ALERT_COOLDOWN_HOURS", "6"))


# ------------------------------------------------------------------
# Dedup helpers
# ------------------------------------------------------------------

async def _already_alerted(db: Any, anomaly_key: str) -> bool:
    cutoff = iso(now_utc() - timedelta(hours=COOLDOWN_HOURS))
    hit = await db.security_alerts_sent.find_one(
        {"anomaly_key": anomaly_key, "sent_at": {"$gte": cutoff}},
        {"_id": 0, "anomaly_key": 1},
    )
    return hit is not None


async def _mark_alerted(db: Any, anomaly_key: str, detail: dict) -> None:
    now = now_utc()
    await db.security_alerts_sent.insert_one({
        "anomaly_key": anomaly_key,
        "sent_at": iso(now),
        "_ts": now,          # date field for TTL
        "detail": detail,
    })


async def ensure_indexes(db: Any = None) -> None:
    """Create the TTL index on `security_alerts_sent`. Idempotent."""
    _db = default_db if db is None else db
    try:
        await _db.security_alerts_sent.create_index(
            [("_ts", 1)], expireAfterSeconds=7 * 24 * 3600, name="ttl_ts_7d",
        )
        await _db.security_alerts_sent.create_index(
            [("anomaly_key", 1), ("sent_at", -1)],
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"security_alerts_sent index setup failed: {e}")


# ------------------------------------------------------------------
# Detectors
# ------------------------------------------------------------------

async def _detect_admin_multi_ip(db: Any) -> list[dict]:
    """Return one dict per staff account with >= threshold distinct IPs in window."""
    cutoff = iso(now_utc() - ADMIN_MULTI_IP_WINDOW)
    pipeline = [
        {"$match": {"kind": "admin_new_ip", "created_at": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$user_id",
            "user_email": {"$last": "$user_email"},
            "ips": {"$addToSet": "$ip"},
            "count": {"$sum": 1},
            "last_seen": {"$max": "$created_at"},
        }},
        {"$match": {"$expr": {"$gte": [{"$size": "$ips"}, ADMIN_MULTI_IP_THRESHOLD]}}},
    ]
    return await db.security_events.aggregate(pipeline).to_list(50)


async def _detect_ip_flood(db: Any, kind: str, window: timedelta,
                           threshold: int) -> list[dict]:
    """Generic 'IP hit >=threshold events of `kind` within `window`' detector."""
    cutoff = iso(now_utc() - window)
    pipeline = [
        {"$match": {"kind": kind, "created_at": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$ip",
            "count": {"$sum": 1},
            "last_seen": {"$max": "$created_at"},
            "top_paths": {"$addToSet": "$path"},
        }},
        {"$match": {"count": {"$gte": threshold}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    return await db.security_events.aggregate(pipeline).to_list(20)


# ------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------

async def _fire_admin_multi_ip(db: Any, row: dict) -> bool:
    user_id = row["_id"]
    key = f"admin_multi_ip:{user_id}"
    if await _already_alerted(db, key):
        return False
    ips = row.get("ips") or []
    email = row.get("user_email") or user_id
    # Mark BEFORE fanout so a raise from notify_all_admins cannot cause the same
    # anomaly to fire every 5 minutes until an unrelated code path re-marks it.
    # notify_all_admins internally swallows per-recipient errors, but we still
    # want the belt-and-braces guarantee.
    await _mark_alerted(db, key, {"user_id": user_id, "email": email, "ips": ips})
    try:
        from admin_alerts import notify_all_admins
        await notify_all_admins(
            db,
            title=f"⚠️ Cuenta staff con {len(ips)} IPs distintas",
            body=(
                f"{email} inició sesión desde {len(ips)} IPs diferentes en las "
                f"últimas 24h: {', '.join(ips[:5])}"
                + ("…" if len(ips) > 5 else "")
                + ". Revísalo en Admin → Seguridad y revoca sesiones si es sospechoso."
            ),
            url_path="/admin/security",
        )
    except Exception as e:  # noqa: BLE001
        logger.exception(f"notify_all_admins failed for {key}: {e}")
    return True


async def _fire_ip_flood(db: Any, row: dict, *, kind_label: str,
                         anomaly_prefix: str, threshold_desc: str) -> bool:
    ip = row["_id"] or "unknown"
    key = f"{anomaly_prefix}:{ip}"
    if await _already_alerted(db, key):
        return False
    paths = (row.get("top_paths") or [])[:3]
    # Mark BEFORE fanout (see comment in _fire_admin_multi_ip).
    await _mark_alerted(db, key, {"ip": ip, "count": row["count"], "paths": paths})

    # iter50/50b — auto-block on detected flood. Persistent record always kept
    # in `cloudflare_ip_blocks`; enforcement is app-level via
    # `middleware.ip_blocklist` (see iter50b). If Cloudflare credentials are
    # ALSO configured, the block is additionally pushed to the CF edge for
    # defense-in-depth.
    cf_outcome = None
    auto_block_on = os.environ.get("APP_AUTO_BLOCK_ENABLED", "true").lower() == "true"
    if ip != "unknown" and auto_block_on:
        try:
            from services import cloudflare_blocks
            res = await cloudflare_blocks.create_block(
                db, ip,
                notes=f"auto: security_alerts_scanner kind={kind_label} count={row['count']}",
                source="scanner",
            )
            if res.get("cf_ok"):
                cf_outcome = " · IP bloqueada en app + Cloudflare WAF ✅"
            elif res.get("already_blocked"):
                cf_outcome = " · IP ya estaba bloqueada ✅"
            elif res.get("created"):
                cf_outcome = " · IP bloqueada a nivel app ✅ (CF sin creds)"
            else:
                cf_outcome = f" · No se pudo bloquear ({res.get('reason','error')})"
            # Invalidate app-level cache so the block takes effect within
            # seconds of the scan (not the 30s TTL).
            try:
                from middleware.ip_blocklist import invalidate_cache
                invalidate_cache()
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            logger.exception(f"auto-block failed for {ip}: {e}")
            cf_outcome = " · Auto-block falló (ver logs)"

    try:
        from admin_alerts import notify_all_admins
        await notify_all_admins(
            db,
            title=f"⚠️ IP sospechosa: {row['count']} eventos {kind_label}",
            body=(
                f"IP {ip} generó {row['count']} eventos '{kind_label}' "
                f"(umbral: {threshold_desc}). "
                f"Endpoints tocados: {', '.join(paths) if paths else 'n/a'}."
                + (cf_outcome or "")
            ),
            url_path="/admin/security",
        )
    except Exception as e:  # noqa: BLE001
        logger.exception(f"notify_all_admins failed for {key}: {e}")
    return True


# ------------------------------------------------------------------
# Public entry point (called by scheduler + tests)
# ------------------------------------------------------------------

async def run_security_alert_scan(db: Optional[Any] = None) -> dict:
    """Scan the security_events collection for anomalies and fire alerts.
    Returns a summary dict with the number of alerts sent by category.
    Safe to invoke concurrently — the dedup layer prevents double-sends."""
    _db = default_db if db is None else db
    sent = {"admin_multi_ip": 0, "ip_rate_flood": 0, "origin_flood": 0}

    try:
        for row in await _detect_admin_multi_ip(_db):
            if await _fire_admin_multi_ip(_db, row):
                sent["admin_multi_ip"] += 1
    except Exception as e:  # noqa: BLE001
        logger.exception(f"admin_multi_ip detector failed: {e}")

    try:
        for row in await _detect_ip_flood(
            _db, "rate_limit_hit", IP_RATE_FLOOD_WINDOW, IP_RATE_FLOOD_THRESHOLD,
        ):
            if await _fire_ip_flood(
                _db, row, kind_label="rate_limit_hit",
                anomaly_prefix="ip_rate_flood",
                threshold_desc=f"{IP_RATE_FLOOD_THRESHOLD}/1h",
            ):
                sent["ip_rate_flood"] += 1
    except Exception as e:  # noqa: BLE001
        logger.exception(f"ip_rate_flood detector failed: {e}")

    try:
        for row in await _detect_ip_flood(
            _db, "origin_blocked", ORIGIN_FLOOD_WINDOW, ORIGIN_FLOOD_THRESHOLD,
        ):
            if await _fire_ip_flood(
                _db, row, kind_label="origin_blocked",
                anomaly_prefix="origin_flood",
                threshold_desc=f"{ORIGIN_FLOOD_THRESHOLD}/1h",
            ):
                sent["origin_flood"] += 1
    except Exception as e:  # noqa: BLE001
        logger.exception(f"origin_flood detector failed: {e}")

    total = sum(sent.values())
    if total > 0:
        logger.warning(f"[security-scan] fired {total} alert(s): {sent}")
    else:
        logger.info("[security-scan] clean: no anomalies detected")
    return sent
