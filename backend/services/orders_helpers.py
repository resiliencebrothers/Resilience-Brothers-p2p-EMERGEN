"""Orders — domain models + workflow helpers extracted from server.py during
iter33 refactor. Pure helpers used by routes/orders.py (client creation) and
routes/admin.py (status transitions, revenue computation).
"""
import logging
import uuid
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import (
    now_utc, iso,
    _enforce_employee_currency_scope, _enforce_totp_step_up,
)
from admin_alerts import notify_all_admins, get_vip_threshold
from email_service import notify_order_approved, notify_order_rejected
from push_service import (
    send_push,
    build_order_approved_payload,
    build_order_rejected_payload,
    build_order_completed_payload,
)

from services.balances import (
    compute_total_usdt,
    accumulate_vip_balance,
)
# Re-exported for existing importers (health, market, admin_revenue, ...).
from services.order_profit import compute_order_profit  # noqa: F401
from services.payment_reference import generate_payment_reference
from services.referrals import maybe_award_referral_bonus


logger = logging.getLogger(__name__)


# ============================================================
# Pydantic models
# ============================================================

class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    user_email: str
    user_name: str
    user_role: str
    from_code: str
    to_code: str
    amount_from: float
    amount_to: float
    rate_applied: float
    commission_percent: float
    delivery_method: Literal["transfer", "cash", "crypto", "accumulate"]
    delivery_details: str = ""
    sender_name: str = ""
    proof_image: str = ""
    # Payout evidence — populated by staff/admin when the order is completed
    # (the screenshot of the bank transfer / crypto tx made TO the client).
    payout_proof_image: str = ""
    payout_tx_hash: str = ""
    # iter143 — snapshot of the tiered payment account the client was told
    # to send funds to (resolved by amount at creation time).
    payment_account_id: str = ""
    payment_account_label: str = ""
    # iter173 §61 — reference the client can include in the bank transfer
    # concept; exact match in the statement = high-confidence signal (+20).
    payment_reference: str = Field(default_factory=generate_payment_reference)
    status: Literal[
        "pending", "requires_double_approval", "approved", "rejected", "completed"
    ] = "pending"
    admin_note: str = ""
    created_at: str = Field(default_factory=lambda: iso(now_utc()))
    updated_at: str = Field(default_factory=lambda: iso(now_utc()))


class OrderCreate(BaseModel):
    from_code: str
    to_code: str
    # iter247 — gt=0 bloquea órdenes con importe negativo o cero.
    amount_from: float = Field(..., gt=0, le=1_000_000_000)
    delivery_method: Literal["transfer", "cash", "crypto", "accumulate"]
    delivery_details: str = ""
    sender_name: str = Field(
        ..., min_length=2,
        description="Nombre del titular de la cuenta que hizo la transferencia",
    )
    proof_image: str = ""


VALID_ORDER_STATUSES = {
    "approved", "rejected", "completed", "pending", "requires_double_approval",
}


# ============================================================
# Order creation pipeline (used by POST /orders)
# ============================================================

async def resolve_order_rate(from_code: str, to_code: str, user: dict,
                             amount_from: Optional[float] = None) -> tuple[float, dict]:
    """Look up the active rate and pick vip vs normal. Returns (rate, rate_doc).

    iter55.7 — Lenient lookup: falls back to a case-insensitive regex that
    tolerates leading/trailing whitespace so legacy `CUP ` rate rows still
    match a normalised `CUP` from the frontend.

    iter143 — when `amount_from` is provided and the rate row has amount
    `tiers`, the matching tier overrides the base rates."""
    fc = (from_code or "").strip().upper()
    tc = (to_code or "").strip().upper()
    rate_doc = await db.rates.find_one({"from_code": fc, "to_code": tc}, {"_id": 0})
    if not rate_doc:
        import re
        rate_doc = await db.rates.find_one(
            {
                "from_code": {"$regex": f"^\\s*{re.escape(fc)}\\s*$", "$options": "i"},
                "to_code": {"$regex": f"^\\s*{re.escape(tc)}\\s*$", "$options": "i"},
            },
            {"_id": 0},
        )
    if not rate_doc:
        raise HTTPException(status_code=400, detail="Tasa de cambio no disponible para ese par")
    from services.rate_tiers import effective_rates
    eff = effective_rates(rate_doc, amount_from)
    is_vip = user["role"] in ("vip", "admin")
    return (eff["rate_vip"] if is_vip else eff["rate_normal"]), rate_doc


