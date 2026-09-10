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
    else:
        # iter254 — los docs transitorios del protocolo de creación no son
        # retiros reales para el panel.
        q["status"] = {"$nin": ["initializing", "failed_init"]}
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
    # iter208 — attach courier delivery status so the frontend can disable
    # the "Entregado" button until the courier confirms the delivery.
    cash_ids = [d["id"] for d in docs
                if d.get("method") == "cash" and d.get("status") != "paid"]
    if cash_ids:
        jobs = await db.deliveries.find(
            {"kind": "withdrawal", "ref_id": {"$in": cash_ids},
             "status": {"$ne": "cancelled"}},
            {"_id": 0, "ref_id": 1, "status": 1, "courier_id": 1,
             "courier_name": 1},
        ).to_list(len(cash_ids))
        by_ref = {j["ref_id"]: j for j in jobs}
        for d in docs:
            if d["id"] in by_ref:
                j = by_ref[d["id"]]
                d["courier_delivery_status"] = j.get("status")
                d["courier_delivery_courier_name"] = j.get("courier_name") or ""
                d["courier_delivery_assigned"] = bool(j.get("courier_id"))
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


def _raise_withdrawal_race() -> None:
    raise HTTPException(
        status_code=409,
        detail="El retiro cambió de estado mientras editabas; recarga la página.")


async def _claim_transition_with_effects(w: dict, new_status: str,
                                         sets: dict) -> None:
    """iter256(S01) — máquina de estados del retiro con efectos VINCULADOS.

    El estado nuevo y la intención de su efecto de saldo (reembolso al entrar
    a 'rejected'; re-débito al salir) se publican en UN único update
    condicional sobre el estado anterior. Consecuencias:
      - dos transiciones simultáneas nunca se pisan (el perdedor recibe 409);
      - ninguna petición puede leer el estado nuevo sin que la intención de
        dinero ya esté persistida (marker/plan) — se acabó el
        "aprobado y reembolsado a la vez";
      - un crash tras el claim deja marker/plan que completa el healer
        (heal_pending_credits / heal_initializing_ops), nunca se pierde el
        reembolso;
      - el abono es idempotente por op_id (nunca se duplica).
    """
    wid = w["id"]
    currency = w.get("currency", "USD")
    # iter257(D11) — si el retiro arrastra un reembolso pendiente (marker de
    # un crash anterior), se LIQUIDA primero (idempotente) y se relee el doc:
    # ninguna transición puede pisar ni perder esa obligación.
    if w.get("credit_pending"):
        from services.credit_recovery import apply_and_clear
        await apply_and_clear("withdrawals", wid, w["credit_pending"])
        w = await db.withdrawals.find_one({"id": wid}, {"_id": 0}) or w
    # iter198 — any charged courier fee travels with the refund/re-debit.
    amount = (float(w.get("amount_usd") or 0.0)
              + float(w.get("courier_fee_currency_amount") or 0.0))
    was_rejected = w["status"] == "rejected"
    entering_rejected = new_status == "rejected" and not was_rejected
    leaving_rejected = was_rejected and new_status != "rejected"
    if entering_rejected:
        from services.credit_recovery import pending_marker, apply_and_clear
        marker = pending_marker(w["user_id"], currency, amount,
                                "withdrawal-refund")
        claim = await db.withdrawals.update_one(
            {"id": wid, "status": w["status"],
             "balance_refunded": {"$ne": True},
             "redebit_pending": {"$exists": False}},
            {"$set": {**sets, "balance_refunded": True,
                      "credit_pending": marker}})
        if claim.matched_count == 0:
            # ¿ya reembolsado por otra vía (p.ej. carrera con un rechazo
            # previo cuyo re-débito no aplicó)? — transición sin dinero.
            claim = await db.withdrawals.update_one(
                {"id": wid, "status": w["status"], "balance_refunded": True,
                 "redebit_pending": {"$exists": False}},
                {"$set": sets})
            if claim.matched_count == 0:
                _raise_withdrawal_race()
            return
        await apply_and_clear("withdrawals", wid, marker)
        return
    if leaving_rejected:
        import uuid as _uuid
        op = f"withdrawal-redebit:{wid}:{_uuid.uuid4().hex[:8]}"
        claim = await db.withdrawals.update_one(
            {"id": wid, "status": "rejected", "balance_refunded": True,
             "credit_pending": {"$exists": False}},
            {"$set": {**sets, "balance_refunded": False,
                      "redebit_pending": {
                          "op_id": op, "amount": round(amount, 8),
                          "currency": currency, "at": iso(now_utc())}}})
        if claim.matched_count == 0:
            # rechazado legado sin reembolso registrado → sin re-débito.
            claim = await db.withdrawals.update_one(
                {"id": wid, "status": "rejected",
                 "balance_refunded": {"$ne": True},
                 "credit_pending": {"$exists": False}},
                {"$set": sets})
            if claim.matched_count == 0:
                _raise_withdrawal_race()
            return
        # iter257(D11) — re-débito por el helper duradero (guard atómico de
        # saldo + op_id idempotente + log credit_ops), no un $inc artesanal.
        from services.balances import debit_balance_idempotent
        st = await debit_balance_idempotent(w["user_id"], currency, amount, op)
        if st == "insufficient":
            await db.withdrawals.update_one(
                {"id": wid, "redebit_pending.op_id": op},
                {"$set": {"status": "rejected", "balance_refunded": True},
                 "$unset": {"redebit_pending": ""}})
            raise HTTPException(
                status_code=409,
                detail=(f"El cliente ya no tiene {amount} {currency} "
                        "disponibles (gastó el reembolso); no se puede "
                        "reactivar este retiro."))
        await db.withdrawals.update_one(
            {"id": wid, "redebit_pending.op_id": op},
            {"$unset": {"redebit_pending": ""}})
        return
    claim = await db.withdrawals.update_one(
        {"id": wid, "status": w["status"]}, {"$set": sets})
    if claim.matched_count == 0:
        _raise_withdrawal_race()


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


