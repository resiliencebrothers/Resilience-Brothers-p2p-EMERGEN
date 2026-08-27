"""iter176 — manual trigger + preview for the daily ops (>48h) report."""
import logging
from typing import Any

from fastapi import APIRouter, Request

from db_client import db
from auth_utils import require_admin
from audit_log import log_action
from services.ops_daily_report import collect_stale_cases, run_daily_ops_fraud_report

logger = logging.getLogger(__name__)
router = APIRouter(tags=["OpsReport"])


@router.get("/admin/ops-report/preview")
async def ops_report_preview(request: Request) -> Any:
    await require_admin(request)
    return await collect_stale_cases(db)


@router.post("/admin/ops-report/run")
async def ops_report_run(request: Request) -> Any:
    actor = await require_admin(request)
    result = await run_daily_ops_fraud_report(db)
    await log_action(db, actor, "ops_report.manual_run", "ops_report", "daily",
                     summary=(f"Reporte de operaciones ejecutado manualmente: "
                              f"{result.get('total', 0)} casos, "
                              f"{result.get('sent', 0)} emails"),
                     details=result)
    return result
