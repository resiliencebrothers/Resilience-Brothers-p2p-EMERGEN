"""iter112 — Referral system endpoints.

    GET  /api/referrals/me                    (any client — code + stats + history)
    POST /api/referrals/claim                 (apply a code, once, pre-first-order)
    GET  /api/admin/referrals/leaderboard     (staff w/ `users` permission)
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from db_client import db
from auth_utils import require_user, require_permission, iso, now_utc
from services.referrals import ensure_referral_code, get_bonus_pct

router = APIRouter(tags=["Referrals"])
logger = logging.getLogger(__name__)


@router.get("/referrals/me")
async def my_referrals(request: Request) -> Any:
    user = await require_user(request)
    code = await ensure_referral_code(user)
    referred = await db.users.find(
        {"referred_by": user["user_id"]},
        {"_id": 0, "user_id": 1, "name": 1, "created_at": 1, "referral_bonus_paid": 1},
    ).to_list(1000)
    bonuses = await db.referral_bonuses.find(
        {"referrer_user_id": user["user_id"]}, {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    return {
        "referral_code": code,
        "bonus_pct": await get_bonus_pct(),
        "referred_count": len(referred),
        "activated_count": sum(1 for r in referred if r.get("referral_bonus_paid")),
        "total_bonus_usdt": round(sum(float(b.get("bonus_usdt") or 0) for b in bonuses), 4),
        "bonuses": bonuses,
    }


class ClaimPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., min_length=4, max_length=20)


@router.post("/referrals/claim")
async def claim_referral(payload: ClaimPayload, request: Request) -> Any:
    user = await require_user(request)
    code = payload.code.strip().upper()
    if user.get("referred_by"):
        raise HTTPException(status_code=409, detail="Ya tienes un código de referido aplicado.")
    owner = await db.users.find_one(
        {"referral_code": code}, {"_id": 0, "user_id": 1, "name": 1},
    )
    if not owner:
        raise HTTPException(status_code=404, detail="Código de referido inválido.")
    if owner["user_id"] == user["user_id"]:
        raise HTTPException(status_code=400, detail="No puedes usar tu propio código de referido.")
    has_settled_orders = await db.orders.count_documents(
        {"user_id": user["user_id"], "status": {"$in": ["approved", "completed"]}},
        limit=1,
    )
    if has_settled_orders:
        raise HTTPException(
            status_code=400,
            detail="El código de referido solo puede aplicarse antes de tu primera orden aprobada.",
        )
    res = await db.users.update_one(
        {"user_id": user["user_id"], "referred_by": {"$in": [None, ""]}},
        {"$set": {"referred_by": owner["user_id"], "referred_at": iso(now_utc())}},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Ya tienes un código de referido aplicado.")
    logger.info("Referral claimed: %s referred_by %s", user["user_id"], owner["user_id"])
    return {"ok": True, "referrer_name": owner.get("name", "")}


@router.get("/admin/referrals/leaderboard")
async def referrals_leaderboard(request: Request) -> Any:
    await require_permission(request, "users")

    bonus_rows = await db.referral_bonuses.aggregate([
        {"$group": {
            "_id": "$referrer_user_id",
            "total_bonus_usdt": {"$sum": "$bonus_usdt"},
            "activated_count": {"$sum": 1},
            "last_bonus_at": {"$max": "$created_at"},
        }},
    ]).to_list(1000)
    referred_rows = await db.users.aggregate([
        {"$match": {"referred_by": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$referred_by", "referred_count": {"$sum": 1}}},
    ]).to_list(1000)

    by_id: Dict[str, dict] = {}
    for r in referred_rows:
        by_id[r["_id"]] = {
            "referrer_user_id": r["_id"], "referred_count": r["referred_count"],
            "activated_count": 0, "total_bonus_usdt": 0.0, "last_bonus_at": "",
        }
    for b in bonus_rows:
        entry = by_id.setdefault(b["_id"], {
            "referrer_user_id": b["_id"], "referred_count": 0,
            "activated_count": 0, "total_bonus_usdt": 0.0, "last_bonus_at": "",
        })
        entry["activated_count"] = b["activated_count"]
        entry["total_bonus_usdt"] = round(float(b["total_bonus_usdt"]), 4)
        entry["last_bonus_at"] = b.get("last_bonus_at") or ""

    ids = list(by_id)
    users = await db.users.find(
        {"user_id": {"$in": ids}},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1, "referral_code": 1},
    ).to_list(len(ids) or 1)
    meta = {u["user_id"]: u for u in users}
    items = []
    for uid, entry in by_id.items():
        u = meta.get(uid, {})
        items.append({
            **entry,
            "name": u.get("name", ""),
            "email": u.get("email", ""),
            "role": u.get("role", ""),
            "referral_code": u.get("referral_code", ""),
        })
    items.sort(key=lambda x: (-x["total_bonus_usdt"], -x["referred_count"]))
    return {
        "items": items[:100],
        "bonus_pct": await get_bonus_pct(),
        "total_paid_usdt": round(sum(i["total_bonus_usdt"] for i in items), 4),
    }