def _cash_no_cents(to_code: str, to_type: str, delivery_method: str) -> bool:
    """iter55.27 — Cash physical delivery to any fiat currency floors the
    delivered amount (Cuba ops doesn't stock coins for USD/CUP/etc.). The
    sub-unit residue is credited to the client's on-platform balance in the
    SAME currency so nothing is lost — the client can accumulate residues
    across trades until they form a whole unit OR convert them to USDT
    (with a 0.01 USDT service fee) via `POST /vip/convert`.

    Applies when: delivery_method == "cash" AND to_type == "fiat".
    Does NOT apply to crypto/USDT destinations (already integer-ish precision).
    """
    return delivery_method == "cash" and (to_type or "").lower() == "fiat"


# Backward-compat alias — some tests still import the old name.
_cash_usd_rounds_down = _cash_no_cents


def build_order_from_payload(payload: "OrderCreate", user: dict, rate: float,
                              to_currency_type: str = "") -> "Order":
    """iter19: commission removed. New orders carry commission_percent=0.0;
    historical orders keep their original 5% value untouched.

    iter55.24 → 55.27: for cash delivery to any fiat, we floor the delivered
    amount. The fractional residue is written to `order.residue_credited` and
    credited to `user.vip_balances[to_code]` by the caller (create_order).
    We do NOT do the credit here to keep this pure/sync — the caller owns
    the DB writes.
    """
    import math
    commission = 0.0
    raw = payload.amount_from * rate * (1 - commission / 100)
    if _cash_no_cents(payload.to_code, to_currency_type, payload.delivery_method):
        amount_to = float(math.floor(raw))
        residue = round(raw - amount_to, 6)  # 6 dp: sub-cent precision
    else:
        amount_to = round(raw, 4)
        residue = 0.0
    order = Order(
        user_id=user["user_id"],
        user_email=user["email"],
        user_name=user["name"],
        user_role=user["role"],
        from_code=payload.from_code,
        to_code=payload.to_code,
        amount_from=payload.amount_from,
        amount_to=amount_to,
        rate_applied=rate,
        commission_percent=commission,
        delivery_method=payload.delivery_method,
        delivery_details=payload.delivery_details,
        sender_name=payload.sender_name,
        proof_image=payload.proof_image,
    )
    # Attach the residue as a plain attribute so callers can credit it after
    # persisting the order. Not part of the pydantic schema (transient hint).
    setattr(order, "_residue_to_credit", residue)
    return order


async def maybe_flag_defensive_margin(order: "Order") -> None:
    """If profit pct is below the configured defensive margin, flag the order for
    double approval. Best-effort — never raises."""
    try:
        rate_doc = await db.rates.find_one(
            {"from_code": order.from_code, "to_code": order.to_code}, {"_id": 0}
        )
        settings_doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
        defensive_pct = settings_doc.get("defensive_margin_pct") if settings_doc else None
        if defensive_pct is None or not rate_doc or not rate_doc.get("real_rate"):
            return
        p = await compute_order_profit(order.model_dump(), rate_doc)
        if p and p["pct"] < float(defensive_pct):
            await db.orders.update_one(
                {"id": order.id}, {"$set": {"status": "requires_double_approval"}}
            )
    except Exception as e:
        logger.error(f"Defensive mode check failed: {e}")


async def check_negative_margin_alert(order: dict) -> None:
    """Notify admins if an order would generate a loss given the current real_rate."""
    rate_doc = await db.rates.find_one(
        {"from_code": order["from_code"], "to_code": order["to_code"]}, {"_id": 0}
    )
    if not rate_doc or rate_doc.get("real_rate") is None:
        return
    profit = await compute_order_profit(order, rate_doc)
    if profit and profit["amount"] < 0:
        loss_amount = abs(profit["amount"])
        await notify_all_admins(
            db,
            title="🚨 Orden con margen negativo",
            body=(
                f"Orden #{order['id'][:8]} de {order.get('user_name', '')} "
                f"({order['from_code']}→{order['to_code']}) generaría pérdida estimada "
                f"de {loss_amount:.2f} {order['to_code']} ({profit['pct']:.2f}%). "
                f"Revisa antes de aprobar."
            ),
            url_path="/admin/orders",
        )


async def dispatch_new_order_alerts(order: "Order", user: dict) -> None:
    """Notify all admins of the new order + raise a negative-margin alert if applicable.
    Best-effort — each side effect is isolated so one failure doesn't block the others."""
    try:
        await notify_all_admins(
            db,
            title="Nueva orden P2P pendiente",
            body=(f"{user['name']} envió {order.amount_from} {order.from_code} → "
                  f"{order.amount_to} {order.to_code} ({user['role'].upper()})."),
            url_path="/admin/orders",
        )
    except Exception as e:
        logger.error(f"Admin notify (new order) failed: {e}")
    try:
        await check_negative_margin_alert(order.model_dump())
    except Exception as e:
        logger.error(f"Negative margin check failed: {e}")