async def _assert_cash_courier_ready(withdrawal: dict, new_status: str) -> None:
    """iter205 — candados anti-pérdida para retiros CASH antes de 'paid'
    (entregado = el mensajero YA entregó el dinero al cliente):
      1. La tarifa debe estar resuelta: cobrada, gratis por umbral, o
         recogida en oficina (sin mensajero).
      2. Debe existir el trabajo de mensajería y el mensajero debe haberlo
         marcado como entregado (delivered/confirmed)."""
    if new_status != "paid" or withdrawal["status"] == "paid" \
            or withdrawal.get("method") != "cash":
        return
    if (withdrawal.get("cash_delivery_mode") or "courier") == "office_pickup":
        return
    from services.courier_fee import quote_courier_fee
    cq = await quote_courier_fee((withdrawal.get("currency") or "USD").upper(),
                                  float(withdrawal.get("amount_usd") or 0.0))
    if not cq["enabled"]:
        return
    fee_charged = bool(withdrawal.get("courier_fee_charged_at")) \
        and float(withdrawal.get("courier_fee_usdt") or 0) > 0
    if not cq["free"] and not fee_charged:
        raise HTTPException(
            status_code=409,
            detail=("Mensajería sin cobrar: usa el botón 'Mensajería' para "
                    "cobrar el costo de la entrega antes de marcar este retiro "
                    "como entregado."))
    job = await db.deliveries.find_one(
        {"kind": "withdrawal", "ref_id": withdrawal["id"],
         "status": {"$ne": "cancelled"}}, {"_id": 0})
    if not job:
        raise HTTPException(
            status_code=409,
            detail=("No existe trabajo de mensajería para este retiro. "
                    "Créalo en la sección Mensajería (o cobra la tarifa) y "
                    "espera a que el mensajero confirme la entrega."))
    if job.get("status") not in ("delivered", "confirmed"):
        if not job.get("courier_id"):
            raise HTTPException(
                status_code=409,
                detail=("Ningún mensajero ha tomado esta entrega todavía. "
                        "Asigna un mensajero o espera a que uno la acepte y "
                        "la marque como entregada."))
        raise HTTPException(
            status_code=409,
            detail=(f"El mensajero {job.get('courier_name') or ''} aún no "
                    "marcó esta entrega como realizada. Debe confirmarla desde "
                    "su panel antes de marcar el retiro como entregado."))


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
    # iter256(S01) — los docs transitorios del protocolo de creación no son
    # operables ni siquiera por llamada directa del personal.
    if w["status"] in ("initializing", "failed_init"):
        raise HTTPException(
            status_code=409,
            detail="Este retiro no es operable (creación incompleta o revertida).",
        )
    _assert_paid_lock(actor, w, new_status)
    _enforce_employee_currency_scope(actor, w.get("currency"))
    update_doc = {"admin_note": payload.get("admin_note", "")}
    # iter153 — per-status timestamps feed the client-facing progress timeline.
    status_sets = {"status": new_status}
    if new_status != w["status"] and new_status in ("approved", "paid", "rejected"):
        status_sets[f"{new_status}_at"] = iso(now_utc())
    # iter250 — TODAS las validaciones (comprobante, tx hash, mensajería,
    # cuenta de origen) corren ANTES de tocar el saldo: si algo falla, la
    # operación devuelve error sin haber descontado ni reembolsado nada.
    _collect_payout_evidence(payload, update_doc, w)
    _validate_paid_evidence(w, update_doc, new_status)
    await _assert_cash_courier_ready(w, new_status)
    # iter194/195 — "paid from account" attribution: explicit staff choice
    # wins; otherwise auto-attribute (cash → company cash box; single active
    # account for the currency → that account).
    if new_status == "paid":
        from services.fund_accounts import (
            resolve_fund_account, auto_paid_from_account,
        )
        acc_id = (payload.get("paid_from_account_id") or "").strip()
        if acc_id:
            acc = await resolve_fund_account(acc_id)
            if not acc:
                raise HTTPException(status_code=400, detail="Cuenta de origen no encontrada")
            update_doc["paid_from_account_id"] = acc_id
            update_doc["paid_from_account_label"] = acc["label"]
        else:
            acc = await auto_paid_from_account(w.get("currency"), w.get("method"))
            if acc:
                update_doc["paid_from_account_id"] = acc["id"]
                update_doc["paid_from_account_label"] = acc["label"]
    # iter256(S01) — la transición de estado Y su intención de efecto de saldo
    # (reembolso/re-débito) se reclaman en UN único update atómico; los campos
    # de evidencia/nota viajan en el mismo claim. Quien pierde la carrera
    # recibe 409 y un crash a mitad lo completa el healer.
    await _claim_transition_with_effects(w, new_status,
                                         {**status_sets, **update_doc})
    updated = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    # iter205 — un retiro rechazado cancela su trabajo de mensajería activo.
    if new_status == "rejected" and w["status"] != "rejected":
        try:
            from services.deliveries import cancel_active_delivery
            await cancel_active_delivery("withdrawal", wid,
                                         actor_id=actor.get("user_id"),
                                         note="retiro rechazado")
        except Exception as e:
            logger.error(f"delivery cancel failed: {e}")

    await _post_status_side_effects(w, updated, new_status, payload, actor, wid)
    # iter215 — cerrar el ciclo: si el admin marca 'Entregado' (paid) un
    # retiro cash cuya entrega ya fue marcada 'delivered' por el mensajero,
    # confirmar la entrega automáticamente (acredita su parte). El TOTP de
    # esta acción ya fue verificado arriba.
    if new_status == "paid" and w.get("method") == "cash":
        try:
            job = await db.deliveries.find_one(
                {"kind": "withdrawal", "ref_id": wid, "status": "delivered"},
                {"_id": 0})
            if job:
                from services.deliveries import do_confirm_delivery
                await do_confirm_delivery(job, actor)
        except Exception as e:
            logger.error(f"delivery confirm after paid failed: {e}")
    return updated


