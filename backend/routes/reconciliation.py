"""iter167 — Conciliación Bancaria (bank reconciliation) admin module.

Flow (spec §4): staff uploads a statement file for a given bank/payment
account + currency → file stored (R2 or Mongo fallback) → background pipeline
extracts, normalizes, fingerprints, dedupes and matches transactions against
pending client orders → auto-match / manual review / unmatched.

All endpoints gated by the dedicated `reconciliation` permission.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import (APIRouter, BackgroundTasks, File, Form, HTTPException,
                     Request, UploadFile)
from fastapi.responses import Response
from pydantic import BaseModel

from auth_utils import require_permission, iso, now_utc
from db_client import db
from audit_log import log_action
from services import storage as storage_service
from services.reconciliation_matcher import (DEFAULT_CONFIG,
                                             get_config, recon_audit,
                                             validate_config_value,
                                             approve_order_from_reconciliation,
                                             approve_batch_item_from_reconciliation,
                                             rollback_batch_item_from_reconciliation,
                                             rematch_transactions,
                                             run_matching)
from services.reconciliation_parser import (PARSER_VERSION,
                                            SUPPORTED_EXTENSIONS,
                                            detect_payment_method,
                                            file_sha256, fingerprint,
                                            parse_statement)

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_STATEMENT_BYTES = 8 * 1024 * 1024  # 8 MB
_EU_DAYFIRST_HINTS = ("sabadell", "bbva", "santander", "caixa", "bankinter")

TX_STATUSES = ("auto_matched", "manual_review", "unmatched", "duplicate",
               "manual_matched", "ignored", "error")

_indexes_ready = False


async def _ensure_indexes() -> None:
    """§8 unique fingerprint + §34 performance indexes (idempotent)."""
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        await db.bank_transactions.create_index("fingerprint", unique=True)
        await db.bank_transactions.create_index([("status", 1), ("transaction_date", -1)])
        await db.bank_transactions.create_index("statement_import_id")
        await db.bank_transactions.create_index("matched_order_id")
        await db.bank_statement_imports.create_index("file_hash")
        await db.reconciliation_audit_log.create_index("bank_transaction_id")
        _indexes_ready = True
    except Exception as e:
        logger.error(f"reconciliation index setup failed: {e}")


def _dayfirst_for(bank_name: str, currency: str) -> bool:
    b = (bank_name or "").lower()
    if any(h in b for h in _EU_DAYFIRST_HINTS):
        return True
    return currency.upper() in ("EUR", "MXN", "BRL")


async def _store_file(import_id: str, filename: str, data: bytes,
                      content_type: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    key = f"reconciliation/{import_id}.{ext}"
    if storage_service.is_enabled():
        stored = storage_service.put_object(key, data, content_type)
        if stored:
            return f"/api/files/{key}"
    # fallback: keep bytes in Mongo (≤ 8 MB, fits BSON)
    await db.statement_files.update_one(
        {"id": import_id},
        {"$set": {"id": import_id, "filename": filename, "data": data,
                  "content_type": content_type}},
        upsert=True,
    )
    return f"mongo://{import_id}"


# ---------------------------------------------------------------------------
# Background pipeline
# ---------------------------------------------------------------------------
async def process_import(import_id: str, data: bytes, ext: str) -> None:
    await _ensure_indexes()
    imp = await db.bank_statement_imports.find_one({"id": import_id}, {"_id": 0})
    if not imp:
        return

    async def _stage(name: str) -> None:
        await db.bank_statement_imports.update_one(
            {"id": import_id}, {"$set": {"processing_stage": name}})

    await db.bank_statement_imports.update_one(
        {"id": import_id},
        {"$set": {"processing_status": "processing",
                  "processing_stage": "reading",
                  "processing_started_at": iso(now_utc())}})
    try:
        dayfirst = _dayfirst_for(imp.get("bank_name") or "", imp["currency"])
        txs, errors, mode = await parse_statement(data, ext, dayfirst)
        await _stage("deduplicating")

        tx_docs, duplicates, credits, debits = [], 0, 0, 0
        now = iso(now_utc())
        seen_in_file: set = set()
        for t in txs:
            # iter187 — date-less rows (no date column in the document) use
            # the row index as the reference component so two identical
            # payments in the same file are NOT collapsed as duplicates.
            fp_ref = (t.get("reference") or t.get("description")
                      or (f"row{t['row_index']}"
                          if not t.get("transaction_date") and t.get("row_index") is not None
                          else ""))
            fp = fingerprint(imp.get("bank_account_id") or "",
                             t["transaction_date"], t["amount"],
                             imp["currency"], fp_ref,
                             t.get("sender_name") or "")
            is_dup = fp in seen_in_file or bool(
                await db.bank_transactions.find_one({"fingerprint": fp}, {"_id": 1}))
            seen_in_file.add(fp)
            stored_fp = fp if not is_dup else f"dup:{uuid.uuid4().hex}:{fp[:16]}"
            if t["direction"] == "credit":
                credits += 1
            else:
                debits += 1
            doc = {
                "id": f"btx_{uuid.uuid4().hex[:12]}",
                "statement_import_id": import_id,
                "bank_account_id": imp.get("bank_account_id"),
                "bank_name": imp.get("bank_name"),
                "currency": imp["currency"],
                "direction": t["direction"],
                "amount": t["amount"],
                "transaction_date": t["transaction_date"],
                "posting_date": t.get("posting_date"),
                "value_date": t.get("value_date"),
                "time": t.get("time"),
                "sender_name": t.get("sender_name"),
                "beneficiary_name": t.get("beneficiary_name"),
                "description": t.get("description"),
                "concept": t.get("concept"),
                "memo": t.get("memo"),
                "reference": t.get("reference"),
                "transaction_id_bank": t.get("transaction_id_bank"),
                "confirmation_number": t.get("confirmation_number"),
                "trace_number": t.get("trace_number"),
                "transfer_number": t.get("transfer_number"),
                "transfer_type": t.get("transfer_type"),
                "payment_method": t.get("payment_method") or detect_payment_method(
                    t.get("description") or ""),
                "balance_after": t.get("balance_after"),
                "last4_account": t.get("last4_account"),
                "fingerprint": stored_fp,
                "fingerprint_original": fp,
                "status": ("duplicate" if is_dup
                           else ("ignored" if t["direction"] == "debit" else "unmatched")),
                "ignored_reason": ("debit" if (t["direction"] == "debit" and not is_dup) else None),
                "confidence_score": None,
                "matched_order_id": None,
                "match_details": None,
                "candidates": [],
                "reviewed_by": None,
                "reviewed_at": None,
                "raw": t.get("raw") or {},
                "created_at": now,
                "updated_at": now,
            }
            if is_dup:
                duplicates += 1
            tx_docs.append(doc)

        if tx_docs:
            await db.bank_transactions.insert_many([dict(d) for d in tx_docs])

        await _stage("matching")
        counts = await run_matching(imp, tx_docs)
        await _stage("finalizing")

        status = "processed"
        # iter186 — never leave a "processed" import that silently produced
        # nothing: mark it failed with a human-readable reason, and warn when
        # every detected movement is a debit (they get auto-ignored, so the
        # admin would otherwise see "processed" but nothing to match).
        notes = None
        if errors > 0 and txs:
            status = "partially_processed"
        elif not txs:
            status = "failed"
            notes = ("No se detectó ningún movimiento en el archivo. Verifica que "
                     "sea un extracto con transacciones legibles (CSV, XLS, XLSX o "
                     "PDF). Si es un PDF escaneado con baja calidad, intenta "
                     "exportarlo de nuevo o usar el formato CSV del banco.")
        if tx_docs and credits == 0:
            notes = ("Se detectaron movimientos pero TODOS son egresos (débitos) y "
                     "se marcaron como ignorados. La conciliación busca pagos "
                     "RECIBIDOS (créditos) — verifica que el extracto sea de la "
                     "cuenta que recibe los pagos.")
        await db.bank_statement_imports.update_one(
            {"id": import_id},
            {"$set": {
                "processing_status": status,
                "notes": notes,
                "processing_finished_at": iso(now_utc()),
                "total_transactions_detected": len(tx_docs),
                "total_credits_detected": credits,
                "total_debits_detected": debits,
                "total_auto_matched": counts["auto"],
                "total_manual_review": counts["review"],
                "total_unmatched": counts["unmatched"],
                "total_duplicates": duplicates,
                "total_errors": max(errors, 0),
                "parse_mode": mode,
                "processing_stage": None,
            }})
        await recon_audit("STATEMENT_IMPORTED",
                          {"user_id": imp.get("uploaded_by_user_id"),
                           "name": imp.get("uploaded_by_name")},
                          import_id=import_id,
                          details={"file": imp.get("original_file_name"),
                                   "detected": len(tx_docs), "credits": credits,
                                   "auto": counts["auto"], "review": counts["review"],
                                   "duplicates": duplicates, "mode": mode})
        try:
            from services.live_bus import publish as live_publish
            await live_publish("reconciliation_import", {
                "import_id": import_id, "status": status,
                "auto": counts["auto"], "review": counts["review"],
            }, roles=("admin", "employee"))
        except Exception:
            pass
    except Exception as e:
        logger.exception(f"reconciliation import {import_id} failed")
        await db.bank_statement_imports.update_one(
            {"id": import_id},
            {"$set": {"processing_status": "failed",
                      "processing_finished_at": iso(now_utc()),
                      "notes": f"Error: {str(e)[:400]}"}})


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
@router.post("/admin/reconciliation/imports")
async def upload_statement(request: Request, background: BackgroundTasks,
                           file: UploadFile = File(...),
                           bank_account_id: str = Form(""),
                           bank_name: str = Form(...),
                           currency: str = Form(...)) -> Any:
    actor = await require_permission(request, "reconciliation")
    filename = file.filename or "statement"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Formato .{ext or '?'} no soportado. Usa: "
                   f"{', '.join(sorted(SUPPORTED_EXTENSIONS))}.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="El archivo está vacío.")
    if len(data) > MAX_STATEMENT_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el límite de 8 MB.")

    fhash = file_sha256(data)
    existing = await db.bank_statement_imports.find_one(
        {"file_hash": fhash, "processing_status": {"$ne": "failed"}}, {"_id": 0, "id": 1})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Este statement ya fue importado (import {existing['id']}). "
                   f"Revísalo en Historial y archivos.")

    import_id = f"imp_{uuid.uuid4().hex[:12]}"
    stored_url = await _store_file(import_id, filename, data,
                                   file.content_type or "application/octet-stream")
    doc = {
        "id": import_id,
        "bank_account_id": bank_account_id or None,
        "bank_name": bank_name.strip(),
        "currency": currency.strip().upper(),
        "original_file_name": filename,
        "stored_file_url": stored_url,
        "file_type": ext,
        "file_hash": fhash,
        "uploaded_by_user_id": actor["user_id"],
        "uploaded_by_name": actor.get("name") or actor.get("email"),
        "uploaded_at": iso(now_utc()),
        "processing_started_at": None,
        "processing_finished_at": None,
        "processing_status": "uploaded",
        "total_transactions_detected": 0,
        "total_credits_detected": 0,
        "total_debits_detected": 0,
        "total_auto_matched": 0,
        "total_manual_review": 0,
        "total_unmatched": 0,
        "total_duplicates": 0,
        "total_errors": 0,
        "parser_version": PARSER_VERSION,
        "notes": None,
    }
    await db.bank_statement_imports.insert_one(dict(doc))
    await log_action(db, actor, "reconciliation.import_uploaded",
                     "bank_statement_import", import_id,
                     summary=f"Statement {filename} ({doc['currency']}, {doc['bank_name']})",
                     details={"file_type": ext, "bank_account_id": bank_account_id})
    background.add_task(process_import, import_id, data, ext)
    return doc


@router.get("/admin/reconciliation/bank-accounts")
async def reconciliation_bank_accounts(request: Request) -> Any:
    """Active payment accounts as the selectable bank-account list."""
    await require_permission(request, "reconciliation")
    items = await db.payment_accounts.find(
        {"is_active": True},
        {"_id": 0, "id": 1, "label": 1, "currency_code": 1, "account_details": 1},
    ).sort("label", 1).to_list(200)
    return {"items": items}


@router.get("/admin/reconciliation/imports")
async def list_imports(request: Request, limit: int = 100,
                       currency: Optional[str] = None) -> Any:
    await require_permission(request, "reconciliation")
    q: Dict[str, Any] = {}
    if currency and currency.strip():
        q["currency"] = currency.strip().upper()
    items = await db.bank_statement_imports.find(q, {"_id": 0}) \
        .sort("uploaded_at", -1).to_list(min(max(limit, 1), 500))
    return {"items": items}


@router.get("/admin/reconciliation/imports/{import_id}")
async def get_import(import_id: str, request: Request) -> Any:
    await require_permission(request, "reconciliation")
    doc = await db.bank_statement_imports.find_one({"id": import_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Importación no encontrada")
    return doc


@router.get("/admin/reconciliation/imports/{import_id}/file")
async def download_import_file(import_id: str, request: Request) -> Any:
    await require_permission(request, "reconciliation")
    doc = await db.bank_statement_imports.find_one({"id": import_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Importación no encontrada")
    url = doc.get("stored_file_url") or ""
    if url.startswith("mongo://"):
        f = await db.statement_files.find_one({"id": import_id})
        if not f:
            raise HTTPException(status_code=404, detail="Archivo no disponible")
        return Response(content=bytes(f["data"]),
                        media_type=f.get("content_type") or "application/octet-stream",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{doc["original_file_name"]}"'})
    key = url.replace("/api/files/", "", 1)
    blob, ctype = storage_service.get_object_bytes(key)
    if blob is None:
        raise HTTPException(status_code=404, detail="Archivo no disponible")
    return Response(content=blob, media_type=ctype or "application/octet-stream",
                    headers={"Content-Disposition":
                             f'attachment; filename="{doc["original_file_name"]}"'})


@router.post("/admin/reconciliation/imports/{import_id}/reprocess")
async def reprocess_import(import_id: str, request: Request,
                           background: BackgroundTasks) -> Any:
    """iter188 — re-runs the full pipeline (parse + matching) over the stored
    file, without re-uploading. Matched movements are preserved; the rest are
    removed and re-created (rows identical to kept matches dedupe naturally)."""
    actor = await require_permission(request, "reconciliation")
    imp = await db.bank_statement_imports.find_one({"id": import_id}, {"_id": 0})
    if not imp:
        raise HTTPException(status_code=404, detail="Importación no encontrada")
    if imp.get("processing_status") in ("uploaded", "processing"):
        raise HTTPException(status_code=409,
                            detail="Este import todavía se está procesando.")
    url = imp.get("stored_file_url") or ""
    data = None
    if url.startswith("mongo://"):
        f = await db.statement_files.find_one({"id": import_id})
        data = bytes(f["data"]) if f else None
    elif url:
        blob, _ct = storage_service.get_object_bytes(url.replace("/api/files/", "", 1))
        data = blob
    if not data:
        raise HTTPException(
            status_code=410,
            detail="El archivo original ya no está disponible. Sube el statement de nuevo.")
    removed = await db.bank_transactions.delete_many({
        "statement_import_id": import_id,
        "status": {"$nin": ["auto_matched", "manual_matched"]}})
    await db.bank_statement_imports.update_one(
        {"id": import_id},
        {"$set": {"processing_status": "uploaded", "processing_stage": None,
                  "notes": None, "processing_finished_at": None}})
    await recon_audit("STATEMENT_REPROCESSED",
                      {"user_id": actor["user_id"],
                       "name": actor.get("name") or actor.get("email")},
                      import_id=import_id,
                      details={"file": imp.get("original_file_name"),
                               "removed_unmatched": removed.deleted_count})
    background.add_task(process_import, import_id, data,
                        imp.get("file_type") or "pdf")
    return {"ok": True, "removed_unmatched": removed.deleted_count}


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------
@router.get("/admin/reconciliation/transactions")
async def list_transactions(request: Request, import_id: Optional[str] = None,
                            status: Optional[str] = None,
                            q: Optional[str] = None,
                            bank: Optional[str] = None,
                            currency: Optional[str] = None,
                            date_from: Optional[str] = None,
                            date_to: Optional[str] = None,
                            amount_min: Optional[float] = None,
                            amount_max: Optional[float] = None,
                            score_min: Optional[float] = None,
                            method: Optional[str] = None,
                            limit: int = 300) -> Any:
    """§40 — filterable transactions list."""
    await require_permission(request, "reconciliation")
    import re as _re
    query: Dict[str, Any] = {}
    if import_id:
        query["statement_import_id"] = import_id
    if status in TX_STATUSES:
        query["status"] = status
    if q and q.strip():
        rx = {"$regex": _re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"sender_name": rx}, {"description": rx},
                        {"reference": rx}, {"beneficiary_name": rx}]
    if bank and bank.strip():
        query["bank_name"] = {"$regex": _re.escape(bank.strip()), "$options": "i"}
    if currency and currency.strip():
        query["currency"] = currency.strip().upper()
    date_q: Dict[str, Any] = {}
    if date_from:
        date_q["$gte"] = str(date_from)[:10]
    if date_to:
        date_q["$lte"] = str(date_to)[:10]
    if date_q:
        query["transaction_date"] = date_q
    amt_q: Dict[str, Any] = {}
    if amount_min is not None:
        amt_q["$gte"] = float(amount_min)
    if amount_max is not None:
        amt_q["$lte"] = float(amount_max)
    if amt_q:
        query["amount"] = amt_q
    if score_min is not None:
        query["confidence_score"] = {"$gte": float(score_min)}
    if method and method.strip():
        query["payment_method"] = {"$regex": _re.escape(method.strip()), "$options": "i"}
    items = await db.bank_transactions.find(query, {"_id": 0, "raw": 0}) \
        .sort([("transaction_date", -1), ("created_at", -1)]) \
        .to_list(min(max(limit, 1), 1000))
    # iter181 — filter stale candidates: orders/batch_items that are already
    # matched against a different bank_transaction should not appear as
    # options in the "Revisar" dialog anymore. We check both by
    # matched_order_id on other bank_transactions and by the underlying
    # order/vip_batch_item no longer being in a "pending" state.
    cand_ids = {c["order_id"] for it in items for c in (it.get("candidates") or [])}
    if cand_ids:
        taken_docs = await db.bank_transactions.find(
            {"matched_order_id": {"$in": list(cand_ids)},
             "status": {"$in": ["auto_matched", "manual_matched"]}},
            {"_id": 0, "matched_order_id": 1}
        ).to_list(None)
        taken_ids = {d["matched_order_id"] for d in taken_docs}
        # Also exclude orders no longer pending (approved elsewhere, cancelled…)
        alive_orders = {o["id"] async for o in db.orders.find(
            {"id": {"$in": list(cand_ids)},
             "status": {"$in": ["pending", "requires_double_approval"]}},
            {"_id": 0, "id": 1})}
        alive_items = {o["id"] async for o in db.vip_batch_items.find(
            {"id": {"$in": list(cand_ids)}, "status": "pending"},
            {"_id": 0, "id": 1})}
        alive_ids = alive_orders | alive_items
        for it in items:
            it["candidates"] = [
                c for c in (it.get("candidates") or [])
                if c["order_id"] in alive_ids and c["order_id"] not in taken_ids
            ]
    # iter190 — legacy ignored rows only stored the user_id: resolve names.
    need_names = {it["reviewed_by"] for it in items
                  if it.get("reviewed_by") and not it.get("reviewed_by_name")}
    if need_names:
        names = {u["user_id"]: (u.get("name") or u.get("email"))
                 async for u in db.users.find(
                     {"user_id": {"$in": list(need_names)}},
                     {"_id": 0, "user_id": 1, "name": 1, "email": 1})}
        for it in items:
            if it.get("reviewed_by") and not it.get("reviewed_by_name"):
                it["reviewed_by_name"] = names.get(it["reviewed_by"])
    return {"items": items}


@router.get("/admin/reconciliation/summary")
async def reconciliation_summary(request: Request,
                                 currency: Optional[str] = None) -> Any:
    await require_permission(request, "reconciliation")
    # iter185 — per-currency workspaces: every stat can be scoped to one
    # currency so a staff member assigned to e.g. EUR only sees EUR data.
    match: Dict[str, Any] = {}
    if currency and currency.strip():
        match["currency"] = currency.strip().upper()
    pipeline: List[Dict[str, Any]] = []
    if match:
        pipeline.append({"$match": match})
    pipeline.append({"$group": {"_id": "$status", "n": {"$sum": 1}}})
    counts = {r["_id"]: r["n"] async for r in db.bank_transactions.aggregate(pipeline)}
    # iter186 — include import currencies so the workspace pill appears even
    # when the statement failed or produced no movements yet.
    tx_curs = await db.bank_transactions.distinct("currency")
    imp_curs = await db.bank_statement_imports.distinct("currency")
    currencies = sorted({c for c in [*tx_curs, *imp_curs] if c})
    return {
        "manual_review": counts.get("manual_review", 0),
        "unmatched": counts.get("unmatched", 0),
        "auto_matched": counts.get("auto_matched", 0),
        "manual_matched": counts.get("manual_matched", 0),
        "duplicate": counts.get("duplicate", 0),
        "ignored": counts.get("ignored", 0),
        "error": counts.get("error", 0),
        "currencies": currencies,
    }


@router.get("/admin/reconciliation/dashboard")
async def reconciliation_dashboard(request: Request, days: int = 30,
                                   currency: Optional[str] = None) -> Any:
    """§38 + §52 — operational metrics over a configurable window."""
    await require_permission(request, "reconciliation")
    from datetime import datetime, timedelta
    days = min(max(days, 1), 730)
    since = iso(now_utc() - timedelta(days=days))
    today_prefix = iso(now_utc())[:10]
    # iter185 — optional per-currency scope for every metric.
    cur = currency.strip().upper() if currency and currency.strip() else None
    tx_scope: Dict[str, Any] = {"currency": cur} if cur else {}
    imp_scope: Dict[str, Any] = {"currency": cur} if cur else {}

    counts = {r["_id"]: r["n"] async for r in db.bank_transactions.aggregate([
        {"$match": {"created_at": {"$gte": since}, **tx_scope}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    by_currency = []
    score_weighted, matched_total = 0.0, 0
    async for r in db.bank_transactions.aggregate([
        {"$match": {"created_at": {"$gte": since}, **tx_scope,
                    "status": {"$in": ["auto_matched", "manual_matched"]}}},
        {"$group": {"_id": "$currency", "total": {"$sum": "$amount"},
                    "count": {"$sum": 1}, "avg_score": {"$avg": "$confidence_score"}}},
        {"$sort": {"total": -1}}]):
        by_currency.append({"currency": r["_id"], "total": round(r["total"], 2),
                            "count": r["count"]})
        score_weighted += (r["avg_score"] or 0) * r["count"]
        matched_total += r["count"]

    imports = await db.bank_statement_imports.find(
        {"uploaded_at": {"$gte": since}, **imp_scope},
        {"_id": 0, "uploaded_at": 1, "processing_started_at": 1,
         "processing_finished_at": 1, "parse_mode": 1,
         "total_transactions_detected": 1, "total_errors": 1}).to_list(3000)
    imports_today = sum(1 for i in imports
                        if str(i.get("uploaded_at") or "").startswith(today_prefix))
    tx_today = await db.bank_transactions.count_documents(
        {"created_at": {"$gte": today_prefix}, **tx_scope})
    durations, ocr_imports, detected_sum, errors_sum = [], 0, 0, 0
    for i in imports:
        detected_sum += int(i.get("total_transactions_detected") or 0)
        errors_sum += int(i.get("total_errors") or 0)
        if "ocr" in str(i.get("parse_mode") or ""):
            ocr_imports += 1
        try:
            a = datetime.fromisoformat(str(i["processing_started_at"]))
            b = datetime.fromisoformat(str(i["processing_finished_at"]))
            durations.append((b - a).total_seconds())
        except (TypeError, ValueError):
            pass
    if cur:
        rb_entries = await db.reconciliation_audit_log.find(
            {"action": "ROLLBACK", "performed_at": {"$gte": since}},
            {"_id": 0, "bank_transaction_id": 1}).to_list(3000)
        rb_tx_ids = [e["bank_transaction_id"] for e in rb_entries
                     if e.get("bank_transaction_id")]
        rollbacks = await db.bank_transactions.count_documents(
            {"id": {"$in": rb_tx_ids}, "currency": cur}) if rb_tx_ids else 0
    else:
        rollbacks = await db.reconciliation_audit_log.count_documents(
            {"action": "ROLLBACK", "performed_at": {"$gte": since}})

    auto = counts.get("auto_matched", 0)
    manual = counts.get("manual_matched", 0)
    review = counts.get("manual_review", 0)
    unmatched = counts.get("unmatched", 0)
    denom = auto + manual + review + unmatched

    def pct(n: float, d: float) -> float:
        return round(n * 100.0 / d, 1) if d else 0.0

    return {
        "window_days": days,
        "currency": cur,
        "today": {"imports": imports_today, "transactions": tx_today},
        "imports_window": len(imports),
        "counts": {s: counts.get(s, 0) for s in TX_STATUSES},
        "reconciled": auto + manual,
        "auto_match_rate": pct(auto, denom),
        "manual_review_rate": pct(review, denom),
        "unmatched_rate": pct(unmatched, denom),
        "avg_score_matched": round(score_weighted / matched_total, 1) if matched_total else 0,
        "avg_processing_seconds": round(sum(durations) / len(durations), 1) if durations else 0,
        "ocr_usage_rate": pct(ocr_imports, len(imports)),
        "parser_error_rate": pct(errors_sum, detected_sum + errors_sum),
        "rollbacks": rollbacks,
        "reconciled_by_currency": by_currency,
    }


_DETAIL_TX_BUCKETS: Dict[str, Any] = {
    "reconciled": {"$in": ["auto_matched", "manual_matched"]},
    "manual_review": "manual_review",
    "unmatched": "unmatched",
    "duplicate": "duplicate",
    "error": "error",
}


@router.get("/admin/reconciliation/dashboard/details")
async def reconciliation_dashboard_details(request: Request, bucket: str,
                                           days: int = 30,
                                           limit: int = 200,
                                           currency: Optional[str] = None) -> Any:
    """iter177 — drill-down de las tarjetas del dashboard."""
    await require_permission(request, "reconciliation")
    from datetime import timedelta
    days = min(max(days, 1), 730)
    limit = min(max(limit, 1), 500)
    since = iso(now_utc() - timedelta(days=days))
    cur = currency.strip().upper() if currency and currency.strip() else None
    tx_scope: Dict[str, Any] = {"currency": cur} if cur else {}
    if bucket in _DETAIL_TX_BUCKETS:
        items = await db.bank_transactions.find(
            {"created_at": {"$gte": since}, "status": _DETAIL_TX_BUCKETS[bucket],
             **tx_scope},
            {"_id": 0, "raw": 0, "candidates": 0, "match_details": 0}) \
            .sort([("transaction_date", -1), ("created_at", -1)]).to_list(limit)
        return {"bucket": bucket, "kind": "transactions", "items": items}
    if bucket == "rollbacks":
        items = await db.reconciliation_audit_log.find(
            {"action": "ROLLBACK", "performed_at": {"$gte": since}},
            {"_id": 0}).sort("performed_at", -1).to_list(limit)
        if cur:
            tx_ids = [i.get("bank_transaction_id") for i in items
                      if i.get("bank_transaction_id")]
            allowed = {d["id"] async for d in db.bank_transactions.find(
                {"id": {"$in": tx_ids}, "currency": cur}, {"_id": 0, "id": 1})}
            items = [i for i in items if i.get("bank_transaction_id") in allowed]
        return {"bucket": bucket, "kind": "audit", "items": items}
    if bucket == "imports":
        items = await db.bank_statement_imports.find(
            {"uploaded_at": {"$gte": since}, **({"currency": cur} if cur else {})},
            {"_id": 0, "id": 1, "original_file_name": 1, "bank_name": 1,
             "currency": 1, "uploaded_at": 1, "processing_status": 1,
             "parse_mode": 1, "total_transactions_detected": 1,
             "total_auto_matched": 1, "total_manual_review": 1,
             "total_unmatched": 1, "total_duplicates": 1}) \
            .sort("uploaded_at", -1).to_list(limit)
        return {"bucket": bucket, "kind": "imports", "items": items}
    raise HTTPException(status_code=400, detail="bucket inválido")


class RematchPayload(BaseModel):
    currency: Optional[str] = None
    import_id: Optional[str] = None


@router.post("/admin/reconciliation/rematch")
async def rematch(request: Request,
                  payload: Optional[RematchPayload] = None) -> Any:
    """iter174 — re-run matching of unresolved movements against the
    CURRENT pending orders and VIP batch items."""
    actor = await require_permission(request, "reconciliation")
    p = payload or RematchPayload()
    counts = await rematch_transactions(actor, currency=p.currency,
                                        import_id=p.import_id)
    await log_action(db, actor, "reconciliation.rematch", "reconciliation",
                     p.import_id or "all",
                     summary=(f"Reproceso de matching: {counts['scanned']} movimientos "
                              f"→ {counts['auto']} auto, {counts['review']} revisión, "
                              f"{counts['unmatched']} sin identificar"),
                     details=counts)
    return counts


class ConfirmPayload(BaseModel):
    order_id: str


@router.post("/admin/reconciliation/transactions/{tx_id}/confirm")
async def confirm_match(tx_id: str, payload: ConfirmPayload, request: Request) -> Any:
    actor = await require_permission(request, "reconciliation")
    tx = await db.bank_transactions.find_one({"id": tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    if tx["status"] in ("auto_matched", "manual_matched"):
        raise HTTPException(status_code=409, detail="Este movimiento ya está conciliado.")
    if tx["status"] == "duplicate":
        raise HTTPException(status_code=409,
                            detail="Movimiento duplicado — no puede conciliar órdenes.")
    order = await db.orders.find_one({"id": payload.order_id}, {"_id": 0})
    item = None
    if not order:
        item = await db.vip_batch_items.find_one({"id": payload.order_id}, {"_id": 0})
    if not order and not item:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if item:
        if item["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"La orden del lote ya no está pendiente (estado: {item['status']}).")
    else:
        if order["status"] == "requires_double_approval":
            raise HTTPException(
                status_code=409,
                detail="Esta orden requiere doble aprobación de un admin. "
                       "Apruébala desde la sección Órdenes.")
        if order["status"] != "pending":
            raise HTTPException(status_code=409,
                                detail=f"La orden ya no está pendiente (estado: {order['status']}).")
    other = await db.bank_transactions.find_one(
        {"matched_order_id": payload.order_id,
         "status": {"$in": ["auto_matched", "manual_matched"]}}, {"_id": 0, "id": 1})
    if other:
        raise HTTPException(status_code=409,
                            detail=f"La orden ya fue conciliada con el movimiento {other['id']}.")

    cand = next((c for c in (tx.get("candidates") or [])
                 if c["order_id"] == payload.order_id), None)
    tx["confidence_score"] = cand["score"] if cand else tx.get("confidence_score")
    matched_kind = "vip_batch_item" if item else "order"
    try:
        if item:
            await approve_batch_item_from_reconciliation(item["id"], tx, actor, auto=False)
        else:
            await approve_order_from_reconciliation(order, tx, actor, auto=False)
    except RuntimeError:
        raise HTTPException(status_code=409, detail="La orden ya no está pendiente.")
    await db.bank_transactions.update_one(
        {"id": tx_id},
        {"$set": {"status": "manual_matched", "matched_order_id": payload.order_id,
                  "matched_kind": matched_kind,
                  "match_details": cand,
                  "confidence_score": cand["score"] if cand else tx.get("confidence_score"),
                  "matched_at": iso(now_utc()), "matched_by": actor["user_id"],
                  "reviewed_by": actor["user_id"], "reviewed_at": iso(now_utc()),
                  "updated_at": iso(now_utc())}})
    await recon_audit("MANUAL_MATCHED", actor, tx=tx, order_id=payload.order_id,
                      prev_status=tx["status"], new_status="manual_matched",
                      score=(cand or {}).get("score"),
                      details=(cand or {}).get("breakdown"),
                      ip=request.client.host if request.client else None)
    return await db.bank_transactions.find_one({"id": tx_id}, {"_id": 0, "raw": 0})


class RejectPayload(BaseModel):
    note: Optional[str] = None


@router.post("/admin/reconciliation/transactions/{tx_id}/reject")
async def reject_suggestion(tx_id: str, payload: RejectPayload, request: Request) -> Any:
    actor = await require_permission(request, "reconciliation")
    tx = await db.bank_transactions.find_one({"id": tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    if tx["status"] in ("auto_matched", "manual_matched"):
        raise HTTPException(status_code=409,
                            detail="Movimiento ya conciliado — no se puede rechazar.")
    await db.bank_transactions.update_one(
        {"id": tx_id},
        {"$set": {"status": "unmatched", "candidates": [],
                  "reviewed_by": actor["user_id"], "reviewed_at": iso(now_utc()),
                  "review_note": (payload.note or "").strip() or None,
                  "updated_at": iso(now_utc())}})
    await log_action(db, actor, "reconciliation.suggestion_rejected",
                     "bank_transaction", tx_id,
                     summary="Sugerencias descartadas — movimiento sin identificar")
    await recon_audit("MATCH_REJECTED", actor, tx=tx,
                      prev_status=tx["status"], new_status="unmatched",
                      details={"note": (payload.note or "").strip() or None},
                      ip=request.client.host if request.client else None)
    return await db.bank_transactions.find_one({"id": tx_id}, {"_id": 0, "raw": 0})


@router.post("/admin/reconciliation/transactions/{tx_id}/ignore")
async def ignore_transaction(tx_id: str, payload: RejectPayload, request: Request) -> Any:
    actor = await require_permission(request, "reconciliation")
    tx = await db.bank_transactions.find_one({"id": tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    if tx["status"] in ("auto_matched", "manual_matched"):
        raise HTTPException(status_code=409,
                            detail="Movimiento ya conciliado — no se puede ignorar.")
    await db.bank_transactions.update_one(
        {"id": tx_id},
        {"$set": {"status": "ignored", "ignored_reason": "manual",
                  "review_note": (payload.note or "").strip() or None,
                  "reviewed_by": actor["user_id"],
                  "reviewed_by_name": actor.get("name") or actor.get("email"),
                  "reviewed_at": iso(now_utc()),
                  "updated_at": iso(now_utc())}})
    await log_action(db, actor, "reconciliation.ignored", "bank_transaction",
                     tx_id, summary="Movimiento marcado como ignorado")
    await recon_audit("TRANSACTION_IGNORED", actor, tx=tx,
                      prev_status=tx["status"], new_status="ignored",
                      ip=request.client.host if request.client else None)
    return await db.bank_transactions.find_one({"id": tx_id}, {"_id": 0, "raw": 0})


@router.post("/admin/reconciliation/transactions/{tx_id}/restore")
async def restore_transaction(tx_id: str, request: Request) -> Any:
    """iter179 — devuelve un movimiento ignorado a 'sin identificar' y lo
    re-evalúa de inmediato contra las órdenes/ítems pendientes actuales."""
    actor = await require_permission(request, "reconciliation")
    tx = await db.bank_transactions.find_one({"id": tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    if tx["status"] != "ignored":
        raise HTTPException(status_code=409,
                            detail="Solo se pueden restaurar movimientos ignorados.")
    if tx.get("direction") == "debit":
        raise HTTPException(status_code=409,
                            detail="Los débitos (cargos) no se concilian con órdenes.")
    await db.bank_transactions.update_one(
        {"id": tx_id},
        {"$set": {"status": "unmatched", "updated_at": iso(now_utc()),
                  "reviewed_by": None, "reviewed_at": None, "review_note": None,
                  "reviewed_by_name": None},
         "$unset": {"ignored_reason": ""}})
    await log_action(db, actor, "reconciliation.restored", "bank_transaction",
                     tx_id, summary="Movimiento restaurado desde ignorados")
    await recon_audit("TRANSACTION_RESTORED", actor, tx=tx,
                      prev_status="ignored", new_status="unmatched",
                      ip=request.client.host if request.client else None)
    try:
        await rematch_transactions(actor, currency=tx.get("currency"))
    except Exception as e:
        logger.error(f"restore rematch failed for {tx_id}: {e}")
    return await db.bank_transactions.find_one({"id": tx_id}, {"_id": 0, "raw": 0})


class RollbackPayload(BaseModel):
    reason: str


@router.post("/admin/reconciliation/transactions/{tx_id}/rollback")
async def rollback_match(tx_id: str, payload: RollbackPayload, request: Request) -> Any:
    """§25 — revert a reconciliation: unlink the movement and return the
    order to `pending`. Reason is mandatory and everything is audited."""
    actor = await require_permission(request, "reconciliation")
    reason = (payload.reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(status_code=422,
                            detail="Indica el motivo del rollback (mínimo 5 caracteres).")
    tx = await db.bank_transactions.find_one({"id": tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    if tx["status"] not in ("auto_matched", "manual_matched"):
        raise HTTPException(status_code=409, detail="Este movimiento no está conciliado.")
    order_id = tx.get("matched_order_id")
    kind = tx.get("matched_kind") or (
        "vip_batch_item" if str(order_id or "").startswith("vitem_") else "order")
    prev_tx_status = tx["status"]
    if kind == "vip_batch_item":
        item = await db.vip_batch_items.find_one({"id": order_id}, {"_id": 0}) if order_id else None
        if not item or (item.get("reconciliation") or {}).get("bank_transaction_id") != tx_id:
            raise HTTPException(status_code=409,
                                detail="La orden del lote ya no referencia este movimiento.")
        if item["status"] != "approved":
            raise HTTPException(
                status_code=409,
                detail=f"El ítem del lote está en '{item['status']}' — no se puede revertir.")
        await rollback_batch_item_from_reconciliation(item, tx_id, actor, reason)
    else:
        order = await db.orders.find_one({"id": order_id}, {"_id": 0}) if order_id else None
        if not order or (order.get("reconciliation") or {}).get("bank_transaction_id") != tx_id:
            raise HTTPException(status_code=409,
                                detail="La orden vinculada ya no referencia este movimiento.")
        if order["status"] != "approved":
            raise HTTPException(
                status_code=409,
                detail=f"La orden avanzó a '{order['status']}' — revierte su estado "
                       f"desde Órdenes antes de hacer rollback.")
        await db.orders.update_one(
            {"id": order_id, "status": "approved"},
            {"$set": {"status": "pending", "updated_at": iso(now_utc()),
                      "admin_note": f"Rollback de conciliación: {reason}"},
             "$unset": {"payment_confirmed_at": "", "payment_confirmation_source": "",
                        "bank_transaction_id": "", "reconciliation_score": "",
                        "reconciliation": ""}})
    new_status = "manual_review" if (tx.get("candidates") or []) else "unmatched"
    await db.bank_transactions.update_one(
        {"id": tx_id},
        {"$set": {"status": new_status, "matched_order_id": None,
                  "matched_kind": None,
                  "match_details": None, "matched_at": None, "matched_by": None,
                  "review_note": f"Rollback: {reason}",
                  "reviewed_by": actor["user_id"], "reviewed_at": iso(now_utc()),
                  "updated_at": iso(now_utc())}})
    await recon_audit("ROLLBACK", actor, tx=tx, order_id=order_id,
                      prev_status=prev_tx_status, new_status=new_status,
                      details={"reason": reason, "kind": kind},
                      ip=request.client.host if request.client else None)
    await log_action(db, actor, "reconciliation.rollback",
                     "vip_batch_item" if kind == "vip_batch_item" else "order",
                     order_id,
                     summary=f"Rollback de conciliación — orden vuelve a pendiente. Motivo: {reason}",
                     details={"bank_transaction_id": tx_id})
    if kind == "order":
        try:
            from services.order_events import publish_order_status_sse
            updated = await db.orders.find_one({"id": order_id}, {"_id": 0})
            await publish_order_status_sse(order_id, updated, "pending", "approved")
        except Exception:
            pass
    return await db.bank_transactions.find_one({"id": tx_id}, {"_id": 0, "raw": 0})


@router.get("/admin/reconciliation/audit")
async def reconciliation_audit_trail(request: Request,
                                     tx_id: Optional[str] = None,
                                     limit: int = 200) -> Any:
    await require_permission(request, "reconciliation")
    q: Dict[str, Any] = {}
    if tx_id:
        q["bank_transaction_id"] = tx_id
    items = await db.reconciliation_audit_log.find(q, {"_id": 0}) \
        .sort("performed_at", -1).to_list(min(max(limit, 1), 500))
    return {"items": items}


@router.get("/admin/reconciliation/orders-search")
async def search_pending_orders(request: Request, currency: str,
                                q: Optional[str] = None, limit: int = 20) -> Any:
    """Pending orders + VIP batch items for the manual-link picker."""
    await require_permission(request, "reconciliation")
    lim = min(max(limit, 1), 50)
    cur = currency.upper()
    query: Dict[str, Any] = {"status": "pending", "from_code": cur}
    import re as _re
    rx = None
    if q:
        rx = {"$regex": _re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"user_name": rx}, {"user_email": rx},
                        {"sender_name": rx}, {"id": rx},
                        {"payment_reference": rx}]
    orders = await db.orders.find(
        query, {"_id": 0, "id": 1, "user_name": 1, "user_email": 1,
                "sender_name": 1, "amount_from": 1, "from_code": 1,
                "to_code": 1, "created_at": 1, "payment_account_label": 1,
                "payment_reference": 1}) \
        .sort("created_at", -1).to_list(lim)
    for o in orders:
        o["kind"] = "order"

    # iter172 — VIP batch items (Lotes VIP) are linkable too.
    item_q: Dict[str, Any] = {
        "status": "pending",
        "$or": [{"from_code": cur},
                {"from_code": None, "currency": cur, "direction": "credit"}],
    }
    if rx:
        item_q = {"$and": [item_q, {"$or": [{"holder_name": rx}, {"id": rx},
                                            {"payment_reference": rx}]}]}
    batch_items = await db.vip_batch_items.find(
        item_q, {"_id": 0, "id": 1, "holder_name": 1, "amount": 1,
                 "currency": 1, "from_code": 1, "to_code": 1, "created_at": 1,
                 "payment_account_label": 1, "payment_reference": 1}) \
        .sort("created_at", -1).to_list(lim)
    items = orders + [{
        "kind": "vip_batch_item",
        "id": it["id"],
        "user_name": it.get("holder_name") or "",
        "user_email": "",
        "sender_name": "",
        "amount_from": it.get("amount"),
        "from_code": it.get("from_code") or it.get("currency"),
        "to_code": it.get("to_code"),
        "created_at": it.get("created_at"),
        "payment_account_label": it.get("payment_account_label"),
        "payment_reference": it.get("payment_reference") or "",
    } for it in batch_items]
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return {"items": items[:lim]}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@router.get("/admin/reconciliation/config")
async def get_reconciliation_config(request: Request) -> Any:
    await require_permission(request, "reconciliation")
    return await get_config()


@router.put("/admin/reconciliation/config")
async def update_reconciliation_config(payload: Dict[str, Any], request: Request) -> Any:
    actor = await require_permission(request, "reconciliation")
    update: Dict[str, Any] = {}
    for k in DEFAULT_CONFIG:
        if k not in payload:
            continue
        try:
            update[k] = validate_config_value(k, payload[k])
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=422, detail=str(e) or f"Valor inválido para {k}")
    if not update:
        raise HTTPException(status_code=422, detail="Nada que actualizar")
    if ("manual_review_score" in update or "auto_match_score" in update):
        cfg = await get_config()
        review = update.get("manual_review_score", cfg["manual_review_score"])
        auto = update.get("auto_match_score", cfg["auto_match_score"])
        if review >= auto:
            raise HTTPException(status_code=422,
                                detail="El umbral de revisión debe ser menor que el umbral automático.")
    await db.settings.update_one({"id": "reconciliation_config"},
                                 {"$set": update}, upsert=True)
    await log_action(db, actor, "reconciliation.config_updated", "settings",
                     "reconciliation_config", summary="Reglas de conciliación actualizadas",
                     details=update)
    return await get_config()
