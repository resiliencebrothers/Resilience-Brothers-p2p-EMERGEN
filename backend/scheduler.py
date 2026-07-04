"""Background scheduler for periodic admin tasks.

Currently handles:
- monthly revenue PDF email to all admins on day 1 at 09:00 UTC.
- iter49: security anomaly scan every 5 minutes.
"""
import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import email_service
from revenue_report import revenue_monthly_pdf
from services.security_alerts import run_security_alert_scan

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler = None


def _previous_month(now: datetime):
    """Return (year, month, label) for the month before `now`."""
    first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_of_prev = first_of_this_month - timedelta(days=1)
    return last_of_prev.year, last_of_prev.month, f"{last_of_prev.year}-{last_of_prev.month:02d}"


async def run_monthly_revenue_email(db, build_timeseries):
    """Generate previous month's PDF and email it to every admin.

    `build_timeseries` is an async callable `(granularity, year, month) -> rows`.
    Passed in to avoid an import cycle with server.py.
    """
    year, month, label = _previous_month(datetime.now(timezone.utc))
    try:
        rows = await build_timeseries("day", year=year, month=month)
    except Exception:
        logger.exception("Monthly revenue: failed to build timeseries for %s", label)
        return

    rows_asc = sorted(rows, key=lambda x: x["bucket"])
    totals = {
        "p2p": sum(r["p2p_profit_usdt"] for r in rows_asc),
        "marketplace": sum(r["marketplace_profit_usdt"] for r in rows_asc),
        "total": sum(r["total_profit_usdt"] for r in rows_asc),
        "volume": sum(r["volume_usdt"] for r in rows_asc),
        "orders": sum(r["orders"] for r in rows_asc),
    }
    try:
        pdf_bytes = revenue_monthly_pdf(rows_asc, label, totals)
    except Exception:
        logger.exception("Monthly revenue: PDF generation failed for %s", label)
        return

    admins = await db.users.find({"role": "admin"},
                                 {"_id": 0, "email": 1, "name": 1}).to_list(200)
    from admin_alerts import resolve_admin_email_recipients
    recipients = await resolve_admin_email_recipients(db, admins=admins)
    sent = 0
    for to_addr in recipients:
        if email_service.notify_monthly_revenue(
            to_addr, label, totals, pdf_bytes
        ):
            sent += 1
    logger.info("Monthly revenue email %s: sent to %s/%s recipient(s)", label, sent, len(recipients))


def start_scheduler(db, build_timeseries):
    """Start APScheduler with the monthly revenue job (day 1 09:00 UTC).

    Idempotent — safe to call once on FastAPI startup.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        run_monthly_revenue_email,
        CronTrigger(day=1, hour=9, minute=0, timezone="UTC"),
        kwargs={"db": db, "build_timeseries": build_timeseries},
        id="monthly_revenue_email",
        replace_existing=True,
        misfire_grace_time=3600,  # if container was down, run within 1h of catch-up
        coalesce=True,
    )
    # iter49 — every 5 minutes scan security_events for anomalies and fanout
    # push + email alerts to every admin. Cheap query (indexed) + de-duped per
    # anomaly_key with 6h cool-off, so scaling this frequency is safe.
    _scheduler.add_job(
        run_security_alert_scan,
        IntervalTrigger(minutes=5),
        kwargs={"db": db},
        id="security_alert_scan",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Scheduler started: monthly_revenue_email (day 1 @ 09:00 UTC) + security_alert_scan (every 5m)")
    return _scheduler


def stop_scheduler():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