async def _post_status_side_effects(w: dict, updated: dict, new_status: str,
                                    payload: dict, actor: dict, wid: str) -> None:
    """SSE + push/in-app + email + audit tras un cambio de estado. Compartido
    entre el endpoint PUT /status y la sincronización automática al confirmar
    la entrega de mensajería (iter209b)."""
    # V02 — retiro de CLIENTE pagado desde la cuenta de caja → salida física
    # en la Caja de Efectivo (idempotente; el backfill periódico lo sana).
    if new_status == "paid" and isinstance(updated, dict):
        try:
            from services.cash_box_sync import (
                mirror_client_withdrawal_to_cash_box,
            )
            mov_id = await mirror_client_withdrawal_to_cash_box(updated)
            if mov_id:
                updated["cash_box_movement_id"] = mov_id
        except Exception as e:  # noqa: BLE001 — el backfill lo sana
            logger.error(f"espejo de retiro de cliente en caja falló: {e}")
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

    # iter196 — email the owner at the two lifecycle checkpoints they care
    # about: `approved` ("en proceso") and `paid` ("exitoso"). Rejections
    # stay push+in-app only; a rejected email is intentionally not sent to
    # avoid confusion with the refund notification already delivered above.
    if new_status != w["status"] and new_status in ("approved", "paid"):
        try:
            target = await db.users.find_one(
                {"user_id": updated.get("user_id")},
                {"_id": 0, "email": 1, "name": 1, "preferred_language": 1},
            )
            if target and target.get("email"):
                from email_service import notify_withdrawal_in_progress, notify_withdrawal_paid
                if new_status == "approved":
                    notify_withdrawal_in_progress(updated, target)
                else:
                    notify_withdrawal_paid(updated, target)
        except Exception as e:
            logger.error(f"withdrawal {new_status} email failed: {e}")

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
                "payout_tx_hash": updated.get("payout_tx_hash"),
            },
        )


