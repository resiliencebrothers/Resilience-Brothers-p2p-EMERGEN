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
from services.security_selfaudit import run_and_email_security_selfaudit
from services.ops_daily_report import run_daily_ops_fraud_report
from services.email_bounce_alerts import dispatch_pending_alerts

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
        "conversion_fees": sum(r.get("conversion_fees_usdt", 0.0) for r in rows_asc),
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


# ============================================================
# iter55.21 — Monthly AUDIT report (day 1 @ 09:15 UTC)
# ============================================================
async def run_monthly_audit_email(db):
    """Generate the previous month's audit-log PDF and email it to admins.

    Reuses services/audit_report.compute_monthly_kpis + compute_integrity_hash
    and audit_pdf_monthly.generate_monthly_audit_pdf (all iter55.17). Runs at
    09:15 UTC on day 1 — 15 min after the revenue email so the two arrive
    in the operator's inbox as a natural pair.

    Opt-out: skips silently when `settings.global.auto_send_monthly_audit`
    is explicitly False. Default = enabled once the code lands.
    """
    from services.audit_report import (
        compute_monthly_kpis, compute_integrity_hash,
        month_range_iso, month_label,
    )
    from audit_pdf_monthly import generate_monthly_audit_pdf
    from services.transactions import fetch_audit_entries

    year, month, slug = _previous_month(datetime.now(timezone.utc))
    label = month_label(year, month)

    # Opt-out flag lives in settings.global (single-doc collection)
    try:
        settings = await db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
    except Exception:
        settings = {}
    if not settings.get("auto_send_monthly_audit", True):
        logger.info("Monthly audit email %s: skipped (opt-out flag)", slug)
        return

    since_iso, until_iso = month_range_iso(year, month)
    try:
        entries = await fetch_audit_entries(
            action=None, actor_id=None, since=since_iso, until=until_iso, limit=5000,
        )
    except Exception:
        logger.exception("Monthly audit: failed to fetch entries for %s", slug)
        return
    kpis = compute_monthly_kpis(entries)
    integrity = compute_integrity_hash(entries, label)
    try:
        pdf_bytes = generate_monthly_audit_pdf(entries, label, kpis, integrity)
    except Exception:
        logger.exception("Monthly audit: PDF generation failed for %s", slug)
        return

    from admin_alerts import resolve_admin_email_recipients
    recipients = await resolve_admin_email_recipients(db)
    sent = 0
    for to_addr in recipients:
        try:
            if email_service.notify_monthly_audit(
                to_addr, label, kpis, integrity, pdf_bytes
            ):
                sent += 1
        except Exception:
            logger.exception("Monthly audit email to %s failed", to_addr)
    logger.info(
        "Monthly audit email %s: sent to %s/%s recipient(s) · %s entries · hash=%s",
        slug, sent, len(recipients), len(entries), integrity[:12],
    )


async def run_monthly_vip_ledger_email(db):
    """iter111.3 — email previous month's ledger PDF statement to every VIP.

    Skips silently when `settings.global.auto_send_monthly_vip_ledger` is
    explicitly False (global admin opt-out). Also skips individual VIPs
    who set `users.monthly_ledger_email_enabled=False`.

    VIPs with an empty statement (0 movements AND zero ledger) are skipped
    to avoid noise — the point of a monthly statement is to reconcile
    activity, not send empty inboxes.
    """
    from datetime import date
    from calendar import monthrange
    from services.vip_ledger_reporting import collect_ledger_movements
    from vip_ledger_pdf import generate_vip_ledger_pdf

    year, month, slug = _previous_month(datetime.now(timezone.utc))
    since = date(year, month, 1).strftime("%Y-%m-%d")
    until = date(year, month, monthrange(year, month)[1]).strftime("%Y-%m-%d")

    try:
        settings = await db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
    except Exception:
        settings = {}
    if not settings.get("auto_send_monthly_vip_ledger", True):
        logger.info("Monthly VIP ledger %s: skipped (opt-out flag)", slug)
        return {"period": slug, "sent": 0, "skipped_empty": 0,
                "failed": 0, "total_vips": 0, "opted_out": True}

    since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    until_dt = datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    vips = await db.users.find(
        {"role": "vip", "email": {"$exists": True, "$ne": ""},
         "monthly_ledger_email_enabled": {"$ne": False}},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1, "preferred_language": 1},
    ).to_list(2000)

    system_actor = {"user_id": "system.scheduler",
                    "name": "Scheduler",
                    "email": "system@resiliencebrothers.com",
                    "preferred_language": "es"}

    sent = 0
    skipped_empty = 0
    failed = 0
    for vip in vips:
        try:
            initial_pos, initial_neg, movements = await collect_ledger_movements(
                vip["user_id"], since_dt, until_dt,
            )
            if not movements and initial_pos == 0 and initial_neg == 0:
                skipped_empty += 1
                continue
            pdf_bytes = generate_vip_ledger_pdf(
                vip={"user_id": vip["user_id"], "name": vip.get("name", ""),
                     "email": vip.get("email", "")},
                since=since, until=until,
                initial_positive=initial_pos,
                initial_negative=initial_neg,
                movements=movements,
                actor=system_actor,
            )
            ok = email_service.notify_vip_ledger_statement(
                email_service.VipLedgerEmailContext(
                    to=vip["email"],
                    vip_name=vip.get("name") or vip["email"],
                    since=since, until=until,
                    movements_count=len(movements),
                    pdf_bytes=pdf_bytes,
                    issuer_name="Resilience Brothers · Automatic Statement",
                    personal_note=(
                        "Este es tu estado de cuenta VIP mensual automático. "
                        "Contiene todos los movimientos confirmados del período."
                    ),
                    lang=(vip.get("preferred_language") or "es"),
                ),
            )
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
            logger.exception("Monthly VIP ledger: failed for %s", vip.get("email"))
    logger.info(
        "Monthly VIP ledger %s: sent=%s skipped_empty=%s failed=%s (total_vips=%s)",
        slug, sent, skipped_empty, failed, len(vips),
    )
    return {"period": slug, "sent": sent, "skipped_empty": skipped_empty,
            "failed": failed, "total_vips": len(vips), "opted_out": False}


