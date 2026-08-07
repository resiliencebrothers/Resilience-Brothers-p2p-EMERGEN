"""iter167 — Conciliación Bancaria (bank reconciliation) admin module.

Flow (spec §4): staff uploads a statement file for a given bank/payment
account + currency → file stored (R2 or Mongo fallback) → background pipeline
extracts, normalizes, fingerprints, dedupes and matches transactions against
pending client orders → auto-match / manual review / unmatched.

All endpoints gated by the dedicated `reconciliation` permission.
"""
import logging
import uuid
from typing import Any, Dict, Optional

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
            fp = fingerprint(imp.get("bank_account_id") or "",
                             t["transaction_date"], t["amount"],
                             imp["currency"], t.get("reference") or t.get("description") or "",
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
        if errors > 0 and txs:
            status = "partially_processed"
        elif not txs:
            status = "failed" if errors else "processed"
        await db.bank_statement_imports.update_one(
            {"id": import_id},
            {"$set": {
                "processing_status": status,
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
async def list_imports(request: Request, limit: int = 100) -> Any:
    await require_permission(request, "reconciliation")
    items = await db.bank_statement_imports.find({}, {"_id": 0}) \
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


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------
@router.get("/admin/reconciliation/transactions")
async def list_transactions(request: Request, import_id: Optional[str] = None,
                            status: Optional[str] = None,
                            limit: int = 300) -> Any:
    await require_permission(request, "reconciliation")
    q: Dict[str, Any] = {}
    if import_id:
        q["statement_import_id"] = import_id
    if status in TX_STATUSES:
        q["status"] = status
    items = await db.bank_transactions.find(q, {"_id": 0, "raw": 0}) \
        .sort([("transaction_date", -1), ("created_at", -1)]) \
        .to_list(min(max(limit, 1), 1000))
    return {"items": items}


@router.get("/admin/reconciliation/summary")
async def reconciliation_summary(request: Request) -> Any:
    await require_permission(request, "reconciliation")
    pipeline = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    counts = {r["_id"]: r["n"] async for r in db.bank_transactions.aggregate(pipeline)}
    return {
        "manual_review": counts.get("manual_review", 0),
        "unmatched": counts.get("unmatched", 0),
        "auto_matched": counts.get("auto_matched", 0),
        "manual_matched": counts.get("manual_matched", 0),
        "duplicate": counts.get("duplicate", 0),
        "ignored": counts.get("ignored", 0),
        "error": counts.get("error", 0),
    }


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
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
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
    try:
        await approve_order_from_reconciliation(order, tx, actor, auto=False)
    except RuntimeError:
        raise HTTPException(status_code=409, detail="La orden ya no está pendiente.")
    await db.bank_transactions.update_one(
        {"id": tx_id},
        {"$set": {"status": "manual_matched", "matched_order_id": payload.order_id,
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
                  "reviewed_by": actor["user_id"], "reviewed_at": iso(now_utc()),
                  "updated_at": iso(now_utc())}})
    await log_action(db, actor, "reconciliation.ignored", "bank_transaction",
                     tx_id, summary="Movimiento marcado como ignorado")
    await recon_audit("TRANSACTION_IGNORED", actor, tx=tx,
                      prev_status=tx["status"], new_status="ignored",
                      ip=request.client.host if request.client else None)
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
    order = await db.orders.find_one({"id": order_id}, {"_id": 0}) if order_id else None
    if not order or (order.get("reconciliation") or {}).get("bank_transaction_id") != tx_id:
        raise HTTPException(status_code=409,
                            detail="La orden vinculada ya no referencia este movimiento.")
    if order["status"] != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"La orden avanzó a '{order['status']}' — revierte su estado "
                   f"desde Órdenes antes de hacer rollback.")
    prev_tx_status = tx["status"]
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
                  "match_details": None, "matched_at": None, "matched_by": None,
                  "review_note": f"Rollback: {reason}",
                  "reviewed_by": actor["user_id"], "reviewed_at": iso(now_utc()),
                  "updated_at": iso(now_utc())}})
    await recon_audit("ROLLBACK", actor, tx=tx, order_id=order_id,
                      prev_status=prev_tx_status, new_status=new_status,
                      details={"reason": reason},
                      ip=request.client.host if request.client else None)
    await log_action(db, actor, "reconciliation.rollback", "order", order_id,
                     summary=f"Rollback de conciliación — orden vuelve a pendiente. Motivo: {reason}",
                     details={"bank_transaction_id": tx_id})
    try:
        from routes.admin import _publish_order_status_sse
        updated = await db.orders.find_one({"id": order_id}, {"_id": 0})
        await _publish_order_status_sse(order_id, updated, "pending", "approved")
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
    """Pending orders for the manual-link picker."""
    await require_permission(request, "reconciliation")
    query: Dict[str, Any] = {"status": "pending", "from_code": currency.upper()}
    if q:
        import re as _re
        rx = {"$regex": _re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"user_name": rx}, {"user_email": rx},
                        {"sender_name": rx}, {"id": rx}]
    items = await db.orders.find(
        query, {"_id": 0, "id": 1, "user_name": 1, "user_email": 1,
                "sender_name": 1, "amount_from": 1, "from_code": 1,
                "to_code": 1, "created_at": 1, "payment_account_label": 1}) \
        .sort("created_at", -1).to_list(min(max(limit, 1), 50))
    return {"items": items}


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