async def mark_paid_from_delivery(wid: str, actor: dict) -> Optional[dict]:
    """iter209b — Al confirmar la entrega de mensajería (TOTP ya verificado),
    el retiro cash vinculado se marca como 'paid' automáticamente para que
    Depósitos y Retiros no quede en 'pendiente'. Acción de sistema: sin
    re-chequeo de scope de moneda ni evidencia (cash no la requiere)."""
    w = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    if not w or w.get("status") in ("paid", "rejected", "cancelled"):
        return None
    update_doc = {
        "status": "paid",
        "paid_at": iso(now_utc()),
        "admin_note": w.get("admin_note") or "Auto: entrega de mensajería confirmada",
    }
    from services.fund_accounts import auto_paid_from_account
    acc = await auto_paid_from_account(w.get("currency"), w.get("method"))
    if acc:
        update_doc["paid_from_account_id"] = acc["id"]
        update_doc["paid_from_account_label"] = acc["label"]
    r = await db.withdrawals.update_one(
        {"id": wid, "status": w["status"]}, {"$set": update_doc})
    if r.modified_count == 0:
        return None
    updated = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    await _post_status_side_effects(
        w, updated, "paid",
        {"admin_note": "Auto: entrega de mensajería confirmada"}, actor, wid)
    return updated


