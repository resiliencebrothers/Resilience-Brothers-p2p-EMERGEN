"""Authenticated file proxy — iter35.

`GET /api/files/{key:path}` streams an object from the configured storage
backend (Cloudflare R2 / AWS S3) **after** verifying the calling user has
permission to view it. This avoids exposing the bucket publicly while still
letting `<img src="/api/files/...">` work natively (cookies are sent
because the cookie is `samesite=none secure`).

Access rules
------------
- Admins / employees see everything.
- A normal user can only fetch objects under `orders/...` or
  `withdrawals/...` that reference one of their own documents.

We keep this simple: we lookup the `key` in `orders.proof_image` and
`withdrawals.payout_proof_image` to derive ownership.
"""
from typing import Any
import logging

from fastapi import APIRouter, HTTPException, Request, Response

from auth_utils import require_user
from db_client import db
from services import storage as storage_service
from services.permissions import _has_permission as _has_perm

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Files"])


async def _can_access(user: dict, key: str) -> bool:
    """Return True if `user` is allowed to view the object identified by `key`."""
    # CB11 — los extractos bancarios NO se conceden por el rol employee:
    # exigen el permiso de conciliación y el alcance de moneda del empleado
    # (misma política que la descarga dedicada del módulo).
    if key.startswith("reconciliation/"):
        if user.get("role") not in ("admin", "employee"):
            return False
        if not _has_perm(user, "reconciliation"):
            return False
        allowed = ([str(c).upper() for c in (user.get("allowed_currencies") or [])]
                   if user.get("role") == "employee" else [])
        if allowed:
            imp_id = key.split("/", 1)[1].rsplit(".", 1)[0]
            imp = await db.bank_statement_imports.find_one(
                {"id": imp_id}, {"_id": 0, "currency": 1})
            if imp and str(imp.get("currency") or "").upper() not in allowed:
                return False
        return True
    if user.get("role") in ("admin", "employee"):
        return True
    ref = f"/api/files/{key}"
    # Payment proof uploaded by the CLIENT when creating an order.
    own_order_deposit = await db.orders.find_one(
        {"user_id": user["user_id"], "proof_image": ref},
        {"_id": 0, "id": 1},
    )
    if own_order_deposit:
        return True
    # iter55.8 — Payout proof uploaded by STAFF when marking the client's own
    # order as `completed` (physical delivery evidence). Previously missing:
    # the client would get 403 "No autorizado" trying to see the proof of
    # their own received payment.
    own_order_payout = await db.orders.find_one(
        {"user_id": user["user_id"], "payout_proof_image": ref},
        {"_id": 0, "id": 1},
    )
    if own_order_payout:
        return True
    # DR07 — comprobante de un depósito PROPIO del cliente ("Depósitos y
    # Retiros"): el dueño puede ver la captura que él mismo subió.
    own_deposit = await db.deposits.find_one(
        {"user_id": user["user_id"], "proof_url": ref},
        {"_id": 0, "id": 1},
    )
    if own_deposit:
        return True
    # Payout proof for the user's own VIP-balance withdrawal.
    own_withdrawal = await db.withdrawals.find_one(
        {"user_id": user["user_id"], "payout_proof_image": ref},
        {"_id": 0, "id": 1},
    )
    return own_withdrawal is not None


@router.get("/files/{key:path}")
async def get_file(key: str, request: Request) -> Any:
    user = await require_user(request)
    if "../" in key or key.startswith("/"):
        raise HTTPException(status_code=400, detail="key inválida")
    if not await _can_access(user, key):
        raise HTTPException(status_code=403, detail="No autorizado")
    body, content_type = storage_service.get_object_bytes(key)
    if body is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return Response(
        content=body,
        media_type=content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=300"},
    )
