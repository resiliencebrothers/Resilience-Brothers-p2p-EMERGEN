"""iter112 — Referral system core logic.

Data model:
  - users.referral_code        unique shareable code (lazy-generated, "RB" + 6 hex).
  - users.referred_by          user_id of the referrer. Claimed ONCE, only
                               before the user's first approved order.
  - users.referral_bonus_paid  one-time flag consumed when the first
                               money-settled order pays the referrer.
  - referral_bonuses (collection): audit trail + leaderboard aggregation.
      {id, referrer_user_id, referred_user_id, referred_name, referred_email,
       order_id, order_profit_usdt, pct_applied, bonus_usdt, created_at}

Bonus rule (owner spec, 26 Jul 2026): the referrer earns
`referral_bonus_pct` (settings.global, default 10%) of the company profit
(USDT-eq) reported by the referred user's FIRST approved/completed order.
One time only. Credited straight to the referrer's `vip_balances.USDT`.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from db_client import db
from auth_utils import iso, now_utc
from services.balances import build_rate_lookup, convert_to_usdt
from services.order_profit import compute_order_profit

logger = logging.getLogger(__name__)

DEFAULT_BONUS_PCT = 10.0


async def get_bonus_pct() -> float:
    doc = await db.settings.find_one(
        {"id": "global"}, {"_id": 0, "referral_bonus_pct": 1},
    ) or {}
    raw = doc.get("referral_bonus_pct")
    try:
        pct = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_BONUS_PCT
    return pct if 0 <= pct <= 100 else DEFAULT_BONUS_PCT


async def ensure_referral_code(user: dict) -> str:
    """Return the user's referral code, allocating a unique one on first use."""
    code = (user.get("referral_code") or "").strip()
    if code:
        return code
    for _ in range(8):
        candidate = "RB" + uuid.uuid4().hex[:6].upper()
        clash = await db.users.find_one({"referral_code": candidate}, {"_id": 1})
        if clash:
            continue
        # Race-guarded: only writes if the user still has no code.
        await db.users.update_one(
            {"user_id": user["user_id"], "referral_code": {"$in": [None, ""]}},
            {"$set": {"referral_code": candidate}},
        )
        fresh = await db.users.find_one(
            {"user_id": user["user_id"]}, {"_id": 0, "referral_code": 1},
        )
        return (fresh or {}).get("referral_code") or candidate
    raise RuntimeError("No se pudo asignar un código de referido único")


async def _compute_order_profit_usdt(order: dict) -> float:
    rate_doc = await db.rates.find_one(
        {"from_code": order.get("from_code"), "to_code": order.get("to_code")},
        {"_id": 0},
    )
    profit = await compute_order_profit(order, rate_doc)
    if not profit or float(profit.get("amount") or 0) <= 0:
        return 0.0
    fx = await build_rate_lookup()
    return convert_to_usdt(float(profit["amount"]), profit["currency"], fx) or 0.0


async def _notify_referrer(referrer_id: str, referred: dict, bonus: float,
                           pct: float, order_id: str) -> None:
    try:
        from routes.notifications import _insert_notification
        from services.notification_i18n import t as _t, resolve_lang
        lang = await resolve_lang(db, referrer_id)
        await _insert_notification(
            recipient_user_id=referrer_id,
            type="referral_bonus",
            title=_t("referral_bonus", lang, "title"),
            message=_t("referral_bonus", lang, "message",
                       name=referred.get("name", ""), bonus=bonus, pct=pct),
            data={"bonus_usdt": bonus, "pct": pct,
                  "referred_user_id": referred["user_id"], "order_id": order_id},
        )
    except Exception as e:
        logger.error(f"Referral bonus notification failed: {e}")


async def maybe_award_referral_bonus(order: dict) -> None:
    """One-time referral bonus when the referred user's FIRST order settles.
    Idempotent: the `referral_bonus_paid` flag is consumed atomically, so
    concurrent/repeated status transitions can never double-pay. Best-effort:
    never raises into the order flow."""
    try:
        referred = await db.users.find_one_and_update(
            {"user_id": order["user_id"],
             "referred_by": {"$nin": [None, ""]},
             "referral_bonus_paid": {"$ne": True}},
            {"$set": {"referral_bonus_paid": True,
                      "referral_bonus_paid_at": iso(now_utc())}},
        )
        if not referred:
            return
        referrer_id: Optional[str] = referred.get("referred_by")
        referrer = await db.users.find_one(
            {"user_id": referrer_id}, {"_id": 0, "user_id": 1, "name": 1},
        )
        if not referrer:
            return

        profit_usdt = await _compute_order_profit_usdt(order)
        pct = await get_bonus_pct()
        bonus = round(profit_usdt * pct / 100.0, 4)
        if bonus <= 0:
            logger.info(
                "Referral bonus skipped (no computable profit) — order %s, referred %s",
                order.get("id"), referred.get("user_id"),
            )
            return

        await db.users.update_one(
            {"user_id": referrer_id},
            {"$inc": {"vip_balances.USDT": bonus}},
        )
        await db.referral_bonuses.insert_one({
            "id": uuid.uuid4().hex,
            "referrer_user_id": referrer_id,
            "referred_user_id": referred["user_id"],
            "referred_name": referred.get("name", ""),
            "referred_email": referred.get("email", ""),
            "order_id": order.get("id", ""),
            "order_profit_usdt": round(profit_usdt, 4),
            "pct_applied": pct,
            "bonus_usdt": bonus,
            "created_at": iso(now_utc()),
        })
        logger.info(
            "Referral bonus paid: %s USDT to %s for first order of %s",
            bonus, referrer_id, referred["user_id"],
        )
        await _notify_referrer(referrer_id or "", referred, bonus, pct,
                               order.get("id", ""))
    except Exception as e:
        logger.error(f"Referral bonus processing failed: {e}")
