"""Admin router — audit log (browse + CSV/PDF export).

Extracted from routes/admin.py during the iter39 split.
"""
import csv
import io
import json as _json
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from db_client import db
from auth_utils import require_admin, _enforce_totp_step_up
from audit_pdf import generate_audit_pdf
from audit_pdf_monthly import generate_monthly_audit_pdf
from services.transactions import build_audit_query, fetch_audit_entries
from services.audit_report import (
    compute_monthly_kpis,
    compute_integrity_hash,
    month_range_iso,
    month_label,
)


router = APIRouter(tags=["Admin"])


@router.get("/admin/audit/actors")
async def list_audit_actors(request: Request, q: Optional[str] = None,
                              limit: int = 20) -> Any:
    """iter55.35 — actor picker for the audit hub. Returns distinct actors
    from the audit_log matching a search string against name/email/user_id.
    Sorted by most-recent activity so operators see the busiest staff first.
    Admin-only (same gate as `/admin/audit`)."""
    await require_admin(request)
    limit = max(1, min(int(limit or 20), 100))
    # Build an aggregation that groups by actor_id and returns the last
    # activity + count. Matching against name/email/user_id is applied AFTER
    # the group so partial matches on any of the three fields work.
    q_str = (q or "").strip().lower()
    pipeline: list = [
        {"$match": {"actor_id": {"$exists": True, "$ne": ""}}},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": "$actor_id",
            "actor_name": {"$first": "$actor_name"},
            "actor_email": {"$first": "$actor_email"},
            "actor_role": {"$first": "$actor_role"},
            "last_seen": {"$first": "$created_at"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"last_seen": -1}},
    ]
    if q_str:
        pipeline.append({"$match": {
            "$or": [
                {"_id": {"$regex": q_str, "$options": "i"}},
                {"actor_name": {"$regex": q_str, "$options": "i"}},
                {"actor_email": {"$regex": q_str, "$options": "i"}},
            ],
        }})
    pipeline.append({"$limit": limit})
    rows = await db.audit_log.aggregate(pipeline).to_list(limit)
    return [{
        "actor_id": r["_id"],
        "actor_name": r.get("actor_name", ""),
        "actor_email": r.get("actor_email", ""),
        "actor_role": r.get("actor_role", ""),
        "last_seen": r.get("last_seen", ""),
        "count": r.get("count", 0),
    } for r in rows]


@router.get("/admin/audit")
async def list_audit_log(request: Request, limit: int = 100, offset: int = 0,
                         action: Optional[str] = None, actor_id: Optional[str] = None,
                         since: Optional[str] = None, until: Optional[str] = None) -> Any:
    await require_admin(request)
    q = build_audit_query(action, actor_id, since, until)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total = await db.audit_log.count_documents(q)
    docs = await db.audit_log.find(q, {"_id": 0}).sort("created_at", -1).skip(offset).to_list(limit)
    return JSONResponse(
        content=docs,
        headers={
            "X-Total-Count": str(total),
            "X-Offset": str(offset),
            "X-Limit": str(limit),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Offset, X-Limit",
        },
    )


@router.get("/admin/audit/export.csv")
async def export_audit_csv(request: Request, action: Optional[str] = None,
                           actor_id: Optional[str] = None,
                           since: Optional[str] = None, until: Optional[str] = None,
                           limit: int = 5000) -> Any:
    await require_admin(request)
    entries = await fetch_audit_entries(action, actor_id, since, until, limit)
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow(["created_at", "actor_id", "actor_email", "actor_name", "actor_role",
                     "actor_permissions_effective",
                     "action", "entity_type", "entity_id", "summary", "details"])
    for e in entries:
        perms = e.get("actor_permissions_effective")
        if isinstance(perms, list):
            perms_str = ";".join(perms) if perms else "all_staff_default"
        else:
            perms_str = perms or ""
        writer.writerow([
            e.get("created_at", ""),
            e.get("actor_id", ""),
            e.get("actor_email", ""),
            e.get("actor_name", ""),
            e.get("actor_role", ""),
            perms_str,
            e.get("action", ""),
            e.get("entity_type", ""),
            e.get("entity_id", ""),
            e.get("summary", ""),
            _json.dumps(e.get("details") or {}, ensure_ascii=False),
        ])
    buf = BytesIO()
    buf.write(text_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"audit_log_{ts}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/audit/export.pdf")
