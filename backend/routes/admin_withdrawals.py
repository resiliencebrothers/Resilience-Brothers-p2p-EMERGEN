"""Admin router — withdrawals (VIP client payouts) management.

Extracted from routes/admin.py during the iter39 split. Owns:
- GET  /admin/withdrawals       (scoped list)
- PUT  /admin/withdrawals/{id}/status (approve/pay/reject + evidence)

The validation/refund/evidence helpers are private to this module.
"""
import re
import logging
from fastapi import APIRouter, HTTPException, Request
from typing import Optional, Any, Dict

from db_client import db
from auth_utils import (
    require_permission, iso, now_utc,
    _enforce_employee_currency_scope, _enforce_totp_step_up,
)
from services.proof_upload import maybe_upload_proof
from audit_log import log_action

logger = logging.getLogger(__name__)


router = APIRouter(tags=["Admin"])


@router.get("/admin/withdrawals")
async def all_withdrawals(request: Request,
                          status: Optional[str] = None,
                          user_q: Optional[str] = None,
                          currency: Optional[str] = None) -> Any:
    actor = await require_permission(request, "withdrawals")
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if currency:
        q["currency"] = currency.upper()
    if user_q:
        rx = {"$regex": re.escape(user_q), "$options": "i"}
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


async def _reconcile_balance_on_status_change(withdrawal: dict, new_status: str,
                                                update_doc: dict) -> None:
    """SEC hardening (auditoría 28/7/2026) — idempotent balance reconciliation.

    A `balance_refunded` flag on the withdrawal makes refunds safe against any
    status flip sequence (e.g. rejected→pending→rejected no longer double-credits):
      - Entering 'rejected' while NOT yet refunded → credit the balance back once.
      - Leaving 'rejected' while previously refunded → re-debit (the payout is
        active again, so the funds must not sit in the balance too).
    The flag is written into `update_doc` so it persists atomically with status.
    """
    already_refunded = bool(withdrawal.get("balance_refunded"))
    currency = withdrawal.get("currency", "USD")
    amount = float(withdrawal.get("amount_usd") or 0.0)
    was_rejected = withdrawal["status"] == "rejected"
    entering_rejected = new_status == "rejected" and not was_rejected
    leaving_rejected = was_rejected and new_status != "rejected"
    if entering_rejected and not already_refunded:
        await db.users.update_one(
            {"user_id": withdrawal["user_id"]},
            {"$inc": {f"vip_balances.{currency}": amount}},
        )
        update_doc["balance_refunded"] = True
    elif leaving_rejected and already_refunded:
        await db.users.update_one(
            {"user_id": withdrawal["user_id"]},
            {"$inc": {f"vip_balances.{currency}": -amount}},
        )
        update_doc["balance_refunded"] = False