async def run_daily_batch_autoclose(db):
    """Daily 00:00 America/Havana — close every open VIP batch so each batch
    accounts for exactly one day of orders. Open batches WITHOUT items are
    deleted instead, so the history never accumulates blank entries."""
    now = datetime.now(timezone.utc).isoformat()
    open_batches = await db.vip_batches.find(
        {"status": "open"}, {"_id": 0, "id": 1, "vip_user_id": 1},
    ).to_list(5000)
    closed = deleted = 0
    touched_vips = set()
    for b in open_batches:
        items = await db.vip_batch_items.count_documents({"batch_id": b["id"]})
        if items == 0:
            await db.vip_batches.delete_one({"id": b["id"]})
            deleted += 1
        else:
            await db.vip_batches.update_one(
                {"id": b["id"]},
                {"$set": {"status": "closed", "closed_at": now,
                          "updated_at": now, "auto_closed": True}},
            )
            closed += 1
        if b.get("vip_user_id"):
            touched_vips.add(b["vip_user_id"])
    try:
        from services.live_bus import publish as live_publish
        for uid in touched_vips:
            await live_publish(
                "vip_batch_item_decision", {"reason": "daily_autoclose"}, user_id=uid,
            )
    except Exception:
        logger.exception("Daily batch autoclose: SSE publish failed")
    logger.info("Daily batch autoclose: closed=%s deleted_empty=%s", closed, deleted)
    return {"closed": closed, "deleted_empty": deleted}


async def run_low_fund_balance_scan():
    """iter224 — escaneo periódico de saldos mínimos configurados."""
    try:
        from services.fund_alerts import check_low_fund_balances
        n = await check_low_fund_balances()
        if n:
            logger.info(f"[low-fund-scan] {n} alerta(s) de saldo bajo enviadas")
    except Exception as e:
        logger.error(f"[low-fund-scan] failed: {e}")


async def run_cash_box_sync():
    """iter263 — espejo de ajustes de capital en efectivo hacia la Caja de
    Efectivo «Fondo Resilience» (backfill histórico + sanación si el espejo
    inline falló). Idempotente por id determinista."""
    try:
        from services.cash_box_sync import backfill_cash_operations
        n = await backfill_cash_operations()
        if n:
            logger.info("[cash-box-sync] %s ajuste(s) replicados en la caja", n)
    except Exception as e:
        logger.error(f"[cash-box-sync] failed: {e}")
    try:
        # V01 — presupuesto de retiros: resincroniza reservas huérfanas
        from services.company_fund_budget import resync_budgets
        m = await resync_budgets()
        if m:
            logger.warning("[fund-budget] %s presupuesto(s) resincronizados", m)
    except Exception as e:
        logger.error(f"[fund-budget-resync] failed: {e}")


async def run_daily_arqueo_request():
    """iter264 — Arqueo Programado: al cierre del día (20:00 Cuba) la caja
    pide el arqueo de billetes de cada fondo de empresa con actividad."""
    try:
        from services.cash_box_arqueo import run_daily_arqueo_request as _req
        n = await _req()
        if n:
            logger.info("[arqueo-request] %s fondo(s) pendientes avisados", n)
    except Exception as e:
        logger.error(f"[arqueo-request] failed: {e}")