# ============================================================
# Order status transitions (used by PUT /admin/orders/{id}/status)
# ============================================================

async def check_vip_threshold_alert(order: dict) -> None:
    """If user's total_usdt crossed the configured threshold, notify admins once."""
    try:
        threshold = await get_vip_threshold(db)
        fresh = await db.users.find_one({"user_id": order["user_id"]}, {"_id": 0})
        if not fresh:
            return
        total_usdt = await compute_total_usdt(fresh)
        last_alert = fresh.get("last_vip_alert_threshold", 0)
        if total_usdt >= threshold and total_usdt > last_alert:
            await notify_all_admins(
                db,
                title="⚠️ Cliente VIP supera umbral",
                body=(f"{fresh['name']} acumula ${total_usdt:,.2f} USDT (umbral "
                      f"${threshold:,.0f}). Considera proponerle cierre o canje."),
                url_path="/admin/users",
            )
            await db.users.update_one(
                {"user_id": order["user_id"]},
                {"$set": {"last_vip_alert_threshold": total_usdt}},
            )
    except Exception as e:
        logger.error(f"VIP threshold alert failed: {e}")


async def send_client_order_email(order: dict, new_status: str, target_user: dict) -> None:
    try:
        if new_status == "approved":
            notify_order_approved(order, target_user)
        else:
            notify_order_rejected(order, target_user)
    except Exception as e:
        logger.error(f"Email notification failed: {e}")


async def send_client_order_push(order: dict, new_status: str) -> None:
    try:
        # iter74 — resolve recipient's language once and pass it to the builder
        from services.notification_i18n import resolve_lang
        lang = await resolve_lang(db, order["user_id"])
        if new_status == "approved":
            push_payload = build_order_approved_payload(order, lang=lang)
        elif new_status == "completed":
            push_payload = build_order_completed_payload(order, lang=lang)
        else:
            push_payload = build_order_rejected_payload(order, lang=lang)
        subs = await db.push_subscriptions.find(
            {"user_id": order["user_id"]}, {"_id": 0}
        ).to_list(50)
        dead_ids = [s["id"] for s in subs if send_push(s["subscription"], push_payload) == "dead"]
        if dead_ids:
            await db.push_subscriptions.delete_many({"id": {"$in": dead_ids}})
    except Exception as e:
        logger.error(f"Push notification failed: {e}")


_EXPLORER_URLS = {
    "TRC20": "https://tronscan.org/#/transaction/{tx_hash}",
    "BEP20": "https://bscscan.com/tx/{tx_hash}",
    "ERC20": "https://etherscan.io/tx/{tx_hash}",
    "POLYGON": "https://polygonscan.com/tx/{tx_hash}",
}


def _detect_payout_network(delivery: str) -> str:
    """Infer the on-chain network from delivery details (same heuristic as the UI)."""
    from services.crypto_networks import detect_family
    up = (delivery or "").upper()
    if "TRC20" in up or detect_family(delivery) == "tron":
        return "TRC20"
    if "BEP20" in up:
        return "BEP20"
    if "ERC20" in up or "ETH" in up:
        return "ERC20"
    if "POLYGON" in up or "MATIC" in up:
        return "POLYGON"
    return ""


def _crypto_payout_payload(order: dict) -> tuple[dict, str]:
    """iter55.19g — on-chain artefacts (hash/network/explorer URL) for a
    completed crypto order. Returns ({}, "") when no hash exists."""
    tx_hash = (order.get("payout_tx_hash") or "").strip()
    if not tx_hash:
        return {}, ""
    network = _detect_payout_network(order.get("delivery_details") or "")
    payload: dict = {"payout_tx_hash": tx_hash}
    if network:
        payload["crypto_network"] = network
        template = _EXPLORER_URLS.get(network)
        if template:
            payload["explorer_url"] = template.format(tx_hash=tx_hash)
    return payload, network


def _completed_order_msg(lang: str, method: Optional[str], network: str,
                         amt: object, code: str) -> str:
    from services.notification_i18n import t as _t
    if method == "accumulate":
        return _t("order_completed", lang, "msg_accumulate", amt=amt, code=code)
    if method == "crypto":
        if network:
            return _t("order_completed", lang, "msg_crypto_with_net",
                      amt=amt, code=code, network=network)
        return _t("order_completed", lang, "msg_crypto", amt=amt, code=code)
    if method == "cash":
        return _t("order_completed", lang, "msg_cash", amt=amt, code=code)
    return _t("order_completed", lang, "msg_transfer", amt=amt, code=code)


