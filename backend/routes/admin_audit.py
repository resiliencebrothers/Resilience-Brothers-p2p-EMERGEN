"""Admin router — audit log (browse + CSV/PDF export).

Extracted from routes/admin.py during the iter39 split.
"""
import csv
import io
import json as _json
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from db_client import db
from auth_utils import require_admin
from audit_pdf import generate_audit_pdf
from services.transactions import build_audit_query, fetch_audit_entries


router = APIRouter(tags=["Admin"])


@router.get("/admin/audit")
async def list_audit_log(request: Request, limit: int = 100, offset: int = 0,
                         action: Optional[str] = None, actor_id: Optional[str] = None,
                         since: Optional[str] = None, until: Optional[str] = None):
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
                           limit: int = 5000):
    await require_admin(request)
    entries = await fetch_audit_entries(action, actor_id, since, until, limit)
    text_buf = io.StringIO()
    writer = csv.writer(text_buf, quoting=csv.QUOTE_ALL)
    writer.writerow(["created_at", "actor_id", "actor_email", "actor_name", "actor_role",
                     "action", "entity_type", "entity_id", "summary", "details"])
    for e in entries:
        writer.writerow([
            e.get("created_at", ""),
            e.get("actor_id", ""),
            e.get("actor_email", ""),
            e.get("actor_name", ""),
            e.get("actor_role", ""),
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
                           limit: int = 2000):
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