@router.post("/admin/withdrawals/{wid}/courier-fee")
async def set_courier_fee(wid: str, payload: dict, request: Request) -> Any:
    """iter198 — charge (or update/annul with km=0) the courier fee of a cash
    withdrawal. Fee = km × rate (USDT/km from settings.global), converted to
    the withdrawal currency and deducted from the client's balance SEPARATELY
    from the withdrawal amount. Free above `courier_free_min_usdt`."""
    actor = await require_permission(request, "withdrawals")
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="cobro de mensajería")
    w = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(status_code=404, detail="No encontrado")
    if w.get("method") != "cash":
        raise HTTPException(
            status_code=400,
            detail="El cobro de mensajería solo aplica a retiros en efectivo.")
    if w.get("status") in ("rejected", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail="Este retiro está en un estado terminal — no se puede cobrar mensajería.")
    _enforce_employee_currency_scope(actor, w.get("currency"))
    from services.courier_fee import (
        parse_km_payload, price_charge_or_raise,
        price_charge_municipality_or_raise,
    )
    currency = (w.get("currency") or "USD").upper()
    muni_key = (payload.get("municipality") or "").strip()
    muni_name = None
    if muni_key:
        # iter211 — cobro por tarifa fija de municipio (mapa falló).
        km = 0.0
        q, fee_usdt, fee_cur, muni = await price_charge_municipality_or_raise(
            muni_key, currency, float(w.get("amount_usd") or 0.0),
            op_label="Este retiro")
        muni_name = muni["municipality"]
    else:
        km = parse_km_payload(payload)
        q, fee_usdt, fee_cur = await price_charge_or_raise(
            km, currency, float(w.get("amount_usd") or 0.0), op_label="Este retiro")
    prev_fee_cur = float(w.get("courier_fee_currency_amount") or 0.0)
    delta = round(fee_cur - prev_fee_cur, 2)
    if delta > 0:
        owner = await db.users.find_one({"user_id": w["user_id"]},
                                        {"_id": 0, "vip_balances": 1})
        bal = float(((owner or {}).get("vip_balances") or {}).get(currency) or 0.0)
        if bal < delta:
            raise HTTPException(
                status_code=400,
                detail=(f"Saldo insuficiente del cliente ({bal} {currency}) "
                        f"para cubrir la mensajería ({delta} {currency})."))
        # iter248 — débito atómico (guard de saldo en la misma operación).
        from services.balances import decrement_balance
        await decrement_balance(w["user_id"], currency, delta)
    elif delta < 0:
        await db.users.update_one(
            {"user_id": w["user_id"]},
            {"$inc": {f"vip_balances.{currency}": -delta}},
        )
    update_doc = {
        "courier_km": km,
        "courier_fee_usdt": fee_usdt,
        "courier_fee_currency_amount": fee_cur,
        "courier_fee_currency": currency,
        "courier_municipality": muni_name,
        "courier_fee_charged_at": iso(now_utc()) if fee_usdt > 0 else None,
        "courier_fee_charged_by": actor.get("user_id"),
        "courier_rate_snapshot": q["rate_usdt_per_km"],
        "courier_min_fee_snapshot": q["min_fee_usdt"],
    }
    await db.withdrawals.update_one({"id": wid}, {"$set": update_doc})
    updated = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
    # iter199 — keep the courier delivery job in sync with this charge.
    try:
        from services.deliveries import upsert_delivery_for_charge
        await upsert_delivery_for_charge("withdrawal", updated or w, km=km,
                                         fee_usdt=fee_usdt,
                                         actor_id=actor.get("user_id"))
    except Exception as e:
        logger.error(f"delivery sync failed: {e}")
    await log_action(
        db, actor, "withdrawal.courier_fee", "withdrawal", wid,
        summary=(f"Mensajería {km} km → {fee_usdt} USDT "
                 f"({fee_cur} {currency}) en retiro {wid[:8]}"),
        details={"km": km, "fee_usdt": fee_usdt, "fee_currency_amount": fee_cur,
                 "currency": currency, "prev_fee_currency_amount": prev_fee_cur,
                 "delta": delta, "user_id": w.get("user_id")},
    )
    try:
        from routes.notifications import _insert_notification
        if fee_usdt > 0:
            title = "Costo de mensajería aplicado"
            msg = (f"Se descontó {fee_cur} {currency} (≈ {fee_usdt} USDT · {km} km) "
                   f"de tu saldo por la entrega en efectivo del retiro #{wid[:8]}.")
        else:
            title = "Cobro de mensajería anulado"
            msg = (f"Se devolvió {abs(delta)} {currency} a tu saldo: el cobro de "
                   f"mensajería del retiro #{wid[:8]} fue anulado.")
        await _insert_notification(recipient_user_id=w["user_id"], type="courier_fee",
                                   title=title, message=msg,
                                   data={"withdrawal_id": wid, "km": km,
                                         "fee_usdt": fee_usdt})
    except Exception as e:
        logger.error(f"courier fee notification failed: {e}")
    try:
        from services.live_bus import publish as live_publish
        await live_publish("balance_updated",
                           {"reason": "courier_fee", "withdrawal_id": wid},
                           user_id=w["user_id"])
    except Exception:
        pass
    return updated


# Registro del handler de liquidación (rompe el ciclo services → routes).
from services.delivery_settlement import register_settlement_handler as _reg_settlement  # noqa: E402
_reg_settlement("withdrawal", mark_paid_from_delivery)
