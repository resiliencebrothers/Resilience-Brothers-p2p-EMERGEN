"""Admin router — withdrawals (VIP client payouts) management.

Extracted from routes/admin.py during the iter39 split. Owns:
- GET  /admin/withdrawals       (scoped list)
- PUT  /admin/withdrawals/{id}/status (approve/pay/reject + evidence)

The validation/refund/evidence helpers are private to this module.
"""
from fastapi import APIRouter, HTTPException, Request
from typing import Optional, Any, Dict

from db_client import db
from auth_utils import (
    require_staff,
    _enforce_employee_currency_scope, _enforce_totp_step_up,
)
from services.proof_upload import maybe_upload_proof


router = APIRouter(tags=["Admin"])


@router.get("/admin/withdrawals")
async def all_withdrawals(request: Request,
                          status: Optional[str] = None,
                          user_q: Optional[str] = None,
                          currency: Optional[str] = None) -> Any:
    actor = await require_staff(request)
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if currency:
        q["currency"] = currency.upper()
    if user_q:
        rx = {"$regex": user_q, "$options": "i"}
        q["$or"] = [{"user_name": rx}, {"user_email": rx}]
    if actor.get("role") == "employee":
        allowed = actor.get("allowed_currencies") or []
        if allowed:
            if "currency" in q:
                if q["currency"] not in allowed:
                    return []
            else:
                q["currency"] = {"$in": allowed}
    docs = await db.withdrawals.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


def _assert_paid_lock(actor: dict, withdrawal: dict, new_status: str) -> None:
    """Block non-admins from un-marking an already-paid withdrawal."""
    if (withdrawal["status"] == "paid"
            and new_status != "paid"
            and actor.get("role") != "admin"):
        raise HTTPException(
            status_code=403,
            detail="Este retiro ya fue entregado. Solo un admin puede modificarlo.",
        )


async def _refund_balance_on_reject(withdrawal: dict, new_status: str) -> None:
    """Restore the VIP balance when a withdrawal moves into 'rejected'."""
    if new_status != "rejected" or withdrawal["status"] == "rejected":
        return
    refund_currency = withdrawal.get("currency", "USD")
    await db.users.update_one(
        {"user_id": withdrawal["user_id"]},
        {"$inc": {f"vip_balances.{refund_currency}": withdrawal["amount_usd"]}},
    )


def _collect_payout_evidence(payload: dict, update_doc: dict) -> None:
    """Persist optional payout proof image + tx hash on the update document."""
    proof = payload.get("payout_proof_image")
    if proof:
        update_doc["payout_proof_image"] = maybe_upload_proof(proof, "withdrawals") or proof
    tx_hash = payload.get("payout_tx_hash")
    if tx_hash:
        update_doc["payout_tx_hash"] = tx_hash


def _validate_paid_evidence(withdrawal: dict, update_doc: dict, new_status: str) -> None:
    """When marking as paid, ensure the required payout artefact is present."""
    if new_status != "paid" or withdrawal["status"] == "paid":
        return
    method = withdrawal.get("method")
    existing_proof = withdrawal.get("payout_proof_image") or update_doc.get("payout_proof_image")
    if method == "transfer" and not existing_proof:
        raise HTTPException(
            status_code=400,
            detail="Adjunta la captura de la transferencia realizada al cliente antes de marcar como entregado",
        )
    if method == "crypto":
        existing_hash = withdrawal.get("payout_tx_hash") or update_doc.get("payout_tx_hash")
        if not existing_hash and not existing_proof:
            raise HTTPException(
                status_code=400,
                detail="Adjunta hash de transacción y/o captura del envío antes de marcar como entregado",
            )


@router.put("/admin/withdrawals/{wid}/status")
async def update_withdrawal(wid: str, payload: dict, request: Request) -> Any:
    actor = await require_staff(request)
    new_status = payload.get("status")
    if new_status not in ("approved", "paid", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="status inválido")
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="gestionar retiro")
    w = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(status_code=404, detail="No encontrado")
    _assert_paid_lock(actor, w, new_status)
    _enforce_employee_currency_scope(actor, w.get("currency"))
    await _refund_balance_on_reject(w, new_status)
    update_doc = {"status": new_status, "admin_note": payload.get("admin_note", "")}
    _collect_payout_evidence(payload, update_doc)
    _validate_paid_evidence(w, update_doc, new_status)
    await db.withdrawals.update_one({"id": wid}, {"$set": update_doc})
    return await db.withdrawals.find_one({"id": wid}, {"_id": 0})