def _order_notification_copy(order: dict, new_status: str, lang: str,
                             network: str) -> tuple[str, str]:
    """Localised (title, message) pair for an order status notification."""
    from services.notification_i18n import t as _t
    short_id = order["id"][:8]
    amt = order.get("amount_to", 0)
    code = order.get("to_code", "")
    if new_status == "approved":
        return (_t("order_approved", lang, "title", short_id=short_id),
                _t("order_approved", lang, "message", amt=amt, code=code))
    if new_status == "completed":
        return (_t("order_completed", lang, "title", short_id=short_id),
                _completed_order_msg(lang, order.get("delivery_method"),
                                     network, amt, code))
    note = (order.get("admin_note") or "").strip()[:120]
    msg = (
        _t("order_rejected", lang, "message_note", note=note)
        if note
        else _t("order_rejected", lang, "message_default")
    )
    return _t("order_rejected", lang, "title", short_id=short_id), msg


async def create_inapp_order_notification(order: dict, new_status: str) -> None:
    """iter55.6 — Mirror push into the in-app inbox so users still see the event
    even if they never subscribed to Web Push (or the push endpoint was pruned).
    iter74 — Renders title/message in the recipient's `preferred_language`."""
    try:
        from routes.notifications import _insert_notification
        from services.notification_i18n import resolve_lang
        lang = await resolve_lang(db, order["user_id"])
        method = order.get("delivery_method")

        data_payload: dict = {
            "order_id": order["id"],
            "from_code": order.get("from_code"),
            "to_code": order.get("to_code", ""),
            "amount_from": order.get("amount_from"),
            "amount_to": order.get("amount_to", 0),
            "delivery_method": method,
        }
        network = ""
        if new_status == "completed" and method == "crypto":
            extra, network = _crypto_payout_payload(order)
            data_payload.update(extra)

        title, msg = _order_notification_copy(order, new_status, lang, network)
        await _insert_notification(
            recipient_user_id=order["user_id"],
            type=f"order_{new_status}",
            title=title,
            message=msg,
            data=data_payload,
        )
    except Exception as e:
        logger.error(f"In-app order notification failed: {e}")


async def authorize_status_transition(actor: dict, order: dict, new_status: str,
                                       totp_code: Optional[str]) -> None:
    """Enforce all permission + scope + 2FA rules before mutating the order.
    Raises HTTPException on rejection."""
    # iter14: once approved, only admin can modify the status
    if (order.get("status") == "approved"
            and new_status != "approved"
            and actor.get("role") != "admin"):
        raise HTTPException(
            status_code=403,
            detail="Esta transferencia ya fue confirmada. Solo un admin puede cambiar su estado.",
        )
    # iter14: employee currency scope — only act on orders touching authorized currencies
    _enforce_employee_currency_scope(actor, order["from_code"], order["to_code"])
    # Defensive: only admin can approve requires_double_approval; high-risk so step-up TOTP
    if order.get("status") == "requires_double_approval" and new_status == "approved":
        if actor.get("role") != "admin":
            raise HTTPException(
                status_code=403,
                detail="Solo un admin puede aprobar órdenes con margen bajo",
            )
        await _enforce_totp_step_up(
            actor, totp_code, action_label="aprobar orden con margen bajo"
        )


async def run_post_status_side_effects(order: dict, new_status: str, prev_status: str) -> None:
    """Apply balance accumulation and notifications after a status change.
    Each side effect is wrapped so one failure doesn't block the others.

    iter51 — accumulation now fires on the first transition into ANY
    money-settled state (`approved` OR `completed`), not just `approved`.
    `accumulate_vip_balance` is idempotent via the `accumulated_at` flag
    so paths like `pending → approved → completed` credit exactly once.
    """
    money_states = {"approved", "completed"}
    is_first_credit = new_status in money_states and prev_status not in money_states
    if is_first_credit and order["delivery_method"] == "accumulate":
        await accumulate_vip_balance(order)
        if order["user_role"] in ("vip", "admin"):
            await check_vip_threshold_alert(order)
    if is_first_credit:
        # iter112 — one-time referral bonus on the user's first settled order.
        await maybe_award_referral_bonus(order)
    if new_status in ("approved", "rejected", "completed") and prev_status != new_status:
        target_user = await db.users.find_one({"user_id": order["user_id"]}, {"_id": 0})
        if target_user:
            # Email: keep the historical approved/rejected copy — no dedicated
            # "completed" template yet. Push covers the completion beat.
            if new_status in ("approved", "rejected"):
                await send_client_order_email(order, new_status, target_user)
            await send_client_order_push(order, new_status)
            await create_inapp_order_notification(order, new_status)