async def run_credit_recovery():
    """iter249 — completa acreditaciones que quedaron a medias (crash entre el
    claim y el abono). Idempotente por op_id; nunca duplica."""
    try:
        from services.credit_recovery import (heal_pending_credits,
                                              heal_initializing_ops)
        n = await heal_pending_credits()
        n += await heal_initializing_ops()
        # iter257(D06) — compactación de registros embebidos: retira solo ops
        # con log duradero confirmado; los 'pending' se conservan como
        # evidencia (sustituye al viejo $slice ciego).
        from services.balances import compact_credit_registries
        from services.inventory import compact_stock_registries
        n += await compact_credit_registries()
        n += await compact_stock_registries()
        if n:
            logger.warning("[credit-recovery] %s operaciones pendientes sanadas", n)
    except Exception as e:
        logger.error(f"[credit-recovery] failed: {e}")


def start_scheduler(db, build_timeseries):
    """Start APScheduler with the monthly jobs + security scan.

    Idempotent — safe to call once on FastAPI startup.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")
    # iter249 — sanador de acreditaciones pendientes (cada 2 min + al arrancar)
    _scheduler.add_job(
        run_credit_recovery,
        IntervalTrigger(seconds=120),
        id="credit_recovery",
        replace_existing=True,
        misfire_grace_time=120,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    # iter263 — espejo de efectivo Fondo de Empresa → Caja (al arrancar + 10 min)
    _scheduler.add_job(
        run_cash_box_sync,
        IntervalTrigger(minutes=10),
        id="cash_box_sync",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    # iter224 — alerta de saldo bajo en cuentas internas / caja (cada 10 min)
    _scheduler.add_job(
        run_low_fund_balance_scan,
        IntervalTrigger(minutes=10),
        id="low_fund_balance_scan",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
    )
    _scheduler.add_job(
        run_monthly_revenue_email,
        CronTrigger(day=1, hour=9, minute=0, timezone="UTC"),
        kwargs={"db": db, "build_timeseries": build_timeseries},
        id="monthly_revenue_email",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # iter55.21 — monthly audit PDF (opt-out via settings.global)
    _scheduler.add_job(
        run_monthly_audit_email,
        CronTrigger(day=1, hour=9, minute=15, timezone="UTC"),
        kwargs={"db": db},
        id="monthly_audit_email",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # iter111.3 — monthly VIP ledger PDF (opt-out via settings.global)
    _scheduler.add_job(
        run_monthly_vip_ledger_email,
        CronTrigger(day=1, hour=9, minute=30, timezone="UTC"),
        kwargs={"db": db},
        id="monthly_vip_ledger_email",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # iter116 — monthly security self-audit checklist (day 1 @ 09:45 UTC).
    _scheduler.add_job(
        run_and_email_security_selfaudit,
        CronTrigger(day=1, hour=9, minute=45, timezone="UTC"),
        kwargs={"db": db},
        id="monthly_security_selfaudit",
        replace_existing=True,
        misfire_grace_time=3600,
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
    # Daily VIP batch auto-close at Cuban midnight — one batch == one day.
    _scheduler.add_job(
        run_daily_batch_autoclose,
        CronTrigger(hour=0, minute=0, timezone="America/Havana"),
        kwargs={"db": db},
        id="daily_batch_autoclose",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # iter264 — Arqueo Programado de la Caja de Efectivo (20:00 America/Havana)
    _scheduler.add_job(
        run_daily_arqueo_request,
        CronTrigger(hour=20, minute=0, timezone="America/Havana"),
        id="daily_arqueo_request",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # iter176 — daily ops digest (>48h fraud/attention cases) at 08:00 Cuba.
    _scheduler.add_job(
        run_daily_ops_fraud_report,
        CronTrigger(hour=8, minute=0, timezone="America/Havana"),
        kwargs={"db": db},
        id="daily_ops_fraud_report",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # iter196 — every 60s dispatch queued email-bounce alerts (fanout to
    # admins when a user racks up 3 consecutive Resend failures).
    _scheduler.add_job(
        dispatch_pending_alerts,
        IntervalTrigger(seconds=60),
        kwargs={"db": db},
        id="email_bounce_dispatch",
        replace_existing=True,
        misfire_grace_time=60,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started: monthly_revenue_email (day 1 09:00 UTC) + "
        "monthly_audit_email (day 1 09:15 UTC) + "
        "monthly_vip_ledger_email (day 1 09:30 UTC) + "
        "monthly_security_selfaudit (day 1 09:45 UTC) + "
        "security_alert_scan (every 5m) + "
        "daily_batch_autoclose (00:00 America/Havana) + "
        "daily_ops_fraud_report (08:00 America/Havana) + "
        "email_bounce_dispatch (every 60s)"
    )
    return _scheduler


def stop_scheduler():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
