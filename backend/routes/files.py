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
import logging

from fastapi import APIRouter, HTTPException, Request, Response

from auth_utils import require_user
from db_client import db
from services import storage as storage_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Files"])


async def _can_access(user: dict, key: str) -> bool:
    """Return True if `user` is allowed to view the object identified by `key`."""
    if user.get("role") in ("admin", "employee"):
        return True
    ref = f"/api/files/{key}"
    # iter35 — order proof or admin payout proof attached to user's own withdrawal.
    own_order = await db.orders.find_one(
        {"user_id": user["user_id"], "proof_image": ref},
        {"_id": 0, "id": 1},
    )
    if own_order:
        return True
    own_withdrawal = await db.withdrawals.find_one(
        {"user_id": user["user_id"], "payout_proof_image": ref},
        {"_id": 0, "id": 1},
    )
    return own_withdrawal is not None


@router.get("/files/{key:path}")
async def get_file(key: str, request: Request):
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