def _collect_payout_evidence(payload: dict, update_doc: dict,
                              withdrawal: Optional[dict] = None) -> None:
    """Persist optional payout proof image + tx hash on the update document.

    iter55.19h: when the withdrawal declares a crypto_network (TRC20/BEP20)
    we also validate the tx_hash format against that network — same "no
    coinciden" guard as the address at creation time, but for the tx hash
    the operator pastes at payout time.
    """
    proof = payload.get("payout_proof_image")
    if proof:
        update_doc["payout_proof_image"] = maybe_upload_proof(proof, "withdrawals") or proof
    tx_hash = payload.get("payout_tx_hash")
    if tx_hash:
        tx_hash = tx_hash.strip()
        network = (withdrawal or {}).get("crypto_network") or ""
        method = (withdrawal or {}).get("method") or ""
        if method == "crypto" and network:
            from services.crypto_networks import (
                is_tx_hash_valid_for_network, tx_hash_mismatch_reason,
            )
            if not is_tx_hash_valid_for_network(tx_hash, network):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "TX_HASH_NETWORK_MISMATCH",
                        "message": tx_hash_mismatch_reason(tx_hash, network),
                        "network": network,
                    },
                )
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
    actor = await require_permission(request, "withdrawals")
    new_status = payload.get("status")
    if new_status not in ("approved", "paid", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="status inválido")
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="gestionar retiro")
    w = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(status_code=404, detail="No encontrado")
    # iter153 — client-cancelled withdrawals are terminal: the funds already
    # returned to the client's balance, so staff must not resurrect them.
    if w["status"] == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="Este retiro fue cancelado por el cliente y no puede modificarse.",
        )
    _assert_paid_lock(actor, w, new_status)
    _enforce_employee_currency_scope(actor, w.get("currency"))
    update_doc = {"status": new_status, "admin_note": payload.get("admin_note", "")}
    # iter153 — per-status timestamps feed the client-facing progress timeline.
    if new_status != w["status"] and new_status in ("approved", "paid", "rejected"):
        update_doc[f"{new_status}_at"] = iso(now_utc())
    await _reconcile_balance_on_status_change(w, new_status, update_doc)
    _collect_payout_evidence(payload, update_doc, w)
    _validate_paid_evidence(w, update_doc, new_status)
    await db.withdrawals.update_one({"id": wid}, {"$set": update_doc})
    updated = await db.withdrawals.find_one({"id": wid}, {"_id": 0})

    # iter97 — SSE push to the withdrawal owner so /dashboard/vip
    # reflects the new status + refreshes balance immediately.
    # iter98 — ALSO push to admin/employee broadcast subscribers so the
    # row is removed from /admin/queue when the withdrawal leaves
    # pending status.
    try:
        from services.live_bus import publish as live_publish
        target_uid = updated.get("user_id") if isinstance(updated, dict) else None
        if new_status != w["status"]:
            status_payload = {
                "withdrawal_id": wid,
                "status": new_status,
                "prev_status": w["status"],
                "amount_usd": updated.get("amount_usd"),
                "currency": updated.get("currency"),
            }
            if target_uid:
                await live_publish("withdrawal_status_changed", status_payload,
                                   user_id=target_uid)
                await live_publish("balance_updated", {"reason": "withdrawal", "withdrawal_id": wid},
                                   user_id=target_uid)
                await live_publish("ledger_changed",
                                   {"reason": "withdrawal", "withdrawal_id": wid,
                                    "user_id": target_uid},
                                   roles=("admin", "employee"))
            await live_publish("withdrawal_status_changed", status_payload,
                               roles=("admin", "employee"))
    except Exception:
        pass

    # iter155 — push + in-app notification to the withdrawal owner for each
    # step (approved = "retirando/en curso", paid = "retiro exitoso",
    # rejected = terminal + refund note).
    if new_status != w["status"] and new_status in ("approved", "paid", "rejected"):
        try:
            from routes.notifications import notify_user_withdrawal_step
            await notify_user_withdrawal_step(
                updated, new_status, note=payload.get("admin_note", ""),
            )
        except Exception as e:
            logger.error(f"withdrawal {new_status} push failed: {e}")

    # iter55.23 — audit trail. Without this, "quién rechazó este retiro?" is
    # unanswerable from the audit log (the endpoint used to be silent). We
    # log the actor + before/after status + amount + method + user affected
    # so the operator's action is always traceable.
    if new_status != w["status"]:
        await log_action(
            db, actor, f"withdrawal.{new_status}", "withdrawal", wid,
            summary=(
                f"Retiro {w.get('method','?')} "
                f"{w.get('amount_usd','?')} USD ({w.get('currency','?')}) "
                f"→ {new_status}"
            ),
            details={
                "prev": w["status"],
                "new": new_status,
                "user_id": w.get("user_id"),
                "amount_usd": w.get("amount_usd"),
                "currency": w.get("currency"),
                "method": w.get("method"),
                "admin_note": payload.get("admin_note", ""),
                "payout_tx_hash": update_doc.get("payout_tx_hash"),
            },
        )
    return updated