async def export_audit_pdf(request: Request, action: Optional[str] = None,
                           actor_id: Optional[str] = None,
                           since: Optional[str] = None, until: Optional[str] = None,
                           limit: int = 2000) -> Any:
    await require_admin(request)
    entries = await fetch_audit_entries(action, actor_id, since, until, limit)
    pdf_bytes = generate_audit_pdf(
        entries,
        {"action": action, "actor_id": actor_id, "since": since, "until": until},
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"audit_log_{ts}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================
# iter55.17 — Monthly audit PDF (exec summary + detail + hash)
# ============================================================

def _validate_year_month(year: int, month: int) -> None:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="mes inválido (1-12)")
    if year < 2020 or year > 2100:
        raise HTTPException(status_code=400, detail="año inválido")


async def _build_monthly_bundle(year: int, month: int) -> dict:
    """Fetch entries for the calendar month and precompute KPIs + integrity
    hash + human label. Reused by the download and the email endpoint."""
    since_iso, until_iso = month_range_iso(year, month)
    # 5000 rows/month upper bound matches the existing CSV export cap.
    entries = await fetch_audit_entries(
        action=None, actor_id=None, since=since_iso, until=until_iso, limit=5000,
    )
    label = month_label(year, month)
    kpis = compute_monthly_kpis(entries)
    integrity = compute_integrity_hash(entries, label)
    return {
        "entries": entries,
        "kpis": kpis,
        "integrity_hash": integrity,
        "period_label": label,
        "period_slug": f"{year}-{month:02d}",
    }


@router.get("/admin/audit/monthly.pdf")
async def admin_audit_monthly_pdf(request: Request, year: int, month: int) -> Any:
    """Download the executive monthly audit report as PDF (admin-only)."""
    await require_admin(request)
    _validate_year_month(year, month)
    bundle = await _build_monthly_bundle(year, month)
    pdf_bytes = generate_monthly_audit_pdf(
        bundle["entries"], bundle["period_label"],
        bundle["kpis"], bundle["integrity_hash"],
    )
    filename = f"auditoria-{bundle['period_slug']}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/audit/monthly.summary")
async def admin_audit_monthly_summary(request: Request, year: int, month: int) -> Any:
    """Return the KPIs of a given month without generating the PDF.

    Used by the frontend to preview the counts before deciding to download or
    email. Cheap enough to call on-demand — reuses the same DB query."""
    await require_admin(request)
    _validate_year_month(year, month)
    bundle = await _build_monthly_bundle(year, month)
    return {
        "period_label": bundle["period_label"],
        "period_slug": bundle["period_slug"],
        "integrity_hash": bundle["integrity_hash"],
        "kpis": bundle["kpis"],
        "row_count": len(bundle["entries"]),
    }


@router.post("/admin/audit/monthly/send-email")
async def admin_audit_monthly_send_email(payload: dict, request: Request) -> Any:
    """Send the monthly audit PDF to the ops mailbox (or all admins). Admin
    only + TOTP step-up because it moves sensitive data to email."""
    actor = await require_admin(request)
    await _enforce_totp_step_up(
        actor, payload.get("totp_code"),
        action_label="enviar reporte mensual de auditoría",
    )
    year = int(payload.get("year") or 0)
    month = int(payload.get("month") or 0)
    _validate_year_month(year, month)

    bundle = await _build_monthly_bundle(year, month)
    pdf_bytes = generate_monthly_audit_pdf(
        bundle["entries"], bundle["period_label"],
        bundle["kpis"], bundle["integrity_hash"],
    )

    # Reuse the ops-notifications-email precedence: if set, only that inbox;
    # else all admins.
    from admin_alerts import resolve_admin_email_recipients
    import email_service

    recipients = await resolve_admin_email_recipients(db)
    if not recipients:
        raise HTTPException(status_code=400,
                            detail="No hay destinatarios configurados")

    sent = 0
    for to_addr in recipients:
        ok = email_service.notify_monthly_audit(
            to_addr, bundle["period_label"], bundle["kpis"],
            bundle["integrity_hash"], pdf_bytes,
        )
        if ok:
            sent += 1
    return {
        "ok": True,
        "sent": sent,
        "recipients": len(recipients),
        "period": bundle["period_slug"],
        "period_label": bundle["period_label"],
        "integrity_hash": bundle["integrity_hash"],
        "row_count": len(bundle["entries"]),
    }
